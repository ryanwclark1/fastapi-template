"""High-level storage service with singleton pattern and full observability.

This module provides the main interface for storage operations with:
- Singleton pattern for application-wide access
- Automatic OpenTelemetry spans and Prometheus metrics
- Proper lifecycle management (startup/shutdown)
- Health check integration
- All operations from StorageClient with added instrumentation
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, BinaryIO

if TYPE_CHECKING:
    from collections.abc import Callable

    from example_service.core.settings.storage import StorageSettings

from example_service.core.settings import get_storage_settings

from .client import StorageClient
from .exceptions import StorageNotConfiguredError
from .instrumentation import track_storage_operation

logger = logging.getLogger(__name__)


class StorageService:
    """High-level storage service with observability.

    Provides:
    - Singleton pattern for app-wide access
    - Automatic metrics and tracing for all operations
    - Lifecycle management (startup/shutdown)
    - Health check integration

    Example:
        # Get singleton instance
        service = get_storage_service()

        # In lifespan
        await service.startup()

        # Use in routes
        result = await service.upload_file(file, key="path/to/file.txt")

        # Shutdown
        await service.shutdown()
    """

    def __init__(self, settings: StorageSettings | None = None) -> None:
        """Initialize storage service.

        Args:
            settings: Optional settings override. If not provided,
                     loads from environment via get_storage_settings()
        """
        self._settings = settings or get_storage_settings()
        self._client: StorageClient | None = None
        self._initialized = False

    @property
    def is_ready(self) -> bool:
        """Check if the service is initialized and ready for operations."""
        return self._initialized and self._client is not None and self._client.is_ready

    @property
    def settings(self) -> StorageSettings:
        """Get the storage settings."""
        return self._settings

    async def startup(self) -> None:
        """Initialize the storage client.

        Called during application lifespan startup.
        Creates the client, validates connection, and optionally
        registers with health aggregator.

        Raises:
            StorageNotConfiguredError: If storage is not configured
            StorageError: If initialization fails
        """
        if not self._settings.is_configured:
            logger.info("Storage not configured, skipping initialization")
            return

        logger.info(
            "Starting storage service",
            extra={
                "bucket": self._settings.bucket,
                "endpoint": self._settings.endpoint,
            },
        )

        self._client = StorageClient(self._settings)
        await self._client.startup()
        self._initialized = True

        # Register health provider if enabled
        if self._settings.health_check_enabled:
            self._register_health_provider()

        logger.info("Storage service started successfully")

    async def shutdown(self) -> None:
        """Shutdown the storage client gracefully.

        Called during application lifespan shutdown.
        Closes connections and cleans up resources.
        """
        if not self._initialized or self._client is None:
            logger.debug("Storage service not initialized, nothing to shutdown")
            return

        logger.info("Shutting down storage service")
        await self._client.shutdown()
        self._initialized = False
        logger.info("Storage service shutdown complete")

    async def health_check(self) -> bool:
        """Check storage service health.

        Returns:
            True if healthy, False otherwise
        """
        if not self.is_ready or self._client is None:
            return False
        return await self._client.health_check()

    def _register_health_provider(self) -> None:
        """Register health provider with the health aggregator."""
        try:
            from example_service.features.health.service import get_health_aggregator
            from example_service.features.health.storage_provider import StorageHealthProvider

            aggregator = get_health_aggregator()
            if aggregator:
                provider = StorageHealthProvider(self)
                aggregator.add_provider(provider)
                logger.debug("Registered storage health provider")
        except Exception as e:
            logger.warning(
                "Failed to register storage health provider",
                extra={"error": str(e)},
            )

    def _ensure_ready(self) -> StorageClient:
        """Ensure the service is ready and return the client.

        Raises:
            StorageNotConfiguredError: If service is not ready
        """
        if not self.is_ready or self._client is None:
            raise StorageNotConfiguredError(
                message="Storage service is not initialized",
                metadata={"is_configured": self._settings.is_configured},
            )
        return self._client

    # ========== File Operations with Instrumentation ==========

    async def upload_file(
        self,
        file_obj: BinaryIO,
        key: str,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
        bucket: str | None = None,
    ) -> dict[str, Any]:
        """Upload a file with automatic instrumentation.

        Args:
            file_obj: File-like object to upload
            key: S3 object key
            content_type: MIME content type
            metadata: Custom metadata
            bucket: Optional bucket override

        Returns:
            Upload result dict with key, bucket, etag, size_bytes, checksum
        """
        client = self._ensure_ready()

        async with track_storage_operation(
            "upload",
            key=key,
            bucket=bucket or self._settings.bucket,
            content_type=content_type,
        ) as ctx:
            result = await client.upload_file(file_obj, key, content_type, metadata, bucket)
            ctx["result_size"] = result.get("size_bytes")
            ctx["checksum"] = result.get("checksum_sha256")
            return result

    async def download_file(
        self,
        key: str,
        bucket: str | None = None,
    ) -> bytes:
        """Download a file with automatic instrumentation.

        Args:
            key: S3 object key
            bucket: Optional bucket override

        Returns:
            File contents as bytes
        """
        client = self._ensure_ready()

        async with track_storage_operation(
            "download",
            key=key,
            bucket=bucket or self._settings.bucket,
        ) as ctx:
            data = await client.download_file(key, bucket)
            ctx["result_size"] = len(data)
            return data

    async def delete_file(
        self,
        key: str,
        bucket: str | None = None,
    ) -> bool:
        """Delete a file with automatic instrumentation.

        Args:
            key: S3 object key
            bucket: Optional bucket override

        Returns:
            True if deleted successfully
        """
        client = self._ensure_ready()

        async with track_storage_operation(
            "delete",
            key=key,
            bucket=bucket or self._settings.bucket,
        ):
            return await client.delete_file(key, bucket)

    async def file_exists(
        self,
        key: str,
        bucket: str | None = None,
    ) -> bool:
        """Check if a file exists.

        Args:
            key: S3 object key
            bucket: Optional bucket override

        Returns:
            True if file exists
        """
        client = self._ensure_ready()
        return await client.file_exists(key, bucket)

    async def get_file_info(
        self,
        key: str,
        bucket: str | None = None,
    ) -> dict[str, Any] | None:
        """Get file metadata.

        Args:
            key: S3 object key
            bucket: Optional bucket override

        Returns:
            File info dict or None if not found
        """
        client = self._ensure_ready()
        return await client.get_file_info(key, bucket)

    async def get_presigned_url(
        self,
        key: str,
        expires_in: int | None = None,
        bucket: str | None = None,
    ) -> str:
        """Generate a presigned download URL.

        Args:
            key: S3 object key
            expires_in: URL expiry in seconds
            bucket: Optional bucket override

        Returns:
            Presigned URL string
        """
        client = self._ensure_ready()

        from .metrics import storage_presigned_urls_generated

        storage_presigned_urls_generated.labels(type="download").inc()

        return await client.get_presigned_url(key, expires_in, bucket)

    async def generate_presigned_upload(
        self,
        key: str,
        content_type: str,
        expires_in: int | None = None,
        bucket: str | None = None,
    ) -> dict[str, Any]:
        """Generate a presigned upload URL for browser uploads.

        Args:
            key: S3 object key
            content_type: Expected content type
            expires_in: URL expiry in seconds
            bucket: Optional bucket override

        Returns:
            Dict with url and fields for POST upload
        """
        client = self._ensure_ready()

        from .metrics import storage_presigned_urls_generated

        storage_presigned_urls_generated.labels(type="upload").inc()

        return await client.generate_presigned_upload(key, content_type, expires_in, bucket)

    async def copy_file(
        self,
        source_key: str,
        dest_key: str,
        source_bucket: str | None = None,
        dest_bucket: str | None = None,
    ) -> bool:
        """Copy a file with automatic instrumentation.

        Args:
            source_key: Source object key
            dest_key: Destination object key
            source_bucket: Source bucket override
            dest_bucket: Destination bucket override

        Returns:
            True if copied successfully
        """
        client = self._ensure_ready()

        async with track_storage_operation(
            "copy",
            key=source_key,
            bucket=source_bucket or self._settings.bucket,
            metadata={"dest_key": dest_key},
        ):
            return await client.copy_file(source_key, dest_key, source_bucket, dest_bucket)

    async def move_file(
        self,
        source_key: str,
        dest_key: str,
        source_bucket: str | None = None,
        dest_bucket: str | None = None,
    ) -> bool:
        """Move a file with automatic instrumentation.

        Args:
            source_key: Source object key
            dest_key: Destination object key
            source_bucket: Source bucket override
            dest_bucket: Destination bucket override

        Returns:
            True if moved successfully
        """
        client = self._ensure_ready()

        async with track_storage_operation(
            "move",
            key=source_key,
            bucket=source_bucket or self._settings.bucket,
            metadata={"dest_key": dest_key},
        ):
            return await client.move_file(source_key, dest_key, source_bucket, dest_bucket)

    async def list_files(
        self,
        prefix: str = "",
        pattern: str | None = None,
        max_keys: int = 1000,
    ) -> list[dict[str, Any]]:
        """List files with optional filtering.

        Args:
            prefix: Key prefix filter
            pattern: Optional glob pattern
            max_keys: Maximum results

        Returns:
            List of file info dicts
        """
        client = self._ensure_ready()

        async with track_storage_operation(
            "list",
            bucket=self._settings.bucket,
            metadata={"prefix": prefix, "max_keys": max_keys},
        ) as ctx:
            files = await client.list_files(prefix, pattern, max_keys)
            ctx["result_count"] = len(files)
            return files

    # ========== Batch Operations ==========

    async def upload_files(
        self,
        files: list[tuple[str, BinaryIO | bytes, str]],
        max_concurrency: int = 5,
        on_progress: Callable[[str, bool, str | None], None] | None = None,
    ) -> list[dict[str, Any]]:
        """Upload multiple files with instrumentation.

        Args:
            files: List of (key, file_obj_or_bytes, content_type) tuples
            max_concurrency: Max concurrent uploads
            on_progress: Optional progress callback

        Returns:
            List of upload results
        """
        client = self._ensure_ready()

        from opentelemetry.trace import Status, StatusCode

        from .instrumentation import create_storage_span
        from .metrics import record_batch_operation

        span = create_storage_span(
            "batch_upload",
            bucket=self._settings.bucket,
            batch_size=len(files),
        )

        try:
            results = await client.upload_files(files, max_concurrency, on_progress)

            # Calculate success/failure counts
            success_count = sum(1 for r in results if r.get("success", False))
            failure_count = len(results) - success_count

            record_batch_operation(
                operation="batch_upload",
                total_count=len(files),
                success_count=success_count,
                failure_count=failure_count,
            )

            span.set_attribute("batch.success_count", success_count)
            span.set_attribute("batch.failure_count", failure_count)
            span.set_status(Status(StatusCode.OK))

            return results

        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise
        finally:
            span.end()

    async def download_files(
        self,
        keys: list[str],
        max_concurrency: int = 5,
        on_progress: Callable[[str, bool, str | None], None] | None = None,
    ) -> list[dict[str, Any]]:
        """Download multiple files with instrumentation.

        Args:
            keys: List of object keys to download
            max_concurrency: Max concurrent downloads
            on_progress: Optional progress callback

        Returns:
            List of download results
        """
        client = self._ensure_ready()

        from opentelemetry.trace import Status, StatusCode

        from .instrumentation import create_storage_span
        from .metrics import record_batch_operation

        span = create_storage_span(
            "batch_download",
            bucket=self._settings.bucket,
            batch_size=len(keys),
        )

        try:
            results = await client.download_files(keys, max_concurrency, on_progress)

            success_count = sum(1 for r in results if r.get("success", False))
            failure_count = len(results) - success_count

            record_batch_operation(
                operation="batch_download",
                total_count=len(keys),
                success_count=success_count,
                failure_count=failure_count,
            )

            span.set_attribute("batch.success_count", success_count)
            span.set_attribute("batch.failure_count", failure_count)
            span.set_status(Status(StatusCode.OK))

            return results

        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise
        finally:
            span.end()

    async def delete_files(
        self,
        keys: list[str],
        dry_run: bool = True,
        max_concurrency: int = 10,
    ) -> dict[str, Any]:
        """Delete multiple files with instrumentation.

        Args:
            keys: List of object keys to delete
            dry_run: If True, only simulates deletion
            max_concurrency: Max concurrent deletes

        Returns:
            Result dict with deleted/failed counts
        """
        client = self._ensure_ready()

        from opentelemetry.trace import Status, StatusCode

        from .instrumentation import create_storage_span
        from .metrics import record_batch_operation

        span = create_storage_span(
            "batch_delete",
            bucket=self._settings.bucket,
            batch_size=len(keys),
            dry_run=dry_run,
        )

        try:
            result = await client.delete_files(keys, dry_run, max_concurrency)

            if not dry_run:
                record_batch_operation(
                    operation="batch_delete",
                    total_count=result.get("total", len(keys)),
                    success_count=len(result.get("deleted", [])),
                    failure_count=len(result.get("failed", [])),
                )

            span.set_attribute("batch.deleted_count", len(result.get("deleted", [])))
            span.set_attribute("batch.failed_count", len(result.get("failed", [])))
            span.set_status(Status(StatusCode.OK))

            return result

        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise
        finally:
            span.end()


# ========== Singleton Management ==========

_storage_service: StorageService | None = None


def get_storage_service() -> StorageService:
    """Get the singleton storage service instance.

    Creates the instance on first call. The service must be
    initialized via startup() before use.

    Returns:
        The global StorageService instance
    """
    global _storage_service
    if _storage_service is None:
        _storage_service = StorageService()
    return _storage_service


def reset_storage_service() -> None:
    """Reset the singleton instance (for testing only)."""
    global _storage_service
    _storage_service = None
