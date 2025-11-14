"""User domain model."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import String, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from example_service.infra.database.base import TimestampedBase


class User(TimestampedBase):
    """User account model.

    Represents a user in the system with authentication and profile information.
    Uses TimestampedBase for automatic created_at/updated_at tracking.

    This model works seamlessly with psycopg through SQLAlchemy's async engine.

    Example:
        ```python
        from example_service.core.models import User
        from example_service.infra.database.session import get_async_session

        async with get_async_session() as session:
            # Create user
            user = User(
                email="alice@example.com",
                full_name="Alice Johnson",
                is_active=True,
            )
            session.add(user)
            await session.commit()

            # Query users
            from sqlalchemy import select
            result = await session.execute(select(User).where(User.is_active == True))
            active_users = result.scalars().all()
        ```
    """

    __tablename__ = "users"

    # Primary key (UUID)
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
        comment="Unique user identifier (UUID)",
    )

    # Authentication fields
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
        comment="User email address (unique, used for login)",
    )
    hashed_password: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Bcrypt hashed password (nullable for OAuth users)",
    )

    # Profile fields
    full_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="User's full name",
    )
    avatar_url: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
        comment="URL to user's avatar image",
    )

    # Status flags
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        index=True,
        comment="Whether user account is active",
    )
    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="Whether user email is verified",
    )
    is_superuser: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="Whether user has admin privileges",
    )

    # Relationships
    products: Mapped[list["Product"]] = relationship(
        "Product",
        back_populates="owner",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        """String representation of User."""
        return f"<User(id={self.id}, email={self.email}, active={self.is_active})>"
