"""Data transfer REST API endpoints.

Provides endpoints for data export and import operations.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import StreamingResponse

from example_service.core.dependencies.accent_auth import get_current_user
from example_service.core.schemas.auth import AuthUser
from example_service.core.dependencies.database import get_db_session
from example_service.core.exceptions import BadRequestException

from .schemas import (
    ExportFormat,
    ExportRequest,
    ExportResult,
    ImportFormat,
    ImportResult,
    SupportedEntitiesResponse,
)
from .service import DataTransferService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/data-transfer", tags=["data-transfer"])


@router.get(
    "/entities",
    response_model=SupportedEntitiesResponse,
    summary="List supported entities",
    description="Get list of entities that can be exported or imported.",
)
async def list_supported_entities(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _user: Annotated[AuthUser, Depends(get_current_user)],
) -> SupportedEntitiesResponse:
    """Get list of entities supported for data transfer.

    Returns information about which entities can be exported/imported
    and their available fields.
    """
    service = DataTransferService(session)
    entities = service.get_supported_entities()
    return SupportedEntitiesResponse(entities=entities)


@router.post(
    "/export",
    response_model=ExportResult,
    summary="Export data to file",
    description="Export entity data to CSV, JSON, or Excel format.",
)
async def export_data(
    request: ExportRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _user: Annotated[AuthUser, Depends(get_current_user)],
) -> ExportResult:
    """Export data to a file.

    Creates an export file in the specified format with optional filters.

    Args:
        request: Export configuration including entity type, format, and filters.

    Returns:
        Export result with file path and statistics.
    """
    service = DataTransferService(session)
    return await service.export(request)


@router.get(
    "/export/download",
    summary="Download export directly",
    description="Export and stream download directly without saving to server.",
)
async def download_export(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _user: Annotated[AuthUser, Depends(get_current_user)],
    entity_type: Annotated[str, Query(description="Entity type to export")],
    format: Annotated[ExportFormat, Query(description="Export format")] = ExportFormat.CSV,
) -> StreamingResponse:
    """Export data and stream directly as download.

    This endpoint exports data and streams it directly to the client
    without saving to the server filesystem.

    Args:
        entity_type: Type of entity to export.
        format: Output format (csv, json, xlsx).

    Returns:
        Streaming file download response.
    """
    service = DataTransferService(session)

    request = ExportRequest(
        entity_type=entity_type,
        format=format,
    )

    try:
        data, content_type, filename = await service.export_to_bytes(request)
    except ValueError as e:
        raise BadRequestException(
            detail=str(e),
            type="export-error",
        ) from e

    return StreamingResponse(
        iter([data]),
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(data)),
        },
    )


@router.post(
    "/import",
    response_model=ImportResult,
    summary="Import data from file",
    description="Import entity data from CSV, JSON, or Excel file.",
)
async def import_data(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _user: Annotated[AuthUser, Depends(get_current_user)],
    file: Annotated[UploadFile, File(description="File to import")],
    entity_type: Annotated[str, Query(description="Entity type to import")],
    format: Annotated[ImportFormat, Query(description="File format")],
    validate_only: Annotated[
        bool, Query(description="Only validate, don't import")
    ] = False,
    skip_errors: Annotated[
        bool, Query(description="Continue on errors")
    ] = False,
    update_existing: Annotated[
        bool, Query(description="Update existing records")
    ] = False,
) -> ImportResult:
    """Import data from an uploaded file.

    Parses the uploaded file, validates records, and imports them
    into the database.

    Args:
        file: Uploaded file to import.
        entity_type: Type of entity to import.
        format: File format (csv, json, xlsx).
        validate_only: If true, only validate without importing.
        skip_errors: If true, continue importing even if some records fail.
        update_existing: If true, update existing records instead of skipping.

    Returns:
        Import result with statistics and any validation errors.
    """
    service = DataTransferService(session)

    # Read file content
    content = await file.read()

    try:
        result = await service.import_from_bytes(
            data=content,
            entity_type=entity_type,
            format=format,
            validate_only=validate_only,
            skip_errors=skip_errors,
            update_existing=update_existing,
        )
    except ValueError as e:
        raise BadRequestException(
            detail=str(e),
            type="import-error",
        ) from e

    return result


@router.post(
    "/import/validate",
    response_model=ImportResult,
    summary="Validate import file",
    description="Validate an import file without actually importing.",
)
async def validate_import(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _user: Annotated[AuthUser, Depends(get_current_user)],
    file: Annotated[UploadFile, File(description="File to validate")],
    entity_type: Annotated[str, Query(description="Entity type")],
    format: Annotated[ImportFormat, Query(description="File format")],
) -> ImportResult:
    """Validate an import file without importing.

    Useful for checking if a file is valid before committing to import.

    Args:
        file: File to validate.
        entity_type: Type of entity.
        format: File format.

    Returns:
        Validation result with any errors found.
    """
    service = DataTransferService(session)
    content = await file.read()

    try:
        result = await service.import_from_bytes(
            data=content,
            entity_type=entity_type,
            format=format,
            validate_only=True,
        )
    except ValueError as e:
        raise BadRequestException(
            detail=str(e),
            type="validation-error",
        ) from e

    return result


@router.get(
    "/formats",
    summary="List supported formats",
    description="Get list of supported export and import formats.",
)
async def list_formats(
    _user: Annotated[AuthUser, Depends(get_current_user)],
) -> dict:
    """Get supported data transfer formats.

    Returns:
        Dictionary with export and import format options.
    """
    return {
        "export_formats": [f.value for f in ExportFormat],
        "import_formats": [f.value for f in ImportFormat],
    }
