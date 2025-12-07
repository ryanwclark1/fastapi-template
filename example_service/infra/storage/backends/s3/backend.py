"""S3-compatible storage backend implementation.

Implements the StorageBackend protocol for AWS S3, MinIO, and other
S3-compatible services using aioboto3.
"""

from __future__ import annotations

import hashlib
from io import BytesIO
import logging
from typing import TYPE_CHECKING, Any, BinaryIO, cast

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from example_service.infra.storage.exceptions import (
    StorageDownloadError,
    StorageError,
    StorageFileNotFoundError,
    StorageNotConfiguredError,
    StorageUploadError,
    map_boto_error,
)

if TYPE_CHECKING:
    from types import TracebackType

    from example_service.core.settings.storage import StorageSettings

from ..protocol import BucketInfo, ObjectMetadata, UploadResult

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


class S3Backend:
    """S3-compatible storage backend.

    Implements StorageBackend protocol for AWS S3, MinIO, and other
    S3-compatible services.

    Attributes:
        settings: Storage configuration settings
        backend_name: Name identifier for this backend ("s3")
        is_ready: Whether backend is initialized

    Example:
        backend = S3Backend(settings)
        await backend.startup()
        result = await backend.upload_object("file.txt", data)
        await backend.shutdown()
    """

    def __init__(self, settings: StorageSettings) -> None:
        """Initialize S3 backend.

        Args:
            settings: Storage settings with S3 configuration

        Raises:
            StorageNotConfiguredError: If aioboto3 not installed or settings invalid
        """
        if not AIOBOTO3_AVAILABLE:
            msg = "aioboto3 is required for S3 backend. Install with: pip install aioboto3"
            raise StorageNotConfiguredError(msg)

        if not settings.is_configured:
            msg = "S3 backend not configured. Set STORAGE_ENABLED=true and provide credentials."
            raise StorageNotConfiguredError(msg)

        self.settings = settings
        self._session = aioboto3.Session()
        self._client = None
        self._client_context = None

    @property
    def backend_name(self) -> str:
        """Backend name identifier."""
        return "s3"

    @property
    def is_ready(self) -> bool:
        """Check if backend is initialized and ready."""
        return self._client is not None

    # ========================================================================
    # Lifecycle Management
    # ========================================================================

    async def startup(self) -> None:
        """Initialize S3 client and connection pool."""
        if self._client is not None:
            logger.debug("S3 backend already initialized")
            return

        logger.info(
            "Initializing S3 backend",
            extra={
                "bucket": self.settings.bucket,
                "endpoint": self.settings.endpoint,
                "region": self.settings.region,
            },
        )

        try:
            # Create boto3 config with retry and connection pooling
            boto_config = Config(
                retries={
                    "max_attempts": self.settings.max_retries,
                    "mode": self.settings.retry_mode,
                },
                connect_timeout=self.settings.timeout,
                read_timeout=self.settings.timeout,
                max_pool_connections=self.settings.max_pool_connections,
            )

            # Get base client configuration
            client_config = self._get_client_config()

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

            logger.info("S3 backend initialized successfully")

        except Exception as e:
            logger.exception("Failed to initialize S3 backend", extra={"error": str(e)})
            raise StorageError(
                f"Failed to initialize S3 backend: {e}",
                code="STORAGE_INITIALIZATION_ERROR",
            ) from e

    async def shutdown(self) -> None:
        """Shutdown S3 client gracefully."""
        if self._client_context is None:
            logger.debug("S3 backend not initialized, nothing to shutdown")
            return

        logger.info("Shutting down S3 backend")

        try:
            await self._client_context.__aexit__(None, None, None)
        except Exception as e:
            logger.warning(f"Error closing S3 client: {e}")
        finally:
            self._client = None
            self._client_context = None

        logger.info("S3 backend shutdown complete")

    async def health_check(self) -> bool:
        """Check S3 connectivity and credentials.

        Returns:
            True if healthy, False otherwise
        """
        if self._client is None:
            return False

        try:
            # HEAD request on the bucket
            await self._client.head_bucket(Bucket=self.settings.bucket)
            return True
        except Exception as e:
            logger.warning(
                "S3 health check failed",
                extra={"error": str(e), "bucket": self.settings.bucket},
            )
            return False

    def _get_client_config(self) -> dict[str, Any]:
        """Get boto3 client configuration."""
        config: dict[str, Any] = {
            "region_name": self.settings.region,
            "use_ssl": self.settings.use_ssl,
            "verify": self.settings.verify_ssl,
        }

        # Add credentials if provided (static auth)
        if (
            self.settings.access_key is not None
            and self.settings.secret_key is not None
        ):
            config["aws_access_key_id"] = self.settings.access_key.get_secret_value()
            config["aws_secret_access_key"] = (
                self.settings.secret_key.get_secret_value()
            )

        # Add endpoint for MinIO/LocalStack
        if self.settings.endpoint:
            config["endpoint_url"] = self.settings.endpoint

        return config

    def _ensure_client(self) -> Any:
        """Ensure client is initialized.

        Returns:
            Initialized S3 client

        Raises:
            StorageNotConfiguredError: If client not initialized
        """
        if self._client is None:
            msg = "S3 backend not initialized. Call startup() first."
            raise StorageNotConfiguredError(msg)
        return self._client

    # ========================================================================
    # Core Object Operations
    # ========================================================================

    async def upload_object(
        self,
        key: str,
        data: BinaryIO,
        bucket: str | None = None,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
        acl: str | None = None,
        storage_class: str | None = None,
    ) -> UploadResult:
        """Upload an object to S3.

        Args:
            key: S3 object key
            data: Binary data to upload
            bucket: Target bucket (uses default if None)
            content_type: MIME type
            metadata: Custom metadata
            acl: Canned ACL (e.g., 'private', 'public-read')
            storage_class: Storage class (e.g., 'STANDARD', 'GLACIER')

        Returns:
            UploadResult with upload information

        Raises:
            StorageUploadError: If upload fails
        """
        client = self._ensure_client()
        bucket = bucket or self.settings.bucket

        # Calculate size and checksum
        data.seek(0)
        file_data = data.read()
        size_bytes = len(file_data)
        checksum_sha256 = hashlib.sha256(file_data).hexdigest()

        # Reset for upload
        file_obj = BytesIO(file_data)

        # Build extra args
        extra_args: dict[str, Any] = {}
        if content_type:
            extra_args["ContentType"] = content_type
        if metadata:
            extra_args["Metadata"] = metadata
        if acl:
            extra_args["ACL"] = acl
        if storage_class:
            extra_args["StorageClass"] = storage_class

        try:
            response = await client.put_object(
                Bucket=bucket,
                Key=key,
                Body=file_obj,
                **extra_args,
            )

            etag = response.get("ETag", "").strip('"')
            version_id = response.get("VersionId")

            logger.info(
                "Object uploaded to S3",
                extra={
                    "key": key,
                    "bucket": bucket,
                    "size_bytes": size_bytes,
                    "content_type": content_type,
                    "acl": acl,
                    "storage_class": storage_class,
                },
            )

            return UploadResult(
                key=key,
                bucket=bucket,
                etag=etag,
                size_bytes=size_bytes,
                checksum_sha256=checksum_sha256,
                version_id=version_id,
            )

        except ClientError as e:
            logger.exception("Failed to upload object to S3", extra={"error": str(e)})
            raise map_boto_error(e, operation="upload", key=key) from e
        except Exception as e:
            logger.exception(
                "Unexpected error during S3 upload", extra={"error": str(e)}
            )
            raise StorageUploadError(
                f"Failed to upload {key}: {e}",
                metadata={"key": key, "bucket": bucket, "error": str(e)},
            ) from e

    async def download_object(
        self,
        key: str,
        bucket: str | None = None,
    ) -> bytes:
        """Download an object from S3.

        Args:
            key: S3 object key
            bucket: Source bucket (uses default if None)

        Returns:
            Object data as bytes

        Raises:
            StorageFileNotFoundError: If object doesn't exist
            StorageDownloadError: If download fails
        """
        client = self._ensure_client()
        bucket = bucket or self.settings.bucket

        try:
            response = await client.get_object(Bucket=bucket, Key=key)
            file_data_raw = await response["Body"].read()
            file_data: bytes = (
                bytes(file_data_raw)
                if not isinstance(file_data_raw, bytes)
                else file_data_raw
            )

            logger.info(
                "Object downloaded from S3",
                extra={"key": key, "bucket": bucket, "size_bytes": len(file_data)},
            )
            return file_data

        except ClientError as e:
            logger.exception(
                "Failed to download object from S3", extra={"error": str(e)}
            )
            raise map_boto_error(e, operation="download", key=key) from e
        except Exception as e:
            logger.exception(
                "Unexpected error during S3 download", extra={"error": str(e)}
            )
            raise StorageDownloadError(
                f"Failed to download {key}: {e}",
                metadata={"key": key, "bucket": bucket, "error": str(e)},
            ) from e

    async def delete_object(
        self,
        key: str,
        bucket: str | None = None,
    ) -> bool:
        """Delete an object from S3.

        Args:
            key: S3 object key
            bucket: Target bucket (uses default if None)

        Returns:
            True if deleted successfully

        Raises:
            StorageError: If deletion fails
        """
        client = self._ensure_client()
        bucket = bucket or self.settings.bucket

        try:
            await client.delete_object(Bucket=bucket, Key=key)

            logger.info("Object deleted from S3", extra={"key": key, "bucket": bucket})
            return True

        except ClientError as e:
            logger.exception("Failed to delete object from S3", extra={"error": str(e)})
            raise map_boto_error(e, operation="delete", key=key) from e
        except Exception as e:
            logger.exception(
                "Unexpected error during S3 deletion", extra={"error": str(e)}
            )
            raise StorageError(
                f"Failed to delete {key}: {e}",
                code="STORAGE_DELETE_ERROR",
                metadata={"key": key, "bucket": bucket, "error": str(e)},
            ) from e

    async def object_exists(
        self,
        key: str,
        bucket: str | None = None,
    ) -> bool:
        """Check if an object exists in S3.

        Args:
            key: S3 object key
            bucket: Target bucket (uses default if None)

        Returns:
            True if object exists
        """
        client = self._ensure_client()
        bucket = bucket or self.settings.bucket

        try:
            await client.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError as e:
            error_code = (
                e.response.get("Error", {}).get("Code", "")
                if hasattr(e, "response")
                else ""
            )
            if error_code in {"NoSuchKey", "404", "NotFound"}:
                return False
            # Other errors should be raised
            logger.exception("Error checking object existence", extra={"error": str(e)})
            raise map_boto_error(e, operation="object_exists", key=key) from e
        except Exception:
            return False

    async def get_object_metadata(
        self,
        key: str,
        bucket: str | None = None,
    ) -> ObjectMetadata | None:
        """Get object metadata from S3.

        Args:
            key: S3 object key
            bucket: Target bucket (uses default if None)

        Returns:
            ObjectMetadata if object exists, None otherwise
        """
        client = self._ensure_client()
        bucket = bucket or self.settings.bucket

        try:
            response = await client.head_object(Bucket=bucket, Key=key)

            return ObjectMetadata(
                key=key,
                size_bytes=response.get("ContentLength", 0),
                content_type=response.get("ContentType"),
                last_modified=response.get("LastModified"),
                etag=response.get("ETag", "").strip('"'),
                storage_class=response.get("StorageClass"),
                custom_metadata=response.get("Metadata", {}),
                acl=None,  # ACL requires separate call
            )

        except ClientError as e:
            error_code = (
                e.response.get("Error", {}).get("Code", "")
                if hasattr(e, "response")
                else ""
            )
            if error_code in {"NoSuchKey", "404", "NotFound"}:
                return None
            logger.exception(
                "Failed to get object metadata from S3", extra={"error": str(e)}
            )
            raise map_boto_error(e, operation="get_object_metadata", key=key) from e
        except Exception as e:
            logger.exception(
                "Unexpected error getting object metadata", extra={"error": str(e)}
            )
            raise StorageError(
                f"Failed to get metadata for {key}: {e}",
                code="STORAGE_METADATA_ERROR",
                metadata={"key": key, "bucket": bucket, "error": str(e)},
            ) from e

    # ========================================================================
    # Advanced Object Operations
    # ========================================================================

    async def copy_object(
        self,
        source_key: str,
        dest_key: str,
        source_bucket: str | None = None,
        dest_bucket: str | None = None,
        acl: str | None = None,
    ) -> bool:
        """Copy an object within or between buckets.

        Args:
            source_key: Source object key
            dest_key: Destination object key
            source_bucket: Source bucket (uses default if None)
            dest_bucket: Destination bucket (uses default if None)
            acl: ACL for destination object

        Returns:
            True if copied successfully

        Raises:
            StorageFileNotFoundError: If source doesn't exist
            StorageError: If copy fails
        """
        client = self._ensure_client()
        source_bucket = source_bucket or self.settings.bucket
        dest_bucket = dest_bucket or self.settings.bucket

        copy_source = {"Bucket": source_bucket, "Key": source_key}

        try:
            extra_args: dict[str, Any] = {}
            if acl:
                extra_args["ACL"] = acl

            await client.copy_object(
                CopySource=copy_source,
                Bucket=dest_bucket,
                Key=dest_key,
                **extra_args,
            )

            logger.info(
                "Object copied in S3",
                extra={
                    "source_bucket": source_bucket,
                    "source_key": source_key,
                    "dest_bucket": dest_bucket,
                    "dest_key": dest_key,
                    "acl": acl,
                },
            )
            return True

        except ClientError as e:
            error_code = (
                e.response.get("Error", {}).get("Code", "")
                if hasattr(e, "response")
                else ""
            )
            if error_code in {"NoSuchKey", "404", "NotFound"}:
                raise StorageFileNotFoundError(
                    f"Source object not found: {source_key}",
                    metadata={"key": source_key, "bucket": source_bucket},
                ) from e
            logger.exception("Failed to copy object in S3", extra={"error": str(e)})
            raise map_boto_error(e, operation="copy", key=source_key) from e
        except Exception as e:
            logger.exception("Unexpected error during S3 copy", extra={"error": str(e)})
            raise StorageError(
                f"Failed to copy {source_key} to {dest_key}: {e}",
                code="STORAGE_COPY_ERROR",
                metadata={
                    "source_key": source_key,
                    "dest_key": dest_key,
                    "error": str(e),
                },
            ) from e

    async def move_object(
        self,
        source_key: str,
        dest_key: str,
        source_bucket: str | None = None,
        dest_bucket: str | None = None,
        acl: str | None = None,
    ) -> bool:
        """Move an object (copy + delete source).

        Args:
            source_key: Source object key
            dest_key: Destination object key
            source_bucket: Source bucket (uses default if None)
            dest_bucket: Destination bucket (uses default if None)
            acl: ACL for destination object

        Returns:
            True if moved successfully

        Raises:
            StorageFileNotFoundError: If source doesn't exist
            StorageError: If move fails
        """
        # Copy first
        await self.copy_object(
            source_key=source_key,
            dest_key=dest_key,
            source_bucket=source_bucket,
            dest_bucket=dest_bucket,
            acl=acl,
        )

        # Delete source after successful copy
        await self.delete_object(key=source_key, bucket=source_bucket)

        logger.info(
            "Object moved in S3",
            extra={
                "source_key": source_key,
                "dest_key": dest_key,
                "source_bucket": source_bucket or self.settings.bucket,
                "dest_bucket": dest_bucket or self.settings.bucket,
            },
        )
        return True

    async def list_objects(
        self,
        prefix: str = "",
        bucket: str | None = None,
        max_keys: int = 1000,
        continuation_token: str | None = None,
    ) -> tuple[list[ObjectMetadata], str | None]:
        """List objects with pagination support.

        Args:
            prefix: Filter by key prefix
            bucket: Target bucket (uses default if None)
            max_keys: Maximum objects to return
            continuation_token: Token for next page

        Returns:
            Tuple of (object list, next continuation token or None)
        """
        client = self._ensure_client()
        bucket = bucket or self.settings.bucket

        try:
            kwargs: dict[str, Any] = {
                "Bucket": bucket,
                "Prefix": prefix,
                "MaxKeys": max_keys,
            }
            if continuation_token:
                kwargs["ContinuationToken"] = continuation_token

            response = await client.list_objects_v2(**kwargs)

            objects: list[ObjectMetadata] = []
            for item in response.get("Contents", []):
                objects.append(
                    ObjectMetadata(
                        key=item["Key"],
                        size_bytes=item["Size"],
                        content_type=None,  # Not returned by list_objects_v2
                        last_modified=item["LastModified"],
                        etag=item.get("ETag", "").strip('"'),
                        storage_class=item.get("StorageClass"),
                        custom_metadata={},
                        acl=None,
                    )
                )

            next_token = response.get("NextContinuationToken")

            logger.info(
                "Listed objects from S3",
                extra={
                    "bucket": bucket,
                    "prefix": prefix,
                    "count": len(objects),
                    "has_more": next_token is not None,
                },
            )

            return objects, next_token

        except ClientError as e:
            logger.exception("Failed to list objects in S3", extra={"error": str(e)})
            raise map_boto_error(e, operation="list", key=prefix) from e
        except Exception as e:
            logger.exception("Unexpected error during S3 list", extra={"error": str(e)})
            raise StorageError(
                f"Failed to list objects with prefix {prefix}: {e}",
                code="STORAGE_LIST_ERROR",
                metadata={"prefix": prefix, "bucket": bucket, "error": str(e)},
            ) from e

    async def stream_objects(
        self,
        prefix: str = "",
        bucket: str | None = None,
    ) -> AsyncIterator[ObjectMetadata]:
        """Stream all objects matching prefix (automatic pagination).

        Args:
            prefix: Filter by key prefix
            bucket: Target bucket (uses default if None)

        Yields:
            ObjectMetadata for each object
        """
        continuation_token: str | None = None

        while True:
            objects, continuation_token = await self.list_objects(
                prefix=prefix,
                bucket=bucket,
                max_keys=1000,
                continuation_token=continuation_token,
            )

            for obj in objects:
                yield obj

            if continuation_token is None:
                break

    # ========================================================================
    # Presigned URLs
    # ========================================================================

    async def generate_presigned_download_url(
        self,
        key: str,
        bucket: str | None = None,
        expires_in: int = 3600,
    ) -> str:
        """Generate a presigned URL for downloading an object.

        Args:
            key: Object key/path
            bucket: Target bucket (uses default if None)
            expires_in: URL expiry in seconds

        Returns:
            Presigned URL string

        Raises:
            StorageError: If URL generation fails
        """
        client = self._ensure_client()
        bucket = bucket or self.settings.bucket

        try:
            url = await client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=expires_in,
            )

            logger.info(
                "Generated presigned download URL",
                extra={"key": key, "bucket": bucket, "expires_in": expires_in},
            )
            return cast("str", url)

        except ClientError as e:
            logger.exception(
                "Failed to generate presigned URL", extra={"error": str(e)}
            )
            raise map_boto_error(e, operation="generate_presigned_url", key=key) from e
        except Exception as e:
            logger.exception(
                "Unexpected error generating presigned URL", extra={"error": str(e)}
            )
            raise StorageError(
                f"Failed to generate presigned URL for {key}: {e}",
                code="STORAGE_PRESIGNED_URL_ERROR",
                metadata={"key": key, "bucket": bucket, "error": str(e)},
            ) from e

    async def generate_presigned_upload_url(
        self,
        key: str,
        bucket: str | None = None,
        content_type: str | None = None,
        expires_in: int = 3600,
    ) -> dict[str, Any]:
        """Generate presigned POST data for browser uploads.

        Args:
            key: Object key/path for upload
            bucket: Target bucket (uses default if None)
            content_type: Expected MIME type
            expires_in: URL expiry in seconds

        Returns:
            Dict with 'url' and 'fields' for POST request

        Raises:
            StorageError: If URL generation fails
        """
        client = self._ensure_client()
        bucket = bucket or self.settings.bucket

        try:
            conditions: list[Any] = [{"key": key}]
            fields: dict[str, str] = {"key": key}

            if content_type:
                conditions.append({"Content-Type": content_type})
                fields["Content-Type"] = content_type

            response = await client.generate_presigned_post(
                Bucket=bucket,
                Key=key,
                Fields=fields,
                Conditions=conditions,
                ExpiresIn=expires_in,
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
            return cast("dict[str, Any]", response)

        except ClientError as e:
            logger.exception(
                "Failed to generate presigned POST", extra={"error": str(e)}
            )
            raise map_boto_error(e, operation="generate_presigned_post", key=key) from e
        except Exception as e:
            logger.exception(
                "Unexpected error generating presigned POST", extra={"error": str(e)}
            )
            raise StorageError(
                f"Failed to generate presigned POST for {key}: {e}",
                code="STORAGE_PRESIGNED_POST_ERROR",
                metadata={"key": key, "bucket": bucket, "error": str(e)},
            ) from e

    # ========================================================================
    # Bucket Management
    # ========================================================================

    async def create_bucket(
        self,
        bucket: str,
        region: str | None = None,
        acl: str | None = None,
    ) -> bool:
        """Create a new bucket.

        Args:
            bucket: Bucket name
            region: Geographic region
            acl: Bucket-level ACL

        Returns:
            True if created successfully

        Raises:
            StorageError: If creation fails
        """
        client = self._ensure_client()
        region = region or self.settings.region

        try:
            kwargs: dict[str, Any] = {"Bucket": bucket}

            if acl:
                kwargs["ACL"] = acl

            # S3 requires CreateBucketConfiguration for regions other than us-east-1
            if region and region != "us-east-1":
                kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}

            await client.create_bucket(**kwargs)

            logger.info(
                "Bucket created in S3",
                extra={"bucket": bucket, "region": region, "acl": acl},
            )
            return True

        except ClientError as e:
            error_code = (
                e.response.get("Error", {}).get("Code", "")
                if hasattr(e, "response")
                else ""
            )
            if error_code == "BucketAlreadyOwnedByYou":
                logger.warning(f"Bucket {bucket} already exists and is owned by you")
                return True
            logger.exception("Failed to create bucket in S3", extra={"error": str(e)})
            raise map_boto_error(e, operation="create_bucket", key=bucket) from e
        except Exception as e:
            logger.exception(
                "Unexpected error creating bucket", extra={"error": str(e)}
            )
            raise StorageError(
                f"Failed to create bucket {bucket}: {e}",
                code="STORAGE_CREATE_BUCKET_ERROR",
                metadata={"bucket": bucket, "region": region, "error": str(e)},
            ) from e

    async def delete_bucket(
        self,
        bucket: str,
        force: bool = False,
    ) -> bool:
        """Delete a bucket.

        Args:
            bucket: Bucket name
            force: If True, delete even if not empty (use with caution!)

        Returns:
            True if deleted successfully

        Raises:
            StorageError: If deletion fails
        """
        client = self._ensure_client()

        try:
            # If force=True, delete all objects first
            if force:
                logger.warning(
                    "Force deleting bucket - removing all objects first",
                    extra={"bucket": bucket},
                )

                # Stream and delete all objects
                async for obj in self.stream_objects(bucket=bucket):
                    await self.delete_object(key=obj.key, bucket=bucket)

            await client.delete_bucket(Bucket=bucket)

            logger.info(
                "Bucket deleted from S3", extra={"bucket": bucket, "force": force}
            )
            return True

        except ClientError as e:
            error_code = (
                e.response.get("Error", {}).get("Code", "")
                if hasattr(e, "response")
                else ""
            )
            if error_code == "BucketNotEmpty":
                raise StorageError(
                    f"Bucket {bucket} is not empty. Use force=True to delete all contents.",
                    code="STORAGE_BUCKET_NOT_EMPTY",
                    metadata={"bucket": bucket},
                ) from e
            logger.exception("Failed to delete bucket from S3", extra={"error": str(e)})
            raise map_boto_error(e, operation="delete_bucket", key=bucket) from e
        except Exception as e:
            logger.exception(
                "Unexpected error deleting bucket", extra={"error": str(e)}
            )
            raise StorageError(
                f"Failed to delete bucket {bucket}: {e}",
                code="STORAGE_DELETE_BUCKET_ERROR",
                metadata={"bucket": bucket, "error": str(e)},
            ) from e

    async def list_buckets(self) -> list[BucketInfo]:
        """List all accessible buckets.

        Returns:
            List of BucketInfo objects

        Raises:
            StorageError: If listing fails
        """
        client = self._ensure_client()

        try:
            response = await client.list_buckets()

            buckets: list[BucketInfo] = []
            for bucket in response.get("Buckets", []):
                # Try to get bucket location (region)
                region = None
                try:
                    location_response = await client.get_bucket_location(
                        Bucket=bucket["Name"]
                    )
                    region = location_response.get("LocationConstraint") or "us-east-1"
                except Exception as e:
                    logger.debug(
                        "Failed to get bucket location",
                        extra={"bucket": bucket["Name"], "error": str(e)},
                    )

                # Try to get versioning status
                versioning_enabled = False
                try:
                    versioning_response = await client.get_bucket_versioning(
                        Bucket=bucket["Name"]
                    )
                    versioning_enabled = versioning_response.get("Status") == "Enabled"
                except Exception as e:
                    logger.debug(
                        "Failed to get bucket versioning",
                        extra={"bucket": bucket["Name"], "error": str(e)},
                    )

                buckets.append(
                    BucketInfo(
                        name=bucket["Name"],
                        region=region,
                        creation_date=bucket.get("CreationDate"),
                        versioning_enabled=versioning_enabled,
                    )
                )

            logger.info("Listed buckets from S3", extra={"count": len(buckets)})
            return buckets

        except ClientError as e:
            logger.exception("Failed to list buckets from S3", extra={"error": str(e)})
            raise map_boto_error(e, operation="list_buckets", key="") from e
        except Exception as e:
            logger.exception(
                "Unexpected error listing buckets", extra={"error": str(e)}
            )
            raise StorageError(
                f"Failed to list buckets: {e}",
                code="STORAGE_LIST_BUCKETS_ERROR",
                metadata={"error": str(e)},
            ) from e

    async def bucket_exists(self, bucket: str) -> bool:
        """Check if a bucket exists and is accessible.

        Args:
            bucket: Bucket name

        Returns:
            True if bucket exists
        """
        client = self._ensure_client()

        try:
            await client.head_bucket(Bucket=bucket)
            return True
        except ClientError as e:
            error_code = (
                e.response.get("Error", {}).get("Code", "")
                if hasattr(e, "response")
                else ""
            )
            if error_code in {"NoSuchBucket", "404", "NotFound"}:
                return False
            # Other errors (like permission denied) should be raised
            logger.exception("Error checking bucket existence", extra={"error": str(e)})
            raise map_boto_error(e, operation="bucket_exists", key=bucket) from e
        except Exception:
            return False

    # ========================================================================
    # ACL Management
    # ========================================================================

    async def set_object_acl(
        self,
        key: str,
        acl: str,
        bucket: str | None = None,
    ) -> bool:
        """Set Access Control List on an existing object.

        Args:
            key: Object key/path
            acl: Canned ACL (e.g., 'private', 'public-read')
            bucket: Target bucket (uses default if None)

        Returns:
            True if ACL set successfully

        Raises:
            StorageFileNotFoundError: If object doesn't exist
            StorageError: If ACL setting fails
        """
        client = self._ensure_client()
        bucket = bucket or self.settings.bucket

        try:
            await client.put_object_acl(Bucket=bucket, Key=key, ACL=acl)

            logger.info(
                "Object ACL updated in S3",
                extra={"key": key, "bucket": bucket, "acl": acl},
            )
            return True

        except ClientError as e:
            error_code = (
                e.response.get("Error", {}).get("Code", "")
                if hasattr(e, "response")
                else ""
            )
            if error_code in {"NoSuchKey", "404", "NotFound"}:
                raise StorageFileNotFoundError(
                    f"Object not found: {key}",
                    metadata={"key": key, "bucket": bucket},
                ) from e
            logger.exception("Failed to set object ACL in S3", extra={"error": str(e)})
            raise map_boto_error(e, operation="set_object_acl", key=key) from e
        except Exception as e:
            logger.exception(
                "Unexpected error setting object ACL", extra={"error": str(e)}
            )
            raise StorageError(
                f"Failed to set ACL for {key}: {e}",
                code="STORAGE_SET_ACL_ERROR",
                metadata={"key": key, "bucket": bucket, "acl": acl, "error": str(e)},
            ) from e

    async def get_object_acl(
        self,
        key: str,
        bucket: str | None = None,
    ) -> dict[str, Any]:
        """Get Access Control List of an object.

        Args:
            key: Object key/path
            bucket: Target bucket (uses default if None)

        Returns:
            ACL information (backend-specific format)

        Raises:
            StorageFileNotFoundError: If object doesn't exist
            StorageError: If ACL retrieval fails
        """
        client = self._ensure_client()
        bucket = bucket or self.settings.bucket

        try:
            response = await client.get_object_acl(Bucket=bucket, Key=key)

            # Return the full ACL response (Grants, Owner, etc.)
            acl_data = {
                "owner": response.get("Owner", {}),
                "grants": response.get("Grants", []),
            }

            logger.info(
                "Retrieved object ACL from S3", extra={"key": key, "bucket": bucket}
            )
            return acl_data

        except ClientError as e:
            error_code = (
                e.response.get("Error", {}).get("Code", "")
                if hasattr(e, "response")
                else ""
            )
            if error_code in {"NoSuchKey", "404", "NotFound"}:
                raise StorageFileNotFoundError(
                    f"Object not found: {key}",
                    metadata={"key": key, "bucket": bucket},
                ) from e
            logger.exception(
                "Failed to get object ACL from S3", extra={"error": str(e)}
            )
            raise map_boto_error(e, operation="get_object_acl", key=key) from e
        except Exception as e:
            logger.exception(
                "Unexpected error getting object ACL", extra={"error": str(e)}
            )
            raise StorageError(
                f"Failed to get ACL for {key}: {e}",
                code="STORAGE_GET_ACL_ERROR",
                metadata={"key": key, "bucket": bucket, "error": str(e)},
            ) from e

    # ========================================================================
    # Advanced Features (Optional)
    # ========================================================================

    async def get_storage_class_summary(
        self,
        prefix: str = "",
        bucket: str | None = None,
    ) -> dict[str, int]:
        """Get total bytes per storage class.

        Args:
            prefix: Filter by key prefix
            bucket: Target bucket (uses default if None)

        Returns:
            Dict mapping storage class name to total bytes
            Example: {"STANDARD": 1024000, "GLACIER": 5242880}
        """
        summary: dict[str, int] = {}

        async for obj in self.stream_objects(prefix=prefix, bucket=bucket):
            storage_class = obj.storage_class or "STANDARD"
            summary[storage_class] = summary.get(storage_class, 0) + obj.size_bytes

        logger.info(
            "Generated storage class summary",
            extra={
                "prefix": prefix,
                "bucket": bucket or self.settings.bucket,
                "summary": summary,
            },
        )
        return summary

    # ========================================================================
    # Context Manager Support (Optional Convenience)
    # ========================================================================

    async def __aenter__(self) -> S3Backend:
        """Async context manager entry."""
        await self.startup()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Async context manager exit."""
        await self.shutdown()
