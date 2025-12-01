"""DataLoader for batch-loading reminders.

Prevents N+1 queries when resolving reminder references by batching
multiple ID lookups into a single database query.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from strawberry.dataloader import DataLoader

from example_service.features.reminders.models import Reminder

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class ReminderDataLoader:
    """DataLoader for batch-loading reminders by ID.

    Prevents N+1 queries when resolving reminder references.
    Each request gets its own loader instance for proper caching.

    Usage:
        loader = ReminderDataLoader(session)
        reminder = await loader.load(uuid)  # Batched with other loads
        reminders = await loader.load_many([uuid1, uuid2, uuid3])
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with a database session.

        Args:
            session: AsyncSession scoped to the current request
        """
        self._session = session
        self._loader: DataLoader[UUID, Reminder | None] = DataLoader(
            load_fn=self._batch_load_reminders
        )

    async def _batch_load_reminders(
        self,
        ids: list[UUID],
    ) -> list[Reminder | None]:
        """Batch load reminders by IDs.

        This function is called by the DataLoader with batched keys.
        Returns results in the same order as input IDs.
        Missing IDs return None.

        Args:
            ids: List of reminder UUIDs to load

        Returns:
            List of Reminder objects (or None) in same order as ids
        """
        if not ids:
            return []

        # Single query for all IDs
        stmt = select(Reminder).where(Reminder.id.in_(ids))
        result = await self._session.execute(stmt)
        reminders = {r.id: r for r in result.scalars().all()}

        # Return in same order as requested, None for missing
        return [reminders.get(id_) for id_ in ids]

    async def load(self, id_: UUID) -> Reminder | None:
        """Load a single reminder by ID.

        This call will be batched with other load() calls made
        in the same event loop tick.

        Args:
            id_: Reminder UUID

        Returns:
            Reminder if found, None otherwise
        """
        return await self._loader.load(id_)

    async def load_many(self, ids: list[UUID]) -> list[Reminder | None]:
        """Load multiple reminders by IDs.

        Args:
            ids: List of reminder UUIDs

        Returns:
            List of Reminder objects (or None) in same order as ids
        """
        return await self._loader.load_many(ids)


__all__ = ["ReminderDataLoader"]
