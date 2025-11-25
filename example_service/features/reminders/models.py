"""SQLAlchemy models for the reminders feature."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from example_service.infra.database.base import TimestampedBase


class Reminder(TimestampedBase):
    """Reminder item persisted in the database."""

    __tablename__ = "reminders"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    remind_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_completed: Mapped[bool] = mapped_column(Boolean(), default=False, nullable=False)
    notification_sent: Mapped[bool] = mapped_column(Boolean(), default=False, nullable=False)
