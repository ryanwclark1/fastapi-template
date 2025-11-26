"""Webhook event types and payload builders.

This module defines standardized event types and payload structures for the webhook system.
It provides constants for all supported events and utility functions to build consistent
payloads across different event sources.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from example_service.features.files.models import File
    from example_service.features.reminders.models import Reminder


class FileEvents:
    """File-related webhook event types.

    Events triggered by file operations including uploads, deletions,
    and processing lifecycle changes.
    """

    UPLOADED = "file.uploaded"
    DELETED = "file.deleted"
    COPIED = "file.copied"
    MOVED = "file.moved"
    PROCESSING_STARTED = "file.processing.started"
    PROCESSING_COMPLETED = "file.processing.completed"
    PROCESSING_FAILED = "file.processing.failed"


class ReminderEvents:
    """Reminder-related webhook event types.

    Events triggered by reminder lifecycle changes and due date notifications.
    """

    CREATED = "reminder.created"
    UPDATED = "reminder.updated"
    DELETED = "reminder.deleted"
    COMPLETED = "reminder.completed"
    DUE = "reminder.due"


# All available event types that webhooks can subscribe to
ALL_EVENT_TYPES = [
    # File events
    FileEvents.UPLOADED,
    FileEvents.DELETED,
    FileEvents.COPIED,
    FileEvents.MOVED,
    FileEvents.PROCESSING_STARTED,
    FileEvents.PROCESSING_COMPLETED,
    FileEvents.PROCESSING_FAILED,
    # Reminder events
    ReminderEvents.CREATED,
    ReminderEvents.UPDATED,
    ReminderEvents.DELETED,
    ReminderEvents.COMPLETED,
    ReminderEvents.DUE,
]


def generate_event_id(event_type: str) -> str:
    """Generate a unique event ID for tracking and idempotency.

    Creates a unique identifier that combines the event type with a UUID.
    This ID can be used for deduplication and tracking event delivery across systems.

    Args:
        event_type: The type of event (e.g., "file.uploaded")

    Returns:
        A unique event ID in the format "evt_{event_type}_{uuid}"

    Examples:
        >>> generate_event_id("file.uploaded")
        'evt_file.uploaded_123e4567-e89b-12d3-a456-426614174000'
        >>> generate_event_id("reminder.due")
        'evt_reminder.due_987fcdeb-51a2-43f8-b912-123456789abc'
    """
    # Replace dots with underscores for cleaner IDs
    sanitized_type = event_type.replace(".", "_")
    unique_id = str(uuid.uuid4())
    return f"evt_{sanitized_type}_{unique_id}"


def build_file_event_payload(
    file: File,
    event_type: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a standardized file event payload.

    Creates a consistent payload structure for file-related webhook events.
    Includes all relevant file metadata and optional extra information.

    Args:
        file: The File model instance
        event_type: The type of file event (should be from FileEvents)
        extra: Optional dictionary of additional data to include in the payload

    Returns:
        A standardized event payload dictionary with the structure:
        {
            "event_type": "file.uploaded",
            "timestamp": "2025-01-15T10:30:00Z",
            "data": {
                "file_id": "uuid",
                "filename": "document.pdf",
                "content_type": "application/pdf",
                "size_bytes": 12345,
                "owner_id": "user123",
                "storage_key": "uploads/...",
                "bucket": "my-bucket",
                "status": "ready",
                "is_public": false,
                "checksum_sha256": "abc123...",
                "etag": "def456...",
                "expires_at": "2025-02-15T10:30:00Z",
                "created_at": "2025-01-15T10:00:00Z",
                "updated_at": "2025-01-15T10:30:00Z",
                ...extra fields
            }
        }

    Examples:
        >>> file = File(
        ...     id=uuid4(),
        ...     original_filename="report.pdf",
        ...     content_type="application/pdf",
        ...     size_bytes=1024,
        ...     owner_id="user_123",
        ...     storage_key="uploads/2025/report.pdf",
        ...     bucket="documents",
        ...     status=FileStatus.READY,
        ... )
        >>> payload = build_file_event_payload(file, FileEvents.UPLOADED)
        >>> payload["event_type"]
        'file.uploaded'
        >>> payload["data"]["filename"]
        'report.pdf'
    """
    # Build base data dictionary with all file attributes
    data: dict[str, Any] = {
        "file_id": str(file.id),
        "filename": file.original_filename,
        "content_type": file.content_type,
        "size_bytes": file.size_bytes,
        "owner_id": file.owner_id,
        "storage_key": file.storage_key,
        "bucket": file.bucket,
        "status": file.status.value if hasattr(file.status, "value") else str(file.status),
        "is_public": file.is_public,
    }

    # Add optional fields if present
    if file.checksum_sha256:
        data["checksum_sha256"] = file.checksum_sha256

    if file.etag:
        data["etag"] = file.etag

    if file.expires_at:
        data["expires_at"] = file.expires_at.isoformat()

    # Add timestamps if available
    if hasattr(file, "created_at") and file.created_at:
        data["created_at"] = file.created_at.isoformat()

    if hasattr(file, "updated_at") and file.updated_at:
        data["updated_at"] = file.updated_at.isoformat()

    # Merge any extra data provided
    if extra:
        data.update(extra)

    # Return standardized payload structure
    return {
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }


