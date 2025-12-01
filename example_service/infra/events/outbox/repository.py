"""Repository for EventOutbox CRUD operations.

Provides methods for:
- Fetching pending events for processing
- Marking events as processed or failed
- Cleaning up old processed events
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import delete, select, update

from example_service.core.database.repository import BaseRepository
from example_service.infra.events.outbox.models import EventOutbox

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession


class OutboxRepository(BaseRepository[EventOutbox]):
    """Repository for outbox event operations.

    Provides specialized methods for the outbox processor beyond
    basic CRUD from BaseRepository.
    """

    def __init__(self) -> None:
        """Initialize repository with EventOutbox model."""
        super().__init__(EventOutbox)

    async def fetch_pending(
        self,
        session: AsyncSession,
        *,
        batch_size: int = 100,
        max_retries: int = 5,
    ) -> Sequence[EventOutbox]:
        """Fetch pending events ready for processing.

        Returns events that:
        - Have not been processed (processed_at is NULL)
        - Are not scheduled for future retry (next_retry_at <= now or NULL)
        - Have not exceeded max retry attempts

        Events are returned in FIFO order (oldest first) based on UUID v7.

        Args:
            session: Database session
            batch_size: Maximum number of events to fetch
            max_retries: Skip events with more retries than this

        Returns:
            Sequence of pending EventOutbox records
        """
        now = datetime.now(UTC)

        stmt = (
            select(EventOutbox)
            .where(
                EventOutbox.processed_at.is_(None),
                EventOutbox.retry_count < max_retries,
            )
            .where((EventOutbox.next_retry_at.is_(None)) | (EventOutbox.next_retry_at <= now))
            .order_by(EventOutbox.created_at.asc())
            .limit(batch_size)
            # Use FOR UPDATE SKIP LOCKED for concurrent processors
            .with_for_update(skip_locked=True)
        )

        result = await session.execute(stmt)
        return result.scalars().all()

    async def mark_processed(
        self,
        session: AsyncSession,
        event_id: str,
    ) -> None:
        """Mark an event as successfully processed.

        Args:
            session: Database session
            event_id: ID of the event to mark
        """
        stmt = (
            update(EventOutbox)
            .where(EventOutbox.id == event_id)
            .values(
                processed_at=datetime.now(UTC),
                error_message=None,
            )
        )
        await session.execute(stmt)

    async def mark_failed(
        self,
        session: AsyncSession,
        event_id: str,
        error_message: str,
        *,
        retry_delay_seconds: int = 60,
    ) -> None:
        """Mark an event as failed and schedule retry.

        Uses exponential backoff based on retry count:
        - 1st retry: 1 minute
        - 2nd retry: 2 minutes
        - 3rd retry: 4 minutes
        - etc.

        Args:
            session: Database session
            event_id: ID of the event that failed
            error_message: Description of the failure
            retry_delay_seconds: Base delay for exponential backoff
        """
        # Fetch current retry count for backoff calculation
        event = await self.get(session, event_id)
        if event is None:
            return

        retry_count = event.retry_count + 1
        backoff_multiplier = 2 ** (retry_count - 1)  # 1, 2, 4, 8, ...
        delay = timedelta(seconds=retry_delay_seconds * backoff_multiplier)
        next_retry = datetime.now(UTC) + delay

        stmt = (
            update(EventOutbox)
            .where(EventOutbox.id == event_id)
            .values(
                retry_count=retry_count,
                error_message=error_message[:1000],  # Truncate long errors
                next_retry_at=next_retry,
            )
        )
        await session.execute(stmt)

    async def cleanup_processed(
        self,
        session: AsyncSession,
        *,
        older_than_days: int = 7,
    ) -> int:
        """Delete processed events older than specified days.

        This is a maintenance operation to prevent the outbox table
        from growing indefinitely.

        Args:
            session: Database session
            older_than_days: Delete events processed more than this many days ago

        Returns:
            Number of events deleted
        """
        cutoff = datetime.now(UTC) - timedelta(days=older_than_days)

        stmt = (
            delete(EventOutbox)
            .where(
                EventOutbox.processed_at.is_not(None),
                EventOutbox.processed_at < cutoff,
            )
            .returning(EventOutbox.id)
        )

        result = await session.execute(stmt)
        deleted_ids = result.scalars().all()
        return len(deleted_ids)

    async def count_pending(self, session: AsyncSession) -> int:
        """Count events waiting to be processed.

        Useful for monitoring and alerting.

        Args:
            session: Database session

        Returns:
            Number of unprocessed events
        """
        from sqlalchemy import func

        stmt = (
            select(func.count()).select_from(EventOutbox).where(EventOutbox.processed_at.is_(None))
        )
        result = await session.execute(stmt)
        return result.scalar_one()

    async def count_failed(
        self,
        session: AsyncSession,
        *,
        max_retries: int = 5,
    ) -> int:
        """Count events that have exceeded max retries.

        These are "dead letter" events that need manual intervention.

        Args:
            session: Database session
            max_retries: Retry threshold

        Returns:
            Number of events exceeding max retries
        """
        from sqlalchemy import func

        stmt = (
            select(func.count())
            .select_from(EventOutbox)
            .where(
                EventOutbox.processed_at.is_(None),
                EventOutbox.retry_count >= max_retries,
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one()


__all__ = ["OutboxRepository"]
