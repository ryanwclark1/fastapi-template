"""API router for the files feature."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated
from uuid import UUID  # noqa: TC003

from fastapi import APIRouter, Depends, File, UploadFile, status

from example_service.core.database import NotFoundError
from example_service.core.dependencies.database import get_db_session
from example_service.core.exceptions import (
    BadRequestException,
    InternalServerException,
    ServiceUnavailableException,
)
from example_service.features.files.repository import (
    FileRepository,
    get_file_repository,
)
from example_service.features.files.schemas import (
    BatchDeleteRequest,
    BatchDeleteResponse,
    BatchDownloadRequest,
    BatchDownloadResponse,
    BatchUploadResponse,
    CopyFileRequest,
    FileDownloadResponse,
    FileList,
    FileRead,
    FileStatusResponse,
    FileUploadComplete,
    MoveFileRequest,
    PresignedUploadRequest,
    PresignedUploadResponse,
)
from example_service.features.files.service import FileService
from example_service.infra.logging import get_lazy_logger
from example_service.infra.metrics.tracking import (
    track_feature_usage,
    track_user_action,
)
from example_service.infra.storage import get_storage_service
from example_service.infra.storage.client import (
    InvalidFileError,
    StorageClientError,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/files", tags=["files"])

# Standard logger for INFO/WARNING/ERROR
logger = logging.getLogger(__name__)
# Lazy logger for DEBUG (zero overhead when DEBUG disabled)
lazy_logger = get_lazy_logger(__name__)


def get_file_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> FileService:
    """Dependency for file service."""
    storage = get_storage_service()
    if not storage.is_ready:
        raise ServiceUnavailableException(
            detail="File storage is not configured",
            type="storage-not-configured",
        )
    return FileService(session=session, storage_service=storage)


@router.post(
    "/upload",
    response_model=FileRead,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a file directly",
    description="Upload a file using multipart form data. Best for smaller files.",
)
async def upload_file(
    file: Annotated[UploadFile, File(...)],
    service: Annotated[FileService, Depends(get_file_service)],
    owner_id: str | None = None,
    is_public: bool = False,
) -> FileRead:
    """Upload a file directly via multipart form data.

    Args:
        file: File to upload
        owner_id: Optional owner identifier
        is_public: Whether file should be publicly accessible
        service: File service

    Returns:
        Created file record

    Raises:
        400: Invalid file (wrong type, too large, etc.)
        503: Storage not available
    """
    # Track business metrics
    track_feature_usage("file_upload", is_authenticated=False)
    track_user_action("upload", is_authenticated=False)

    if not file.filename:
        raise BadRequestException(
            detail="Filename is required",
            type="missing-filename",
        )

    if not file.content_type:
        raise BadRequestException(
            detail="Content type is required",
            type="missing-content-type",
        )

    try:
        created_file = await service.upload_file(
            file_obj=file.file,
            filename=file.filename,
            content_type=file.content_type,
            owner_id=owner_id,
            is_public=is_public,
        )

        return FileRead.model_validate(created_file)

    except InvalidFileError as e:
        raise BadRequestException(
            detail=str(e),
            type="invalid-file",
        ) from e
    except StorageClientError as e:
        logger.error("Storage error during file upload", extra={"error": str(e)})
        raise ServiceUnavailableException(
            detail="Failed to upload file to storage",
            type="storage-upload-failed",
        ) from e


@router.post(
    "/presigned-upload",
    response_model=PresignedUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Get presigned upload URL",
    description="Get a presigned URL for direct client-to-S3 upload. Best for large files.",
)
async def create_presigned_upload(
    request: PresignedUploadRequest,
    service: Annotated[FileService, Depends(get_file_service)],
) -> PresignedUploadResponse:
    """Create a presigned upload URL for client-side upload.

    The client should:
    1. Call this endpoint to get upload URL and file ID
    2. POST the file to the upload_url with upload_fields
    3. Call POST /files/{file_id}/complete to finalize

    Args:
        request: Presigned upload request
        service: File service

    Returns:
        Presigned upload URL and metadata

    Raises:
        400: Invalid file parameters
        503: Storage not available
    """
    track_feature_usage("file_presigned_upload", is_authenticated=False)

    try:
        result = await service.create_presigned_upload(
            filename=request.filename,
            content_type=request.content_type,
            size_bytes=request.size_bytes,
            owner_id=request.owner_id,
            is_public=request.is_public,
            expires_at=request.expires_at,
        )

        return PresignedUploadResponse(**result)

    except InvalidFileError as e:
        raise BadRequestException(
            detail=str(e),
            type="invalid-file",
        ) from e
    except StorageClientError as e:
        logger.error("Storage error during presigned upload creation", extra={"error": str(e)})
        raise ServiceUnavailableException(
            detail="Failed to create presigned upload URL",
            type="presigned-upload-failed",
        ) from e


@router.post(
    "/{file_id}/complete",
    response_model=FileRead,
    summary="Complete presigned upload",
    description="Mark a presigned upload as complete after client uploads to S3.",
)
async def complete_presigned_upload(
    file_id: UUID,
    completion: FileUploadComplete,
    service: Annotated[FileService, Depends(get_file_service)],
) -> FileRead:
    """Complete a presigned upload after client uploads to S3.

    Args:
        file_id: File ID from presigned upload response
        completion: Upload completion data
        service: File service

    Returns:
        Updated file record

    Raises:
        400: Invalid file state or upload not verified
        404: File not found
    """
    track_user_action("upload_complete", is_authenticated=False)

    if completion.file_id != file_id:
        raise BadRequestException(
            detail="File ID in URL does not match request body",
            type="file-id-mismatch",
        )

    try:
        completed_file = await service.complete_upload(
            file_id=file_id,
            etag=completion.etag,
        )

        return FileRead.model_validate(completed_file)

    except NotFoundError:
        msg = "File"
        raise NotFoundError(msg, {"id": str(file_id)}) from None
    except ValueError as e:
        raise BadRequestException(
            detail=str(e),
            type="invalid-upload-state",
        ) from e
    except StorageClientError as e:
        logger.error("Storage error during upload completion", extra={"error": str(e)})
        raise BadRequestException(
            detail="Upload verification failed - file not found in storage",
            type="upload-verification-failed",
        ) from e


@router.get(
    "/",
    response_model=FileList,
    summary="List files",
    description="List files with optional pagination and owner filter.",
)
async def list_files(
    service: Annotated[FileService, Depends(get_file_service)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    repo: Annotated[FileRepository, Depends(get_file_repository)],
    owner_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> FileList:
    """List files with pagination.

    Args:
        owner_id: Optional owner filter
        limit: Maximum results (default: 50)
        offset: Results to skip (default: 0)
        service: File service
        session: Database session
        repo: File repository

    Returns:
        Paginated list of files
    """
    files = await service.list_files(owner_id=owner_id, limit=limit, offset=offset)

    # Get total count for pagination
    search_result = await repo.search_files(
        session,
        owner_id=owner_id,
        limit=limit,
        offset=offset,
    )

    return FileList(
        items=[FileRead.model_validate(f) for f in files],
        total=search_result.total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{file_id}",
    response_model=FileRead,
    summary="Get file metadata",
    description="Get file metadata by ID.",
    responses={404: {"description": "File not found"}},
)
async def get_file(
    file_id: UUID,
    service: Annotated[FileService, Depends(get_file_service)],
) -> FileRead:
    """Get file metadata by ID.

    Args:
        file_id: File UUID
        service: File service

    Returns:
        File metadata

    Raises:
        404: File not found
    """
    file = await service.get_file(file_id)

    if file is None:
        msg = "File"
        raise NotFoundError(msg, {"id": str(file_id)})

    return FileRead.model_validate(file)


@router.get(
    "/{file_id}/download",
    response_model=FileDownloadResponse,
    summary="Get download URL",
    description="Get a presigned download URL for a file.",
    responses={
        404: {"description": "File not found"},
        400: {"description": "File not ready for download"},
    },
)
async def get_download_url(
    file_id: UUID,
    service: Annotated[FileService, Depends(get_file_service)],
) -> FileDownloadResponse:
    """Get presigned download URL for a file.

    Args:
        file_id: File UUID
        service: File service

    Returns:
        Presigned download URL and metadata

    Raises:
        404: File not found
        400: File not ready
    """
    track_user_action("download", is_authenticated=False)

    try:
        download_data = await service.get_download_url(file_id)
        return FileDownloadResponse(**download_data)

    except NotFoundError as err:
        msg = "File"
        raise NotFoundError(msg, {"id": str(file_id)}) from err
    except ValueError as e:
        raise BadRequestException(
            detail=str(e),
            type="file-not-ready",
        ) from e


@router.delete(
    "/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete file",
    description="Soft delete a file (marks as deleted but keeps in database).",
    responses={404: {"description": "File not found"}},
)
async def delete_file(
    file_id: UUID,
    service: Annotated[FileService, Depends(get_file_service)],
    hard_delete: bool = False,
) -> None:
    """Delete a file (soft or hard delete).

    Args:
        file_id: File UUID
        hard_delete: If true, permanently delete from storage; if false, soft delete
        service: File service

    Raises:
        404: File not found
    """
    track_user_action("delete", is_authenticated=False)

    try:
        await service.delete_file(file_id, hard_delete=hard_delete)

        logger.info(
            "File deleted",
            extra={
                "file_id": str(file_id),
                "hard_delete": hard_delete,
                "operation": "endpoint.delete_file",
            },
        )

    except NotFoundError as err:
        msg = "File"
        raise NotFoundError(msg, {"id": str(file_id)}) from err


@router.get(
    "/{file_id}/status",
    response_model=FileStatusResponse,
    summary="Get processing status",
    description="Get file processing status and thumbnail generation progress.",
    responses={404: {"description": "File not found"}},
)
async def get_processing_status(
    file_id: UUID,
    service: Annotated[FileService, Depends(get_file_service)],
) -> FileStatusResponse:
    """Get file processing status.

    Args:
        file_id: File UUID
        service: File service

    Returns:
        Processing status information

    Raises:
        404: File not found
    """
    try:
        status_data = await service.get_processing_status(file_id)
        return FileStatusResponse(**status_data)

    except NotFoundError as err:
        msg = "File"
        raise NotFoundError(msg, {"id": str(file_id)}) from err


# Batch Operations


@router.post(
    "/batch/upload",
    response_model=BatchUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Batch upload files",
    description="Upload multiple files in a single request.",
)
async def batch_upload_files(
    files: Annotated[list[UploadFile], File(...)],
    service: Annotated[FileService, Depends(get_file_service)],
    owner_id: str | None = None,
    is_public: bool = False,
) -> BatchUploadResponse:
    """Upload multiple files in batch.

    Args:
        files: List of files to upload
        owner_id: Optional owner identifier
        is_public: Whether files should be publicly accessible
        service: File service

    Returns:
        Batch upload results with success/failure details

    Raises:
        400: Invalid files in batch
        503: Storage not available
    """
    track_feature_usage("file_batch_upload", is_authenticated=False)
    track_user_action("batch_upload", is_authenticated=False)

    if not files:
        raise BadRequestException(
            detail="No files provided",
            type="no-files",
        )

    if len(files) > 100:
        raise BadRequestException(
            detail="Maximum 100 files per batch upload",
            type="too-many-files",
        )

    # Prepare files for batch upload
    file_tuples = []
    for file in files:
        if not file.filename:
            raise BadRequestException(
                detail="Filename is required for all files",
                type="missing-filename",
            )
        if not file.content_type:
            raise BadRequestException(
                detail="Content type is required for all files",
                type="missing-content-type",
            )
        file_tuples.append((file.file, file.filename, file.content_type))

    try:
        result = await service.batch_upload_files(
            files=file_tuples,
            owner_id=owner_id,
            is_public=is_public,
        )

        return BatchUploadResponse(**result)

    except StorageClientError as e:
        logger.error("Storage error during batch upload", extra={"error": str(e)})
        raise ServiceUnavailableException(
            detail="Failed to upload files to storage",
            type="storage-batch-upload-failed",
        ) from e


@router.post(
    "/batch/download",
    response_model=BatchDownloadResponse,
    summary="Batch download files",
    description="Get download URLs for multiple files.",
)
async def batch_download_files(
    request: BatchDownloadRequest,
    service: Annotated[FileService, Depends(get_file_service)],
) -> BatchDownloadResponse:
    """Get download URLs for multiple files in batch.

    Args:
        request: Batch download request with file IDs
        service: File service

    Returns:
        Batch download response with URLs for each file

    Raises:
        400: Invalid request
    """
    track_feature_usage("file_batch_download", is_authenticated=False)
    track_user_action("batch_download", is_authenticated=False)

    try:
        result = await service.batch_download_urls(file_ids=request.file_ids)
        return BatchDownloadResponse(**result)

    except Exception as e:
        logger.error("Error during batch download", extra={"error": str(e)})
        raise InternalServerException(
            detail="Failed to generate download URLs",
            type="batch-download-failed",
        ) from e


@router.post(
    "/batch/delete",
    response_model=BatchDeleteResponse,
    summary="Batch delete files",
    description="Delete multiple files with optional dry-run preview.",
)
async def batch_delete_files(
    request: BatchDeleteRequest,
    service: Annotated[FileService, Depends(get_file_service)],
) -> BatchDeleteResponse:
    """Delete multiple files in batch with optional dry-run.

    Args:
        request: Batch delete request with file IDs and options
        service: File service

    Returns:
        Batch delete results with success/failure details

    Raises:
        400: Invalid request
    """
    track_feature_usage("file_batch_delete", is_authenticated=False)
    track_user_action("batch_delete", is_authenticated=False)

    try:
        result = await service.batch_delete_files(
            file_ids=request.file_ids,
            dry_run=request.dry_run,
            hard_delete=request.hard_delete,
        )

        return BatchDeleteResponse(**result)

    except Exception as e:
        logger.error("Error during batch delete", extra={"error": str(e)})
        raise InternalServerException(
            detail="Failed to delete files",
            type="batch-delete-failed",
        ) from e


# File Operations


@router.post(
    "/{file_id}/copy",
    response_model=FileRead,
    status_code=status.HTTP_201_CREATED,
    summary="Copy file",
    description="Create a copy of a file.",
    responses={
        404: {"description": "File not found"},
        400: {"description": "File not ready for copying"},
    },
)
async def copy_file(
    file_id: UUID,
    request: CopyFileRequest,
    service: Annotated[FileService, Depends(get_file_service)],
) -> FileRead:
    """Create a copy of a file.

    Args:
        file_id: File UUID to copy
        request: Copy request with optional new filename
        service: File service

    Returns:
        Created file copy

    Raises:
        404: File not found
        400: File not ready for copying
    """
    track_feature_usage("file_copy", is_authenticated=False)
    track_user_action("copy", is_authenticated=False)

    try:
        copied_file = await service.copy_file(
            file_id=file_id,
            new_filename=request.new_filename,
        )

        return FileRead.model_validate(copied_file)

    except NotFoundError as err:
        msg = "File"
        raise NotFoundError(msg, {"id": str(file_id)}) from err
    except ValueError as e:
        raise BadRequestException(
            detail=str(e),
            type="file-not-ready-for-copy",
        ) from e
    except StorageClientError as e:
        logger.error("Storage error during file copy", extra={"error": str(e)})
        raise ServiceUnavailableException(
            detail="Failed to copy file in storage",
            type="storage-copy-failed",
        ) from e


@router.post(
    "/{file_id}/move",
    response_model=FileRead,
    summary="Move/rename file",
    description="Move or rename a file.",
    responses={404: {"description": "File not found"}},
)
async def move_file(
    file_id: UUID,
    request: MoveFileRequest,
    service: Annotated[FileService, Depends(get_file_service)],
) -> FileRead:
    """Move or rename a file.

    Args:
        file_id: File UUID to move/rename
        request: Move request with new filename
        service: File service

    Returns:
        Updated file record

    Raises:
        404: File not found
    """
    track_feature_usage("file_move", is_authenticated=False)
    track_user_action("move", is_authenticated=False)

    try:
        moved_file = await service.move_file(
            file_id=file_id,
            new_filename=request.new_filename,
        )

        return FileRead.model_validate(moved_file)

    except NotFoundError as err:
        msg = "File"
        raise NotFoundError(msg, {"id": str(file_id)}) from err
