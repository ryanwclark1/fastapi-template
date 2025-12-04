"""Reminder notification tasks.

This module provides scheduled checking for due reminders
and triggers notifications when they're due.
"""

from __future__ import annotations

try:
    from .tasks import check_due_reminders, send_reminder_notification
except ImportError:
    check_due_reminders = None  # type: ignore[assignment]
    send_reminder_notification = None  # type: ignore[assignment]
    __all__: list[str] = []
else:
    __all__ = [
        "check_due_reminders",
        "send_reminder_notification",
    ]
