"""Core database package with composable base classes, mixins, and repository.

This package provides a flexible foundation for database models with
both direct SQLAlchemy usage and an optional thin repository layer.
Use whichever approach fits your needs - or mix them.

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
    - BaseRepository[T]: Generic CRUD with explicit session passing
    - SearchResult[T]: Paginated result container

Query Filters:
    - SearchFilter: Multi-field text search with LIKE/ILIKE
    - OrderBy: Column sorting (asc/desc)
    - LimitOffset: Pagination helper
    - CollectionFilter: WHERE ... IN clauses
    - BeforeAfter: Date range filtering
    - OnBeforeAfter: Inclusive date range filtering
    - FilterGroup: Combine multiple filters

Custom Types:
    - EncryptedString: Transparent encryption for sensitive data
    - EncryptedText: Encrypted Text type for larger content

Exceptions:
    - DatabaseError: Base exception for database operations
    - NotFoundError: Entity not found (404-like)

Example (Repository approach):
    from example_service.core.database import BaseRepository, SearchResult
    from example_service.core.models import User

    class UserRepository(BaseRepository[User]):
        async def find_by_email(self, session, email: str) -> User | None:
            return await self.get_by(session, User.email, email)

    # Usage
    repo = UserRepository(User)
    user = await repo.get(session, user_id)

Example (Direct SQLAlchemy):
    from sqlalchemy import select
    from example_service.core.database import SearchFilter, OrderBy

    # Direct SQLAlchemy with filters - bypass repository when needed
    async def search_users(session: AsyncSession, query: str) -> list[User]:
        stmt = select(User)
        stmt = SearchFilter([User.name, User.email], query).apply(stmt)
        stmt = OrderBy(User.created_at, "desc").apply(stmt)

        result = await session.execute(stmt)
        return list(result.scalars().all())
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
    DatabaseError,
    NotFoundError,
)
from example_service.core.database.filters import (
    BeforeAfter,
    CollectionFilter,
    FilterGroup,
    LimitOffset,
    OnBeforeAfter,
    OrderBy,
    SearchFilter,
    StatementFilter,
)
from example_service.core.database.repository import (
    BaseRepository,
    SearchResult,
)
from example_service.core.database.types import (
    EncryptedString,
    EncryptedText,
)

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
    # Filters
    "StatementFilter",
    "SearchFilter",
    "OrderBy",
    "LimitOffset",
    "CollectionFilter",
    "BeforeAfter",
    "OnBeforeAfter",
    "FilterGroup",
    # Custom types
    "EncryptedString",
    "EncryptedText",
    # Exceptions
    "DatabaseError",
    "NotFoundError",
]
