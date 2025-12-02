"""GraphQL type definitions.

This package contains Strawberry types for:
- Custom scalars (UUID)
- Base types (PageInfo, Connection patterns)
- Feature types (Reminder types and inputs)
"""

from __future__ import annotations

from example_service.features.graphql.types.base import PageInfoType
from example_service.features.graphql.types.reminders import (
    CreateReminderInput,
    DeletePayload,
    ReminderConnection,
    ReminderEdge,
    ReminderError,
    ReminderEvent,
    ReminderEventType,
    ReminderPayload,
    ReminderSuccess,
    ReminderType,
    UpdateReminderInput,
)
from example_service.features.graphql.types.scalars import UUID

__all__ = [
    # Scalars
    "UUID",
    # Base types
    "PageInfoType",
    # Reminder types
    "ReminderType",
    "ReminderEdge",
    "ReminderConnection",
    "CreateReminderInput",
    "UpdateReminderInput",
    "ReminderSuccess",
    "ReminderError",
    "ReminderPayload",
    "DeletePayload",
    # Reminder event types (for subscriptions)
    "ReminderEvent",
    "ReminderEventType",
]
