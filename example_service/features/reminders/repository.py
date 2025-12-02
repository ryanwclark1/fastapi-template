"""Repository for the reminders feature."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from example_service.core.database import SearchFilter
from example_service.core.database.repository import BaseRepository, SearchResult
from example_service.features.reminders.models import Reminder

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class ReminderRepository(BaseRepository[Reminder]):
    """Repository for Reminder model.

    Inherits from BaseRepository:
        - get(session, id) -> Reminder | None
        - get_or_raise(session, id) -> Reminder
        - get_by(session, attr, value) -> Reminder | None
        - list(session, limit, offset) -> Sequence[Reminder]
        - search(session, statement, limit, offset) -> SearchResult[Reminder]
        - create(session, instance) -> Reminder
        - create_many(session, instances) -> Sequence[Reminder]
        - delete(session, instance) -> None

    Feature-specific methods below.
    """

    def __init__(self) -> None:
        """Initialize with Reminder model."""
        super().__init__(Reminder)

    async def find_pending(
        self,
        session: AsyncSession,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Reminder]:
        """Find all pending (not completed) reminders.

        Args:
            session: Database session
            limit: Maximum results
            offset: Results to skip

        Returns:
            Sequence of pending reminders, ordered by remind_at
        """
        stmt = (
            select(Reminder)
            .where(Reminder.is_completed == False)  # noqa: E712
            .order_by(
                Reminder.remind_at.asc().nullslast(),
                Reminder.created_at.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        items = result.scalars().all()

        self._lazy.debug(
            lambda: f"db.find_pending: Reminder(limit={limit}, offset={offset}) -> {len(items)} items"
        )
        return items

    async def find_overdue(
        self,
        session: AsyncSession,
        *,
        as_of: datetime | None = None,
    ) -> Sequence[Reminder]:
        """Find overdue reminders (past remind_at, not completed).

        Args:
            session: Database session
            as_of: Reference time (defaults to now)

        Returns:
            Sequence of overdue reminders
        """
        now = as_of or datetime.now(UTC)
        stmt = (
            select(Reminder)
            .where(
                Reminder.is_completed == False,  # noqa: E712
                Reminder.remind_at.is_not(None),
                Reminder.remind_at < now,
            )
            .order_by(Reminder.remind_at.asc())
        )
        result = await session.execute(stmt)
        items = result.scalars().all()

        # INFO level when overdue reminders found (actionable condition)
        if items:
            self._logger.info(
                "Found overdue reminders",
                extra={
                    "count": len(items),
                    "as_of": now.isoformat(),
                    "operation": "db.find_overdue",
                },
            )
        else:
            self._lazy.debug(lambda: f"db.find_overdue: no overdue reminders as of {now}")
        return items

    async def find_pending_notifications(
        self,
        session: AsyncSession,
        *,
        as_of: datetime | None = None,
    ) -> Sequence[Reminder]:
        """Find reminders needing notification (due, not sent, not completed).

        Args:
            session: Database session
            as_of: Reference time (defaults to now)

        Returns:
            Sequence of reminders needing notification
        """
        now = as_of or datetime.now(UTC)
        stmt = (
            select(Reminder)
            .where(
                Reminder.is_completed == False,  # noqa: E712
                Reminder.notification_sent == False,  # noqa: E712
                Reminder.remind_at.is_not(None),
                Reminder.remind_at <= now,
            )
            .order_by(Reminder.remind_at.asc())
        )
        result = await session.execute(stmt)
        items = result.scalars().all()

        self._lazy.debug(lambda: f"db.find_pending_notifications: {len(items)} pending as of {now}")
        return items

    async def search_reminders(
        self,
        session: AsyncSession,
        *,
        query: str | None = None,
        include_completed: bool = True,
        before: datetime | None = None,
        after: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> SearchResult[Reminder]:
        """Search reminders with filters.

        Args:
            session: Database session
            query: Search term (searches title and description)
            include_completed: Include completed reminders
            before: Filter reminders created before this time
            after: Filter reminders created after this time
            limit: Page size
            offset: Results to skip

        Returns:
            SearchResult with reminders and pagination info
        """
        stmt = select(Reminder)

        # Text search
        if query:
            stmt = SearchFilter(
                [Reminder.title, Reminder.description],
                query,
                case_insensitive=True,
            ).apply(stmt)

        # Status filter
        if not include_completed:
            stmt = stmt.where(Reminder.is_completed == False)  # noqa: E712

        # Date range
        if after:
            stmt = stmt.where(Reminder.created_at > after)
        if before:
            stmt = stmt.where(Reminder.created_at < before)

        # Default ordering
        stmt = stmt.order_by(
            Reminder.is_completed.asc(),
            Reminder.remind_at.asc().nullslast(),
            Reminder.created_at.desc(),
        )

        search_result = await self.search(session, stmt, limit=limit, offset=offset)

        # DEBUG level - search context (useful for debugging search issues)
        self._lazy.debug(
            lambda: f"db.search_reminders: query={query!r}, include_completed={include_completed}, "
            f"before={before}, after={after} -> {len(search_result.items)}/{search_result.total}"
        )
        return search_result

    async def mark_completed(
        self,
        session: AsyncSession,
        reminder_id: UUID,
    ) -> Reminder | None:
        """Mark a reminder as completed.

        Args:
            session: Database session
            reminder_id: Reminder UUID

        Returns:
            Updated reminder or None if not found
        """
        reminder = await self.get(session, reminder_id)
        if reminder is None:
            self._lazy.debug(lambda: f"db.mark_completed({reminder_id}) -> not found")
            return None

        reminder.is_completed = True
        await session.flush()
        await session.refresh(reminder)

        self._lazy.debug(lambda: f"db.mark_completed({reminder_id}) -> success")
        return reminder

    async def list_all(
        self,
        session: AsyncSession,
        *,
        include_completed: bool = True,
    ) -> Sequence[Reminder]:
        """List all reminders with smart ordering.

        Args:
            session: Database session
            include_completed: Whether to include completed reminders

        Returns:
            Sequence of reminders ordered by: pending first, by date, newest created
        """
        stmt = select(Reminder)

        if not include_completed:
            stmt = stmt.where(Reminder.is_completed == False)  # noqa: E712

        # Smart ordering: pending first, by date, newest created first
        stmt = stmt.order_by(
            Reminder.is_completed.asc(),  # Pending reminders first
            Reminder.remind_at.asc().nullslast(),  # Soonest dates first
            Reminder.created_at.desc(),  # Newest first
        )

        result = await session.execute(stmt)
        items = result.scalars().all()

        self._lazy.debug(
            lambda: f"db.list_all: include_completed={include_completed} -> {len(items)} items"
        )
        return items

    async def find_broken_out_occurrences(
        self,
        session: AsyncSession,
        parent_id: UUID,
    ) -> dict[datetime, Reminder]:
        """Find all broken-out occurrences for a recurring reminder.

        Args:
            session: Database session
            parent_id: ID of the parent recurring reminder

        Returns:
            Dict mapping occurrence_date to the broken-out reminder
        """
        stmt = (
            select(Reminder)
            .where(Reminder.parent_id == parent_id)
            .where(Reminder.occurrence_date.is_not(None))
        )
        result = await session.execute(stmt)
        items = result.scalars().all()

        self._lazy.debug(
            lambda: f"db.find_broken_out_occurrences({parent_id}) -> {len(items)} items"
        )
        # Filter ensures occurrence_date is not None (query already filters, but type checker needs help)
        return {r.occurrence_date: r for r in items if r.occurrence_date is not None}

    async def find_occurrence_by_date(
        self,
        session: AsyncSession,
        parent_id: UUID,
        occurrence_date: datetime,
    ) -> Reminder | None:
        """Find a broken-out occurrence by parent ID and date.

        Args:
            session: Database session
            parent_id: ID of the parent recurring reminder
            occurrence_date: The specific occurrence date

        Returns:
            The broken-out reminder or None if not found
        """
        stmt = (
            select(Reminder)
            .where(Reminder.parent_id == parent_id)
            .where(Reminder.occurrence_date == occurrence_date)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def mark_notification_sent(
        self,
        session: AsyncSession,
        reminder_id: UUID,
    ) -> Reminder | None:
        """Mark notification as sent for a reminder.

        Args:
            session: Database session
            reminder_id: Reminder UUID

        Returns:
            Updated reminder or None if not found
        """
        reminder = await self.get(session, reminder_id)
        if reminder is None:
            self._lazy.debug(lambda: f"db.mark_notification_sent({reminder_id}) -> not found")
            return None

        reminder.notification_sent = True
        await session.flush()
        await session.refresh(reminder)

        self._lazy.debug(lambda: f"db.mark_notification_sent({reminder_id}) -> success")
        return reminder


# Factory function for dependency injection
_reminder_repository: ReminderRepository | None = None


def get_reminder_repository() -> ReminderRepository:
    """Get ReminderRepository instance.

    Usage in FastAPI routes:
            from example_service.features.reminders.repository import (
            ReminderRepository,
            get_reminder_repository,
        )

        @router.get("/{reminder_id}")
        async def get_reminder(
            reminder_id: UUID,
            session: AsyncSession = Depends(get_db_session),
            repo: ReminderRepository = Depends(get_reminder_repository),
        ):
            return await repo.get_or_raise(session, reminder_id)
    """
    global _reminder_repository
    if _reminder_repository is None:
        _reminder_repository = ReminderRepository()
    return _reminder_repository
