"""Pydantic schemas for the reminders feature."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ReminderBase(BaseModel):
    """Shared attributes for reminder payloads."""

    title: str = Field(..., max_length=200)
    description: str | None = None
    remind_at: datetime | None = None


class ReminderCreate(ReminderBase):
    """Payload used when creating a reminder."""


class ReminderResponse(ReminderBase):
    """Representation returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    is_completed: bool
    created_at: datetime
    updated_at: datetime
