"""User model for demonstrating database migrations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from example_service.core.database import TimestampedBase

if TYPE_CHECKING:
    from .post import Post


class User(TimestampedBase):
    """User model with basic authentication fields.

    Demonstrates:
    - Primary key with UUID
    - Unique constraints
    - Indexes for query optimization
    - Relationships to other models
    - Timestamps (via TimestampedBase)
    """

    __tablename__ = "users"

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Authentication fields
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    username: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)

    # User profile fields
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    # Relationships
    posts: Mapped[list["Post"]] = relationship(
        "Post", back_populates="author", cascade="all, delete-orphan"
    )

    # Additional indexes
    __table_args__ = (
        Index("ix_users_email_username", "email", "username"),
        Index("ix_users_is_active", "is_active"),
    )

    def __repr__(self) -> str:
        """String representation of User."""
        return f"<User(id={self.id}, email={self.email}, username={self.username})>"
