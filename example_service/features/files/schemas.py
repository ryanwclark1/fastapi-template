"""Pydantic schemas for the files feature."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from example_service.features.files.models import FileStatus
from example_service.utils.runtime_dependencies import require_runtime_dependency

require_runtime_dependency(datetime, UUID, FileStatus)


class FileCreate(BaseModel):
    """Payload for creating a file metadata record."""

    original_filename: str = Field(..., max_length=255)
    storage_key: str = Field(..., max_length=500)
    bucket: str = Field(..., max_length=63)
    content_type: str = Field(..., max_length=127)
    size_bytes: int = Field(..., ge=0)
    checksum_sha256: str | None = Field(None, max_length=64)
    etag: str | None = Field(None, max_length=255)
    status: FileStatus = FileStatus.PENDING
    owner_id: str | None = Field(None, max_length=255)
    is_public: bool = False
    expires_at: datetime | None = None


class FileUpdate(BaseModel):
    """Payload for updating file metadata."""

    status: FileStatus | None = None
    is_public: bool | None = None
    expires_at: datetime | None = None


class FileThumbnailRead(BaseModel):
    """Thumbnail information returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    file_id: UUID
    storage_key: str
    width: int
    height: int
    size_bytes: int
    created_at: datetime


class FileRead(BaseModel):
    """File information returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    original_filename: str
    storage_key: str
    bucket: str
    content_type: str
    size_bytes: int
    checksum_sha256: str | None
    etag: str | None
    status: FileStatus
    owner_id: str | None
    is_public: bool
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime
    thumbnails: list[FileThumbnailRead] = []


class FileList(BaseModel):
    """Paginated list of files."""

    items: list[FileRead]
    total: int
    limit: int
    offset: int


class PresignedUploadRequest(BaseModel):
    """Request for presigned upload URL."""

    filename: str = Field(..., max_length=255, description="Original filename")
    content_type: str = Field(..., max_length=127, description="MIME type of the file")
    size_bytes: int = Field(..., ge=1, description="File size in bytes")
    owner_id: str | None = Field(None, max_length=255, description="Optional owner identifier")
    is_public: bool = Field(False, description="Whether file should be publicly accessible")
    expires_at: datetime | None = Field(None, description="Optional expiration timestamp")


class PresignedUploadResponse(BaseModel):
    """Response containing presigned upload URL and metadata."""

    upload_url: str = Field(..., description="URL to POST the file to")
    upload_fields: dict[str, str] = Field(..., description="Form fields to include in POST")
    file_id: UUID = Field(..., description="File ID to use after upload completes")
    storage_key: str = Field(..., description="Storage key where file will be stored")
    expires_in: int = Field(..., description="Seconds until upload URL expires")


class FileUploadComplete(BaseModel):
    """Notification that a presigned upload has completed."""

    file_id: UUID = Field(..., description="File ID from presigned upload response")
    etag: str | None = Field(None, description="ETag returned from S3 (optional)")


class FileDownloadResponse(BaseModel):
    """Response containing presigned download URL."""

    download_url: str = Field(..., description="Presigned URL for downloading the file")
    expires_in: int = Field(..., description="Seconds until download URL expires")
    filename: str = Field(..., description="Original filename")
    content_type: str = Field(..., description="MIME type")
    size_bytes: int = Field(..., description="File size in bytes")


class FileStatusResponse(BaseModel):
    """File processing status response."""

    file_id: UUID
    status: FileStatus
    original_filename: str
    content_type: str
    size_bytes: int
    created_at: datetime
    updated_at: datetime
    thumbnail_count: int = 0


# Batch Operations Schemas


class BatchUploadResult(BaseModel):
    """Individual file upload result in batch operation."""

    filename: str = Field(..., description="Original filename")
    file_id: UUID | None = Field(None, description="File ID if upload succeeded")
    success: bool = Field(..., description="Whether upload succeeded")
    error: str | None = Field(None, description="Error message if upload failed")


class BatchUploadResponse(BaseModel):
    """Response for batch file upload operation."""

    total: int = Field(..., description="Total number of files in batch")
    successful: int = Field(..., description="Number of successful uploads")
    failed: int = Field(..., description="Number of failed uploads")
    results: list[BatchUploadResult] = Field(..., description="Individual upload results")


class BatchDownloadRequest(BaseModel):
    """Request for batch file download."""

    file_ids: list[UUID] = Field(
        ..., min_length=1, max_length=100, description="List of file IDs to download (max 100)",
    )


class BatchDownloadItem(BaseModel):
    """Individual file download information in batch operation."""

    file_id: UUID
    download_url: str | None = Field(None, description="Presigned download URL if available")
    filename: str | None = Field(None, description="Original filename")
    content_type: str | None = Field(None, description="MIME type")
    size_bytes: int | None = Field(None, description="File size in bytes")
    success: bool = Field(..., description="Whether download URL was generated")
    error: str | None = Field(None, description="Error message if generation failed")


class BatchDownloadResponse(BaseModel):
    """Response for batch file download operation."""

    total: int = Field(..., description="Total number of files requested")
    successful: int = Field(..., description="Number of successful URL generations")
    failed: int = Field(..., description="Number of failed URL generations")
    expires_in: int = Field(..., description="Seconds until download URLs expire")
    items: list[BatchDownloadItem] = Field(..., description="Individual download items")


class BatchDeleteRequest(BaseModel):
    """Request for batch file deletion."""

    file_ids: list[UUID] = Field(
        ..., min_length=1, max_length=100, description="List of file IDs to delete (max 100)",
    )
    dry_run: bool = Field(False, description="If true, preview deletion without executing")
    hard_delete: bool = Field(False, description="If true, permanently delete from storage")


class BatchDeleteItem(BaseModel):
    """Individual file deletion result in batch operation."""

    file_id: UUID
    filename: str | None = Field(None, description="Original filename")
    would_delete: bool | None = Field(
        None, description="Whether file would be deleted (dry run only)",
    )
    deleted: bool | None = Field(None, description="Whether file was deleted (actual run)")
    success: bool = Field(..., description="Whether operation succeeded")
    error: str | None = Field(None, description="Error message if operation failed")


class BatchDeleteResponse(BaseModel):
    """Response for batch file deletion operation."""

    total: int = Field(..., description="Total number of files in batch")
    successful: int = Field(..., description="Number of successful operations")
    failed: int = Field(..., description="Number of failed operations")
    dry_run: bool = Field(..., description="Whether this was a dry run")
    hard_delete: bool = Field(..., description="Whether hard delete was requested")
    items: list[BatchDeleteItem] = Field(..., description="Individual deletion results")


class CopyFileRequest(BaseModel):
    """Request to copy a file."""

    new_filename: str | None = Field(
        None,
        max_length=255,
        description="New filename for the copy (defaults to 'Copy of {original}')",
    )


class MoveFileRequest(BaseModel):
    """Request to move/rename a file."""

    new_filename: str = Field(..., max_length=255, description="New filename for the file")
