"""GraphQL types for the Reminders feature.

Provides:
- ReminderType: GraphQL representation of a Reminder
- Input types: CreateReminderInput, UpdateReminderInput
- Payload types: ReminderSuccess, ReminderError (union for mutations)
- Connection types: ReminderEdge, ReminderConnection
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Annotated

import strawberry

from example_service.features.graphql.types.base import PageInfoType

if TYPE_CHECKING:

    from example_service.features.reminders.models import Reminder


@strawberry.enum(description="Error codes for GraphQL mutation errors")
class ErrorCode(Enum):
    """Error codes for mutation responses."""

    NOT_FOUND = "NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@strawberry.type(description="A reminder task with optional due date")
class ReminderType:
    """GraphQL type for Reminder entity.

    Maps from SQLAlchemy Reminder model to GraphQL type.
    """

    id: strawberry.ID = strawberry.field(description="Unique identifier (UUID)")
    title: str = strawberry.field(description="Reminder title (max 200 characters)")
    description: str | None = strawberry.field(description="Optional detailed description")
    remind_at: datetime | None = strawberry.field(description="When to trigger notification")
    is_completed: bool = strawberry.field(description="Whether the reminder has been completed")
    created_at: datetime = strawberry.field(description="When the reminder was created")
    updated_at: datetime = strawberry.field(description="When the reminder was last updated")

    @classmethod
    def from_model(cls, reminder: Reminder) -> ReminderType:
        """Convert SQLAlchemy model to GraphQL type.

        Args:
            reminder: SQLAlchemy Reminder model instance

        Returns:
            ReminderType instance
        """
        return cls(
            id=strawberry.ID(str(reminder.id)),
            title=reminder.title,
            description=reminder.description,
            remind_at=reminder.remind_at,
            is_completed=reminder.is_completed,
            created_at=reminder.created_at,
            updated_at=reminder.updated_at,
        )


# --- Input Types ---


@strawberry.input(description="Input for creating a new reminder")
class CreateReminderInput:
    """Input for createReminder mutation."""

    title: str = strawberry.field(description="Reminder title (max 200 characters)")
    description: str | None = strawberry.field(
        default=None,
        description="Optional detailed description",
    )
    remind_at: datetime | None = strawberry.field(
        default=None,
        description="When to trigger notification",
    )


@strawberry.input(description="Input for updating an existing reminder")
class UpdateReminderInput:
    """Input for updateReminder mutation."""

    title: str | None = strawberry.field(
        default=None,
        description="New title (if provided)",
    )
    description: str | None = strawberry.field(
        default=None,
        description="New description (if provided)",
    )
    remind_at: datetime | None = strawberry.field(
        default=None,
        description="New notification time (if provided)",
    )


# --- Mutation Payload Types (Union Pattern) ---


@strawberry.type(description="Successful reminder operation result")
class ReminderSuccess:
    """Success payload for reminder mutations."""

    reminder: ReminderType = strawberry.field(description="The created/updated reminder")


@strawberry.type(description="Error result from a reminder operation")
class ReminderError:
    """Error payload for reminder mutations.

    Uses structured error codes for type-safe error handling.
    """

    code: ErrorCode = strawberry.field(description="Error code")
    message: str = strawberry.field(description="Human-readable error message")
    field: str | None = strawberry.field(
        default=None,
        description="Field that caused the error (for validation errors)",
    )


# Union type for mutation results (type-safe error handling)
ReminderPayload = Annotated[
    ReminderSuccess | ReminderError,
    strawberry.union(name="ReminderPayload", description="Result of a reminder mutation"),
]


@strawberry.type(description="Result of a delete operation")
class DeletePayload:
    """Payload for delete mutations."""

    success: bool = strawberry.field(description="Whether the deletion succeeded")
    message: str | None = strawberry.field(
        default=None,
        description="Additional message (e.g., error details)",
    )


# --- Connection Types (Relay Pattern) ---


@strawberry.type(description="Edge containing a reminder and its cursor")
class ReminderEdge:
    """Edge wrapper for paginated reminders (Relay pattern)."""

    node: ReminderType = strawberry.field(description="The reminder")
    cursor: str = strawberry.field(description="Cursor for this item")


@strawberry.type(description="Paginated connection of reminders")
class ReminderConnection:
    """GraphQL Connection for cursor-paginated reminders.

    Follows the Relay specification for pagination.
    """

    edges: list[ReminderEdge] = strawberry.field(description="List of edges (items with cursors)")
    page_info: PageInfoType = strawberry.field(description="Pagination metadata")


# --- Event Types (for Subscriptions) ---


@strawberry.enum(description="Types of reminder events")
class ReminderEventType(Enum):
    """Event types for reminder subscriptions."""

    CREATED = "CREATED"
    UPDATED = "UPDATED"
    COMPLETED = "COMPLETED"
    DELETED = "DELETED"


@strawberry.type(description="Real-time reminder event")
class ReminderEvent:
    """Event payload for reminder subscriptions."""

    event_type: ReminderEventType = strawberry.field(description="Type of event")
    reminder: ReminderType | None = strawberry.field(
        default=None,
        description="The affected reminder (None for DELETED events)",
    )
    reminder_id: strawberry.ID = strawberry.field(description="ID of the affected reminder")


__all__ = [
    "ErrorCode",
    "ReminderType",
    "CreateReminderInput",
    "UpdateReminderInput",
    "ReminderSuccess",
    "ReminderError",
    "ReminderPayload",
    "DeletePayload",
    "ReminderEdge",
    "ReminderConnection",
    "ReminderEventType",
    "ReminderEvent",
]
