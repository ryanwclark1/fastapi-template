"""Base repository for async database operations.

Provides a generic CRUD interface inspired by accent-dao patterns with
enhancements for pagination, filtering, eager loading, and soft deletes.

The repository pattern centralizes data access logic and provides a
consistent interface across all models, making it easier to:
- Test business logic (mock repositories instead of raw SQLAlchemy)
- Change database implementations
- Add cross-cutting concerns (caching, metrics, audit logging)
- Maintain consistent query patterns
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from sqlalchemy import Select, func, inspect, select
from sqlalchemy.exc import MultipleResultsFound, NoResultFound
from sqlalchemy.orm import InstrumentedAttribute

from example_service.core.database.exceptions import (
    MultipleResultsFoundError,
    NotFoundError,
    RepositoryError,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

# Generic type for model class
T = TypeVar("T")


class SearchResult(Generic[T]):
    """Paginated search results with metadata.

    Provides pagination information along with the query results,
    making it easy to build pagination UIs.

    Attributes:
        items: List of entities matching the search
        total: Total number of matching entities (before pagination)
        limit: Maximum results per page
        offset: Number of results skipped
        has_next: Whether there are more results available
        has_prev: Whether there are previous results
        page: Current page number (1-indexed, calculated from offset/limit)
        total_pages: Total number of pages
    """

    def __init__(
        self,
        items: list[T],
        total: int,
        limit: int,
        offset: int,
    ):
        """Initialize search result.

        Args:
            items: Entities for current page
            total: Total matching entities
            limit: Page size
            offset: Starting position
        """
        self.items = items
        self.total = total
        self.limit = limit
        self.offset = offset

    @property
    def has_next(self) -> bool:
        """Check if there are more results."""
        return self.offset + self.limit < self.total

    @property
    def has_prev(self) -> bool:
        """Check if there are previous results."""
        return self.offset > 0

    @property
    def page(self) -> int:
        """Current page number (1-indexed)."""
        if self.limit == 0:
            return 1
        return (self.offset // self.limit) + 1

    @property
    def total_pages(self) -> int:
        """Total number of pages."""
        if self.limit == 0:
            return 1
        return (self.total + self.limit - 1) // self.limit

    def __repr__(self) -> str:
        """Repr for debugging."""
        return (
            f"SearchResult(items={len(self.items)}, total={self.total}, "
            f"page={self.page}/{self.total_pages})"
        )


class BaseRepository(Generic[T]):
    """Generic async repository providing CRUD operations.

    This base class implements common database operations for SQLAlchemy
    models. It can be used directly or subclassed for model-specific queries.

    Type Parameters:
        T: The SQLAlchemy model class this repository operates on

    Example:
        ```python
        # Direct usage
        user_repo = BaseRepository(User, session)
        user = await user_repo.get_by_id(123)

        # Subclass for custom methods
        class UserRepository(BaseRepository[User]):
            async def find_by_email(self, email: str) -> User | None:
                stmt = select(User).where(User.email == email)
                result = await self._session.execute(stmt)
                return result.scalar_one_or_none()

        user_repo = UserRepository(User, session)
        user = await user_repo.find_by_email("user@example.com")
        ```

    Attributes:
        model: The SQLAlchemy model class
        _session: Database session for executing queries
    """

    model: type[T]
    _session: AsyncSession

    def __init__(self, model: type[T], session: AsyncSession):
        """Initialize repository.

        Args:
            model: SQLAlchemy model class
            session: Async database session
        """
        self.model = model
        self._session = session

    # ========================================================================
    # Primary Key Helpers
    # ========================================================================

    def _get_pk_column(self) -> InstrumentedAttribute[Any]:
        """Get the primary key column for the model.

        Returns:
            Primary key column (e.g., User.id)

        Raises:
            RepositoryError: If model has no primary key or composite keys
        """
        mapper = inspect(self.model)
        if not mapper:
            raise RepositoryError(
                f"Cannot inspect model {self.model.__name__}",
                details={"model": self.model.__name__},
            )

        pk_columns = list(mapper.primary_key)
        if not pk_columns:
            raise RepositoryError(
                f"Model {self.model.__name__} has no primary key defined",
                details={"model": self.model.__name__},
            )

        if len(pk_columns) > 1:
            raise RepositoryError(
                f"Model {self.model.__name__} has composite primary key, use get() instead",
                details={"model": self.model.__name__, "pk_columns": len(pk_columns)},
            )

        # Return the mapped column attribute
        pk_col = pk_columns[0]
        return getattr(self.model, pk_col.name)

    def _get_entity_id(self, entity: T) -> Any:
        """Extract primary key value from an entity.

        Args:
            entity: Entity instance

        Returns:
            Primary key value

        Raises:
            RepositoryError: If PK is not set or model has no PK
        """
        mapper = inspect(self.model)
        if not mapper:
            raise RepositoryError(
                f"Cannot inspect model {self.model.__name__}",
                details={"model": self.model.__name__},
            )

        pk_columns = mapper.primary_key
        if not pk_columns:
            raise RepositoryError(
                f"Model {self.model.__name__} has no primary key",
                details={"model": self.model.__name__},
            )

        # For single PK, return scalar value
        if len(pk_columns) == 1:
            pk_attr_name = pk_columns[0].name
            pk_value = getattr(entity, pk_attr_name, None)
            if pk_value is None:
                raise RepositoryError(
                    f"Primary key '{pk_attr_name}' is None on {self.model.__name__}",
                    details={"model": self.model.__name__, "pk_column": pk_attr_name},
                )
            return pk_value

        # For composite PK, return tuple
        pk_values = []
        for pk_col in pk_columns:
            pk_value = getattr(entity, pk_col.name, None)
            if pk_value is None:
                raise RepositoryError(
                    f"Primary key '{pk_col.name}' is None on {self.model.__name__}",
                    details={"model": self.model.__name__, "pk_column": pk_col.name},
                )
            pk_values.append(pk_value)
        return tuple(pk_values)

    # ========================================================================
    # Read Operations
    # ========================================================================

    async def get(
        self,
        pk_value: Any,
        *,
        options: Iterable[Any] | None = None,
    ) -> T | None:
        """Get entity by primary key, returning None if not found.

        This is a "soft" lookup that doesn't raise exceptions.

        Args:
            pk_value: Primary key value
            options: SQLAlchemy query options (e.g., selectinload for eager loading)

        Returns:
            Entity if found, None otherwise

        Example:
            ```python
            # Simple lookup
            user = await repo.get(123)
            if user is None:
                print("User not found")

            # With eager loading
            from sqlalchemy.orm import selectinload
            user = await repo.get(123, options=[selectinload(User.posts)])
            ```
        """
        try:
            return await self.get_by_id(pk_value, options=options)
        except NotFoundError:
            return None

    async def get_by_id(
        self,
        pk_value: Any,
        *,
        options: Iterable[Any] | None = None,
    ) -> T:
        """Get entity by primary key, raising NotFoundError if not found.

        This is a "hard" lookup that enforces entity existence.

        Args:
            pk_value: Primary key value
            options: SQLAlchemy query options

        Returns:
            Entity instance

        Raises:
            NotFoundError: If entity doesn't exist
            RepositoryError: If model configuration is invalid

        Example:
            ```python
            try:
                user = await repo.get_by_id(123)
                print(user.email)
            except NotFoundError:
                return {"error": "User not found"}, 404
            ```
        """
        pk_col = self._get_pk_column()
        stmt = select(self.model).where(pk_col == pk_value)

        if options:
            stmt = stmt.options(*options)

        result = await self._session.execute(stmt)
        instance = result.scalar_one_or_none()

        if instance is None:
            raise NotFoundError(self.model.__name__, {pk_col.key: pk_value})

        return instance

    async def list_all(
        self,
        *,
        options: Iterable[Any] | None = None,
    ) -> Sequence[T]:
        """Return all entities.

        Warning: Use with caution on large tables. Consider using
        search() with pagination instead.

        Args:
            options: SQLAlchemy query options for eager loading

        Returns:
            All entities in the table

        Example:
            ```python
            # Get all users (dangerous if table is large!)
            users = await repo.list_all()

            # Better: use pagination
            result = await repo.search(limit=100, offset=0)
            ```
        """
        stmt = select(self.model)
        if options:
            stmt = stmt.options(*options)

        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def search(
        self,
        *,
        filters: Select[tuple[T]] | None = None,
        limit: int = 50,
        offset: int = 0,
        order_by: list[Any] | None = None,
        options: Iterable[Any] | None = None,
    ) -> SearchResult[T]:
        """Execute paginated search with optional filtering and sorting.

        Args:
            filters: Pre-built SELECT statement with filters applied
            limit: Maximum results per page (default: 50)
            offset: Number of results to skip (default: 0)
            order_by: List of columns/expressions to order by
            options: SQLAlchemy query options (eager loading)

        Returns:
            SearchResult with items and pagination metadata

        Example:
            ```python
            # Simple pagination
            result = await repo.search(limit=10, offset=20)
            print(f"Page {result.page} of {result.total_pages}")
            for user in result.items:
                print(user.email)

            # With filtering
            stmt = select(User).where(User.is_active == True)
            result = await repo.search(filters=stmt, limit=10)

            # With sorting
            result = await repo.search(
                order_by=[User.created_at.desc()],
                limit=10
            )
            ```
        """
        # Start with filters or base select
        if filters is not None:
            base_stmt = filters
        else:
            base_stmt = select(self.model)

        # Apply eager loading
        if options:
            base_stmt = base_stmt.options(*options)

        # Apply sorting
        if order_by:
            base_stmt = base_stmt.order_by(*order_by)

        # Get total count (before pagination)
        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total = (await self._session.execute(count_stmt)).scalar_one()

        # Apply pagination
        stmt = base_stmt.limit(limit).offset(offset)

        # Execute query
        result = await self._session.execute(stmt)
        items: Sequence[T] = result.scalars().all()

        return SearchResult(items=list(items), total=total, limit=limit, offset=offset)

    # ========================================================================
    # Write Operations
    # ========================================================================

    async def create(self, entity: T, *, auto_commit: bool = False) -> T:
        """Create new entity.

        Args:
            entity: Entity instance to persist
            auto_commit: If True, commit immediately (default: False)

        Returns:
            Created entity with database-generated values populated

        Example:
            ```python
            user = User(email="user@example.com", username="john")
            user = await repo.create(user)
            print(user.id)  # Database-generated ID

            # Auto-commit (not recommended, use UnitOfWork pattern)
            user = await repo.create(user, auto_commit=True)
            ```

        Note:
            Setting auto_commit=True is convenient but prevents transaction
            grouping. Prefer explicit session.commit() for better control.
        """
        self._session.add(entity)
        await self._session.flush()
        await self._session.refresh(entity)

        if auto_commit:
            await self._session.commit()

        return entity

    async def update(self, entity: T, *, auto_commit: bool = False) -> T:
        """Update existing entity.

        Args:
            entity: Entity instance with modified fields
            auto_commit: If True, commit immediately

        Returns:
            Updated entity with refreshed values

        Raises:
            RepositoryError: If entity has no primary key

        Example:
            ```python
            user = await repo.get_by_id(123)
            user.email = "newemail@example.com"
            user = await repo.update(user)
            ```
        """
        # Validate entity has PK
        _ = self._get_entity_id(entity)

        # Merge into session
        merged = await self._session.merge(entity)
        await self._session.flush()
        await self._session.refresh(merged)

        if auto_commit:
            await self._session.commit()

        return merged

    async def delete(self, entity: T, *, auto_commit: bool = False) -> None:
        """Hard delete entity (permanent removal).

        Args:
            entity: Entity to delete
            auto_commit: If True, commit immediately

        Example:
            ```python
            user = await repo.get_by_id(123)
            await repo.delete(user)
            await session.commit()
            ```

        Warning:
            This is a permanent deletion. Consider using soft_delete()
            for recoverable deletions.
        """
        await self._session.delete(entity)
        await self._session.flush()

        if auto_commit:
            await self._session.commit()

    # ========================================================================
    # Soft Delete Operations
    # ========================================================================

    async def soft_delete(self, entity: T, *, auto_commit: bool = False) -> T:
        """Soft delete entity (set deleted_at timestamp).

        Only works for models with SoftDeleteMixin.

        Args:
            entity: Entity to soft delete
            auto_commit: If True, commit immediately

        Returns:
            Updated entity with deleted_at set

        Raises:
            RepositoryError: If model doesn't support soft delete

        Example:
            ```python
            user = await repo.get_by_id(123)
            user = await repo.soft_delete(user)
            print(user.is_deleted)  # True
            ```
        """
        if not hasattr(entity, "deleted_at"):
            raise RepositoryError(
                f"Model {self.model.__name__} does not support soft delete",
                details={
                    "model": self.model.__name__,
                    "hint": "Add SoftDeleteMixin to the model",
                },
            )

        entity.deleted_at = datetime.now(UTC)  # type: ignore
        return await self.update(entity, auto_commit=auto_commit)

    async def restore(self, entity: T, *, auto_commit: bool = False) -> T:
        """Restore soft-deleted entity.

        Args:
            entity: Soft-deleted entity to restore
            auto_commit: If True, commit immediately

        Returns:
            Restored entity with deleted_at cleared

        Raises:
            RepositoryError: If model doesn't support soft delete

        Example:
            ```python
            user = await repo.get_by_id(123)  # Soft-deleted user
            user = await repo.restore(user)
            print(user.is_deleted)  # False
            ```
        """
        if not hasattr(entity, "deleted_at"):
            raise RepositoryError(
                f"Model {self.model.__name__} does not support soft delete",
                details={"model": self.model.__name__},
            )

        entity.deleted_at = None  # type: ignore
        return await self.update(entity, auto_commit=auto_commit)

    # ========================================================================
    # Bulk Operations
    # ========================================================================

    async def bulk_create(
        self,
        entities: list[T],
        *,
        auto_commit: bool = False,
    ) -> list[T]:
        """Create multiple entities efficiently.

        Args:
            entities: List of entities to create
            auto_commit: If True, commit immediately

        Returns:
            List of created entities with IDs populated

        Example:
            ```python
            users = [
                User(email="user1@example.com"),
                User(email="user2@example.com"),
            ]
            created = await repo.bulk_create(users)
            ```
        """
        self._session.add_all(entities)
        await self._session.flush()

        # Refresh all entities to get generated IDs
        for entity in entities:
            await self._session.refresh(entity)

        if auto_commit:
            await self._session.commit()

        return entities


__all__ = [
    "BaseRepository",
    "SearchResult",
]
