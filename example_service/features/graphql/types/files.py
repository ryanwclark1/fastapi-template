"""GraphQL types for files feature.

Provides Strawberry GraphQL types for file management with full Pydantic integration.
Supports presigned URL uploads for efficient client-side file handling.

Auto-generated from Pydantic schemas:
- FileType: Auto-generated from FileRead
- FileThumbnailType: Auto-generated from FileThumbnailRead
- PresignedUploadInput: Auto-generated from PresignedUploadRequest
"""

from __future__ import annotations

import strawberry

from example_service.features.files.models import FileStatus as ModelFileStatus
from example_service.features.files.schemas import (
    FileRead,
    FileThumbnailRead,
    PresignedUploadRequest,
)
from example_service.features.graphql.types.base import PageInfoType
from example_service.features.graphql.types.pydantic_bridge import (
    pydantic_field,
    pydantic_input,
    pydantic_type,
)

# ============================================================================
# Enums
# ============================================================================


@strawberry.enum(description="File processing status")
class FileStatus:
    """File processing status types."""

    PENDING = "pending"  # Upload initiated but not confirmed
    PROCESSING = "processing"  # File being processed
    READY = "ready"  # File ready for use
    FAILED = "failed"  # Processing failed
    DELETED = "deleted"  # Soft deleted


# ============================================================================
# File Thumbnail Type (Output)
# ============================================================================


@pydantic_type(model=FileThumbnailRead, description="A thumbnail generated from an image file")
class FileThumbnailType:
    """Thumbnail type auto-generated from FileThumbnailRead Pydantic schema.

    Thumbnails are automatically generated for image uploads.
    Multiple sizes may be available for responsive image display.

    All fields are auto-generated from the Pydantic FileThumbnailRead schema.
    """

    # Override ID fields
    id: strawberry.ID = pydantic_field(description="Unique identifier for the thumbnail")
    file_id: strawberry.ID = pydantic_field(description="Parent file ID")

    # Computed fields
    @strawberry.field(description="Presigned download URL for the thumbnail")
    async def download_url(self, info) -> str:  # noqa: ARG002
        """Generate presigned download URL for thumbnail.

        Uses the storage service to generate a time-limited URL.

        Args:
            info: Strawberry info with context

        Returns:
            Presigned URL valid for configured duration
        """
        from example_service.infra.storage.service import get_storage_service

        storage = get_storage_service()
        if hasattr(self, "storage_key") and self.storage_key:
            return await storage.get_presigned_url(self.storage_key)
        return ""


# ============================================================================
# File Type (Output)
# ============================================================================


@pydantic_type(model=FileRead, description="An uploaded file with metadata")
class FileType:
    """File type auto-generated from FileRead Pydantic schema.

    Files support:
    - Direct multipart uploads
    - Presigned URL uploads (for large files)
    - Automatic thumbnail generation (for images)
    - Expiration timestamps
    - Public/private access control

    All fields are auto-generated from the Pydantic FileRead schema.
    """

    # Override ID field
    id: strawberry.ID = pydantic_field(description="Unique identifier for the file")

    # Override thumbnails to use GraphQL type
    @strawberry.field(description="Thumbnails generated for this file")
    def thumbnails(self) -> list[FileThumbnailType]:
        """Get thumbnails with proper GraphQL type conversion.

        Returns:
            List of thumbnail objects with download URLs
        """
        if hasattr(self, "_thumbnails") and self._thumbnails:
            return [FileThumbnailType.from_pydantic(t) for t in self._thumbnails]
        return []

    # Computed fields
    @strawberry.field(description="Presigned download URL for the file")
    async def download_url(self, info) -> str:  # noqa: ARG002
        """Generate presigned download URL for file.

        Uses the storage service to generate a time-limited URL.
        Only available for files in READY status.

        Args:
            info: Strawberry info with context

        Returns:
            Presigned URL valid for configured duration
        """
        from example_service.infra.storage.service import get_storage_service

        # Only generate URLs for ready files
        if hasattr(self, "status") and self.status != ModelFileStatus.READY.value:
            return ""

        storage = get_storage_service()
        if hasattr(self, "storage_key") and self.storage_key:
            try:
                return await storage.get_presigned_url(self.storage_key)
            except Exception:
                # Return empty string if URL generation fails
                return ""
        return ""

    @strawberry.field(description="Whether this file is expired")
    def is_expired(self) -> bool:
        """Check if file has expired based on expires_at timestamp.

        Returns:
            True if file has passed its expiration time
        """
        from datetime import UTC, datetime

        if hasattr(self, "expires_at") and self.expires_at:
            return datetime.now(UTC) > self.expires_at
        return False


