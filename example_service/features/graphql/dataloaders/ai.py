"""DataLoader for batch-loading AI jobs.

Prevents N+1 queries when resolving AI job references by batching
multiple ID lookups into a single database query.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from strawberry.dataloader import DataLoader

from example_service.features.ai.models import AIJob

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class AIJobDataLoader:
    """DataLoader for batch-loading AI jobs by ID.

    Prevents N+1 queries when resolving AI job references.
    Each request gets its own loader instance for proper caching.

    Usage:
        loader = AIJobDataLoader(session)
        job = await loader.load(uuid)  # Batched with other loads
        jobs = await loader.load_many([uuid1, uuid2, uuid3])
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with a database session.

        Args:
            session: AsyncSession scoped to the current request
        """
        self._session = session
        self._loader: DataLoader[UUID, AIJob | None] = DataLoader(
            load_fn=self._batch_load_ai_jobs
        )

    async def _batch_load_ai_jobs(
        self,
        ids: list[UUID],
    ) -> list[AIJob | None]:
        """Batch load AI jobs by IDs.

        This function is called by the DataLoader with batched keys.
        Returns results in the same order as input IDs.
        Missing IDs return None.

        Args:
            ids: List of AI job UUIDs to load

        Returns:
            List of AIJob objects (or None) in same order as ids
        """
        if not ids:
            return []

        # Single query for all IDs
        stmt = select(AIJob).where(AIJob.id.in_(ids))
        result = await self._session.execute(stmt)
        jobs = {job.id: job for job in result.scalars().all()}

        # Return in same order as requested, None for missing
        return [jobs.get(id_) for id_ in ids]

    async def load(self, id_: UUID) -> AIJob | None:
        """Load a single AI job by ID.

        This call will be batched with other load() calls made
        in the same event loop tick.

        Args:
            id_: AI job UUID

        Returns:
            AIJob if found, None otherwise
        """
        return await self._loader.load(id_)

    async def load_many(self, ids: list[UUID]) -> list[AIJob | None]:
        """Load multiple AI jobs by IDs.

        Args:
            ids: List of AI job UUIDs

        Returns:
            List of AIJob objects (or None) in same order as ids
        """
        return await self._loader.load_many(ids)


__all__ = ["AIJobDataLoader"]
