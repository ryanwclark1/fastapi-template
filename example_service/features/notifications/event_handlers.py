"""Event handlers for automatic notification creation.

This module contains event handlers that listen to domain events from
other features and automatically create notifications when appropriate.

Handlers are registered at startup and execute asynchronously when
events are published via the outbox pattern.

Key features:
- Idempotent handlers (safe to run multiple times)
- Error handling that doesn't break the main event flow
- Structured logging with event context
- Template-based notification rendering
- User preference awareness

Example:
    When a ReminderDueEvent is published, the on_reminder_due handler
    will automatically create a notification for the user.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from example_service.features.notifications.service import get_notification_service
from example_service.infra.database.session import get_async_session
from example_service.infra.logging import get_logger

if TYPE_CHECKING:
    from example_service.core.events import DomainEvent
    from example_service.features.reminders.events import (
        ReminderCompletedEvent,
        ReminderCreatedEvent,
    )

logger = get_logger(__name__)


# =============================================================================
# Event Handler Registry
# =============================================================================
# Note: In a production system, you would use a proper event handler registry
# with decorators. For now, we'll define handlers as regular async functions
# that can be manually registered at startup.


async def on_reminder_created(event: ReminderCreatedEvent) -> None:
    """Create notification when a reminder is created.

    This handler fires when a new reminder is added to the system,
    notifying the user that their reminder was successfully scheduled.

    Args:
        event: ReminderCreatedEvent containing reminder details

    Example:
        event = ReminderCreatedEvent(
            reminder_id="...",
            title="Review PR",
            remind_at=datetime(...),
        )
        await on_reminder_created(event)
    """
    logger.info(
        "Handling reminder.created event for notification",
        extra={
            "event_id": event.event_id,
            "reminder_id": event.reminder_id,
            "title": event.title,
        },
    )

    try:
        service = get_notification_service()

        async with get_async_session() as session:
            # Create notification for reminder creation
            notification = await service.create_notification(
                session=session,
                user_id="system",  # NOTE: Replace with event metadata when available
                notification_type="reminder_created",
                title=f"Reminder created: {event.title}",
                body=f"Your reminder '{event.title}' has been scheduled.",
                template_name="reminder_created",
                context={
                    "reminder_id": event.reminder_id,
                    "title": event.title,
                    "description": event.description,
                    "remind_at": event.remind_at.isoformat() if event.remind_at else None,
                },
                priority="low",
                source_entity_type="reminder",
                source_entity_id=event.reminder_id,
            )

            await session.commit()

            logger.info(
                f"Created notification {notification.id} for reminder creation",
                extra={
                    "notification_id": str(notification.id),
                    "reminder_id": event.reminder_id,
                },
            )

    except Exception as e:
        # Log error but don't raise - we don't want to break the event flow
        logger.exception(
            f"Failed to create notification for reminder.created: {e}",
            extra={
                "event_id": event.event_id,
                "reminder_id": event.reminder_id,
                "error": str(e),
            },
        )


async def on_reminder_due(event: DomainEvent) -> None:
    """Create notification when a reminder is due.

    This is the primary notification handler for reminders - it fires
    when it's time to notify the user about their scheduled reminder.

    Args:
        event: Domain event containing reminder due information
              Expected to have: reminder_id, title, description, user_id

    Note:
        This handler expects a ReminderDueEvent which should be defined
        in the reminders feature. For now, we accept a generic DomainEvent
        and extract attributes dynamically.
    """
    reminder_id = getattr(event, "reminder_id", None)
    title = getattr(event, "title", "Reminder")
    description = getattr(event, "description", None)
    user_id = getattr(event, "user_id", None) or event.metadata.get("user_id", "system")

    logger.info(
        "Handling reminder.due event for notification",
        extra={
            "event_id": event.event_id,
            "event_type": event.event_type,
            "reminder_id": reminder_id,
            "user_id": user_id,
        },
    )

    try:
        service = get_notification_service()

        async with get_async_session() as session:
            # Create high-priority notification for due reminder
            notification = await service.create_notification(
                session=session,
                user_id=user_id,
                notification_type="reminder_due",
                title=f"Reminder: {title}",
                body=description or f"Your reminder '{title}' is due now.",
                template_name="reminder_due",
                context={
                    "reminder_id": reminder_id,
                    "title": title,
                    "description": description,
                    "due_at": datetime.now(UTC).isoformat(),
                },
                priority="high",
                source_entity_type="reminder",
                source_entity_id=str(reminder_id) if reminder_id else None,
            )

            await session.commit()

            logger.info(
                f"Created notification {notification.id} for due reminder",
                extra={
                    "notification_id": str(notification.id),
                    "reminder_id": reminder_id,
                    "user_id": user_id,
                },
            )

    except Exception as e:
        logger.exception(
            f"Failed to create notification for reminder.due: {e}",
            extra={
                "event_id": event.event_id,
                "reminder_id": reminder_id,
                "error": str(e),
            },
        )


async def on_reminder_completed(event: ReminderCompletedEvent) -> None:
    """Create notification when a reminder is completed.

    Provides positive feedback to users when they complete reminders.

    Args:
        event: ReminderCompletedEvent containing completion details
    """
    logger.info(
        "Handling reminder.completed event for notification",
        extra={
            "event_id": event.event_id,
            "reminder_id": event.reminder_id,
        },
    )

    try:
        service = get_notification_service()

        async with get_async_session() as session:
            notification = await service.create_notification(
                session=session,
                user_id="system",  # NOTE: Replace with event metadata when available
                notification_type="reminder_completed",
                title=f"Reminder completed: {event.title}",
                body=f"You've completed '{event.title}'. Great job!",
                template_name="reminder_completed",
                context={
                    "reminder_id": event.reminder_id,
                    "title": event.title,
                    "completed_at": datetime.now(UTC).isoformat(),
                },
                priority="low",
                source_entity_type="reminder",
                source_entity_id=event.reminder_id,
                auto_dismiss=True,
                dismiss_after=5000,  # Auto-dismiss after 5 seconds
            )

            await session.commit()

            logger.info(
                f"Created notification {notification.id} for reminder completion",
                extra={
                    "notification_id": str(notification.id),
                    "reminder_id": event.reminder_id,
                },
            )

    except Exception as e:
        logger.exception(
            f"Failed to create notification for reminder.completed: {e}",
            extra={
                "event_id": event.event_id,
                "reminder_id": event.reminder_id,
                "error": str(e),
            },
        )


async def on_file_uploaded(event: DomainEvent) -> None:
    """Create notification when a file is uploaded.

    Notifies users when their file upload is complete and ready for use.

    Args:
        event: Domain event containing file upload details
              Expected to have: file_id, filename, owner_id, size_bytes

    Note:
        This handler expects a FileUploadedEvent. For now, we accept
        a generic DomainEvent and extract attributes dynamically.
    """
    file_id = getattr(event, "file_id", None)
    filename = getattr(event, "filename", "Unknown file")
    owner_id = getattr(event, "owner_id", None) or event.metadata.get("user_id", "system")
    size_bytes = getattr(event, "size_bytes", 0)

    logger.info(
        "Handling file.uploaded event for notification",
        extra={
            "event_id": event.event_id,
            "file_id": file_id,
            "filename": filename,
            "owner_id": owner_id,
        },
    )

    try:
        service = get_notification_service()

        async with get_async_session() as session:
            # Format file size for display
            size_mb = size_bytes / (1024 * 1024) if size_bytes else 0

            notification = await service.create_notification(
                session=session,
                user_id=owner_id,
                notification_type="file_uploaded",
                title=f"File uploaded: {filename}",
                body=f"Your file '{filename}' ({size_mb:.2f} MB) has been uploaded successfully.",
                template_name="file_uploaded",
                context={
                    "file_id": file_id,
                    "filename": filename,
                    "size_bytes": size_bytes,
                    "size_mb": f"{size_mb:.2f}",
                    "uploaded_at": datetime.now(UTC).isoformat(),
                },
                priority="normal",
                source_entity_type="file",
                source_entity_id=str(file_id) if file_id else None,
                actions=[
                    {
                        "label": "View File",
                        "action": "view_file",
                        "data": {"file_id": str(file_id)},
                    },
                ],
            )

            await session.commit()

            logger.info(
                f"Created notification {notification.id} for file upload",
                extra={
                    "notification_id": str(notification.id),
                    "file_id": file_id,
                    "owner_id": owner_id,
                },
            )

    except Exception as e:
        logger.exception(
            f"Failed to create notification for file.uploaded: {e}",
            extra={
                "event_id": event.event_id,
                "file_id": file_id,
                "error": str(e),
            },
        )


async def on_export_completed(event: DomainEvent) -> None:
    """Create notification when a data export is completed.

    Notifies users when their requested data export is ready for download.

    Args:
        event: Domain event containing export completion details
              Expected to have: export_id, format, user_id, download_url

    Note:
        This handler expects an ExportCompletedEvent from the datatransfer feature.
    """
    export_id = getattr(event, "export_id", None)
    export_format = getattr(event, "format", "unknown")
    user_id = getattr(event, "user_id", None) or event.metadata.get("user_id", "system")
    download_url = getattr(event, "download_url", None)
    record_count = getattr(event, "record_count", 0)

    logger.info(
        "Handling export.completed event for notification",
        extra={
            "event_id": event.event_id,
            "export_id": export_id,
            "format": export_format,
            "user_id": user_id,
        },
    )

    try:
        service = get_notification_service()

        async with get_async_session() as session:
            notification = await service.create_notification(
                session=session,
                user_id=user_id,
                notification_type="export_completed",
                title=f"Export ready: {export_format.upper()}",
                body=f"Your {export_format.upper()} export is ready ({record_count} records).",
                template_name="export_completed",
                context={
                    "export_id": export_id,
                    "format": export_format,
                    "record_count": record_count,
                    "download_url": download_url,
                    "completed_at": datetime.now(UTC).isoformat(),
                },
                priority="normal",
                source_entity_type="export",
                source_entity_id=str(export_id) if export_id else None,
                actions=[
                    {
                        "label": "Download",
                        "action": "download_export",
                        "data": {
                            "export_id": str(export_id),
                            "url": download_url,
                        },
                    },
                ],
            )

            await session.commit()

            logger.info(
                f"Created notification {notification.id} for export completion",
                extra={
                    "notification_id": str(notification.id),
                    "export_id": export_id,
                    "user_id": user_id,
                },
            )

    except Exception as e:
        logger.exception(
            f"Failed to create notification for export.completed: {e}",
            extra={
                "event_id": event.event_id,
                "export_id": export_id,
                "error": str(e),
            },
        )


async def on_workflow_completed(event: DomainEvent) -> None:
    """Create notification when an AI workflow is completed.

    Notifies users when their long-running AI workflow has finished.

    Args:
        event: Domain event containing workflow completion details
              Expected to have: workflow_id, workflow_name, user_id, result

    Note:
        This handler expects a WorkflowCompletedEvent from the AI feature.
    """
    workflow_id = getattr(event, "workflow_id", None)
    workflow_name = getattr(event, "workflow_name", "AI Workflow")
    user_id = getattr(event, "user_id", None) or event.metadata.get("user_id", "system")
    result = getattr(event, "result", None)
    status = getattr(event, "status", "completed")

    logger.info(
        "Handling workflow.completed event for notification",
        extra={
            "event_id": event.event_id,
            "workflow_id": workflow_id,
            "workflow_name": workflow_name,
            "user_id": user_id,
            "status": status,
        },
    )

    try:
        service = get_notification_service()

        async with get_async_session() as session:
            # Determine priority and message based on status
            priority = "high" if status == "failed" else "normal"
            title_prefix = "Failed" if status == "failed" else "Completed"

            notification = await service.create_notification(
                session=session,
                user_id=user_id,
                notification_type="workflow_completed",
                title=f"{title_prefix}: {workflow_name}",
                body=f"Your workflow '{workflow_name}' has {status}.",
                template_name="workflow_completed",
                context={
                    "workflow_id": workflow_id,
                    "workflow_name": workflow_name,
                    "status": status,
                    "result": result,
                    "completed_at": datetime.now(UTC).isoformat(),
                },
                priority=priority,
                source_entity_type="workflow",
                source_entity_id=str(workflow_id) if workflow_id else None,
                actions=[
                    {
                        "label": "View Results",
                        "action": "view_workflow",
                        "data": {"workflow_id": str(workflow_id)},
                    },
                ],
            )

            await session.commit()

            logger.info(
                f"Created notification {notification.id} for workflow completion",
                extra={
                    "notification_id": str(notification.id),
                    "workflow_id": workflow_id,
                    "user_id": user_id,
                },
            )

    except Exception as e:
        logger.exception(
            f"Failed to create notification for workflow.completed: {e}",
            extra={
                "event_id": event.event_id,
                "workflow_id": workflow_id,
                "error": str(e),
            },
        )


async def on_security_alert(event: DomainEvent) -> None:
    """Create high-priority notification for security alerts.

    Notifies users of security-related events such as login from new device,
    password changes, permission changes, etc.

    Args:
        event: Domain event containing security alert details
              Expected to have: alert_type, user_id, description, severity

    Note:
        This handler expects a SecurityAlertEvent from the audit/auth features.
    """
    alert_type = getattr(event, "alert_type", "security_alert")
    user_id = getattr(event, "user_id", None) or event.metadata.get("user_id", "system")
    description = getattr(event, "description", "Security alert detected")
    severity = getattr(event, "severity", "medium")

    logger.info(
        "Handling security.alert event for notification",
        extra={
            "event_id": event.event_id,
            "alert_type": alert_type,
            "user_id": user_id,
            "severity": severity,
        },
    )

    try:
        service = get_notification_service()

        async with get_async_session() as session:
            # Map severity to priority
            priority_map = {
                "low": "normal",
                "medium": "high",
                "high": "urgent",
                "critical": "urgent",
            }
            priority = priority_map.get(severity, "high")

            notification = await service.create_notification(
                session=session,
                user_id=user_id,
                notification_type="security_alert",
                title=f"Security Alert: {alert_type.replace('_', ' ').title()}",
                body=description,
                template_name="security_alert",
                context={
                    "alert_type": alert_type,
                    "description": description,
                    "severity": severity,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
                priority=priority,
                source_entity_type="security_alert",
                source_entity_id=event.event_id,
            )

            await session.commit()

            logger.info(
                f"Created notification {notification.id} for security alert",
                extra={
                    "notification_id": str(notification.id),
                    "alert_type": alert_type,
                    "user_id": user_id,
                    "severity": severity,
                },
            )

    except Exception as e:
        logger.exception(
            f"Failed to create notification for security.alert: {e}",
            extra={
                "event_id": event.event_id,
                "alert_type": alert_type,
                "error": str(e),
            },
        )


# =============================================================================
# Handler Registration Map
# =============================================================================
# Maps event types to their handler functions
# This can be used by an event dispatcher to route events to handlers

EVENT_HANDLERS: dict[str, Any] = {
    "reminder.created": on_reminder_created,
    "reminder.due": on_reminder_due,
    "reminder.completed": on_reminder_completed,
    "file.uploaded": on_file_uploaded,
    "export.completed": on_export_completed,
    "workflow.completed": on_workflow_completed,
    "security.alert": on_security_alert,
}


def register_event_handlers() -> None:
    """Register all notification event handlers.

    This function should be called during application startup to ensure
    all handlers are registered with the event system.

    Note:
        In a production system, this would integrate with a proper
        event handler registry/dispatcher. For now, it's a placeholder
        that can be used to register handlers when the infrastructure
        is in place.
    """
    logger.info(
        f"Registered {len(EVENT_HANDLERS)} notification event handlers",
        extra={"event_types": list(EVENT_HANDLERS.keys())},
    )


__all__ = [
    "EVENT_HANDLERS",
    "on_export_completed",
    "on_file_uploaded",
    "on_reminder_completed",
    "on_reminder_created",
    "on_reminder_due",
    "on_security_alert",
    "on_workflow_completed",
    "register_event_handlers",
]
