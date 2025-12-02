"""Repository for the tags feature."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from sqlalchemy import func, select

from example_service.core.database.repository import BaseRepository
from example_service.features.tags.models import Tag, reminder_tags

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class TagRepository(BaseRepository[Tag]):
    """Repository for Tag model.

    Inherits from BaseRepository:
        - get(session, id) -> Tag | None
        - get_or_raise(session, id) -> Tag
        - get_by(session, attr, value) -> Tag | None
        - list(session, limit, offset) -> Sequence[Tag]
        - search(session, statement, limit, offset) -> SearchResult[Tag]
        - create(session, instance) -> Tag
        - create_many(session, instances) -> Sequence[Tag]
        - delete(session, instance) -> None

    Feature-specific methods below.
    """

    def __init__(self) -> None:
        """Initialize with Tag model."""
        super().__init__(Tag)

    async def get_by_name(
        self,
        session: AsyncSession,
        name: str,
    ) -> Tag | None:
        """Get a tag by its name.

        Args:
            session: Database session
            name: Tag name to search for

        Returns:
            Tag if found, None otherwise
        """
        stmt = select(Tag).where(Tag.name == name)
        result = await session.execute(stmt)
        tag = result.scalar_one_or_none()

        self._lazy.debug(lambda: f"db.get_by_name({name!r}) -> {tag is not None}")
        return tag

    async def list_with_search(
        self,
        session: AsyncSession,
        *,
        search: str | None = None,
    ) -> Sequence[Tag]:
        """List all tags with optional name search.

        Args:
            session: Database session
            search: Filter tags by name (case-insensitive contains)

        Returns:
            Sequence of tags ordered by name
        """
        stmt = select(Tag)

        if search:
            stmt = stmt.where(Tag.name.ilike(f"%{search}%"))

        stmt = stmt.order_by(Tag.name.asc())

        result = await session.execute(stmt)
        items = result.scalars().all()

        self._lazy.debug(
            lambda: f"db.list_with_search(search={search!r}) -> {len(items)} items"
        )
        return items

    async def get_reminder_counts(
        self,
        session: AsyncSession,
    ) -> dict[UUID, int]:
        """Get reminder count for all tags.

        Args:
            session: Database session

        Returns:
            Dict mapping tag_id to reminder count
        """
        count_stmt = select(
            reminder_tags.c.tag_id,
            func.count(reminder_tags.c.reminder_id).label("count"),
        ).group_by(reminder_tags.c.tag_id)

        result = await session.execute(count_stmt)
        counts: dict[UUID, int] = {row.tag_id: cast("int", row.count) for row in result}

        self._lazy.debug(lambda: f"db.get_reminder_counts() -> {len(counts)} tags with counts")
        return counts

    async def get_reminder_count_for_tag(
        self,
        session: AsyncSession,
        tag_id: UUID,
    ) -> int:
        """Get reminder count for a specific tag.

        Args:
            session: Database session
            tag_id: Tag UUID

        Returns:
            Number of reminders with this tag
        """
        stmt = (
            select(func.count())
            .select_from(reminder_tags)
            .where(reminder_tags.c.tag_id == tag_id)
        )
        result = await session.execute(stmt)
        count = result.scalar() or 0

        self._lazy.debug(lambda: f"db.get_reminder_count_for_tag({tag_id}) -> {count}")
        return count

    async def get_tags_by_ids(
        self,
        session: AsyncSession,
        tag_ids: list[UUID],
    ) -> Sequence[Tag]:
        """Get multiple tags by their IDs.

        Args:
            session: Database session
            tag_ids: List of tag UUIDs to fetch

        Returns:
            Sequence of found tags (may be fewer than requested if some don't exist)
        """
        if not tag_ids:
            return []

        stmt = select(Tag).where(Tag.id.in_(tag_ids))
        result = await session.execute(stmt)
        items = result.scalars().all()

        self._lazy.debug(
            lambda: f"db.get_tags_by_ids({len(tag_ids)} ids) -> {len(items)} found"
        )
        return items


# Factory function for dependency injection
_tag_repository: TagRepository | None = None


def get_tag_repository() -> TagRepository:
    """Get TagRepository instance.

    Usage in FastAPI routes:
        from example_service.features.tags.repository import (
            TagRepository,
            get_tag_repository,
        )

        @router.get("/{tag_id}")
        async def get_tag(
            tag_id: UUID,
            session: AsyncSession = Depends(get_db_session),
            repo: TagRepository = Depends(get_tag_repository),
        ):
            return await repo.get_or_raise(session, tag_id)
    """
    global _tag_repository
    if _tag_repository is None:
        _tag_repository = TagRepository()
    return _tag_repository
