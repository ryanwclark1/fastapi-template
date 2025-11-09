"""Base database model classes."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all database models.

    Provides common functionality for SQLAlchemy ORM models.
    """

    pass


class TimestampedBase(Base):
    """Base model with timestamp fields.

    Automatically tracks creation and update timestamps.

    Example:
        ```python
        class User(TimestampedBase):
            __tablename__ = "users"

            id: Mapped[str] = mapped_column(primary_key=True)
            email: Mapped[str] = mapped_column(unique=True)
        ```
    """

    __abstract__ = True

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
