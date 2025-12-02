"""DataLoader for batch-loading tags.

Prevents N+1 queries when resolving tag references by batching
multiple ID lookups into a single database query.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from strawberry.dataloader import DataLoader

from example_service.features.tags.models import Tag

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class TagDataLoader:
    """DataLoader for batch-loading tags by ID.

    Prevents N+1 queries when resolving tag references.
    Each request gets its own loader instance for proper caching.

    Usage:
        loader = TagDataLoader(session)
        tag = await loader.load(uuid)  # Batched with other loads
        tags = await loader.load_many([uuid1, uuid2, uuid3])
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with a database session.

        Args:
            session: AsyncSession scoped to the current request
        """
        self._session = session
        self._loader: DataLoader[UUID, Tag | None] = DataLoader(load_fn=self._batch_load_tags)

    async def _batch_load_tags(
        self,
        ids: list[UUID],
    ) -> list[Tag | None]:
        """Batch load tags by IDs.

        This function is called by the DataLoader with batched keys.
        Returns results in the same order as input IDs.
        Missing IDs return None.

        Args:
            ids: List of tag UUIDs to load

        Returns:
            List of Tag objects (or None) in same order as ids
        """
        if not ids:
            return []

        # Single query for all IDs
        stmt = select(Tag).where(Tag.id.in_(ids))
        result = await self._session.execute(stmt)
        tags = {t.id: t for t in result.scalars().all()}

        # Return in same order as requested, None for missing
        return [tags.get(id_) for id_ in ids]

    async def load(self, id_: UUID) -> Tag | None:
        """Load a single tag by ID.

        This call will be batched with other load() calls made
        in the same event loop tick.

        Args:
            id_: Tag UUID

        Returns:
            Tag if found, None otherwise
        """
        return await self._loader.load(id_)

    async def load_many(self, ids: list[UUID]) -> list[Tag | None]:
        """Load multiple tags by IDs.

        Args:
            ids: List of tag UUIDs

        Returns:
            List of Tag objects (or None) in same order as ids
        """
        return await self._loader.load_many(ids)


__all__ = ["TagDataLoader"]
