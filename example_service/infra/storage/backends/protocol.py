"""Storage backend protocol and normalized data structures.

This module defines:
- Protocol interface that all storage backends must implement
- Normalized data structures for cross-backend compatibility
- Tenant context for multi-tenant operations
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, BinaryIO, Protocol

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from datetime import datetime

# ============================================================================
# Tenant Context
# ============================================================================


@dataclass(frozen=True)
class TenantContext:
    """Tenant context for multi-tenant storage operations.

    Attributes:
        tenant_uuid: Unique tenant identifier
        tenant_slug: URL-friendly tenant identifier (1-10 chars)
        metadata: Additional tenant metadata from auth token
    """

    tenant_uuid: str
    tenant_slug: str
    metadata: dict[str, Any] = field(default_factory=dict)


# ============================================================================
# Normalized Data Structures
# ============================================================================


@dataclass(frozen=True)
class ObjectMetadata:
    """Normalized object metadata across all storage backends.

    This provides a consistent interface regardless of the underlying
    storage backend (S3, GCS, Azure, etc.).

    Attributes:
        key: Object key/path
        size_bytes: Object size in bytes
        content_type: MIME type
        last_modified: Last modification timestamp
        etag: Entity tag for version identification
        storage_class: Storage tier (e.g., STANDARD, GLACIER)
        custom_metadata: Backend-agnostic custom metadata
        acl: Access Control List setting
    """

    key: str
    size_bytes: int
    content_type: str | None
    last_modified: datetime
    etag: str | None
    storage_class: str | None
    custom_metadata: dict[str, str]
    acl: str | None = None


@dataclass(frozen=True)
class UploadResult:
    """Result of an upload operation.

    Attributes:
        key: Object key where file was uploaded
        bucket: Bucket name
        etag: Entity tag of uploaded object
        size_bytes: Size of uploaded object in bytes
        checksum_sha256: SHA256 checksum (when available)
        version_id: Version ID (for versioned buckets)
    """

    key: str
    bucket: str
    etag: str | None
    size_bytes: int
    checksum_sha256: str | None
    version_id: str | None = None


@dataclass(frozen=True)
class BucketInfo:
    """Information about a storage bucket.

    Attributes:
        name: Bucket name
        region: Geographic region
        creation_date: When bucket was created
        versioning_enabled: Whether versioning is enabled
    """

    name: str
    region: str | None
    creation_date: datetime | None
    versioning_enabled: bool = False


# ============================================================================
# Storage Backend Protocol
# ============================================================================


class StorageBackend(Protocol):
    """Protocol interface for storage backends.

    All storage backends (S3, GCS, Azure, etc.) must implement this protocol.
    Uses structural typing (Protocol) rather than inheritance for flexibility.

    Example:
        class S3Backend:
            @property
            def backend_name(self) -> str:
                return "s3"

            async def upload_object(self, key: str, data: BinaryIO, ...) -> UploadResult:
                # S3-specific implementation
                ...
    """

    # ========================================================================
    # Properties
    # ========================================================================

    @property
    def backend_name(self) -> str:
        """Name of the backend (e.g., 's3', 'gcs', 'azure')."""
        ...

    @property
    def is_ready(self) -> bool:
        """Check if backend is initialized and ready for operations."""
        ...

    # ========================================================================
    # Lifecycle Management
    # ========================================================================

    async def startup(self) -> None:
        """Initialize backend (create clients, connection pools, etc.)."""
        ...

    async def shutdown(self) -> None:
        """Gracefully shutdown backend (close connections, cleanup resources)."""
        ...

    async def health_check(self) -> bool:
        """Check backend health and connectivity.

        Returns:
            True if healthy, False otherwise
        """
        ...

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
        """Upload an object to storage.

        Args:
            key: Object key/path
            data: Binary data to upload
            bucket: Target bucket (uses default if None)
            content_type: MIME type
            metadata: Custom metadata
            acl: Access Control List (e.g., 'private', 'public-read')
            storage_class: Storage tier (e.g., 'STANDARD', 'GLACIER')

        Returns:
            UploadResult with upload information

        Raises:
            StorageError: If upload fails
        """
        ...

    async def download_object(
        self,
        key: str,
        bucket: str | None = None,
    ) -> bytes:
        """Download an object from storage.

        Args:
            key: Object key/path
            bucket: Source bucket (uses default if None)

        Returns:
            Object data as bytes

        Raises:
            StorageFileNotFoundError: If object doesn't exist
            StorageError: If download fails
        """
        ...

    async def delete_object(
        self,
        key: str,
        bucket: str | None = None,
    ) -> bool:
        """Delete an object from storage.

        Args:
            key: Object key/path
            bucket: Target bucket (uses default if None)

        Returns:
            True if deleted successfully

        Raises:
            StorageError: If deletion fails
        """
        ...

    async def object_exists(
        self,
        key: str,
        bucket: str | None = None,
    ) -> bool:
        """Check if an object exists in storage.

        Args:
            key: Object key/path
            bucket: Target bucket (uses default if None)

        Returns:
            True if object exists
        """
        ...

    async def get_object_metadata(
        self,
        key: str,
        bucket: str | None = None,
    ) -> ObjectMetadata | None:
        """Get object metadata without downloading content.

        Args:
            key: Object key/path
            bucket: Target bucket (uses default if None)

        Returns:
            ObjectMetadata if object exists, None otherwise
        """
        ...

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
        ...

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
        ...

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
        ...

    def stream_objects(
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
        ...

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
        ...

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
        ...

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
        ...

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
        ...

    async def list_buckets(self) -> list[BucketInfo]:
        """List all accessible buckets.

        Returns:
            List of BucketInfo objects

        Raises:
            StorageError: If listing fails
        """
        ...

    async def bucket_exists(self, bucket: str) -> bool:
        """Check if a bucket exists and is accessible.

        Args:
            bucket: Bucket name

        Returns:
            True if bucket exists
        """
        ...

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
        ...

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
        ...

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

        Note:
            This is an optional advanced feature. Backends may raise
            NotImplementedError if not supported.
        """
        ...
