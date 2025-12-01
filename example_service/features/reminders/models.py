"""SQLAlchemy models for the reminders feature."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, ClassVar
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from example_service.core.database import TimestampedBase
from example_service.core.database.search import TSVECTOR

if TYPE_CHECKING:
    from example_service.features.tags.models import Tag


class Reminder(TimestampedBase):
    """Reminder item persisted in the database.

    Includes full-text search capability via the search_vector column.
    The search vector is automatically updated by a database trigger
    whenever title or description changes.

    Supports recurring reminders via the recurrence_rule field, which stores
    an iCalendar RRULE string (e.g., "FREQ=WEEKLY;BYDAY=MO,WE,FR").
    """

    __tablename__ = "reminders"

    # Search configuration (used by trigger, defined here for documentation)
    __search_fields__: ClassVar[list[str]] = ["title", "description"]
    __search_config__: ClassVar[str] = "english"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    remind_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_completed: Mapped[bool] = mapped_column(Boolean(), default=False, nullable=False)
    notification_sent: Mapped[bool] = mapped_column(Boolean(), default=False, nullable=False)

    # Recurrence fields
    recurrence_rule: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="iCalendar RRULE string for recurring reminders",
    )
    recurrence_end_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When the recurrence series ends",
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("reminders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Parent reminder ID for occurrences broken out from a series",
    )
    occurrence_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Specific occurrence date for broken-out instances",
    )

    # Self-referential relationship
    parent: Mapped[Reminder | None] = relationship(
        "Reminder",
        remote_side=[id],
        back_populates="occurrences",
        foreign_keys=[parent_id],
    )
    occurrences: Mapped[list[Reminder]] = relationship(
        "Reminder",
        back_populates="parent",
        foreign_keys=[parent_id],
    )

    # Many-to-many relationship with tags
    tags: Mapped[list[Tag]] = relationship(
        "Tag",
        secondary="reminder_tags",
        back_populates="reminders",
        lazy="selectin",
    )

    # Full-text search vector (managed by database trigger)
    search_vector: Mapped[Any] = mapped_column(
        TSVECTOR,
        nullable=True,
        comment="Full-text search vector for title and description",
    )

    @property
    def is_recurring(self) -> bool:
        """Check if this reminder has a recurrence rule."""
        return self.recurrence_rule is not None

    @property
    def is_occurrence(self) -> bool:
        """Check if this reminder is a broken-out occurrence from a series."""
        return self.parent_id is not None

    # Note: GIN index is created in migration, not here, to avoid conflicts
    # with existing table definition
