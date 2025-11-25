"""Reminder repository with custom query methods.

Demonstrates feature-specific repository extending BaseRepository.
Kept in features/ rather than core/repositories/ since reminders
is a feature, not a core domain entity.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

from example_service.core.database import BaseRepository, SearchResult
from example_service.features.reminders.models import Reminder

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession


class ReminderRepository(BaseRepository[Reminder]):
    """Reminder-specific repository with custom query methods.

    Extends BaseRepository to add domain-specific queries for reminders
    like filtering by completion status, finding overdue reminders, etc.

    Inherits all standard CRUD operations:
    - get(id) / get_by_id(id)
    - create(reminder)
    - update(reminder)
    - delete(reminder)
    - search(filters, limit, offset)
    - list_all()

    Example:
        ```python
        # Using inherited methods
        reminder = await reminder_repo.get_by_id(uuid_value)
        reminder.is_completed = True
        await reminder_repo.update(reminder)

        # Using custom methods
        pending = await reminder_repo.find_pending()
        overdue = await reminder_repo.find_overdue()
        ```
    """

    def __init__(self, session: AsyncSession):
        """Initialize reminder repository.

        Args:
            session: Async database session
        """
        super().__init__(Reminder, session)

    # ========================================================================
    # Custom Query Methods
    # ========================================================================

    async def find_pending(self) -> Sequence[Reminder]:
        """Get all pending (not completed) reminders.

        Returns:
            List of pending reminders ordered by remind_at (soonest first)

        Example:
            ```python
            pending = await repo.find_pending()
            print(f"You have {len(pending)} pending reminders")
            ```
        """
        stmt = (
            select(Reminder)
            .where(Reminder.is_completed == False)  # noqa: E712
            .order_by(Reminder.remind_at.asc().nullslast())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def find_completed(self) -> Sequence[Reminder]:
        """Get all completed reminders.

        Returns:
            List of completed reminders ordered by completion date (most recent first)

        Example:
            ```python
            completed = await repo.find_completed()
            ```
        """
        stmt = (
            select(Reminder)
            .where(Reminder.is_completed == True)  # noqa: E712
            .order_by(Reminder.updated_at.desc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def find_overdue(self) -> Sequence[Reminder]:
        """Get all overdue reminders that haven't been completed.

        A reminder is overdue if:
        - It has a remind_at date
        - remind_at is in the past
        - It's not completed

        Returns:
            List of overdue reminders

        Example:
            ```python
            overdue = await repo.find_overdue()
            for reminder in overdue:
                print(f"Overdue: {reminder.title}")
            ```
        """
        now = datetime.utcnow()
        stmt = (
            select(Reminder)
            .where(
                Reminder.is_completed == False,  # noqa: E712
                Reminder.remind_at.is_not(None),
                Reminder.remind_at < now,
            )
            .order_by(Reminder.remind_at.asc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def find_upcoming(self, hours: int = 24) -> Sequence[Reminder]:
        """Get reminders due within the next N hours.

        Args:
            hours: Number of hours to look ahead (default: 24)

        Returns:
            List of upcoming reminders

        Example:
            ```python
            # Get reminders due in next 24 hours
            upcoming = await repo.find_upcoming()

            # Get reminders due in next 4 hours
            soon = await repo.find_upcoming(hours=4)
            ```
        """
        from datetime import timedelta

        now = datetime.utcnow()
        future = now + timedelta(hours=hours)

        stmt = (
            select(Reminder)
            .where(
                Reminder.is_completed == False,  # noqa: E712
                Reminder.remind_at.is_not(None),
                Reminder.remind_at >= now,
                Reminder.remind_at <= future,
            )
            .order_by(Reminder.remind_at.asc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def find_unsent_notifications(self) -> Sequence[Reminder]:
        """Get reminders that need notifications sent.

        Finds reminders where:
        - remind_at has passed
        - notification_sent is False
        - not completed

        Returns:
            List of reminders needing notifications

        Example:
            ```python
            reminders = await repo.find_unsent_notifications()
            for reminder in reminders:
                await send_notification(reminder)
                reminder.notification_sent = True
                await repo.update(reminder)
            ```
        """
        now = datetime.utcnow()
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
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def search_by_title(
        self,
        search_term: str,
        *,
        include_completed: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> SearchResult[Reminder]:
        """Search reminders by title (case-insensitive partial match).

        Args:
            search_term: Search term to match against title
            include_completed: Whether to include completed reminders
            limit: Maximum results per page
            offset: Number of results to skip

        Returns:
            SearchResult with matching reminders

        Example:
            ```python
            # Search pending reminders only
            result = await repo.search_by_title("meeting", limit=10)

            # Search all reminders
            result = await repo.search_by_title(
                "meeting",
                include_completed=True,
                limit=10
            )

            for reminder in result.items:
                print(reminder.title)
            ```
        """
        ilike_term = f"%{search_term}%"
        stmt = select(Reminder).where(Reminder.title.ilike(ilike_term))

        if not include_completed:
            stmt = stmt.where(Reminder.is_completed == False)  # noqa: E712

        return await self.search(
            filters=stmt,
            limit=limit,
            offset=offset,
            order_by=[Reminder.created_at.desc()],
        )

    async def list_all_ordered(
        self,
        *,
        include_completed: bool = True,
    ) -> Sequence[Reminder]:
        """List all reminders with smart ordering.

        Orders by:
        1. Completion status (pending first)
        2. remind_at date (soonest first, nulls last)
        3. created_at (newest first)

        Args:
            include_completed: Whether to include completed reminders

        Returns:
            Ordered list of reminders

        Example:
            ```python
            # All reminders
            all_reminders = await repo.list_all_ordered()

            # Only pending
            pending = await repo.list_all_ordered(include_completed=False)
            ```
        """
        stmt = select(Reminder)

        if not include_completed:
            stmt = stmt.where(Reminder.is_completed == False)  # noqa: E712

        stmt = stmt.order_by(
            Reminder.is_completed.asc(),  # Pending first
            Reminder.remind_at.asc().nullslast(),  # Soonest dates first
            Reminder.created_at.desc(),  # Newest first
        )

        result = await self._session.execute(stmt)
        return result.scalars().all()

    # ========================================================================
    # Business Logic Helpers
    # ========================================================================

    async def mark_completed(self, reminder_id: UUID) -> Reminder:
        """Mark a reminder as completed.

        Convenience method that combines get + update.

        Args:
            reminder_id: Reminder UUID

        Returns:
            Updated reminder

        Raises:
            NotFoundError: If reminder doesn't exist

        Example:
            ```python
            reminder = await repo.mark_completed(reminder_id)
            print(f"Marked '{reminder.title}' as completed")
            ```
        """
        reminder = await self.get_by_id(reminder_id)
        reminder.is_completed = True
        return await self.update(reminder)

    async def mark_notification_sent(self, reminder_id: UUID) -> Reminder:
        """Mark notification as sent for a reminder.

        Args:
            reminder_id: Reminder UUID

        Returns:
            Updated reminder

        Raises:
            NotFoundError: If reminder doesn't exist

        Example:
            ```python
            reminder = await repo.mark_notification_sent(reminder_id)
            ```
        """
        reminder = await self.get_by_id(reminder_id)
        reminder.notification_sent = True
        return await self.update(reminder)

    async def count_pending(self) -> int:
        """Count pending reminders.

        Returns:
            Number of pending reminders

        Example:
            ```python
            count = await repo.count_pending()
            print(f"You have {count} pending reminders")
            ```
        """
        from sqlalchemy import func

        stmt = select(func.count()).select_from(Reminder).where(Reminder.is_completed == False)  # noqa: E712
        result = await self._session.execute(stmt)
        return result.scalar_one()
