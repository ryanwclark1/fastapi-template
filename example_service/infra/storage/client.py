"""Enhanced S3-compatible storage client for file uploads.

Provides async operations for uploading, downloading, and managing files
with support for presigned URLs, file metadata, and comprehensive error handling.
"""

from __future__ import annotations

import asyncio
import fnmatch
import hashlib
from io import BytesIO
import logging
from typing import TYPE_CHECKING, Any, BinaryIO

from example_service.infra.storage.exceptions import (
    StorageDownloadError,
    StorageError,
    StorageFileNotFoundError,
    StorageNotConfiguredError,
    StorageUploadError,
    map_boto_error,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

    from example_service.core.settings.storage import StorageSettings

logger = logging.getLogger(__name__)

# Optional aioboto3 dependency
try:
    import aioboto3  # type: ignore[import-not-found]
    from botocore.config import Config
    from botocore.exceptions import BotoCoreError, ClientError

    AIOBOTO3_AVAILABLE = True
except ImportError:
    aioboto3 = None
    Config = None
    ClientError = Exception
    BotoCoreError = Exception
    AIOBOTO3_AVAILABLE = False


# Legacy exception aliases for backward compatibility
class StorageClientError(StorageError):
    """Storage client operation error (legacy alias)."""

    def __init__(self, message: str) -> None:
        """Initialize legacy storage client error."""
        super().__init__(message=message, code="STORAGE_CLIENT_ERROR")


class FileNotFoundError(StorageFileNotFoundError):
    """File not found in storage (legacy alias)."""

    def __init__(self, message: str) -> None:
        """Initialize legacy file not found error."""
        super().__init__(message=message)


class InvalidFileError(StorageError):
    """Invalid file or file operation (legacy alias)."""

    def __init__(self, message: str) -> None:
        """Initialize legacy invalid file error."""
        super().__init__(message=message, code="INVALID_FILE_ERROR")


class StorageClient:
    """Async S3-compatible storage client for file uploads.

    Supports AWS S3, MinIO, LocalStack, and other S3-compatible services.
    Provides file upload, download, deletion, and presigned URL generation.

    Example:
        >>> from example_service.core.settings import get_storage_settings
        >>> settings = get_storage_settings()
        >>> client = StorageClient(settings)
        >>>
        >>> # Upload a file
        >>> with open("photo.jpg", "rb") as f:
        ...     result = await client.upload_file(
        ...         file_obj=f, key="uploads/photo.jpg", content_type="image/jpeg"
        ...     )
        >>>
        >>> # Get presigned download URL
        >>> url = await client.get_presigned_url("uploads/photo.jpg", expires_in=3600)
    """

    def __init__(self, settings: StorageSettings) -> None:
        """Initialize storage client with settings.

        Args:
            settings: Storage settings containing S3 configuration.

        Raises:
            StorageClientError: If aioboto3 is not installed or storage is not configured.
        """
        if not AIOBOTO3_AVAILABLE:
            msg = "aioboto3 is required for storage support. Install with: pip install aioboto3"
            raise StorageNotConfiguredError(msg)

        if not settings.is_configured:
            msg = "Storage is not configured. Set STORAGE_ENABLED=true and provide credentials."
            raise StorageNotConfiguredError(msg)

        self.settings = settings
        self._session = aioboto3.Session()
        self._client = None
        self._client_context = None

    async def __aenter__(self) -> StorageClient:
        """Async context manager entry."""
        await self.ensure_client()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Async context manager exit."""
        await self.close()

    async def startup(self) -> None:
        """Initialize the S3 client connection.

        Called during application startup in lifespan context.
        Creates the boto3 client, validates connection, and initializes the pool.

        Raises:
            StorageNotConfiguredError: If storage is not configured
            StorageError: If client initialization fails
        """
        if self._client is not None:
            logger.debug("Storage client already initialized")
            return

        logger.info(
            "Initializing storage client",
            extra={
                "bucket": self.settings.bucket,
                "endpoint": self.settings.endpoint,
                "region": self.settings.region,
            },
        )

        try:
            # Record initialization attempt
            from .metrics import storage_client_initializations

            # Use existing ensure_client logic but track metrics
            await self.ensure_client()

            # Validate connection with a simple operation
            await self._validate_connection()

            storage_client_initializations.labels(status="success").inc()
            logger.info("Storage client initialized successfully")

        except Exception:
            from .metrics import storage_client_initializations

            storage_client_initializations.labels(status="error").inc()
            logger.exception("Failed to initialize storage client")
            raise

    async def shutdown(self) -> None:
        """Shutdown the S3 client connection gracefully.

        Called during application shutdown in lifespan context.
        Drains the connection pool and closes the client.
        """
        if self._client is None:
            logger.debug("Storage client not initialized, nothing to shutdown")
            return

        logger.info("Shutting down storage client")

        try:
            await self.close()
            logger.info("Storage client shutdown complete")
        except Exception:
            logger.exception("Error during storage client shutdown")

    async def health_check(self) -> bool:
        """Check S3 connectivity and credentials.

        Performs a lightweight HEAD request to verify the bucket is accessible.

        Returns:
            True if healthy, False otherwise
        """
        if self._client is None:
            return False

        try:
            await self.ensure_client()
            # HEAD request on the bucket
            await self._client.head_bucket(Bucket=self.settings.bucket)
            return True
        except Exception as e:
            logger.warning(
                "Storage health check failed",
                extra={"error": str(e), "bucket": self.settings.bucket},
            )
            return False

    async def _validate_connection(self) -> None:
        """Validate the S3 connection by performing a test operation.

        Raises:
            StorageError: If connection validation fails
        """
        if self._client is None:
            raise StorageError(
                message="Storage client not initialized",
                code="STORAGE_CLIENT_ERROR",
            )
        try:
            await self._client.head_bucket(Bucket=self.settings.bucket)
        except Exception as e:
            raise StorageError(
                message=f"Failed to validate storage connection: {e}",
                code="STORAGE_CONNECTION_ERROR",
                metadata={"bucket": self.settings.bucket, "error": str(e)},
            ) from e

    @property
    def is_ready(self) -> bool:
        """Check if the client is initialized and ready for operations."""
        return self._client is not None

    async def ensure_client(self) -> Any:
        """Ensure S3 client is initialized and return it.

        Returns:
            The initialized S3 client.

        Raises:
            StorageError: If client initialization fails.
        """
        if self._client is None:
            # Create boto3 config with adaptive retry and connection pooling
            boto_config = Config(
                retries={
                    "max_attempts": self.settings.max_retries,
                    "mode": self.settings.retry_mode,
                },
                connect_timeout=self.settings.timeout,
                read_timeout=self.settings.timeout,
                max_pool_connections=self.settings.max_pool_connections,
            )

            # Get base client configuration from settings
            client_config = self.settings.get_boto3_config()

            # Create client context manager
            self._client_context = self._session.client(
                "s3",
                **client_config,
                config=boto_config,
            )

            # Enter the context manager
            if self._client_context is None:
                msg = "Failed to create S3 client context"
                raise StorageError(
                    msg,
                    code="STORAGE_CLIENT_ERROR",
                )
            self._client = await self._client_context.__aenter__()

            logger.info(
                "Storage client initialized",
                extra={
                    "endpoint": self.settings.endpoint,
                    "bucket": self.settings.bucket,
                    "region": self.settings.region,
                    "use_ssl": self.settings.use_ssl,
                    "verify_ssl": self.settings.verify_ssl,
                    "max_retries": self.settings.max_retries,
                    "retry_mode": self.settings.retry_mode,
                },
            )

        return self._client

    async def close(self) -> None:
        """Close the S3 client and clean up resources."""
        if self._client_context is not None:
            try:
                await self._client_context.__aexit__(None, None, None)
            except Exception as e:
                logger.warning("Error closing storage client: %s", e)
            finally:
                self._client = None
                self._client_context = None

    def _get_client_config(self) -> dict:
        """Get boto3 client configuration (deprecated - use ensure_client instead)."""
        return self.settings.get_boto3_config()

    async def upload_file(
        self,
        file_obj: BinaryIO,
        key: str,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
        bucket: str | None = None,
    ) -> dict:
        """Upload a file to S3.

        Args:
            file_obj: File-like object to upload.
            key: S3 object key (path in bucket).
            content_type: MIME type of the file.
            metadata: Optional metadata to attach to the object.
            bucket: Optional bucket name (uses default if not provided).

        Returns:
            Dictionary with upload information:
            - key: S3 object key
            - bucket: Bucket name
            - etag: Object ETag
            - size_bytes: File size
            - checksum_sha256: SHA256 checksum

        Raises:
            StorageClientError: If upload fails.
        """
        bucket = bucket or self.settings.bucket

        # Calculate file size and SHA256 checksum
        file_obj.seek(0)
        file_data = file_obj.read()
        size_bytes = len(file_data)
        checksum_sha256 = hashlib.sha256(file_data).hexdigest()

        # Reset to beginning for upload
        file_obj_bytes: BinaryIO = BytesIO(file_data)

        extra_args: dict[str, str | dict[str, str]] = {}
        if content_type:
            extra_args["ContentType"] = content_type
        if metadata:
            extra_args["Metadata"] = metadata

        try:
            s3 = await self.ensure_client()
            response = await s3.put_object(
                Bucket=bucket,
                Key=key,
                Body=file_obj_bytes,
                **extra_args,
            )

            etag = response.get("ETag", "").strip('"')

            logger.info(
                "File uploaded to storage",
                extra={
                    "key": key,
                    "bucket": bucket,
                    "size_bytes": size_bytes,
                    "content_type": content_type,
                },
            )

            return {
                "key": key,
                "bucket": bucket,
                "etag": etag,
                "size_bytes": size_bytes,
                "checksum_sha256": checksum_sha256,
            }

        except ClientError as e:
            logger.exception(
                "Failed to upload file to storage", extra={"error": str(e)}
            )
            raise map_boto_error(e, operation="upload", key=key) from e
        except Exception as e:
            logger.exception(
                "Unexpected error during file upload", extra={"error": str(e)}
            )
            raise StorageUploadError(
                f"Failed to upload {key}: {e}",
                metadata={"key": key, "bucket": bucket, "error": str(e)},
            ) from e

    async def download_file(self, key: str, bucket: str | None = None) -> bytes:
        """Download a file from S3.

        Args:
            key: S3 object key.
            bucket: Optional bucket name (uses default if not provided).

        Returns:
            File contents as bytes.

        Raises:
            FileNotFoundError: If file doesn't exist.
            StorageClientError: If download fails.
        """
        bucket = bucket or self.settings.bucket

        try:
            s3 = await self.ensure_client()
            response = await s3.get_object(Bucket=bucket, Key=key)
            file_data_raw = await response["Body"].read()
            file_data: bytes = (
                bytes(file_data_raw)
                if not isinstance(file_data_raw, bytes)
                else file_data_raw
            )

            logger.info(
                "File downloaded from storage",
                extra={"key": key, "bucket": bucket, "size_bytes": len(file_data)},
            )
            return file_data

        except ClientError as e:
            logger.exception(
                "Failed to download file from storage", extra={"error": str(e)}
            )
            raise map_boto_error(e, operation="download", key=key) from e
        except Exception as e:
            logger.exception(
                "Unexpected error during file download", extra={"error": str(e)}
            )
            raise StorageDownloadError(
                f"Failed to download {key}: {e}",
                metadata={"key": key, "bucket": bucket, "error": str(e)},
            ) from e

    async def delete_file(self, key: str, bucket: str | None = None) -> bool:
        """Delete a file from S3.

        Args:
            key: S3 object key.
            bucket: Optional bucket name (uses default if not provided).

        Returns:
            True if deleted successfully.

        Raises:
            StorageClientError: If deletion fails.
        """
        bucket = bucket or self.settings.bucket

        try:
            s3 = await self.ensure_client()
            await s3.delete_object(Bucket=bucket, Key=key)

            logger.info(
                "File deleted from storage", extra={"key": key, "bucket": bucket}
            )
            return True

        except ClientError as e:
            logger.exception(
                "Failed to delete file from storage", extra={"error": str(e)}
            )
            raise map_boto_error(e, operation="delete", key=key) from e
        except Exception as e:
            logger.exception(
                "Unexpected error during file deletion", extra={"error": str(e)}
            )
            raise StorageError(
                f"Failed to delete {key}: {e}",
                code="STORAGE_DELETE_ERROR",
                metadata={"key": key, "bucket": bucket, "error": str(e)},
            ) from e

    async def get_presigned_url(
        self,
        key: str,
        expires_in: int | None = None,
        bucket: str | None = None,
    ) -> str:
        """Generate a presigned URL for downloading a file.

        Args:
            key: S3 object key.
            expires_in: URL expiration in seconds (uses settings default if not provided).
            bucket: Optional bucket name (uses default if not provided).

        Returns:
            Presigned URL for downloading the file.

        Raises:
            StorageClientError: If URL generation fails.
        """
        bucket = bucket or self.settings.bucket
        expires_in = expires_in or self.settings.presigned_url_expiry_seconds

        try:
            s3 = await self.ensure_client()
            url_raw = await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=expires_in,
            )
            url: str = str(url_raw)

            logger.debug(
                "Generated presigned download URL for %s (expires in %ss)",
                key,
                expires_in,
            )
            return url

        except ClientError as e:
            logger.exception(
                "Failed to generate presigned URL", extra={"error": str(e)}
            )
            raise map_boto_error(e, operation="presigned_url", key=key) from e
        except Exception as e:
            logger.exception(
                "Unexpected error generating presigned URL", extra={"error": str(e)}
            )
            raise StorageError(
                f"Failed to generate presigned URL for {key}: {e}",
                code="STORAGE_PRESIGNED_URL_ERROR",
                metadata={"key": key, "bucket": bucket, "error": str(e)},
            ) from e

    async def generate_presigned_upload(
        self,
        key: str,
        content_type: str,
        expires_in: int | None = None,
        bucket: str | None = None,
    ) -> dict:
        """Generate presigned POST data for direct browser upload.

        Args:
            key: S3 object key for the upload.
            content_type: MIME type of the file to upload.
            expires_in: URL expiration in seconds (uses settings default if not provided).
            bucket: Optional bucket name (uses default if not provided).

        Returns:
            Dictionary with presigned POST data:
            - url: Upload URL
            - fields: Form fields to include in the POST request

        Raises:
            StorageClientError: If presigned POST generation fails.
        """
        bucket = bucket or self.settings.bucket
        expires_in = expires_in or self.settings.presigned_url_expiry_seconds

        conditions = [
            {"Content-Type": content_type},
            ["content-length-range", 1, self.settings.max_file_size_bytes],
        ]

        try:
            s3 = await self.ensure_client()
            presigned_post_raw = await s3.generate_presigned_post(
                Bucket=bucket,
                Key=key,
                Fields={"Content-Type": content_type},
                Conditions=conditions,
                ExpiresIn=expires_in,
            )
            presigned_post: dict[Any, Any] = (
                dict(presigned_post_raw)
                if isinstance(presigned_post_raw, dict)
                else {"url": str(presigned_post_raw), "fields": {}}
            )

            logger.info(
                "Generated presigned upload URL",
                extra={
                    "key": key,
                    "bucket": bucket,
                    "content_type": content_type,
                    "expires_in": expires_in,
                },
            )

            return presigned_post

        except ClientError as e:
            logger.exception(
                "Failed to generate presigned upload", extra={"error": str(e)}
            )
            raise map_boto_error(e, operation="presigned_upload", key=key) from e
        except Exception as e:
            logger.exception(
                "Unexpected error generating presigned upload", extra={"error": str(e)}
            )
            raise StorageError(
                f"Failed to generate presigned upload for {key}: {e}",
                code="STORAGE_PRESIGNED_UPLOAD_ERROR",
                metadata={"key": key, "bucket": bucket, "error": str(e)},
            ) from e

    async def file_exists(self, key: str, bucket: str | None = None) -> bool:
        """Check if a file exists in S3.

        Args:
            key: S3 object key.
            bucket: Optional bucket name (uses default if not provided).

        Returns:
            True if file exists, False otherwise.
        """
        bucket = bucket or self.settings.bucket

        try:
            s3 = await self.ensure_client()
            await s3.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError as e:
            # NoSuchKey means file doesn't exist - return False
            error_code = (
                e.response.get("Error", {}).get("Code", "")
                if hasattr(e, "response")
                else ""
            )
            if error_code in {"NoSuchKey", "404", "NotFound"}:
                return False
            # Other errors should be raised
            logger.exception("Error checking file existence", extra={"error": str(e)})
            raise map_boto_error(e, operation="file_exists", key=key) from e
        except Exception as e:
            logger.exception(
                "Unexpected error checking file existence", extra={"error": str(e)}
            )
            return False

    async def get_file_info(self, key: str, bucket: str | None = None) -> dict | None:
        """Get file metadata from S3.

        Args:
            key: S3 object key.
            bucket: Optional bucket name (uses default if not provided).

        Returns:
            Dictionary with file metadata or None if not found.
            - key: Object key
            - size_bytes: File size in bytes
            - content_type: MIME type
            - last_modified: Last modification datetime
            - etag: Object ETag
            - metadata: Custom metadata

        Raises:
            StorageClientError: If metadata retrieval fails (except for not found).
        """
        bucket = bucket or self.settings.bucket

        try:
            s3 = await self.ensure_client()
            response = await s3.head_object(Bucket=bucket, Key=key)

            return {
                "key": key,
                "size_bytes": response.get("ContentLength"),
                "content_type": response.get("ContentType"),
                "last_modified": response.get("LastModified"),
                "etag": response.get("ETag", "").strip('"'),
                "metadata": response.get("Metadata", {}),
            }

        except ClientError as e:
            error_code = (
                e.response.get("Error", {}).get("Code", "")
                if hasattr(e, "response")
                else ""
            )
            if error_code in {"NoSuchKey", "404", "NotFound"}:
                return None
            logger.exception(
                "Failed to get file info from storage", extra={"error": str(e)}
            )
            raise map_boto_error(e, operation="get_file_info", key=key) from e
        except Exception as e:
            logger.exception(
                "Unexpected error getting file info", extra={"error": str(e)}
            )
            raise StorageError(
                f"Failed to get file info for {key}: {e}",
                code="STORAGE_FILE_INFO_ERROR",
                metadata={"key": key, "bucket": bucket, "error": str(e)},
            ) from e

    async def upload_files(
        self,
        files: list[tuple[str, BinaryIO | bytes, str]],
        max_concurrency: int = 5,
        on_progress: Callable[[str, bool, str | None], None] | None = None,
    ) -> list[dict[str, Any]]:
        """Upload multiple files concurrently with semaphore-based rate limiting.

        Args:
            files: List of tuples (key, file_obj, content_type) to upload.
            max_concurrency: Maximum number of concurrent uploads (default: 5).
            on_progress: Optional callback called after each upload completes.
                         Receives (key, success, error_message).

        Returns:
            List of results, one per file:
            [{"key": str, "success": bool, "url": str | None, "error": str | None}, ...]

        Example:
            >>> files = [
            ...     ("uploads/file1.jpg", open("file1.jpg", "rb"), "image/jpeg"),
            ...     ("uploads/file2.png", open("file2.png", "rb"), "image/png"),
            ... ]
            >>> results = await client.upload_files(files, max_concurrency=3)
            >>> successful = [r for r in results if r["success"]]
        """
        semaphore = asyncio.Semaphore(max_concurrency)

        async def upload_one(
            key: str, file_obj: BinaryIO | bytes, content_type: str
        ) -> dict[str, Any]:
            """Upload a single file with semaphore control."""
            async with semaphore:
                try:
                    # Convert bytes to BytesIO if needed
                    if isinstance(file_obj, bytes):
                        file_obj = BytesIO(file_obj)

                    result = await self.upload_file(
                        file_obj=file_obj,
                        key=key,
                        content_type=content_type,
                    )

                    # Call progress callback if provided
                    if on_progress:
                        on_progress(key, True, None)

                    logger.debug("Successfully uploaded file in batch: %s", key)
                    return {
                        "key": key,
                        "success": True,
                        "url": result.get("key"),
                        "error": None,
                        "etag": result.get("etag"),
                        "size_bytes": result.get("size_bytes"),
                    }

                except Exception as e:
                    error_msg = str(e)
                    logger.warning(
                        "Failed to upload file in batch: %s",
                        key,
                        extra={"error": error_msg},
                    )

                    # Call progress callback if provided
                    if on_progress:
                        on_progress(key, False, error_msg)

                    return {
                        "key": key,
                        "success": False,
                        "url": None,
                        "error": error_msg,
                    }

        # Execute all uploads concurrently with error handling
        tasks = [
            upload_one(key, file_obj, content_type)
            for key, file_obj, content_type in files
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert any exceptions to error results
        processed_results: list[dict[str, Any]] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                key = files[i][0]
                error_msg = str(result)
                logger.error("Unexpected error uploading %s: %s", key, error_msg)
                processed_results.append({
                    "key": key,
                    "success": False,
                    "url": None,
                    "error": error_msg,
                })
            else:
                # Type narrowing: result is dict[str, Any] here
                processed_results.append(result)  # type: ignore[arg-type]

        successful_count = sum(1 for r in processed_results if r["success"])
        logger.info(
            "Batch upload completed: %s/%s successful",
            successful_count,
            len(files),
            extra={
                "total": len(files),
                "successful": successful_count,
                "failed": len(files) - successful_count,
            },
        )

        return processed_results

    async def download_files(
        self,
        keys: list[str],
        max_concurrency: int = 5,
        on_progress: Callable[[str, bool, str | None], None] | None = None,
    ) -> list[dict[str, Any]]:
        """Download multiple files concurrently.

        Args:
            keys: List of S3 object keys to download.
            max_concurrency: Maximum number of concurrent downloads (default: 5).
            on_progress: Optional callback called after each download completes.
                         Receives (key, success, error_message).

        Returns:
            List of results, one per file:
            [{"key": str, "success": bool, "data": bytes | None, "error": str | None}, ...]

        Example:
            >>> keys = ["uploads/file1.jpg", "uploads/file2.png"]
            >>> results = await client.download_files(keys, max_concurrency=3)
            >>> for result in results:
            ...     if result["success"]:
            ...         with open(f"downloaded_{result['key']}", "wb") as f:
            ...             f.write(result["data"])
        """
        semaphore = asyncio.Semaphore(max_concurrency)

        async def download_one(key: str) -> dict[str, Any]:
            """Download a single file with semaphore control."""
            async with semaphore:
                try:
                    data = await self.download_file(key=key)

                    # Call progress callback if provided
                    if on_progress:
                        on_progress(key, True, None)

                    logger.debug("Successfully downloaded file in batch: %s", key)
                    return {
                        "key": key,
                        "success": True,
                        "data": data,
                        "error": None,
                        "size_bytes": len(data),
                    }

                except Exception as e:
                    error_msg = str(e)
                    logger.warning(
                        "Failed to download file in batch: %s",
                        key,
                        extra={"error": error_msg},
                    )

                    # Call progress callback if provided
                    if on_progress:
                        on_progress(key, False, error_msg)

                    return {
                        "key": key,
                        "success": False,
                        "data": None,
                        "error": error_msg,
                    }

        # Execute all downloads concurrently with error handling
        tasks = [download_one(key) for key in keys]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert any exceptions to error results
        processed_results: list[dict[str, Any]] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                key = keys[i]
                error_msg = str(result)
                logger.error("Unexpected error downloading %s: %s", key, error_msg)
                processed_results.append({
                    "key": key,
                    "success": False,
                    "data": None,
                    "error": error_msg,
                })
            else:
                # Type narrowing: result is dict[str, Any] here
                processed_results.append(result)  # type: ignore[arg-type]

        successful_count = sum(1 for r in processed_results if r["success"])
        logger.info(
            "Batch download completed: %s/%s successful",
            successful_count,
            len(keys),
            extra={
                "total": len(keys),
                "successful": successful_count,
                "failed": len(keys) - successful_count,
            },
        )

        return processed_results

    async def delete_files(
        self,
        keys: list[str],
        dry_run: bool = True,
        max_concurrency: int = 10,
    ) -> dict[str, Any]:
        """Delete multiple files with optional dry-run preview.

        Args:
            keys: List of S3 object keys to delete.
            dry_run: If True, only preview what would be deleted (default: True).
            max_concurrency: Maximum number of concurrent deletions (default: 10).

        Returns:
            Dictionary with deletion results:
            {
                "dry_run": bool,
                "deleted": list[str],  # Successfully deleted keys
                "failed": list[dict],  # Failed deletions with error info
                "total": int,          # Total number of keys
            }

        Example:
            >>> # Preview what would be deleted
            >>> result = await client.delete_files(["uploads/old1.jpg", "uploads/old2.jpg"])
            >>> print(f"Would delete {len(result['deleted'])} files")
            >>>
            >>> # Actually delete the files
            >>> result = await client.delete_files(
            ...     ["uploads/old1.jpg", "uploads/old2.jpg"], dry_run=False
            ... )
        """
        if dry_run:
            logger.info(
                "DRY RUN: Would delete %s files",
                len(keys),
                extra={"keys": keys[:10]},  # Log first 10 keys
            )
            return {
                "dry_run": True,
                "deleted": keys,
                "failed": [],
                "total": len(keys),
            }

        semaphore = asyncio.Semaphore(max_concurrency)
        deleted = []
        failed = []

        async def delete_one(key: str) -> tuple[str, bool, str | None]:
            """Delete a single file with semaphore control."""
            async with semaphore:
                try:
                    await self.delete_file(key=key)
                    logger.debug("Successfully deleted file in batch: %s", key)
                    return (key, True, None)

                except Exception as e:
                    error_msg = str(e)
                    logger.warning(
                        "Failed to delete file in batch: %s",
                        key,
                        extra={"error": error_msg},
                    )
                    return (key, False, error_msg)

        # Execute all deletions concurrently with error handling
        tasks = [delete_one(key) for key in keys]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                key = keys[i]
                error_msg = str(result)
                logger.error("Unexpected error deleting %s: %s", key, error_msg)
                failed.append({"key": key, "error": error_msg})
            # Type narrowing: result is tuple[str, bool, str | None] here
            elif isinstance(result, tuple) and len(result) == 3:
                key, success, error = result
                if success:
                    deleted.append(key)
                else:
                    failed.append({"key": key, "error": error or "Unknown error"})
            else:
                # Fallback for unexpected result type
                logger.warning("Unexpected result type: %s", type(result))
                failed.append({"key": keys[i], "error": "Unexpected result format"})

        logger.info(
            "Batch deletion completed: %s/%s deleted",
            len(deleted),
            len(keys),
            extra={
                "total": len(keys),
                "deleted": len(deleted),
                "failed": len(failed),
            },
        )

        return {
            "dry_run": False,
            "deleted": deleted,
            "failed": failed,
            "total": len(keys),
        }

    async def copy_file(
        self,
        source_key: str,
        dest_key: str,
        source_bucket: str | None = None,
        dest_bucket: str | None = None,
    ) -> bool:
        """Copy file within or between buckets.

        Args:
            source_key: Source object key.
            dest_key: Destination object key.
            source_bucket: Source bucket (uses default if not provided).
            dest_bucket: Destination bucket (uses default if not provided).

        Returns:
            True if copy was successful.

        Raises:
            StorageError: If copy operation fails.

        Example:
            >>> # Copy within same bucket
            >>> await client.copy_file("uploads/old.jpg", "uploads/new.jpg")
            >>>
            >>> # Copy between buckets
            >>> await client.copy_file(
            ...     "file.jpg", "file.jpg", source_bucket="bucket-a", dest_bucket="bucket-b"
            ... )
        """
        source_bucket = source_bucket or self.settings.bucket
        dest_bucket = dest_bucket or self.settings.bucket

        copy_source = {"Bucket": source_bucket, "Key": source_key}

        try:
            s3 = await self.ensure_client()
            await s3.copy_object(
                CopySource=copy_source,
                Bucket=dest_bucket,
                Key=dest_key,
            )

            logger.info(
                "File copied: %s/%s -> %s/%s",
                source_bucket,
                source_key,
                dest_bucket,
                dest_key,
                extra={
                    "source_bucket": source_bucket,
                    "source_key": source_key,
                    "dest_bucket": dest_bucket,
                    "dest_key": dest_key,
                },
            )
            return True

        except ClientError as e:
            logger.exception(
                "Failed to copy file from %s to %s",
                source_key,
                dest_key,
                extra={"error": str(e)},
            )
            raise map_boto_error(e, operation="copy", key=source_key) from e
        except Exception as e:
            logger.exception(
                "Unexpected error during file copy", extra={"error": str(e)}
            )
            raise StorageError(
                f"Failed to copy {source_key} to {dest_key}: {e}",
                code="STORAGE_COPY_ERROR",
                metadata={
                    "source_key": source_key,
                    "dest_key": dest_key,
                    "source_bucket": source_bucket,
                    "dest_bucket": dest_bucket,
                    "error": str(e),
                },
            ) from e

    async def move_file(
        self,
        source_key: str,
        dest_key: str,
        source_bucket: str | None = None,
        dest_bucket: str | None = None,
    ) -> bool:
        """Move file (copy then delete source).

        Args:
            source_key: Source object key.
            dest_key: Destination object key.
            source_bucket: Source bucket (uses default if not provided).
            dest_bucket: Destination bucket (uses default if not provided).

        Returns:
            True if move was successful.

        Raises:
            StorageError: If move operation fails.

        Example:
            >>> # Move within same bucket
            >>> await client.move_file("uploads/temp.jpg", "uploads/final.jpg")
            >>>
            >>> # Move between buckets
            >>> await client.move_file(
            ...     "file.jpg", "file.jpg", source_bucket="temp-bucket", dest_bucket="permanent-bucket"
            ... )
        """
        source_bucket = source_bucket or self.settings.bucket
        dest_bucket = dest_bucket or self.settings.bucket

        try:
            # First copy the file
            await self.copy_file(
                source_key=source_key,
                dest_key=dest_key,
                source_bucket=source_bucket,
                dest_bucket=dest_bucket,
            )

            # Then delete the source
            await self.delete_file(key=source_key, bucket=source_bucket)

            logger.info(
                "File moved: %s/%s -> %s/%s",
                source_bucket,
                source_key,
                dest_bucket,
                dest_key,
                extra={
                    "source_bucket": source_bucket,
                    "source_key": source_key,
                    "dest_bucket": dest_bucket,
                    "dest_key": dest_key,
                },
            )
            return True

        except Exception as e:
            logger.exception(
                "Failed to move file from %s to %s",
                source_key,
                dest_key,
                extra={"error": str(e)},
            )
            raise StorageError(
                f"Failed to move {source_key} to {dest_key}: {e}",
                code="STORAGE_MOVE_ERROR",
                metadata={
                    "source_key": source_key,
                    "dest_key": dest_key,
                    "source_bucket": source_bucket,
                    "dest_bucket": dest_bucket,
                    "error": str(e),
                },
            ) from e

    async def list_files(
        self,
        prefix: str = "",
        pattern: str | None = None,
        max_keys: int = 1000,
    ) -> list[dict[str, Any]]:
        """List files with optional glob pattern filtering.

        Args:
            prefix: Prefix to filter keys (e.g., "uploads/2024/").
            pattern: Optional glob pattern to match keys (e.g., "*.jpg", "**/*.png").
            max_keys: Maximum number of keys to return (default: 1000).

        Returns:
            List of file metadata dictionaries:
            [{"key": str, "size": int, "last_modified": datetime, "etag": str}, ...]

        Example:
            >>> # List all files in a prefix
            >>> files = await client.list_files(prefix="uploads/2024/")
            >>>
            >>> # List only JPEG files
            >>> jpg_files = await client.list_files(prefix="uploads/", pattern="*.jpg")
            >>>
            >>> # List all images recursively
            >>> images = await client.list_files(prefix="uploads/", pattern="**/*.{jpg,png,gif}")
        """
        bucket = self.settings.bucket

        try:
            s3 = await self.ensure_client()
            paginator = s3.get_paginator("list_objects_v2")

            files = []
            async for page in paginator.paginate(
                Bucket=bucket,
                Prefix=prefix,
                PaginationConfig={"MaxItems": max_keys},
            ):
                if "Contents" not in page:
                    continue

                for obj in page["Contents"]:
                    key = obj["Key"]

                    # Apply glob pattern filtering if provided
                    if pattern and not fnmatch.fnmatch(key, pattern):
                        continue

                    files.append({
                        "key": key,
                        "size": obj["Size"],
                        "last_modified": obj["LastModified"],
                        "etag": obj.get("ETag", "").strip('"'),
                    })

            logger.info(
                "Listed %s files",
                len(files),
                extra={
                    "bucket": bucket,
                    "prefix": prefix,
                    "pattern": pattern,
                    "count": len(files),
                },
            )

            return files

        except ClientError as e:
            logger.exception(
                "Failed to list files from storage", extra={"error": str(e)}
            )
            raise map_boto_error(e, operation="list_files", key=prefix) from e
        except Exception as e:
            logger.exception("Unexpected error listing files", extra={"error": str(e)})
            raise StorageError(
                f"Failed to list files with prefix {prefix}: {e}",
                code="STORAGE_LIST_ERROR",
                metadata={"prefix": prefix, "pattern": pattern, "error": str(e)},
            ) from e


__all__ = [
    "FileNotFoundError",
    "InvalidFileError",
    "StorageClient",
    "StorageClientError",
]
