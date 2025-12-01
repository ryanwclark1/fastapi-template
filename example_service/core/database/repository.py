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

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import Select, func, insert, select
from sqlalchemy import delete as sql_delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

from example_service.core.database.exceptions import NotFoundError
from example_service.infra.logging import get_lazy_logger

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

    __slots__ = ("model", "_logger", "_lazy")

    def __init__(self, model: type[T]) -> None:
        """Initialize repository with model class.

        Args:
            model: SQLAlchemy model class (e.g., User, Post)
        """
        self.model = model
        # Standard logger for INFO/WARNING/ERROR
        self._logger = logging.getLogger(f"repository.{model.__name__}")
        # Lazy logger for DEBUG (zero overhead when DEBUG disabled)
        self._lazy = get_lazy_logger(f"repository.{model.__name__}")

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
            instance = result.scalar_one_or_none()
        else:
            instance = await session.get(self.model, id)

        self._lazy.debug(
            lambda: f"db.get: {self.model.__name__}({id}) -> {'found' if instance else 'not found'}"
        )
        return instance

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
            self._logger.info(
                "Entity not found",
                extra={
                    "entity": self.model.__name__,
                    "id": str(id),
                    "operation": "db.get_or_raise",
                },
            )
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
        instance = result.scalar_one_or_none()

        self._lazy.debug(
            lambda: f"db.get_by: {self.model.__name__}.{attr.key}={value!r} -> {'found' if instance else 'not found'}"
        )
        return instance

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
        items = result.scalars().all()

        self._lazy.debug(
            lambda: f"db.list: {self.model.__name__}(limit={limit}, offset={offset}) -> {len(items)} items"
        )
        return items

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

        search_result = SearchResult(items=items, total=total, limit=limit, offset=offset)
        self._lazy.debug(
            lambda: f"db.search: {self.model.__name__}(limit={limit}, offset={offset}) -> {len(items)}/{total} items, page {search_result.page}/{search_result.pages}"
        )
        return search_result

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

        entity_id = getattr(instance, "id", None)
        self._lazy.debug(lambda: f"db.create: {self.model.__name__}(id={entity_id})")
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

        self._lazy.debug(
            lambda: f"db.create_many: {self.model.__name__} -> {len(instances_list)} created"
        )
        return instances_list

    async def delete(self, session: AsyncSession, instance: T) -> None:
        """Delete an entity.

        Args:
            session: Database session
            instance: Entity to delete
        """
        entity_id = getattr(instance, "id", None)
        await session.delete(instance)
        await session.flush()

        self._logger.info(
            "Entity deleted",
            extra={"entity": self.model.__name__, "id": str(entity_id), "operation": "db.delete"},
        )

    async def update_many(
        self,
        session: AsyncSession,
        instances: Iterable[T],
    ) -> Sequence[T]:
        """Update multiple entities.

        Each instance must already be tracked by the session (either loaded
        or previously added). Flushes changes and refreshes all instances.

        Args:
            session: Database session
            instances: Entity instances with modifications

        Returns:
            Sequence of updated entities

        Example:
                users = await repo.list(session, limit=100)
            for user in users:
                user.is_verified = True
            updated = await repo.update_many(session, users)
        """
        instances_list = list(instances)
        session.add_all(instances_list)  # Ensures all are tracked
        await session.flush()
        for instance in instances_list:
            await session.refresh(instance)

        self._lazy.debug(
            lambda: f"db.update_many: {self.model.__name__} -> {len(instances_list)} updated"
        )
        return instances_list

    async def delete_many(
        self,
        session: AsyncSession,
        ids: Iterable[Any],
    ) -> int:
        """Delete multiple entities by primary key.

        Uses a single DELETE statement for efficiency. Does not load entities
        into session - directly executes DELETE WHERE id IN (...).

        Args:
            session: Database session
            ids: Primary key values to delete

        Returns:
            Number of rows deleted

        Example:
                deleted_count = await repo.delete_many(session, [1, 2, 3])
            print(f"Deleted {deleted_count} records")
        """
        ids_list = list(ids)
        if not ids_list:
            return 0

        pk_attr = self._pk_attr()
        stmt = sql_delete(self.model).where(pk_attr.in_(ids_list))
        result = await session.execute(stmt)
        await session.flush()
        deleted_count: int = result.rowcount if hasattr(result, "rowcount") else 0

        # WARNING level for bulk deletes > 10 (audit-worthy)
        if deleted_count > 10:
            self._logger.warning(
                "Bulk delete executed",
                extra={
                    "entity": self.model.__name__,
                    "requested": len(ids_list),
                    "deleted": deleted_count,
                    "operation": "db.delete_many",
                },
            )
        else:
            self._lazy.debug(
                lambda: f"db.delete_many: {self.model.__name__} -> {deleted_count} deleted"
            )
        return deleted_count

    async def upsert_many(
        self,
        session: AsyncSession,
        instances: Iterable[T],
        *,
        conflict_columns: Sequence[str],
        update_columns: Sequence[str],
    ) -> Sequence[T]:
        """Upsert (insert or update) multiple entities.

        Uses PostgreSQL's ON CONFLICT DO UPDATE for atomic upsert.
        Requires explicit specification of conflict and update columns
        for safety and clarity.

        Args:
            session: Database session
            instances: Entity instances to upsert
            conflict_columns: Columns that define uniqueness (e.g., ['email'])
            update_columns: Columns to update on conflict (e.g., ['name', 'updated_at'])

        Returns:
            Sequence of upserted entities

        Raises:
            ValueError: If conflict_columns or update_columns is empty

        Example:
                users = [User(email=\"a@b.com\", name=\"Alice\"), User(email=\"c@d.com\", name=\"Carol\")]
            upserted = await repo.upsert_many(
                session,
                users,
                conflict_columns=[\"email\"],
                update_columns=[\"name\", \"updated_at\"],
            )

        Note:
            PostgreSQL-specific. For other databases, use create_many with
            appropriate error handling.
        """
        if not conflict_columns:
            raise ValueError("conflict_columns must not be empty")
        if not update_columns:
            raise ValueError("update_columns must not be empty")

        instances_list = list(instances)
        if not instances_list:
            return []

        # Convert instances to dicts for Core insert
        from sqlalchemy import inspect as sa_inspect

        def instance_to_dict(inst: T) -> dict[str, Any]:
            mapper = sa_inspect(type(inst))
            if mapper is None:
                return {}
            column_attrs = getattr(mapper, "column_attrs", None)
            if column_attrs is None:
                return {}
            return {c.key: getattr(inst, c.key) for c in column_attrs}

        values = [instance_to_dict(inst) for inst in instances_list]

        # Build upsert statement
        stmt = pg_insert(self.model).values(values)
        update_dict = {col: stmt.excluded[col] for col in update_columns}
        stmt = stmt.on_conflict_do_update(  # type: ignore[assignment]
            index_elements=conflict_columns,
            set_=update_dict,
        ).returning(self.model)

        result = await session.execute(stmt)
        await session.flush()

        # Scalars returns model instances when using RETURNING
        upserted = list(result.scalars().all())
        self._lazy.debug(
            lambda: f"db.upsert_many: {self.model.__name__}(conflict={conflict_columns}) -> {len(upserted)} upserted"
        )
        return upserted

    async def bulk_create(
        self,
        session: AsyncSession,
        instances: Iterable[T],
        *,
        batch_size: int = 1000,
    ) -> int:
        """High-performance bulk insert using SQLAlchemy Core.

        Bypasses ORM overhead for maximum insert speed. Does not return
        created instances or populate generated fields - use create_many()
        if you need the instances back.

        Best for:
        - Large data imports (10k+ rows)
        - When you don't need the created instances
        - Background jobs and data migrations

        Args:
            session: Database session
            instances: Entity instances to insert
            batch_size: Number of rows per INSERT statement (default 1000)

        Returns:
            Total number of rows inserted

        Example:
                users = [User(email=f\"user{i}@example.com\") for i in range(10000)]
            count = await repo.bulk_create(session, users, batch_size=2000)
            print(f\"Inserted {count} users\")
        """
        from sqlalchemy import inspect as sa_inspect

        def instance_to_dict(inst: T) -> dict[str, Any]:
            mapper = sa_inspect(type(inst))
            if mapper is None:
                return {}
            column_attrs = getattr(mapper, "column_attrs", None)
            if column_attrs is None:
                return {}
            return {c.key: getattr(inst, c.key) for c in column_attrs}

        instances_list = list(instances)
        if not instances_list:
            return 0

        total_inserted = 0

        # Process in batches
        for i in range(0, len(instances_list), batch_size):
            batch = instances_list[i : i + batch_size]
            values = [instance_to_dict(inst) for inst in batch]
            stmt = insert(self.model).values(values)
            await session.execute(stmt)
            total_inserted += len(batch)

        await session.flush()

        # INFO level for bulk inserts (important data operation)
        self._logger.info(
            "Bulk create completed",
            extra={
                "entity": self.model.__name__,
                "count": total_inserted,
                "batch_size": batch_size,
                "operation": "db.bulk_create",
            },
        )
        return total_inserted

    async def paginate_cursor(
        self,
        session: AsyncSession,
        statement: Select[tuple[T]],
        *,
        first: int | None = None,
        after: str | None = None,
        last: int | None = None,
        before: str | None = None,
        order_by: Sequence[tuple[InstrumentedAttribute[Any], str]] | None = None,
        include_total: bool = False,
    ) -> Any:  # Returns Connection[T]
        """Execute cursor-paginated query.

        Implements cursor-based (keyset) pagination with support for both
        forward and backward navigation. Returns a GraphQL Connection-style
        response that can be converted to simpler REST format.

        Args:
            session: Database session
            statement: SQLAlchemy select statement (without pagination)
            first: Number of items for forward pagination
            after: Cursor for forward pagination (fetch items after this)
            last: Number of items for backward pagination
            before: Cursor for backward pagination (fetch items before this)
            order_by: List of (column, direction) tuples
            include_total: Whether to include total count (can be expensive)

        Returns:
            Connection[T] with edges and page_info

        Example:
            from example_service.core.pagination import Connection

            stmt = select(User).where(User.is_active == True)
            result: Connection[User] = await repo.paginate_cursor(
                session,
                stmt,
                first=50,
                after=cursor_from_request,
                order_by=[(User.created_at, "desc"), (User.id, "asc")],
            )

            # Access items
            for edge in result.edges:
                print(edge.node, edge.cursor)

            # Check for more pages
            if result.page_info.has_next_page:
                next_cursor = result.page_info.end_cursor
        """
        from example_service.core.pagination import (
            Connection,
            CursorCodec,
            CursorFilter,
            Edge,
            PageInfo,
        )

        # Determine pagination direction and limit
        if first is not None:
            limit = first
            cursor = after
            direction = "after"
        elif last is not None:
            limit = last
            cursor = before
            direction = "before"
        else:
            limit = 50  # Default
            cursor = None
            direction = "after"

        # Convert order_by to proper type hints
        if order_by is None:
            typed_order_by: list[tuple[InstrumentedAttribute[Any], str]] = []
        else:
            typed_order_by = [(col, dir_) for col, dir_ in order_by]

        # Apply cursor filter
        cursor_filter = CursorFilter(
            cursor=cursor,
            order_by=typed_order_by,  # type: ignore[arg-type]
            limit=limit,
            direction=direction,  # type: ignore[arg-type]
        )
        paginated_stmt = cursor_filter.apply(statement)

        # Execute query
        result = await session.execute(paginated_stmt)
        rows = list(result.scalars().all())

        # Check if there are more items (we fetched limit+1)
        has_more = len(rows) > limit
        if has_more:
            rows = rows[:limit]

        # For backward pagination, reverse the results
        if direction == "before":
            rows = list(reversed(rows))

        # Get total count if requested
        total_count = None
        if include_total:
            from sqlalchemy import func

            count_stmt = select(func.count()).select_from(statement.subquery())
            total_count = (await session.execute(count_stmt)).scalar_one()

        # Build sort field names for cursor creation
        sort_fields = [col.key for col, _ in typed_order_by]

        # Build edges with cursors
        edges: list[Edge[T]] = []
        for row in rows:
            item_cursor = CursorCodec.create_cursor(row, sort_fields, "forward")
            edges.append(Edge(node=row, cursor=item_cursor))

        # Build page info
        has_next = has_more if direction == "after" else (cursor is not None)
        has_prev = (cursor is not None) if direction == "after" else has_more

        page_info = PageInfo(
            has_previous_page=has_prev,
            has_next_page=has_next,
            start_cursor=edges[0].cursor if edges else None,
            end_cursor=edges[-1].cursor if edges else None,
            total_count=total_count,
        )

        connection: Connection[Any] = Connection(edges=edges, page_info=page_info)

        self._lazy.debug(
            lambda: f"db.paginate_cursor: {self.model.__name__}(limit={limit}) -> {len(edges)} items, has_next={has_next}"
        )

        return connection

    def _pk_attr(self) -> InstrumentedAttribute[Any]:
        """Get primary key attribute.

        Inspects the model to find the primary key column.
        Falls back to 'id' if inspection fails.
        """
        from sqlalchemy import inspect as sa_inspect

        try:
            mapper = sa_inspect(self.model)
            if mapper is None:
                raise AttributeError("No mapper found")
            pk_cols = getattr(mapper, "primary_key", None)
            if pk_cols and len(pk_cols) > 0:
                # Return the first primary key column's attribute
                return cast("InstrumentedAttribute[Any]", getattr(self.model, pk_cols[0].name))
        except Exception:
            pass

        # Fallback to 'id'
        # Most SQLAlchemy models have an 'id' attribute, but type checker doesn't know this
        # Using getattr with cast to satisfy type checker
        attr = getattr(self.model, "id", None)
        if attr is None:
            raise AttributeError(f"{self.model.__name__} has no 'id' attribute")
        return cast("InstrumentedAttribute[Any]", attr)


__all__ = [
    "BaseRepository",
    "SearchResult",
]
