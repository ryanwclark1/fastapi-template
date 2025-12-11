"""SQLAlchemy models for the tags feature."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Column, ForeignKey, String, Table, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from example_service.core.database import Base, TimestampedBase

if TYPE_CHECKING:
    from example_service.features.reminders.models import Reminder

# Many-to-many association table for reminders <-> tags
reminder_tags = Table(
    "reminder_tags",
    Base.metadata,
    Column(
        "reminder_id",
        ForeignKey("reminders.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "tag_id",
        ForeignKey("tags.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Tag(TimestampedBase):
    """Tag for categorizing reminders.

    Tags allow users to organize reminders into categories like:
    - "work", "personal", "health"
    - "urgent", "low-priority"
    - "project-alpha", "quarterly-review"

    A reminder can have multiple tags, and a tag can be applied to many reminders.
    """

    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("name", name="uq_tags_name"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="Unique tag name (e.g., 'work', 'urgent')",
    )
    color: Mapped[str | None] = mapped_column(
        String(7),
        nullable=True,
        comment="Hex color code (e.g., '#FF5733')",
    )
    description: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        comment="Optional description of the tag's purpose",
    )

    # Many-to-many relationship with reminders
    reminders: Mapped[list["Reminder"]] = relationship(
        "Reminder",
        secondary=reminder_tags,
        back_populates="tags",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        """Return tag summary for debugging."""
        return f"<Tag(id={self.id}, name={self.name!r})>"
