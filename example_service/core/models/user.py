# =============================================================================
# EXAMPLE MODEL - For demonstration and template purposes
# This model demonstrates SQLAlchemy patterns but is not used in production.
# Safe to remove when building your application (update migrations accordingly).
# =============================================================================
"""User model for demonstrating database migrations and full-text search."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from sqlalchemy import Boolean, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from example_service.core.database import TimestampedBase
from example_service.core.database.search import TSVECTOR

if TYPE_CHECKING:
    from .post import Post


class User(TimestampedBase):
    """User model with authentication fields and full-text search.

    Demonstrates:
    - Primary key with auto-increment
    - Unique constraints
    - Indexes for query optimization
    - Relationships to other models
    - Timestamps (via TimestampedBase)
    - Full-text search for finding users

    The search vector includes:
    - Email (weight A - using 'simple' config for exact matching)
    - Username (weight A - using 'simple' config)
    - Full name (weight B - using 'english' for name matching)
    """

    __tablename__ = "users"

    # Search configuration
    # Note: email and username use 'simple' config to preserve exact tokens
    # full_name uses 'english' for better name matching
    __search_fields__: ClassVar[list[str]] = ["email", "username", "full_name"]
    __search_config__: ClassVar[str] = "simple"  # Default for identifiers
    __search_field_configs__: ClassVar[dict[str, str]] = {
        "email": "simple",
        "username": "simple",
        "full_name": "english",
    }
    __search_weights__: ClassVar[dict[str, str]] = {
        "email": "A",
        "username": "A",
        "full_name": "B",
    }
    __trigram_fields__: ClassVar[list[str]] = ["username", "full_name"]

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Authentication fields
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)

    # User profile fields
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Full-text search vector (managed by database trigger)
    search_vector: Mapped[Any] = mapped_column(
        TSVECTOR,
        nullable=True,
        comment="Full-text search vector for email, username, and full_name",
    )

    # Relationships
    posts: Mapped[list["Post"]] = relationship(
        "Post", back_populates="author", cascade="all, delete-orphan",
    )

    # Additional indexes
    __table_args__ = (
        Index("ix_users_email_username", "email", "username"),
        Index("ix_users_is_active", "is_active"),
    )

    def __repr__(self) -> str:
        """String representation of User."""
        return f"<User(id={self.id}, email={self.email}, username={self.username})>"
