"""Base database model classes."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Define consistent naming convention for database constraints
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for all database models.

    Provides common functionality for SQLAlchemy ORM models with
    consistent naming conventions for database constraints.

    The naming convention ensures that all constraints (indexes, foreign keys,
    unique constraints, etc.) have predictable, standardized names across
    the database schema.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


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