# ============================================================================
# Input Types
# ============================================================================


@pydantic_input(
    model=PresignedUploadRequest,
    fields=["filename", "content_type", "size_bytes", "owner_id", "is_public", "expires_at"],
    description="Input for initiating a presigned file upload",
)
class InitiateUploadInput:
    """Input for initiating a presigned file upload.

    Auto-generated from PresignedUploadRequest Pydantic schema.
    Pydantic validators run automatically:
    - filename: max 255 characters
    - content_type: max 127 characters, MIME type validation
    - size_bytes: must be >= 1
    """


@strawberry.input(description="Input for confirming a completed file upload")
class ConfirmUploadInput:
    """Input for confirming that a presigned upload has completed.

    After the client uploads directly to S3 using the presigned URL,
    they must call the confirm mutation to mark the file as ready.
    """

    file_id: strawberry.ID = strawberry.field(description="File ID from initiate response")
    etag: str | None = strawberry.field(
        default=None,
        description="ETag returned from S3 upload (optional)",
    )


# ============================================================================
# Response Types
# ============================================================================


@strawberry.type(description="Presigned upload URL response")
class PresignedUploadResponse:
    """Response containing presigned upload URL and metadata.

    Client should POST the file to upload_url with upload_fields included.
    """

    upload_url: str = strawberry.field(description="URL to POST the file to")
    upload_fields: strawberry.scalars.JSON = strawberry.field(
        description="Form fields to include in POST"
    )
    file_id: strawberry.ID = strawberry.field(description="File ID to use after upload completes")
    storage_key: str = strawberry.field(description="Storage key where file will be stored")
    expires_in: int = strawberry.field(description="Seconds until upload URL expires")


@strawberry.type(description="File operation success response")
class FileSuccess:
    """Successful file operation response."""

    file: FileType


@strawberry.enum(description="File error codes")
class FileErrorCode(strawberry.enum.EnumMeta):
    """Error codes for file operations."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    INVALID_STATUS = "INVALID_STATUS"
    STORAGE_ERROR = "STORAGE_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@strawberry.type(description="File operation error")
class FileError:
    """Error response for file operations."""

    code: FileErrorCode
    message: str
    field: str | None = None


# Union type for mutations
FilePayload = strawberry.union("FilePayload", (FileSuccess, FileError))


@strawberry.type(description="Generic success/failure response")
class DeletePayload:
    """Response for delete operations."""

    success: bool
    message: str


# ============================================================================
# Edge and Connection Types for Pagination
# ============================================================================


@strawberry.type(description="Edge containing a file node and cursor")
class FileEdge:
    """Edge in a Relay-style connection."""

    node: FileType
    cursor: str


@strawberry.type(description="Paginated list of files")
class FileConnection:
    """Relay-style connection for file pagination."""

    edges: list[FileEdge]
    page_info: PageInfoType


# ============================================================================
# Subscription Event Types
# ============================================================================


@strawberry.enum(description="Types of file events for subscriptions")
class FileEventType(strawberry.enum.Enum):
    """Event types for file subscriptions.

    Clients can subscribe to specific event types or all events.
    """

    UPLOADED = "UPLOADED"  # Upload initiated (presigned URL generated)
    READY = "READY"  # File confirmed and ready for use
    FAILED = "FAILED"  # Processing or upload failed
    DELETED = "DELETED"


@strawberry.type(description="Real-time file event via subscription")
class FileEvent:
    """Event payload for file subscriptions.

    Pushed to subscribed clients when files are uploaded, become ready,
    fail processing, or are deleted.
    Useful for progress tracking in client applications.
    """

    event_type: FileEventType = strawberry.field(description="Type of event that occurred")
    file: FileType | None = strawberry.field(
        default=None,
        description="File data (null for DELETED events)",
    )
    file_id: strawberry.ID = strawberry.field(description="File ID")
    error_message: str | None = strawberry.field(
        default=None,
        description="Error message (for FAILED events)",
    )


__all__ = [
    "ConfirmUploadInput",
    "DeletePayload",
    "FileConnection",
    # Pagination
    "FileEdge",
    "FileError",
    "FileErrorCode",
    "FileEvent",
    "FileEventType",
    "FilePayload",
    # Enums
    "FileStatus",
    # Responses
    "FileSuccess",
    "FileThumbnailType",
    # Types
    "FileType",
    # Inputs
    "InitiateUploadInput",
    "PresignedUploadResponse",
]
