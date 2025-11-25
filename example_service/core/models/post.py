"""Post model for demonstrating foreign key relationships."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from example_service.core.database import TimestampedBase

if TYPE_CHECKING:
    from .user import User


class Post(TimestampedBase):
    """Post model with foreign key to User.

    Demonstrates:
    - Foreign key relationships
    - Text fields
    - Indexes on foreign keys
    - Timestamps (via TimestampedBase)
    """

    __tablename__ = "posts"

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
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
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
