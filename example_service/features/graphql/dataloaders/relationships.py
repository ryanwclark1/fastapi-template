"""Relationship DataLoaders for solving N+1 queries on associations.

These loaders handle many-to-many and one-to-many relationships efficiently.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from strawberry.dataloader import DataLoader

from example_service.features.tags.models import Tag, reminder_tags

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class ReminderTagsDataLoader:
    """DataLoader for batch-loading tags by reminder ID.

    Solves N+1 problem when loading tags for multiple reminders.
    Maps reminder_id -> list of tags.

    Usage:
        loader = ReminderTagsDataLoader(session)
        tags = await loader.load(reminder_uuid)  # Returns list[Tag]
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with a database session.

        Args:
            session: AsyncSession scoped to the current request
        """
        self._session = session
        self._loader: DataLoader[UUID, list[Tag]] = DataLoader(
            load_fn=self._batch_load_tags_by_reminder,
        )

    async def _batch_load_tags_by_reminder(
        self,
        reminder_ids: list[UUID],
    ) -> list[list[Tag]]:
        """Batch load tags for multiple reminders.

        Uses the reminder_tags association table to efficiently load
        all tags for the given reminders in a single query.

        Args:
            reminder_ids: List of reminder UUIDs

        Returns:
            List of tag lists, one per reminder_id (empty list if none)
        """
        if not reminder_ids:
            return []

        # Query tags through the association table
        # This does: SELECT tags.* FROM tags
        #            JOIN reminder_tags ON tags.id = reminder_tags.tag_id
        #            WHERE reminder_tags.reminder_id IN (...)
        stmt = (
            select(Tag, reminder_tags.c.reminder_id)
            .join(reminder_tags, Tag.id == reminder_tags.c.tag_id)
            .where(reminder_tags.c.reminder_id.in_(reminder_ids))
        )
        result = await self._session.execute(stmt)
        rows = result.all()

        # Group tags by reminder_id
        tags_by_reminder: dict[UUID, list[Tag]] = {rid: [] for rid in reminder_ids}
        for tag, reminder_id in rows:
            tags_by_reminder.setdefault(reminder_id, []).append(tag)

        # Return in same order as requested
        return [tags_by_reminder.get(rid, []) for rid in reminder_ids]

    async def load(self, reminder_id: UUID) -> list[Tag]:
        """Load tags for a single reminder.

        Args:
            reminder_id: Reminder UUID

        Returns:
            List of tags for the reminder (empty list if none)
        """
        return await self._loader.load(reminder_id)

    async def load_many(self, reminder_ids: list[UUID]) -> list[list[Tag]]:
        """Load tags for multiple reminders.

        Args:
            reminder_ids: List of reminder UUIDs

        Returns:
            List of tag lists, one per reminder_id
        """
        return await self._loader.load_many(reminder_ids)


__all__ = ["ReminderTagsDataLoader"]
