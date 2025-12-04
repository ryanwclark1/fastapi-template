"""Mutation resolvers for files.

Provides write operations for files:
- initiateFileUpload: Generate presigned upload URL for client-side upload
- confirmFileUpload: Confirm that presigned upload completed successfully
- deleteFile: Delete a file (soft or hard delete)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

import strawberry

from example_service.features.files.schemas import FileRead
from example_service.features.files.service import FileService
from example_service.features.graphql.events import (
    publish_file_event,
    serialize_model_for_event,
)
from example_service.features.graphql.types.files import (
    ConfirmUploadInput,
    DeletePayload,
    FileError,
    FileErrorCode,
    FilePayload,
    FileSuccess,
    FileType,
    InitiateUploadInput,
    PresignedUploadResponse,
)
from example_service.infra.storage.exceptions import (
    StorageError,
    StorageNotConfiguredError,
)

if TYPE_CHECKING:
    from strawberry.types import Info

    from example_service.features.graphql.context import GraphQLContext

logger = logging.getLogger(__name__)


async def initiate_file_upload_mutation(
    info: Info[GraphQLContext, None],
    input: InitiateUploadInput,
) -> PresignedUploadResponse | FileError:
    """Initiate a presigned file upload.

    This mutation generates a presigned URL that the client can use to upload
    directly to S3, bypassing the server for better performance with large files.

    Flow:
    1. Call this mutation to get presigned URL
    2. Client POSTs file to upload_url with upload_fields
    3. Client calls confirmFileUpload with file_id

    Args:
        info: Strawberry info with context
        input: Upload initiation data

    Returns:
        PresignedUploadResponse with upload URL, or FileError
    """
    ctx = info.context

    # Convert GraphQL input to Pydantic for validation
    try:
        upload_request = input.to_pydantic()
    except Exception as e:
        return FileError(
            code=FileErrorCode.VALIDATION_ERROR,
            message=f"Invalid input: {e!s}",
            field="input",
        )

    try:
        # Create file service
        service = FileService(session=ctx.session)

        # Generate presigned upload
        result = await service.create_presigned_upload(
            filename=upload_request.filename,
            content_type=upload_request.content_type,
            size_bytes=upload_request.size_bytes,
            owner_id=upload_request.owner_id,
            is_public=upload_request.is_public,
            expires_at=upload_request.expires_at,
        )

        await ctx.session.commit()

        logger.info(f"Presigned upload initiated: {result['file_id']}")

        # Fetch file record for event publishing
        from example_service.features.files.repository import get_file_repository

        file_repo = get_file_repository()
        file = await file_repo.get(ctx.session, result["file_id"])
        if file:
            # Publish event for real-time subscriptions
            await publish_file_event(
                event_type="INITIATED",
                file_data=serialize_model_for_event(file),
            )

        return PresignedUploadResponse(
            upload_url=result["upload_url"],
            upload_fields=result["upload_fields"],
            file_id=strawberry.ID(str(result["file_id"])),
            storage_key=result["storage_key"],
            expires_in=result["expires_in"],
        )

    except StorageNotConfiguredError as e:
        logger.exception(f"Storage not configured: {e}")
        await ctx.session.rollback()
        return FileError(
            code=FileErrorCode.STORAGE_ERROR,
            message="File storage is not configured",
        )
    except Exception as e:
        # Catch validation errors from service (InvalidFileError, etc.)
        error_msg = str(e)
        logger.exception(f"Error initiating file upload: {e}")
        await ctx.session.rollback()

        # Determine error code based on exception type
        if "not allowed" in error_msg.lower() or "exceeds maximum" in error_msg.lower():
            return FileError(
                code=FileErrorCode.VALIDATION_ERROR,
                message=error_msg,
            )
        return FileError(
            code=FileErrorCode.INTERNAL_ERROR,
            message="Failed to initiate file upload",
        )


async def confirm_file_upload_mutation(
    info: Info[GraphQLContext, None],
    input: ConfirmUploadInput,
) -> FilePayload:
    """Confirm that a presigned file upload has completed.

    After the client uploads directly to S3, they must call this mutation
    to verify the file exists and mark it as ready for use.

    Args:
        info: Strawberry info with context
        input: Upload confirmation data

    Returns:
        FileSuccess with the confirmed file, or FileError
    """
    ctx = info.context

    try:
        file_uuid = UUID(str(input.file_id))
    except ValueError:
        return FileError(
            code=FileErrorCode.VALIDATION_ERROR,
            message="Invalid file ID format",
            field="file_id",
        )

    try:
        # Create file service
        service = FileService(session=ctx.session)

        # Complete the upload
        file = await service.complete_upload(
            file_id=file_uuid,
            etag=input.etag,
        )

        await ctx.session.commit()

        logger.info(f"File upload confirmed: {file_uuid}")

        # Publish event for real-time subscriptions
        await publish_file_event(
            event_type="CONFIRMED",
            file_data=serialize_model_for_event(file),
        )

        # Convert: SQLAlchemy → Pydantic → GraphQL
        file_pydantic = FileRead.from_orm(file)
        return FileSuccess(file=FileType.from_pydantic(file_pydantic))

    except ValueError as e:
        # File not found or invalid status
        await ctx.session.rollback()

        # Publish FAILED event
        file_data = {"id": str(file_uuid), "error_message": str(e)}
        await publish_file_event(
            event_type="FAILED",
            file_data=file_data,
        )

        return FileError(
            code=FileErrorCode.INVALID_STATUS,
            message=str(e),
        )
    except StorageError as e:
        # File not found in storage
        logger.exception(f"Storage error confirming upload: {e}")
        await ctx.session.rollback()

        # Publish FAILED event
        file_data = {"id": str(file_uuid), "error_message": "File not found in storage"}
        await publish_file_event(
            event_type="FAILED",
            file_data=file_data,
        )

        return FileError(
            code=FileErrorCode.STORAGE_ERROR,
            message="File not found in storage. Upload may have failed.",
        )
    except Exception as e:
        logger.exception(f"Error confirming file upload: {e}")
        await ctx.session.rollback()
        return FileError(
            code=FileErrorCode.INTERNAL_ERROR,
            message="Failed to confirm file upload",
        )


async def delete_file_mutation(
    info: Info[GraphQLContext, None],
    id: strawberry.ID,
    hard_delete: bool = False,
) -> DeletePayload:
    """Delete a file.

    By default performs a soft delete (marks as DELETED).
    If hard_delete=true, deletes from storage and database.

    Args:
        info: Strawberry info with context
        id: File UUID
        hard_delete: If true, permanently delete from storage

    Returns:
        DeletePayload indicating success or failure
    """
    ctx = info.context

    try:
        file_uuid = UUID(str(id))
    except ValueError:
        return DeletePayload(
            success=False,
            message="Invalid file ID format",
        )

    try:
        # Create file service
        service = FileService(session=ctx.session)

        # Fetch file record before deletion for event publishing
        from example_service.features.files.repository import get_file_repository

        file_repo = get_file_repository()
        file = await file_repo.get(ctx.session, file_uuid)
        if not file:
            return DeletePayload(
                success=False,
                message=f"File with ID {id} not found",
            )

        # Capture file data before deletion
        file_data = serialize_model_for_event(file)

        # Delete file
        await service.delete_file(file_id=file_uuid, hard_delete=hard_delete)
        await ctx.session.commit()

        logger.info(
            f"File {'hard' if hard_delete else 'soft'} deleted: {file_uuid}"
        )

        # Publish event for real-time subscriptions
        await publish_file_event(
            event_type="DELETED",
            file_data=file_data,
        )

        return DeletePayload(
            success=True,
            message=f"File {'permanently deleted' if hard_delete else 'deleted successfully'}",
        )

    except ValueError as e:
        # File not found
        await ctx.session.rollback()
        return DeletePayload(
            success=False,
            message=str(e),
        )
    except Exception as e:
        logger.exception(f"Error deleting file: {e}")
        await ctx.session.rollback()
        return DeletePayload(
            success=False,
            message="Failed to delete file",
        )


__all__ = [
    "confirm_file_upload_mutation",
    "delete_file_mutation",
    "initiate_file_upload_mutation",
]
