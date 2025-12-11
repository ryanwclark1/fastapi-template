# =============================================================================
# EXAMPLE MODEL - For demonstration and template purposes
# This model demonstrates SQLAlchemy patterns but is not used in production.
# Safe to remove when building your application (update migrations accordingly).
# =============================================================================
"""Post model for demonstrating foreign key relationships and full-text search."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from example_service.core.database import TimestampedBase
from example_service.core.database.search import TSVECTOR

if TYPE_CHECKING:
    from .user import User


class Post(TimestampedBase):
    """Post model with foreign key to User and full-text search.

    Demonstrates:
    - Foreign key relationships
    - Text fields
    - Indexes on foreign keys
    - Timestamps (via TimestampedBase)
    - Full-text search with weighted fields

    The search vector includes:
    - Title (weight A - highest priority)
    - Content (weight B - medium priority)
    - Slug (weight C - lower priority for exact matches)
    """

    __tablename__ = "posts"

    # Search configuration
    __search_fields__: ClassVar[list[str]] = ["title", "content", "slug"]
    __search_config__: ClassVar[str] = "english"
    __search_weights__: ClassVar[dict[str, str]] = {
        "title": "A",
        "content": "B",
        "slug": "C",
    }
    __trigram_fields__: ClassVar[list[str]] = ["title"]  # For fuzzy search

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Content fields
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    # Status fields
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Foreign key to User
    author_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
    )

    # Full-text search vector (managed by database trigger)
    search_vector: Mapped[Any] = mapped_column(
        TSVECTOR,
        nullable=True,
        comment="Full-text search vector for title, content, and slug",
    )

    # Relationships
    author: Mapped["User"] = relationship("User", back_populates="posts")

    # Additional indexes
    __table_args__ = (
        Index("ix_posts_author_id_is_published", "author_id", "is_published"),
        Index("ix_posts_slug", "slug"),
    )

    def __repr__(self) -> str:
        """String representation of Post."""
        return f"<Post(id={self.id}, title={self.title}, author_id={self.author_id})>"
