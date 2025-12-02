"""Domain events for the reminders feature.

These events are published when significant changes occur to reminders.
They can be consumed by other services or features for:
- Sending notifications
- Updating search indexes
- Triggering workflows
- Building audit logs
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from pydantic import Field

from example_service.core.events import DomainEvent, event_registry

if TYPE_CHECKING:
    from datetime import datetime


@event_registry.register
class ReminderCreatedEvent(DomainEvent):
    """Published when a new reminder is created.

    Example:
        event = ReminderCreatedEvent(
            reminder_id="...",
            title="Meeting with team",
            remind_at=datetime(2025, 1, 15, 10, 0),
        )
        await publisher.publish(event)
    """

    event_type: ClassVar[str] = "reminder.created"
    event_version: ClassVar[int] = 1

    reminder_id: str = Field(description="UUID of the created reminder")
    title: str = Field(description="Reminder title")
    description: str | None = Field(default=None, description="Reminder description")
    remind_at: datetime | None = Field(default=None, description="When to send reminder")


@event_registry.register
class ReminderUpdatedEvent(DomainEvent):
    """Published when a reminder is updated.

    Only non-None fields in `changes` were actually modified.
    """

    event_type: ClassVar[str] = "reminder.updated"
    event_version: ClassVar[int] = 1

    reminder_id: str = Field(description="UUID of the updated reminder")
    changes: dict[str, object] = Field(
        default_factory=dict,
        description="Fields that were changed with their new values",
    )


@event_registry.register
class ReminderCompletedEvent(DomainEvent):
    """Published when a reminder is marked as completed."""

    event_type: ClassVar[str] = "reminder.completed"
    event_version: ClassVar[int] = 1

    reminder_id: str = Field(description="UUID of the completed reminder")
    title: str = Field(description="Reminder title for context")


@event_registry.register
class ReminderDeletedEvent(DomainEvent):
    """Published when a reminder is deleted."""

    event_type: ClassVar[str] = "reminder.deleted"
    event_version: ClassVar[int] = 1

    reminder_id: str = Field(description="UUID of the deleted reminder")


__all__ = [
    "ReminderCompletedEvent",
    "ReminderCreatedEvent",
    "ReminderDeletedEvent",
    "ReminderUpdatedEvent",
]
