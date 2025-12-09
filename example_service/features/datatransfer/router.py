"""Data transfer REST API endpoints.

Provides endpoints for data export and import operations.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import StreamingResponse

from example_service.core.dependencies.accent_auth import get_current_user
from example_service.core.schemas.auth import AuthUser
from example_service.core.dependencies.database import get_db_session
from example_service.core.dependencies.ratelimit import per_user_rate_limit, rate_limit
from example_service.core.dependencies.tenant import TenantContextDep
from example_service.core.exceptions import BadRequestException
from example_service.core.settings import get_datatransfer_settings

from .audit import log_export_operation, log_import_operation
from .webhooks import notify_export_complete, notify_import_complete
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


async def validate_file_size(file: UploadFile) -> bytes:
    """Validate uploaded file size and return content.

    Args:
        file: Uploaded file to validate.

    Returns:
        File content as bytes.

    Raises:
        BadRequestException: If file exceeds maximum size.
    """
    settings = get_datatransfer_settings()
    max_size = settings.max_import_size_bytes

    # Read file content
    content = await file.read()

    # Check size
    if len(content) > max_size:
        raise BadRequestException(
            detail=(
                f"File size ({len(content) / (1024 * 1024):.2f} MB) exceeds "
                f"maximum allowed size ({settings.max_import_size_mb} MB)"
            ),
            type="file-too-large",
        )

    return content


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


# Rate limit for export operations: 20 exports per minute per user
ExportRateLimit = Annotated[None, Depends(per_user_rate_limit(limit=20, window=60))]

# Rate limit for import operations: 10 imports per minute per user
ImportRateLimit = Annotated[None, Depends(per_user_rate_limit(limit=10, window=60))]

# Rate limit for streaming exports: 5 per minute (more resource-intensive)
StreamingRateLimit = Annotated[None, Depends(per_user_rate_limit(limit=5, window=60))]


@router.post(
    "/export",
    response_model=ExportResult,
    summary="Export data to file",
    description="Export entity data to CSV, JSON, or Excel format.",
)
async def export_data(
    request: ExportRequest,
    http_request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _user: Annotated[AuthUser, Depends(get_current_user)],
    user: Annotated[dict, Depends(get_current_user)],
    _rate_limit: ExportRateLimit,
    tenant: TenantContextDep = None,
) -> ExportResult:
    """Export data to a file.

    Creates an export file in the specified format with optional filters.

    Args:
        request: Export configuration including entity type, format, and filters.
        tenant: Optional tenant context for multi-tenant filtering.

    Returns:
        Export result with file path and statistics.
    """
    service = DataTransferService(session)
    tenant_id = tenant.tenant_uuid if tenant else None
    result = await service.export(request, tenant_id=tenant_id)

    user_id = user.get("id") or user.get("sub")

    # Log audit event
    await log_export_operation(
        session=session,
        request=request,
        result=result,
        user_id=user_id,
        tenant_id=tenant_id,
        ip_address=http_request.client.host if http_request.client else None,
        request_id=http_request.headers.get("x-request-id"),
    )

    # Send webhook notification
    await notify_export_complete(
        session=session,
        result=result,
        user_id=user_id,
        tenant_id=tenant_id,
    )

    return result


@router.get(
    "/export/download",
    summary="Download export directly",
    description="Export and stream download directly without saving to server.",
)
async def download_export(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _user: Annotated[AuthUser, Depends(get_current_user)],
    _rate_limit: ExportRateLimit,
    entity_type: Annotated[str, Query(description="Entity type to export")],
    format: Annotated[ExportFormat, Query(description="Export format")] = ExportFormat.CSV,
    compress: Annotated[
        bool | None, Query(description="Enable gzip compression (default from settings)")
    ] = None,
    tenant: TenantContextDep = None,
) -> StreamingResponse:
    """Export data and stream directly as download.

    This endpoint exports data and streams it directly to the client
    without saving to the server filesystem.

    Args:
        entity_type: Type of entity to export.
        format: Output format (csv, json, xlsx).
        compress: Enable gzip compression (None = use settings default).
        tenant: Optional tenant context for multi-tenant filtering.

    Returns:
        Streaming file download response.
    """
    service = DataTransferService(session)
    tenant_id = tenant.tenant_uuid if tenant else None

    request = ExportRequest(
        entity_type=entity_type,
        format=format,
    )

    try:
        data, content_type, filename = await service.export_to_bytes(
            request, tenant_id=tenant_id, compress=compress
        )
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


@router.get(
    "/export/stream",
    summary="Stream export for large datasets",
    description="Stream export data in chunks for efficient handling of large datasets.",
)
async def stream_export(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _user: Annotated[AuthUser, Depends(get_current_user)],
    _rate_limit: StreamingRateLimit,
    entity_type: Annotated[str, Query(description="Entity type to export")],
    format: Annotated[ExportFormat, Query(description="Export format")] = ExportFormat.CSV,
    chunk_size: Annotated[
        int, Query(description="Records per chunk (100-10000)", ge=100, le=10000)
    ] = 1000,
    tenant: TenantContextDep = None,
) -> StreamingResponse:
    """Stream export data for large datasets.

    This endpoint streams data in chunks to handle large exports
    without loading everything into memory. Ideal for exports with
    10,000+ records.

    Args:
        entity_type: Type of entity to export.
        format: Output format (csv or json - xlsx not supported for streaming).
        chunk_size: Number of records per chunk.
        tenant: Optional tenant context for multi-tenant filtering.

    Returns:
        Streaming response with chunked data.

    Note:
        For JSON format, data is streamed as JSON Lines (JSONL) format
        where each line is a complete JSON object.
    """
    # Excel format doesn't support streaming well
    if format == ExportFormat.XLSX:
        raise BadRequestException(
            detail="Excel format does not support streaming. Use CSV or JSON.",
            type="unsupported-format",
        )

    service = DataTransferService(session)
    tenant_id = tenant.tenant_uuid if tenant else None

    request = ExportRequest(
        entity_type=entity_type,
        format=format,
    )

    # Determine content type and filename
    timestamp = __import__("datetime").datetime.now(__import__("datetime").UTC).strftime("%Y%m%d_%H%M%S")
    if format == ExportFormat.CSV:
        content_type = "text/csv"
        filename = f"{entity_type}_{timestamp}.csv"
    else:
        content_type = "application/x-ndjson"  # JSON Lines format
        filename = f"{entity_type}_{timestamp}.jsonl"

    async def generate():
        async for chunk in service.stream_export(request, tenant_id=tenant_id, chunk_size=chunk_size):
            yield chunk

    return StreamingResponse(
        generate(),
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Streaming": "true",
        },
    )


@router.get(
    "/export/count",
    summary="Get export record count",
    description="Get the count of records that would be exported.",
)
async def get_export_count(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _user: Annotated[AuthUser, Depends(get_current_user)],
    entity_type: Annotated[str, Query(description="Entity type to count")],
    tenant: TenantContextDep = None,
) -> dict:
    """Get count of records that would be exported.

    Useful for determining whether to use streaming export for large datasets.

    Args:
        entity_type: Type of entity to count.
        tenant: Optional tenant context for multi-tenant filtering.

    Returns:
        Dictionary with record count.
    """
    service = DataTransferService(session)
    tenant_id = tenant.tenant_uuid if tenant else None

    try:
        count = await service.get_export_count(entity_type, tenant_id=tenant_id)
    except ValueError as e:
        raise BadRequestException(
            detail=str(e),
            type="count-error",
        ) from e

    return {
        "entity_type": entity_type,
        "count": count,
        "recommended_export": "streaming" if count > 10000 else "standard",
    }


@router.post(
    "/import",
    response_model=ImportResult,
    summary="Import data from file",
    description="Import entity data from CSV, JSON, or Excel file.",
)
async def import_data(
    http_request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[AuthUser, Depends(get_current_user)],
    _rate_limit: ImportRateLimit,
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
    batch_size: Annotated[
        int, Query(description="Records per batch (1-1000)", ge=1, le=1000)
    ] = 100,
    tenant: TenantContextDep = None,
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
    tenant_id = tenant.tenant_uuid if tenant else None

    # Read and validate file content
    content = await validate_file_size(file)

    try:
        result = await service.import_from_bytes(
            data=content,
            entity_type=entity_type,
            format=format,
            validate_only=validate_only,
            skip_errors=skip_errors,
            update_existing=update_existing,
            batch_size=batch_size,
        )
    except ValueError as e:
        raise BadRequestException(
            detail=str(e),
            type="import-error",
        ) from e

    user_id = user.get("id") or user.get("sub")

    # Log audit event and send webhook (only for actual imports, not validation-only)
    if not validate_only:
        await log_import_operation(
            session=session,
            result=result,
            user_id=user_id,
            tenant_id=tenant_id,
            ip_address=http_request.client.host if http_request.client else None,
            request_id=http_request.headers.get("x-request-id"),
        )

        # Send webhook notification
        await notify_import_complete(
            session=session,
            result=result,
            user_id=user_id,
            tenant_id=tenant_id,
        )

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

    # Read and validate file content
    content = await validate_file_size(file)

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


@router.get(
    "/import/template",
    summary="Download import template",
    description="Download a sample template file for importing data.",
)
async def download_import_template(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _user: Annotated[AuthUser, Depends(get_current_user)],
    entity_type: Annotated[str, Query(description="Entity type to get template for")],
    format: Annotated[ImportFormat, Query(description="Template format")] = ImportFormat.CSV,
) -> StreamingResponse:
    """Download a sample import template.

    Returns a template file with headers and sample data showing the
    expected format for importing the specified entity type.

    Args:
        entity_type: Type of entity to get template for.
        format: Output format (csv, json, xlsx).

    Returns:
        Streaming file download with template.
    """
    service = DataTransferService(session)

    try:
        data, content_type, filename = service.generate_import_template(
            entity_type=entity_type,
            format=format,
        )
    except ValueError as e:
        raise BadRequestException(
            detail=str(e),
            type="template-error",
        ) from e

    # Rename file to indicate it's a template
    template_filename = f"{entity_type}_template.{format.value}"

    return StreamingResponse(
        iter([data]),
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{template_filename}"',
            "Content-Length": str(len(data)),
        },
    )


# =============================================================================
# Job Status Endpoints
# =============================================================================


@router.get(
    "/jobs/{job_id}",
    summary="Get job status",
    description="Get the status and progress of a background job.",
)
async def get_job_status(
    job_id: str,
    _user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    """Get status of a background job.

    Args:
        job_id: ID of the job to check.

    Returns:
        Job progress information.
    """
    from .jobs import get_job_tracker

    tracker = get_job_tracker()
    job = await tracker.get_job(job_id)

    if job is None:
        raise BadRequestException(
            detail=f"Job not found: {job_id}",
            type="job-not-found",
        )

    return job.to_dict()


@router.get(
    "/jobs",
    summary="List jobs",
    description="List background jobs with optional filtering.",
)
async def list_jobs(
    _user: Annotated[AuthUser, Depends(get_current_user)],
    job_type: Annotated[str | None, Query(description="Filter by job type (export/import)")] = None,
    status: Annotated[str | None, Query(description="Filter by status")] = None,
    limit: Annotated[int, Query(description="Maximum jobs to return", ge=1, le=500)] = 100,
) -> dict:
    """List background jobs.

    Args:
        job_type: Optional filter by job type.
        status: Optional filter by status.
        limit: Maximum number of jobs to return.

    Returns:
        List of jobs.
    """
    from .jobs import JobStatus, JobType, get_job_tracker

    tracker = get_job_tracker()

    jt = JobType(job_type) if job_type else None
    st = JobStatus(status) if status else None

    jobs = await tracker.list_jobs(job_type=jt, status=st, limit=limit)

    return {
        "jobs": [j.to_dict() for j in jobs],
        "total": len(jobs),
    }


@router.post(
    "/jobs/{job_id}/cancel",
    summary="Cancel job",
    description="Cancel a pending or running job.",
)
async def cancel_job(
    job_id: str,
    _user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    """Cancel a background job.

    Args:
        job_id: ID of the job to cancel.

    Returns:
        Cancellation result.
    """
    from .jobs import get_job_tracker

    tracker = get_job_tracker()
    cancelled = await tracker.cancel_job(job_id)

    if not cancelled:
        raise BadRequestException(
            detail=f"Job cannot be cancelled: {job_id}",
            type="job-cancel-failed",
        )

    return {"job_id": job_id, "cancelled": True}


# =============================================================================
# Stats Endpoint
# =============================================================================


@router.get(
    "/stats",
    summary="Get export statistics",
    description="Get statistics about export files.",
)
async def get_stats(
    _user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    """Get export file statistics.

    Returns:
        Export statistics including file count and sizes.
    """
    from .cleanup import get_export_stats

    return get_export_stats()


# =============================================================================
# Webhook Events Endpoint
# =============================================================================


@router.get(
    "/webhooks/events",
    summary="List webhook events",
    description="Get list of webhook events triggered by data transfer operations.",
)
async def list_webhook_events(
    _user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    """Get list of supported webhook events.

    Returns information about webhook events that can be subscribed to
    for data transfer operations.

    Returns:
        List of webhook event types and descriptions.
    """
    from .webhooks import get_supported_events

    return {
        "events": get_supported_events(),
        "description": (
            "Subscribe to these events to receive notifications when "
            "data transfer operations complete. Configure webhooks at "
            "/api/v1/webhooks with the event types listed above."
        ),
    }
