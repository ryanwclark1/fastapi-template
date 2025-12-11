"""Webhook notifications for data transfer operations.

Dispatches webhook events when export and import operations complete,
allowing external systems to react to data transfer activities.
"""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import TYPE_CHECKING
import uuid

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from .schemas import ExportResult, ImportResult

logger = logging.getLogger(__name__)


# Event type constants
class DataTransferEvent:
    """Event types for data transfer webhook notifications."""

    EXPORT_COMPLETED = "datatransfer.export.completed"
    EXPORT_FAILED = "datatransfer.export.failed"
    IMPORT_COMPLETED = "datatransfer.import.completed"
    IMPORT_FAILED = "datatransfer.import.failed"
    IMPORT_PARTIALLY_COMPLETED = "datatransfer.import.partially_completed"


async def notify_export_complete(
    session: AsyncSession,
    result: ExportResult,
    user_id: str | None = None,
    tenant_id: str | None = None,
) -> int:
    """Send webhook notification for completed export.

    Args:
        session: Database session.
        result: Export result.
        user_id: User who initiated the export.
        tenant_id: Tenant context.

    Returns:
        Number of webhook deliveries created.
    """
    from example_service.features.webhooks.dispatcher import dispatch_event

    # Determine event type based on status
    if result.status.value == "completed":
        event_type = DataTransferEvent.EXPORT_COMPLETED
    else:
        event_type = DataTransferEvent.EXPORT_FAILED

    # Build payload
    payload = {
        "export_id": result.export_id,
        "entity_type": result.entity_type,
        "format": result.format.value if result.format else None,
        "status": result.status.value,
        "record_count": result.record_count,
        "size_bytes": result.size_bytes,
        "file_name": result.file_name,
        "download_url": result.download_url,
        "storage_uri": result.storage_uri,
        "started_at": result.started_at.isoformat() if result.started_at else None,
        "completed_at": result.completed_at.isoformat() if result.completed_at else None,
        "error_message": result.error_message,
        "user_id": user_id,
        "tenant_id": tenant_id,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    # Generate event ID
    event_id = f"export-{result.export_id}"

    try:
        count = await dispatch_event(
            session=session,
            event_type=event_type,
            event_id=event_id,
            payload=payload,
        )
        logger.debug(
            "Dispatched export webhook notification",
            extra={
                "event_type": event_type,
                "event_id": event_id,
                "webhook_count": count,
            },
        )
        return count
    except Exception as e:
        logger.warning(
            "Failed to dispatch export webhook notification",
            extra={"error": str(e), "export_id": result.export_id},
        )
        return 0


async def notify_import_complete(
    session: AsyncSession,
    result: ImportResult,
    user_id: str | None = None,
    tenant_id: str | None = None,
) -> int:
    """Send webhook notification for completed import.

    Args:
        session: Database session.
        result: Import result.
        user_id: User who initiated the import.
        tenant_id: Tenant context.

    Returns:
        Number of webhook deliveries created.
    """
    from example_service.features.webhooks.dispatcher import dispatch_event

    # Determine event type based on status
    status = result.status.value
    if status == "completed":
        event_type = DataTransferEvent.IMPORT_COMPLETED
    elif status == "partially_completed":
        event_type = DataTransferEvent.IMPORT_PARTIALLY_COMPLETED
    else:
        event_type = DataTransferEvent.IMPORT_FAILED

    # Build payload
    payload = {
        "import_id": result.import_id,
        "entity_type": result.entity_type,
        "format": result.format.value if result.format else None,
        "status": status,
        "total_rows": result.total_rows,
        "processed_rows": result.processed_rows,
        "successful_rows": result.successful_rows,
        "failed_rows": result.failed_rows,
        "skipped_rows": result.skipped_rows,
        "validation_error_count": len(result.validation_errors) if result.validation_errors else 0,
        "started_at": result.started_at.isoformat() if result.started_at else None,
        "completed_at": result.completed_at.isoformat() if result.completed_at else None,
        "error_message": result.error_message,
        "user_id": user_id,
        "tenant_id": tenant_id,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    # Generate event ID
    event_id = f"import-{result.import_id}"

    try:
        count = await dispatch_event(
            session=session,
            event_type=event_type,
            event_id=event_id,
            payload=payload,
        )
        logger.debug(
            "Dispatched import webhook notification",
            extra={
                "event_type": event_type,
                "event_id": event_id,
                "webhook_count": count,
            },
        )
        return count
    except Exception as e:
        logger.warning(
            "Failed to dispatch import webhook notification",
            extra={"error": str(e), "import_id": result.import_id},
        )
        return 0


async def notify_streaming_export_complete(
    session: AsyncSession,
    entity_type: str,
    format: str,
    total_records: int,
    user_id: str | None = None,
    tenant_id: str | None = None,
) -> int:
    """Send webhook notification for completed streaming export.

    Args:
        session: Database session.
        entity_type: Type of entity exported.
        format: Export format.
        total_records: Number of records exported.
        user_id: User who initiated the export.
        tenant_id: Tenant context.

    Returns:
        Number of webhook deliveries created.
    """
    from example_service.features.webhooks.dispatcher import dispatch_event

    event_type = DataTransferEvent.EXPORT_COMPLETED
    export_id = str(uuid.uuid4())

    payload = {
        "export_id": export_id,
        "entity_type": entity_type,
        "format": format,
        "status": "completed",
        "record_count": total_records,
        "streaming": True,
        "user_id": user_id,
        "tenant_id": tenant_id,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    event_id = f"export-stream-{export_id}"

    try:
        return await dispatch_event(
            session=session,
            event_type=event_type,
            event_id=event_id,
            payload=payload,
        )
    except Exception as e:
        logger.warning(
            "Failed to dispatch streaming export webhook notification",
            extra={"error": str(e)},
        )
        return 0


def get_supported_events() -> list[dict[str, str]]:
    """Get list of supported webhook events for data transfer.

    Returns:
        List of event dictionaries with name and description.
    """
    return [
        {
            "event_type": DataTransferEvent.EXPORT_COMPLETED,
            "description": "Triggered when a data export completes successfully",
        },
        {
            "event_type": DataTransferEvent.EXPORT_FAILED,
            "description": "Triggered when a data export fails",
        },
        {
            "event_type": DataTransferEvent.IMPORT_COMPLETED,
            "description": "Triggered when a data import completes successfully",
        },
        {
            "event_type": DataTransferEvent.IMPORT_FAILED,
            "description": "Triggered when a data import fails",
        },
        {
            "event_type": DataTransferEvent.IMPORT_PARTIALLY_COMPLETED,
            "description": "Triggered when a data import completes with some failures",
        },
    ]