def build_reminder_event_payload(
    reminder: Reminder,
    event_type: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a standardized reminder event payload.

    Creates a consistent payload structure for reminder-related webhook events.
    Includes all relevant reminder metadata and optional extra information.

    Args:
        reminder: The Reminder model instance
        event_type: The type of reminder event (should be from ReminderEvents)
        extra: Optional dictionary of additional data to include in the payload

    Returns:
        A standardized event payload dictionary with the structure:
        {
            "event_type": "reminder.created",
            "timestamp": "2025-01-15T10:30:00Z",
            "data": {
                "reminder_id": "uuid",
                "title": "Team meeting",
                "description": "Weekly sync",
                "remind_at": "2025-01-20T14:00:00Z",
                "is_completed": false,
                "notification_sent": false,
                "created_at": "2025-01-15T10:00:00Z",
                "updated_at": "2025-01-15T10:30:00Z",
                ...extra fields
            }
        }

    Examples:
        >>> reminder = Reminder(
        ...     id=uuid4(),
        ...     title="Call client",
        ...     description="Discuss project requirements",
        ...     remind_at=datetime(2025, 1, 20, 14, 0, tzinfo=timezone.utc),
        ...     is_completed=False,
        ... )
        >>> payload = build_reminder_event_payload(reminder, ReminderEvents.CREATED)
        >>> payload["event_type"]
        'reminder.created'
        >>> payload["data"]["title"]
        'Call client'
    """
    # Build base data dictionary with all reminder attributes
    data: dict[str, Any] = {
        "reminder_id": str(reminder.id),
        "title": reminder.title,
        "is_completed": reminder.is_completed,
        "notification_sent": reminder.notification_sent,
    }

    # Add optional description if present
    if reminder.description:
        data["description"] = reminder.description

    # Add remind_at timestamp if set
    if reminder.remind_at:
        data["remind_at"] = reminder.remind_at.isoformat()

    # Add timestamps if available
    if hasattr(reminder, "created_at") and reminder.created_at:
        data["created_at"] = reminder.created_at.isoformat()

    if hasattr(reminder, "updated_at") and reminder.updated_at:
        data["updated_at"] = reminder.updated_at.isoformat()

    # Merge any extra data provided
    if extra:
        data.update(extra)

    # Return standardized payload structure
    return {
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }


def validate_event_type(event_type: str) -> bool:
    """Validate that an event type is supported by the webhook system.

    Args:
        event_type: The event type string to validate

    Returns:
        True if the event type is valid, False otherwise

    Examples:
        >>> validate_event_type("file.uploaded")
        True
        >>> validate_event_type("invalid.event")
        False
    """
    return event_type in ALL_EVENT_TYPES


def get_event_category(event_type: str) -> str | None:
    """Determine the category of an event type.

    Args:
        event_type: The event type string

    Returns:
        The event category ("file" or "reminder") or None if unknown

    Examples:
        >>> get_event_category("file.uploaded")
        'file'
        >>> get_event_category("reminder.due")
        'reminder'
        >>> get_event_category("unknown.event")
        None
    """
    if event_type.startswith("file."):
        return "file"
    elif event_type.startswith("reminder."):
        return "reminder"
    return None
