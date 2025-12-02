"""High-level storage service with singleton pattern and full observability.

This module provides the main interface for storage operations with:
- Singleton pattern for application-wide access
- Automatic OpenTelemetry spans and Prometheus metrics
- Proper lifecycle management (startup/shutdown)
- Health check integration
- Protocol-based backend abstraction (S3, GCS, Azure, etc.)
- Multi-tenant bucket isolation support
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, BinaryIO

if TYPE_CHECKING:

    from example_service.core.settings.storage import StorageSettings

from example_service.core.settings import get_storage_settings

from .backends.factory import create_storage_backend
from .exceptions import StorageNotConfiguredError
from .instrumentation import track_storage_operation

if TYPE_CHECKING:
    from .backends.protocol import StorageBackend, TenantContext

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
        self._backend: StorageBackend | None = None
        self._initialized = False

    @property
    def is_ready(self) -> bool:
        """Check if the service is initialized and ready for operations."""
        return self._initialized and self._backend is not None and self._backend.is_ready

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
                "backend": self._settings.backend.value,
            },
        )

        # Create backend using factory
        self._backend = create_storage_backend(self._settings)
        await self._backend.startup()

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
        if not self._initialized:
            logger.debug("Storage service not initialized, nothing to shutdown")
            return

        logger.info("Shutting down storage service")

        # Shutdown backend
        if self._backend is not None:
            await self._backend.shutdown()

        self._initialized = False
        logger.info("Storage service shutdown complete")

    async def health_check(self) -> bool:
        """Check storage service health.

        Returns:
            True if healthy, False otherwise
        """
        if not self.is_ready or self._backend is None:
            return False
        return await self._backend.health_check()

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

    def _ensure_ready(self) -> StorageBackend:
        """Ensure the service is ready and return the backend.

        Raises:
            StorageNotConfiguredError: If service is not ready
        """
        if not self.is_ready or self._backend is None:
            raise StorageNotConfiguredError(
                message="Storage service is not initialized",
                metadata={"is_configured": self._settings.is_configured},
            )
        return self._backend

    def _resolve_bucket(
        self,
        tenant_context: TenantContext | None,
        bucket: str | None = None,
    ) -> str:
        """Resolve bucket name based on tenant context.

        Args:
            tenant_context: Optional tenant context
            bucket: Explicit bucket override

        Returns:
            Resolved bucket name
        """
        if bucket:
            return bucket  # Explicit override

        if self._settings.enable_multi_tenancy and tenant_context:
            # Use tenant bucket
            return self._settings.bucket_naming_pattern.format(
                tenant_uuid=tenant_context.tenant_uuid,
                tenant_slug=tenant_context.tenant_slug,
            )

        if self._settings.require_tenant_context and not tenant_context:
            from .exceptions import StorageError

            raise StorageError(
                message="Tenant context required but not provided",
                code="TENANT_CONTEXT_REQUIRED",
                status_code=400,
            )

        # Fallback to shared/default bucket
        return self._settings.effective_shared_bucket

    # ========== File Operations with Instrumentation ==========

    async def upload_file(
        self,
        file_obj: BinaryIO,
        key: str,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
        bucket: str | None = None,
        acl: str | None = None,
        storage_class: str | None = None,
        tenant_context: TenantContext | None = None,
    ) -> dict[str, Any]:
        """Upload a file with automatic instrumentation.

        Args:
            file_obj: File-like object to upload
            key: S3 object key
            content_type: MIME content type
            metadata: Custom metadata
            bucket: Optional bucket override
            acl: Access Control List (e.g., 'private', 'public-read')
            storage_class: Storage class (e.g., 'STANDARD', 'GLACIER')
            tenant_context: Optional tenant context for multi-tenant storage

        Returns:
            Upload result dict with key, bucket, etag, size_bytes, checksum, version_id
        """
        backend = self._ensure_ready()

        # Resolve bucket based on tenant context
        resolved_bucket = self._resolve_bucket(tenant_context, bucket)

        # Apply defaults from settings
        acl = acl or self._settings.default_acl
        storage_class = storage_class or self._settings.default_storage_class

        async with track_storage_operation(
            "upload",
            key=key,
            bucket=resolved_bucket,
            content_type=content_type,
        ) as ctx:
            upload_result = await backend.upload_object(
                key=key,
                data=file_obj,
                bucket=resolved_bucket,
                content_type=content_type,
                metadata=metadata,
                acl=acl,
                storage_class=storage_class,
            )

            # Convert UploadResult to dict for backward compatibility
            result = {
                "key": upload_result.key,
                "bucket": upload_result.bucket,
                "etag": upload_result.etag,
                "size_bytes": upload_result.size_bytes,
                "checksum_sha256": upload_result.checksum_sha256,
                "version_id": upload_result.version_id,
            }

            ctx["result_size"] = result["size_bytes"]
            ctx["checksum"] = result["checksum_sha256"]
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
        backend = self._ensure_ready()

        async with track_storage_operation(
            "download",
            key=key,
            bucket=bucket or self._settings.bucket,
        ) as ctx:
            data = await backend.download_object(key, bucket)
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
        backend = self._ensure_ready()

        async with track_storage_operation(
            "delete",
            key=key,
            bucket=bucket or self._settings.bucket,
        ):
            return await backend.delete_object(key, bucket)

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
        backend = self._ensure_ready()
        return await backend.object_exists(key, bucket)

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
        backend = self._ensure_ready()
        metadata = await backend.get_object_metadata(key, bucket)
        if metadata is None:
            return None
        # Convert ObjectMetadata to dict for backward compatibility
        return {
            "key": metadata.key,
            "size_bytes": metadata.size_bytes,
            "content_type": metadata.content_type,
            "last_modified": metadata.last_modified,
            "etag": metadata.etag,
            "storage_class": metadata.storage_class,
            "metadata": metadata.custom_metadata,
            "acl": metadata.acl,
        }

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
        backend = self._ensure_ready()

        from .metrics import storage_presigned_urls_generated

        storage_presigned_urls_generated.labels(type="download").inc()

        return await backend.generate_presigned_download_url(
            key, bucket, expires_in or self._settings.presigned_url_expiry_seconds
        )

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
        backend = self._ensure_ready()

        from .metrics import storage_presigned_urls_generated

        storage_presigned_urls_generated.labels(type="upload").inc()

        return await backend.generate_presigned_upload_url(
            key, bucket, content_type, expires_in or self._settings.presigned_url_expiry_seconds
        )

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
        backend = self._ensure_ready()

        async with track_storage_operation(
            "copy",
            key=source_key,
            bucket=source_bucket or self._settings.bucket,
            metadata={"dest_key": dest_key},
        ):
            return await backend.copy_object(source_key, dest_key, source_bucket, dest_bucket)

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
        backend = self._ensure_ready()

        async with track_storage_operation(
            "move",
            key=source_key,
            bucket=source_bucket or self._settings.bucket,
            metadata={"dest_key": dest_key},
        ):
            return await backend.move_object(source_key, dest_key, source_bucket, dest_bucket)

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
        backend = self._ensure_ready()

        async with track_storage_operation(
            "list",
            bucket=self._settings.bucket,
            metadata={"prefix": prefix, "max_keys": max_keys},
        ) as ctx:
            objects, _ = await backend.list_objects(prefix=prefix, max_keys=max_keys)

            # Convert ObjectMetadata to dict for backward compatibility
            files = [
                {
                    "key": obj.key,
                    "size_bytes": obj.size_bytes,
                    "content_type": obj.content_type,
                    "last_modified": obj.last_modified,
                    "etag": obj.etag,
                    "storage_class": obj.storage_class,
                    "metadata": obj.custom_metadata,
                    "acl": obj.acl,
                }
                for obj in objects
            ]

            # Apply pattern matching if specified
            if pattern:
                import fnmatch

                files = [f for f in files if fnmatch.fnmatch(str(f["key"]), pattern)]

            ctx["result_count"] = len(files)
            return files

    # ========== Bucket Management ==========

    async def create_bucket(
        self,
        bucket: str,
        region: str | None = None,
        acl: str | None = None,
    ) -> bool:
        """Create a new storage bucket."""
        backend = self._ensure_ready()

        async with track_storage_operation(
            "create_bucket",
            bucket=bucket,
        ):
            return await backend.create_bucket(
                bucket=bucket,
                region=region or self._settings.region,
                acl=acl,
            )

    async def delete_bucket(
        self,
        bucket: str,
        force: bool = False,
    ) -> bool:
        """Delete a storage bucket."""
        backend = self._ensure_ready()

        async with track_storage_operation(
            "delete_bucket",
            bucket=bucket,
        ):
            return await backend.delete_bucket(bucket=bucket, force=force)

    async def list_buckets(self) -> list[dict[str, Any]]:
        """List all accessible storage buckets."""
        backend = self._ensure_ready()

        async with track_storage_operation(
            "list_buckets",
        ):
            buckets = await backend.list_buckets()

            # Convert BucketInfo to dict for consistency
            return [
                {
                    "name": b.name,
                    "region": b.region,
                    "creation_date": b.creation_date,
                    "versioning_enabled": b.versioning_enabled,
                }
                for b in buckets
            ]

    async def bucket_exists(self, bucket: str) -> bool:
        """Check if a bucket exists."""
        backend = self._ensure_ready()
        return await backend.bucket_exists(bucket)

    # ========== ACL Management ==========

    async def set_object_acl(
        self,
        key: str,
        acl: str,
        bucket: str | None = None,
        tenant_context: TenantContext | None = None,
    ) -> bool:
        """Set ACL on an object."""
        backend = self._ensure_ready()
        resolved_bucket = self._resolve_bucket(tenant_context, bucket)

        async with track_storage_operation(
            "set_acl",
            key=key,
            bucket=resolved_bucket,
        ):
            return await backend.set_object_acl(
                key=key,
                acl=acl,
                bucket=resolved_bucket,
            )

    async def get_object_acl(
        self,
        key: str,
        bucket: str | None = None,
        tenant_context: TenantContext | None = None,
    ) -> dict[str, Any]:
        """Get ACL of an object."""
        backend = self._ensure_ready()
        resolved_bucket = self._resolve_bucket(tenant_context, bucket)

        async with track_storage_operation(
            "get_acl",
            key=key,
            bucket=resolved_bucket,
        ):
            return await backend.get_object_acl(
                key=key,
                bucket=resolved_bucket,
            )


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
