"""Core database package with enhanced base classes and repository pattern.

This package provides a flexible foundation for database operations:

Base Classes and Mixins:
    - Base: Enhanced declarative base with auto table naming
    - IntegerPKMixin, UUIDPKMixin: Flexible primary key strategies
    - TimestampMixin: created_at, updated_at tracking
    - AuditColumnsMixin: created_by, updated_by tracking
    - SoftDeleteMixin: Soft delete support with deleted_at

Convenience Bases:
    - TimestampedBase: Integer PK + timestamps (backward compatible)
    - UUIDTimestampedBase: UUID PK + timestamps
    - AuditedBase: Integer PK + timestamps + audit columns

Repository:
    - BaseRepository: Generic async repository with CRUD operations
    - SearchResult: Paginated search results with metadata

Exceptions:
    - RepositoryError: Base exception for repository operations
    - NotFoundError: Entity not found (404-like)
    - MultipleResultsFoundError: Multiple entities when expecting one
    - InvalidFilterError: Invalid filter parameters

Example:
    ```python
    from example_service.core.database import (
        Base,
        UUIDPKMixin,
        TimestampMixin,
        AuditColumnsMixin,
        BaseRepository,
    )

    # Define model
    class User(Base, UUIDPKMixin, TimestampMixin, AuditColumnsMixin):
        __tablename__ = "users"
        email: Mapped[str] = mapped_column(String(255), unique=True)

    # Use repository
    user_repo = BaseRepository(User, session)
    user = await user_repo.get_by_id(uuid_value)
    ```
"""
from __future__ import annotations

from example_service.core.database.base import (
    NAMING_CONVENTION,
    AuditColumnsMixin,
    AuditedBase,
    Base,
    IntegerPKMixin,
    SoftDeleteMixin,
    TimestampedBase,
    TimestampMixin,
    UUIDPKMixin,
    UUIDTimestampedBase,
)
from example_service.core.database.exceptions import (
    InvalidFilterError,
    MultipleResultsFoundError,
    NotFoundError,
    RepositoryError,
)
from example_service.core.database.repository import BaseRepository, SearchResult

__all__ = [
    # Base and metadata
    "Base",
    "NAMING_CONVENTION",
    # Primary key mixins
    "IntegerPKMixin",
    "UUIDPKMixin",
    # Audit mixins
    "TimestampMixin",
    "AuditColumnsMixin",
    "SoftDeleteMixin",
    # Convenience bases
    "TimestampedBase",
    "UUIDTimestampedBase",
    "AuditedBase",
    # Repository
    "BaseRepository",
    "SearchResult",
    # Exceptions
    "RepositoryError",
    "NotFoundError",
    "MultipleResultsFoundError",
    "InvalidFilterError",
]
