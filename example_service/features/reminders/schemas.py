"""Pydantic schemas for the reminders feature."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from example_service.core.pagination import Connection, CursorPage, Edge, PageInfo
from example_service.core.validators import validate_rrule_optional
from example_service.features.reminders.recurrence import (
    Frequency,
    RecurrenceRule,
    Weekday,
    describe_rrule,
)
from example_service.utils.runtime_dependencies import require_runtime_dependency

if TYPE_CHECKING:
    from example_service.features.reminders.models import Reminder

require_runtime_dependency(datetime, UUID)


class ReminderBase(BaseModel):
    """Shared attributes for reminder payloads."""

    title: str = Field(..., max_length=200)
    description: str | None = None
    remind_at: datetime | None = None


class RecurrenceRuleCreate(BaseModel):
    """Schema for creating a recurrence rule in a user-friendly format.

    Instead of requiring raw RRULE strings, this schema accepts structured
    input that gets converted to an RRULE internally.
    """

    frequency: Frequency = Field(
        ...,
        description="How often the reminder repeats",
    )
    interval: int = Field(
        default=1,
        ge=1,
        le=365,
        description="Repeat every N frequency units (e.g., every 2 weeks)",
    )
    weekdays: list[Weekday] | None = Field(
        default=None,
        description="Days of the week for weekly recurrence",
    )
    month_day: int | None = Field(
        default=None,
        ge=1,
        le=31,
        description="Day of month for monthly recurrence",
    )
    count: int | None = Field(
        default=None,
        ge=1,
        le=999,
        description="Number of occurrences before stopping",
    )
    until: datetime | None = Field(
        default=None,
        description="Date when recurrence ends",
    )

    def to_rrule_string(self) -> str:
        """Convert to iCalendar RRULE string."""
        rule = RecurrenceRule(
            frequency=self.frequency,
            interval=self.interval,
            weekdays=self.weekdays,
            month_day=self.month_day,
            count=self.count,
            until=self.until,
        )
        return rule.to_rrule_string()


class ReminderCreate(ReminderBase):
    """Payload used when creating a reminder."""

    recurrence: RecurrenceRuleCreate | None = Field(
        default=None,
        description="Recurrence rule for repeating reminders",
    )
    recurrence_rule: str | None = Field(
        default=None,
        description="Raw iCalendar RRULE string (alternative to recurrence)",
    )
    recurrence_end_at: datetime | None = Field(
        default=None,
        description="When the recurrence series ends",
    )

    @field_validator("recurrence_rule")
    @classmethod
    def validate_rrule_string(cls, v: str | None) -> str | None:
        """Validate RRULE string if provided."""
        return validate_rrule_optional(v)


class ReminderUpdate(BaseModel):
    """Payload for updating a reminder."""

    title: str | None = Field(default=None, max_length=200)
    description: str | None = None
    remind_at: datetime | None = None
    recurrence: RecurrenceRuleCreate | None = None
    recurrence_rule: str | None = None
    recurrence_end_at: datetime | None = None

    @field_validator("recurrence_rule")
    @classmethod
    def validate_rrule_string(cls, v: str | None) -> str | None:
        """Validate RRULE string if provided."""
        return validate_rrule_optional(v)


class RecurrenceInfo(BaseModel):
    """Recurrence information in the response."""

    rule: str = Field(description="iCalendar RRULE string")
    description: str = Field(description="Human-readable description")
    end_at: datetime | None = Field(default=None, description="When recurrence ends")
    is_occurrence: bool = Field(
        default=False,
        description="Whether this is a broken-out occurrence",
    )
    parent_id: UUID | None = Field(
        default=None,
        description="Parent reminder ID if this is a broken-out occurrence",
    )


class ReminderResponse(ReminderBase):
    """Representation returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    is_completed: bool
    created_at: datetime
    updated_at: datetime
    recurrence: RecurrenceInfo | None = None

    @classmethod
    def from_model(cls, reminder: Reminder) -> ReminderResponse:
        """Create response from model instance with recurrence info."""
        recurrence = None
        if reminder.recurrence_rule:
            recurrence = RecurrenceInfo(
                rule=reminder.recurrence_rule,
                description=describe_rrule(reminder.recurrence_rule),
                end_at=reminder.recurrence_end_at,
                is_occurrence=reminder.is_occurrence,
                parent_id=reminder.parent_id,
            )
        elif reminder.is_occurrence:
            # This is a broken-out occurrence without its own rule
            recurrence = RecurrenceInfo(
                rule="",
                description="Single occurrence",
                end_at=None,
                is_occurrence=True,
                parent_id=reminder.parent_id,
            )

        return cls(
            id=reminder.id,
            title=reminder.title,
            description=reminder.description,
            remind_at=reminder.remind_at,
            is_completed=reminder.is_completed,
            created_at=reminder.created_at,
            updated_at=reminder.updated_at,
            recurrence=recurrence,
        )


class OccurrenceResponse(BaseModel):
    """A single occurrence in a recurrence series."""

    date: datetime = Field(description="The occurrence date/time")
    is_modified: bool = Field(
        default=False,
        description="Whether this occurrence has been broken out and modified",
    )
    reminder_id: UUID | None = Field(
        default=None,
        description="ID of the broken-out reminder if modified",
    )


class OccurrencesResponse(BaseModel):
    """List of occurrences for a recurring reminder."""

    reminder_id: UUID
    rule: str
    description: str
    occurrences: list[OccurrenceResponse]
    total_count: int | None = Field(
        default=None,
        description="Total occurrences (if bounded)",
    )


class ReminderSearchResult(ReminderResponse):
    """Reminder with full-text search relevance score.

    The relevance score indicates how well the reminder matches
    the search query, with higher scores indicating better matches.
    """

    relevance: float = Field(
        default=0.0,
        ge=0.0,
        description="Full-text search relevance score (higher is better)",
    )


# Type aliases for reminder pagination
ReminderEdge = Edge[ReminderResponse]
ReminderConnection = Connection[ReminderResponse]
ReminderCursorPage = CursorPage[ReminderResponse]


__all__ = [
    "Frequency",
    "OccurrenceResponse",
    "OccurrencesResponse",
    "PageInfo",
    "RecurrenceInfo",
    "RecurrenceRuleCreate",
    "ReminderBase",
    "ReminderConnection",
    "ReminderCreate",
    "ReminderCursorPage",
    "ReminderEdge",
    "ReminderResponse",
    "ReminderSearchResult",
    "ReminderUpdate",
    "Weekday",
]
