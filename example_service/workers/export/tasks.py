"""Data export task definitions.

This module provides:
- CSV and JSON export of database records via DataTransferService
- Flexible filtering and field selection
- Optional S3 upload of exports
- Job tracking and progress updates via JobManager
"""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID
import warnings

from example_service.core.settings.datatransfer import DEFAULT_EXPORT_DIR
from example_service.features.datatransfer.schemas import ExportFormat, ExportRequest
from example_service.features.datatransfer.service import DataTransferService
from example_service.infra.database.session import get_async_session
from example_service.infra.tasks.broker import broker
from example_service.infra.tasks.jobs.manager import JobManager, JobNotFoundError

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# Export directory (development/testing - use proper temp directory in production)
EXPORT_DIR = DEFAULT_EXPORT_DIR


def ensure_export_dir() -> Path:
    """Ensure export directory exists."""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    return EXPORT_DIR


if broker is not None:

    @broker.task(retry_on_error=True, max_retries=3)
    async def export_data_csv(
        model_name: str | None = None,
        entity_type: str | None = None,
        filters: dict[str, Any] | None = None,
        fields: list[str] | None = None,
        upload_to_s3: bool = False,
        job_id: str | None = None,
    ) -> dict:
        """Export data to CSV file using DataTransferService.

        Args:
            model_name: DEPRECATED - Use entity_type instead.
                Legacy parameter for backward compatibility.
            entity_type: Type of entity to export
                (e.g., "reminders", "files", "webhooks", "audit_logs").
            filters: Optional query filters (simple equality filters).
            fields: Optional list of fields to include (all if not specified).
            upload_to_s3: Whether to upload to S3 after export.
            job_id: Optional job ID for JobManager tracking.

        Returns:
            Export result with file path and record count.

        Example:
            from example_service.workers.export import export_data_csv

            # Export all reminders (new style)
            task = await export_data_csv.kiq(entity_type="reminders")

            # Export with filters
            task = await export_data_csv.kiq(
                entity_type="reminders",
                filters={"is_completed": False},
            )
            result = await task.wait_result()
            print(result["filepath"])

            # With job tracking
            task = await export_data_csv.kiq(
                entity_type="reminders",
                job_id="123e4567-e89b-12d3-a456-426614174000",
            )
        """
        # Handle backward compatibility for model_name parameter
        if model_name is not None and entity_type is None:
            warnings.warn(
                "Parameter 'model_name' is deprecated and will be removed in "
                "a future version. Use 'entity_type' instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            entity_type = model_name
        elif entity_type is None:
            msg = (
                "Either 'entity_type' or deprecated 'model_name' parameter "
                "must be provided"
            )
            raise ValueError(msg)

        async with get_async_session() as session:
            # Initialize JobManager if job_id provided
            job_manager = None
            job_uuid = None
            if job_id:
                try:
                    job_uuid = UUID(job_id)
                    job_manager = JobManager(session)
                    await job_manager.mark_running(job_uuid)
                    logger.info(
                        "Export job started",
                        extra={
                            "job_id": job_id,
                            "entity_type": entity_type,
                            "format": "csv",
                        },
                    )
                except (ValueError, JobNotFoundError) as e:
                    logger.warning(
                        "Failed to initialize job tracking",
                        extra={"job_id": job_id, "error": str(e)},
                    )
                    job_manager = None

            try:
                # Use DataTransferService for export
                service = DataTransferService(session)

                # Build export request
                request = ExportRequest(
                    entity_type=entity_type,
                    format=ExportFormat.CSV,
                    filters=filters,
                    fields=fields,
                    upload_to_storage=upload_to_s3,
                )

                # Execute export
                # Note: DataTransferService.export() does not currently support
                # progress_callback. This is a TODO for future enhancement
                export_result = await service.export(
                    request,
                    # Pass tenant context when multi-tenancy is enabled (https://github.com/example-service/issues/1234)
                    tenant_id=None,
                )

                # Check if export was successful
                if export_result.status.value != "completed":
                    error_msg = (
                        export_result.error_message
                        or "Export failed with unknown error"
                    )
                    if job_manager and job_uuid:
                        await job_manager.mark_failed(job_uuid, error_msg)

                    logger.error(
                        "CSV export failed",
                        extra={
                            "entity_type": entity_type,
                            "status": export_result.status.value,
                            "error": error_msg,
                        },
                    )

                    return {
                        "status": "error",
                        "reason": error_msg,
                        "entity_type": entity_type,
                        "format": "csv",
                    }

                # Update job status if tracking
                if job_manager and job_uuid:
                    await job_manager.mark_completed(
                        job_uuid,
                        result_data={
                            "file_path": export_result.file_path,
                            "file_name": export_result.file_name,
                            "record_count": export_result.record_count,
                            "size_bytes": export_result.size_bytes,
                            "storage_uri": export_result.storage_uri,
                        },
                    )

                # Build legacy-compatible return dict
                timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
                result = {
                    "status": "success",
                    "format": "csv",
                    "model": entity_type,  # For backward compatibility
                    "entity_type": entity_type,
                    "filepath": export_result.file_path or "",
                    "filename": export_result.file_name or "",
                    "record_count": export_result.record_count,
                    "size_bytes": export_result.size_bytes,
                    "size_kb": (
                        round(export_result.size_bytes / 1024, 2)
                        if export_result.size_bytes
                        else 0
                    ),
                    "timestamp": timestamp,
                    "export_id": export_result.export_id,
                }

                # Add S3 URI if uploaded
                if export_result.storage_uri:
                    result["s3_uri"] = export_result.storage_uri
                elif upload_to_s3:
                    result["s3_skipped"] = "S3 upload requested but not completed"

                logger.info("CSV export completed", extra=result)

                return result

            except Exception as e:
                error_msg = f"Export task failed: {e}"
                logger.exception(
                    "CSV export task failed",
                    extra={
                        "entity_type": entity_type,
                        "job_id": job_id,
                        "error": str(e),
                    },
                )

                if job_manager and job_uuid:
                    await job_manager.mark_failed(job_uuid, error_msg)

                raise

    @broker.task(retry_on_error=True, max_retries=3)
    async def export_data_json(
        model_name: str | None = None,
        entity_type: str | None = None,
        filters: dict[str, Any] | None = None,
        fields: list[str] | None = None,
        upload_to_s3: bool = False,
        job_id: str | None = None,
    ) -> dict:
        """Export data to JSON file using DataTransferService.

        Args:
            model_name: DEPRECATED - Use entity_type instead.
                Legacy parameter for backward compatibility.
            entity_type: Type of entity to export
                (e.g., "reminders", "files", "webhooks", "audit_logs").
            filters: Optional query filters (simple equality filters).
            fields: Optional list of fields to include (all if not specified).
            upload_to_s3: Whether to upload to S3 after export.
            job_id: Optional job ID for JobManager tracking.

        Returns:
            Export result with file path and record count.

        Example:
            from example_service.workers.export import export_data_json

            # Export all reminders (new style)
            task = await export_data_json.kiq(entity_type="reminders")

            # Export with filters
            task = await export_data_json.kiq(
                entity_type="webhooks",
                filters={"is_active": True},
            )
            result = await task.wait_result()
            print(result["filepath"])

            # With job tracking
            task = await export_data_json.kiq(
                entity_type="audit_logs",
                job_id="123e4567-e89b-12d3-a456-426614174000",
            )
        """
        # Handle backward compatibility for model_name parameter
        if model_name is not None and entity_type is None:
            warnings.warn(
                "Parameter 'model_name' is deprecated and will be removed in "
                "a future version. Use 'entity_type' instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            entity_type = model_name
        elif entity_type is None:
            msg = (
                "Either 'entity_type' or deprecated 'model_name' parameter "
                "must be provided"
            )
            raise ValueError(msg)

        async with get_async_session() as session:
            # Initialize JobManager if job_id provided
            job_manager = None
            job_uuid = None
            if job_id:
                try:
                    job_uuid = UUID(job_id)
                    job_manager = JobManager(session)
                    await job_manager.mark_running(job_uuid)
                    logger.info(
                        "Export job started",
                        extra={
                            "job_id": job_id,
                            "entity_type": entity_type,
                            "format": "json",
                        },
                    )
                except (ValueError, JobNotFoundError) as e:
                    logger.warning(
                        "Failed to initialize job tracking",
                        extra={"job_id": job_id, "error": str(e)},
                    )
                    job_manager = None

            try:
                # Use DataTransferService for export
                service = DataTransferService(session)

                # Build export request
                request = ExportRequest(
                    entity_type=entity_type,
                    format=ExportFormat.JSON,
                    filters=filters,
                    fields=fields,
                    upload_to_storage=upload_to_s3,
                )

                # Execute export
                # Note: DataTransferService.export() does not currently support
                # progress_callback. This is a TODO for future enhancement
                export_result = await service.export(
                    request,
                    # Pass tenant context when multi-tenancy is enabled (https://github.com/example-service/issues/1234)
                    tenant_id=None,
                )

                # Check if export was successful
                if export_result.status.value != "completed":
                    error_msg = (
                        export_result.error_message
                        or "Export failed with unknown error"
                    )
                    if job_manager and job_uuid:
                        await job_manager.mark_failed(job_uuid, error_msg)

                    logger.error(
                        "JSON export failed",
                        extra={
                            "entity_type": entity_type,
                            "status": export_result.status.value,
                            "error": error_msg,
                        },
                    )

                    return {
                        "status": "error",
                        "reason": error_msg,
                        "entity_type": entity_type,
                        "format": "json",
                    }

                # Update job status if tracking
                if job_manager and job_uuid:
                    await job_manager.mark_completed(
                        job_uuid,
                        result_data={
                            "file_path": export_result.file_path,
                            "file_name": export_result.file_name,
                            "record_count": export_result.record_count,
                            "size_bytes": export_result.size_bytes,
                            "storage_uri": export_result.storage_uri,
                        },
                    )

                # Build legacy-compatible return dict
                timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
                result = {
                    "status": "success",
                    "format": "json",
                    "model": entity_type,  # For backward compatibility
                    "entity_type": entity_type,
                    "filepath": export_result.file_path or "",
                    "filename": export_result.file_name or "",
                    "record_count": export_result.record_count,
                    "size_bytes": export_result.size_bytes,
                    "size_kb": (
                        round(export_result.size_bytes / 1024, 2)
                        if export_result.size_bytes
                        else 0
                    ),
                    "timestamp": timestamp,
                    "export_id": export_result.export_id,
                }

                # Add S3 URI if uploaded
                if export_result.storage_uri:
                    result["s3_uri"] = export_result.storage_uri
                elif upload_to_s3:
                    result["s3_skipped"] = "S3 upload requested but not completed"

                logger.info("JSON export completed", extra=result)

                return result

            except Exception as e:
                error_msg = f"Export task failed: {e}"
                logger.exception(
                    "JSON export task failed",
                    extra={
                        "entity_type": entity_type,
                        "job_id": job_id,
                        "error": str(e),
                    },
                )

                if job_manager and job_uuid:
                    await job_manager.mark_failed(job_uuid, error_msg)

                raise

    @broker.task()
    async def list_exports() -> dict:
        """List available export files.

        Returns:
            Dictionary with list of export files.
        """
        export_dir = ensure_export_dir()

        exports = []
        for export_file in sorted(export_dir.glob("*.*"), reverse=True):
            if export_file.is_file():
                stat = export_file.stat()
                exports.append(
                    {
                        "filename": export_file.name,
                        "path": str(export_file),
                        "size_bytes": stat.st_size,
                        "size_kb": round(stat.st_size / 1024, 2),
                        "modified": datetime.fromtimestamp(
                            stat.st_mtime, tz=UTC,
                        ).isoformat(),
                    },
                )

        return {
            "status": "success",
            "export_dir": str(export_dir),
            "count": len(exports),
            "exports": exports,
        }
