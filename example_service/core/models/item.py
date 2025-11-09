"""Item database model."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from example_service.infra.database.base import TimestampedBase

if TYPE_CHECKING:
    pass


class Item(TimestampedBase):
    """Item model for demonstrating CRUD operations.

    Example of a simple resource with common fields:
    - UUID primary key
    - Timestamps (created_at, updated_at)
    - Soft delete (is_deleted)
    - User ownership (owner_id)
    - Basic text fields (title, description)
    """

    __tablename__ = "items"

    # Primary key
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)

    # Core fields
    title: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Ownership
    owner_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # Status
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    # Timestamps (inherited from Base: created_at, updated_at)

    def __repr__(self) -> str:
        """String representation."""
        return f"<Item(id={self.id}, title={self.title!r}, owner={self.owner_id})>"

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": str(self.id),
            "title": self.title,
            "description": self.description,
            "owner_id": self.owner_id,
            "is_completed": self.is_completed,
            "is_deleted": self.is_deleted,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
