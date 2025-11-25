"""Minimal generic repository for SQLAlchemy models.

Provides basic CRUD operations with explicit session passing.
For complex queries, use the session directly - this is a convenience, not a cage.

Example:
    from example_service.core.database import BaseRepository
    from example_service.core.models import User

    class UserRepository(BaseRepository[User]):
        '''User-specific queries beyond basic CRUD.'''

        async def find_by_email(self, session: AsyncSession, email: str) -> User | None:
            stmt = select(User).where(User.email == email)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    # Usage in service
    user_repo = UserRepository(User)
    user = await user_repo.get(session, user_id)  # Repository method
    # OR bypass for complex queries:
    stmt = select(User).where(User.is_active == True).options(selectinload(User.posts))
    result = await session.execute(stmt)  # Direct SQLAlchemy
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import Select, func, select

from example_service.core.database.exceptions import NotFoundError

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import InstrumentedAttribute


@dataclass(slots=True, frozen=True)
class SearchResult[T]:
    """Paginated search result container.

    Attributes:
        items: List of items for current page
        total: Total count across all pages
        limit: Page size
        offset: Current offset

    Example:
            result = await repo.search(session, limit=20, offset=0)
        print(f"Showing {len(result.items)} of {result.total}")
        if result.has_next:
            next_result = await repo.search(session, limit=20, offset=20)
    """

    items: Sequence[T]
    total: int
    limit: int
    offset: int

    @property
    def page(self) -> int:
        """Current page number (1-indexed)."""
        return (self.offset // self.limit) + 1 if self.limit else 1

    @property
    def pages(self) -> int:
        """Total number of pages."""
        if self.limit == 0:
            return 1
        return (self.total + self.limit - 1) // self.limit

    @property
    def has_next(self) -> bool:
        """Whether there are more pages after current."""
        return self.offset + len(self.items) < self.total

    @property
    def has_prev(self) -> bool:
        """Whether there are pages before current."""
        return self.offset > 0


class BaseRepository[T]:
    """Minimal generic repository for CRUD operations.

    Provides:
        - get(session, id) -> T | None
        - get_or_raise(session, id) -> T (raises NotFoundError)
        - get_by(session, attr, value) -> T | None
        - list(session, limit, offset) -> Sequence[T]
        - search(session, statement, limit, offset) -> SearchResult[T]
        - create(session, instance) -> T
        - create_many(session, instances) -> Sequence[T]
        - delete(session, instance) -> None

    Session is always explicit - no hidden state. For queries not covered here,
    use the session directly. This is a thin convenience layer, not an ORM wrapper.

    Example:
            class UserRepository(BaseRepository[User]):
            pass  # That's it for basic CRUD

        # With custom methods
        class UserRepository(BaseRepository[User]):
            async def find_active(self, session: AsyncSession) -> Sequence[User]:
                stmt = select(User).where(User.is_active == True)
                result = await session.execute(stmt)
                return result.scalars().all()
    """

    __slots__ = ("model",)

    def __init__(self, model: type[T]) -> None:
        """Initialize repository with model class.

        Args:
            model: SQLAlchemy model class (e.g., User, Post)
        """
        self.model = model

    async def get(
        self,
        session: AsyncSession,
        id: Any,  # noqa: A002
        *,
        options: Iterable[Any] | None = None,
    ) -> T | None:
        """Get entity by primary key.

        Args:
            session: Database session
            id: Primary key value
            options: SQLAlchemy loader options (e.g., selectinload)

        Returns:
            Entity if found, None otherwise

        Example:
                    user = await repo.get(session, 123)
            # With eager loading
            user = await repo.get(session, 123, options=[selectinload(User.posts)])
        """
        if options:
            stmt = select(self.model).where(self._pk_attr() == id).options(*options)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()
        return await session.get(self.model, id)

    async def get_or_raise(
        self,
        session: AsyncSession,
        id: Any,  # noqa: A002
        *,
        options: Iterable[Any] | None = None,
    ) -> T:
        """Get entity by primary key or raise NotFoundError.

        Args:
            session: Database session
            id: Primary key value
            options: SQLAlchemy loader options

        Returns:
            Entity instance

        Raises:
            NotFoundError: If entity doesn't exist
        """
        instance = await self.get(session, id, options=options)
        if instance is None:
            raise NotFoundError(self.model.__name__, {"id": id})
        return instance

    async def get_by(
        self,
        session: AsyncSession,
        attr: InstrumentedAttribute[Any],
        value: Any,
        *,
        options: Iterable[Any] | None = None,
    ) -> T | None:
        """Get entity by arbitrary attribute.

        Args:
            session: Database session
            attr: Model attribute to filter by (e.g., User.email)
            value: Value to match
            options: SQLAlchemy loader options

        Returns:
            First matching entity or None

        Example:
                    user = await repo.get_by(session, User.email, "john@example.com")
        """
        stmt = select(self.model).where(attr == value)
        if options:
            stmt = stmt.options(*options)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        session: AsyncSession,
        *,
        limit: int = 100,
        offset: int = 0,
        options: Iterable[Any] | None = None,
    ) -> Sequence[T]:
        """List entities with pagination.

        Args:
            session: Database session
            limit: Maximum results to return
            offset: Number of results to skip
            options: SQLAlchemy loader options

        Returns:
            Sequence of entities
        """
        stmt = select(self.model).limit(limit).offset(offset)
        if options:
            stmt = stmt.options(*options)
        result = await session.execute(stmt)
        return result.scalars().all()

    async def search(
        self,
        session: AsyncSession,
        statement: Select[tuple[T]],
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> SearchResult[T]:
        """Execute paginated search with total count.

        Takes a pre-built statement (with filters applied) and adds pagination.
        Use this with StatementFilter classes for complex queries.

        Args:
            session: Database session
            statement: SQLAlchemy select statement (apply filters before calling)
            limit: Page size
            offset: Results to skip

        Returns:
            SearchResult with items, total count, and pagination info

        Example:
                    from example_service.core.database import SearchFilter, OrderBy

            # Build statement with filters
            stmt = select(User)
            stmt = SearchFilter([User.name, User.email], "john").apply(stmt)
            stmt = OrderBy(User.created_at, "desc").apply(stmt)

            # Execute with pagination
            result = await repo.search(session, stmt, limit=20, offset=0)
            print(f"Found {result.total} users, showing page {result.page}")
        """
        # Count total before pagination
        count_stmt = select(func.count()).select_from(statement.subquery())
        total = (await session.execute(count_stmt)).scalar_one()

        # Apply pagination
        paginated = statement.limit(limit).offset(offset)
        result = await session.execute(paginated)
        items = result.scalars().all()

        return SearchResult(items=items, total=total, limit=limit, offset=offset)

    async def create(self, session: AsyncSession, instance: T) -> T:
        """Persist a new entity.

        Adds to session, flushes to get generated values (like id),
        and refreshes to ensure instance is up-to-date.

        Args:
            session: Database session
            instance: Entity instance to persist

        Returns:
            Persisted entity with generated fields populated
        """
        session.add(instance)
        await session.flush()
        await session.refresh(instance)
        return instance

    async def create_many(self, session: AsyncSession, instances: Iterable[T]) -> Sequence[T]:
        """Persist multiple entities.

        Args:
            session: Database session
            instances: Entity instances to persist

        Returns:
            Sequence of persisted entities
        """
        instances_list = list(instances)
        session.add_all(instances_list)
        await session.flush()
        for instance in instances_list:
            await session.refresh(instance)
        return instances_list

    async def delete(self, session: AsyncSession, instance: T) -> None:
        """Delete an entity.

        Args:
            session: Database session
            instance: Entity to delete
        """
        await session.delete(instance)
        await session.flush()

    def _pk_attr(self) -> InstrumentedAttribute[Any]:
        """Get primary key attribute.

        Inspects the model to find the primary key column.
        Falls back to 'id' if inspection fails.
        """
        from sqlalchemy import inspect as sa_inspect

        try:
            mapper = sa_inspect(self.model)
            pk_cols = mapper.primary_key
            if pk_cols:
                # Return the first primary key column's attribute
                return getattr(self.model, pk_cols[0].name)
        except Exception:
            pass

        # Fallback to 'id'
        return self.model.id  # type: ignore[return-value]


__all__ = [
    "BaseRepository",
    "SearchResult",
]
