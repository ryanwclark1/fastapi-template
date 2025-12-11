"""Notification tasks.

This module provides:
- Scheduled checking for due reminders
- Background notification dispatch to all channels
- Retry logic for failed deliveries
- Processing of scheduled notifications
"""

from __future__ import annotations

try:
    from .tasks import (
        check_due_reminders,
        dispatch_notification_task,
        process_scheduled_notifications,
        retry_failed_delivery_task,
        send_reminder_notification,
    )
except ImportError:
    check_due_reminders = None  # type: ignore[assignment]
    send_reminder_notification = None  # type: ignore[assignment]
    dispatch_notification_task = None  # type: ignore[assignment]
    retry_failed_delivery_task = None  # type: ignore[assignment]
    process_scheduled_notifications = None  # type: ignore[assignment]
    __all__: list[str] = []
else:
    __all__ = [
        "check_due_reminders",
        "dispatch_notification_task",
        "process_scheduled_notifications",
        "retry_failed_delivery_task",
        "send_reminder_notification",
    ]
