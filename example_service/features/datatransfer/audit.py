"""Audit logging for data transfer operations.

Provides integration with the audit system for tracking all export
and import operations with detailed metadata.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from example_service.features.audit.models import AuditAction
from example_service.features.audit.service import AuditService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from .schemas import ExportRequest, ExportResult, ImportResult

logger = logging.getLogger(__name__)


class DataTransferAuditLogger:
    """Audit logger for data transfer operations.

    Provides methods for logging export and import operations
    with standardized metadata.

    Example:
        audit_logger = DataTransferAuditLogger(session)

        # Log an export
        await audit_logger.log_export(
            request=export_request,
            result=export_result,
            user_id="user-123",
        )

        # Log an import
        await audit_logger.log_import(
            result=import_result,
            user_id="user-123",
        )
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize audit logger.

        Args:
            session: Async database session.
        """
        self.session = session
        self._audit_service = AuditService(session)

    async def log_export_start(
        self,
        request: ExportRequest,
        user_id: str | None = None,
        tenant_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
    ) -> None:
        """Log the start of an export operation.

        Args:
            request: Export request details.
            user_id: User initiating the export.
            tenant_id: Tenant context.
            ip_address: Client IP.
            user_agent: Client user agent.
            request_id: Request correlation ID.
        """
        await self._audit_service.log(
            action=AuditAction.EXPORT,
            entity_type=f"datatransfer.export.{request.entity_type}",
            user_id=user_id,
            tenant_id=tenant_id,
            ip_address=ip_address,
            user_agent=user_agent,
            request_id=request_id,
            metadata={
                "status": "started",
                "entity_type": request.entity_type,
                "format": request.format.value,
                "fields": request.fields,
                "has_filters": bool(request.filters or request.filter_conditions),
                "include_headers": request.include_headers,
                "upload_to_storage": request.upload_to_storage,
            },
            success=True,
        )

    async def log_export_complete(
        self,
        request: ExportRequest,
        result: ExportResult,
        user_id: str | None = None,
        tenant_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        """Log completion of an export operation.

        Args:
            request: Export request details.
            result: Export result.
            user_id: User who initiated the export.
            tenant_id: Tenant context.
            ip_address: Client IP.
            user_agent: Client user agent.
            request_id: Request correlation ID.
            duration_ms: Operation duration in milliseconds.
        """
        success = result.status.value == "completed"

        await self._audit_service.log(
            action=AuditAction.EXPORT,
            entity_type=f"datatransfer.export.{request.entity_type}",
            entity_id=result.export_id,
            user_id=user_id,
            tenant_id=tenant_id,
            ip_address=ip_address,
            user_agent=user_agent,
            request_id=request_id,
            new_values={
                "export_id": result.export_id,
                "status": result.status.value,
                "record_count": result.record_count,
                "size_bytes": result.size_bytes,
                "file_name": result.file_name,
                "storage_uri": result.storage_uri,
            },
            metadata={
                "entity_type": request.entity_type,
                "format": request.format.value,
                "fields": request.fields,
                "has_filters": bool(request.filters or request.filter_conditions),
            },
            success=success,
            error_message=result.error_message,
            duration_ms=duration_ms,
        )

        if success:
            logger.info(
                "Export completed successfully",
                extra={
                    "export_id": result.export_id,
                    "entity_type": request.entity_type,
                    "record_count": result.record_count,
                    "user_id": user_id,
                },
            )
        else:
            logger.warning(
                "Export failed",
                extra={
                    "export_id": result.export_id,
                    "entity_type": request.entity_type,
                    "error": result.error_message,
                    "user_id": user_id,
                },
            )

    async def log_import_start(
        self,
        entity_type: str,
        format: str,
        file_size: int,
        user_id: str | None = None,
        tenant_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
        validate_only: bool = False,
    ) -> None:
        """Log the start of an import operation.

        Args:
            entity_type: Type of entity being imported.
            format: Import file format.
            file_size: Size of uploaded file in bytes.
            user_id: User initiating the import.
            tenant_id: Tenant context.
            ip_address: Client IP.
            user_agent: Client user agent.
            request_id: Request correlation ID.
            validate_only: Whether this is validation only.
        """
        await self._audit_service.log(
            action=AuditAction.IMPORT,
            entity_type=f"datatransfer.import.{entity_type}",
            user_id=user_id,
            tenant_id=tenant_id,
            ip_address=ip_address,
            user_agent=user_agent,
            request_id=request_id,
            metadata={
                "status": "started",
                "entity_type": entity_type,
                "format": format,
                "file_size_bytes": file_size,
                "validate_only": validate_only,
            },
            success=True,
        )

    async def log_import_complete(
        self,
        result: ImportResult,
        user_id: str | None = None,
        tenant_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        """Log completion of an import operation.

        Args:
            result: Import result.
            user_id: User who initiated the import.
            tenant_id: Tenant context.
            ip_address: Client IP.
            user_agent: Client user agent.
            request_id: Request correlation ID.
            duration_ms: Operation duration in milliseconds.
        """
        success = result.status.value in ("completed", "partially_completed")

        await self._audit_service.log(
            action=AuditAction.IMPORT,
            entity_type=f"datatransfer.import.{result.entity_type}",
            entity_id=result.import_id,
            user_id=user_id,
            tenant_id=tenant_id,
            ip_address=ip_address,
            user_agent=user_agent,
            request_id=request_id,
            new_values={
                "import_id": result.import_id,
                "status": result.status.value,
                "total_rows": result.total_rows,
                "successful_rows": result.successful_rows,
                "failed_rows": result.failed_rows,
                "skipped_rows": result.skipped_rows,
            },
            metadata={
                "entity_type": result.entity_type,
                "format": result.format.value if result.format else None,
                "validation_errors_count": len(result.validation_errors) if result.validation_errors else 0,
            },
            success=success,
            error_message=result.error_message,
            duration_ms=duration_ms,
        )

        if success:
            logger.info(
                "Import completed",
                extra={
                    "import_id": result.import_id,
                    "entity_type": result.entity_type,
                    "successful_rows": result.successful_rows,
                    "failed_rows": result.failed_rows,
                    "user_id": user_id,
                },
            )
        else:
            logger.warning(
                "Import failed",
                extra={
                    "import_id": result.import_id,
                    "entity_type": result.entity_type,
                    "error": result.error_message,
                    "user_id": user_id,
                },
            )

    async def log_streaming_export(
        self,
        entity_type: str,
        format: str,
        total_records: int,
        user_id: str | None = None,
        tenant_id: str | None = None,
        ip_address: str | None = None,
        request_id: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        """Log a streaming export operation.

        Args:
            entity_type: Type of entity exported.
            format: Export format.
            total_records: Total records exported.
            user_id: User who initiated the export.
            tenant_id: Tenant context.
            ip_address: Client IP.
            request_id: Request correlation ID.
            duration_ms: Operation duration in milliseconds.
        """
        await self._audit_service.log(
            action=AuditAction.EXPORT,
            entity_type=f"datatransfer.export.{entity_type}",
            user_id=user_id,
            tenant_id=tenant_id,
            ip_address=ip_address,
            request_id=request_id,
            new_values={
                "type": "streaming",
                "total_records": total_records,
            },
            metadata={
                "entity_type": entity_type,
                "format": format,
                "streaming": True,
            },
            success=True,
            duration_ms=duration_ms,
        )


def get_audit_logger(session: AsyncSession) -> DataTransferAuditLogger:
    """Get a data transfer audit logger instance.

    Args:
        session: Database session.

    Returns:
        DataTransferAuditLogger instance.
    """
    return DataTransferAuditLogger(session)


async def log_export_operation(
    session: AsyncSession,
    request: ExportRequest,
    result: ExportResult,
    user_id: str | None = None,
    tenant_id: str | None = None,
    ip_address: str | None = None,
    request_id: str | None = None,
) -> None:
    """Convenience function to log an export operation.

    Args:
        session: Database session.
        request: Export request.
        result: Export result.
        user_id: User ID.
        tenant_id: Tenant ID.
        ip_address: Client IP.
        request_id: Request correlation ID.
    """
    started_at = result.started_at
    completed_at = result.completed_at
    duration_ms = None
    if started_at and completed_at:
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)

    audit_logger = get_audit_logger(session)
    await audit_logger.log_export_complete(
        request=request,
        result=result,
        user_id=user_id,
        tenant_id=tenant_id,
        ip_address=ip_address,
        request_id=request_id,
        duration_ms=duration_ms,
    )


async def log_import_operation(
    session: AsyncSession,
    result: ImportResult,
    user_id: str | None = None,
    tenant_id: str | None = None,
    ip_address: str | None = None,
    request_id: str | None = None,
) -> None:
    """Convenience function to log an import operation.

    Args:
        session: Database session.
        result: Import result.
        user_id: User ID.
        tenant_id: Tenant ID.
        ip_address: Client IP.
        request_id: Request correlation ID.
    """
    started_at = result.started_at
    completed_at = result.completed_at
    duration_ms = None
    if started_at and completed_at:
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)

    audit_logger = get_audit_logger(session)
    await audit_logger.log_import_complete(
        result=result,
        user_id=user_id,
        tenant_id=tenant_id,
        ip_address=ip_address,
        request_id=request_id,
        duration_ms=duration_ms,
    )
