"""Event publisher service for reliable event delivery.

The EventPublisher uses the transactional outbox pattern to ensure
events are reliably published even in the face of failures:

1. Events are written to the outbox table in the same transaction
   as the domain changes
2. A background processor reads from the outbox and publishes to
   the message broker
3. Successfully published events are marked as processed

This guarantees at-least-once delivery semantics.

Usage:
    from example_service.core.events import EventPublisher, DomainEvent

    async def create_user(session: AsyncSession, data: UserCreate) -> User:
        # Create the domain entity
        user = User(**data.model_dump())
        session.add(user)

        # Publish event in same transaction
        publisher = EventPublisher(session)
        await publisher.publish(
            UserCreatedEvent(user_id=str(user.id), email=user.email)
        )

        # Both user and event are committed together
        await session.commit()
        return user
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from example_service.core.events.base import DomainEvent

logger = logging.getLogger(__name__)


class EventPublisher:
    """Publisher for domain events using the outbox pattern.

    Events are staged in the outbox table rather than published directly.
    This ensures transactional consistency - if the database transaction
    rolls back, the event is also rolled back.

    The background outbox processor is responsible for actually publishing
    events to the message broker.

    Attributes:
        session: Database session for outbox writes
        correlation_id: Optional correlation ID to attach to all events
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        correlation_id: str | None = None,
    ) -> None:
        """Initialize the event publisher.

        Args:
            session: Database session (events are written in same transaction)
            correlation_id: Optional correlation ID for distributed tracing
        """
        self._session = session
        self._correlation_id = correlation_id
        self._pending_count = 0

    async def publish(
        self,
        event: DomainEvent,
        *,
        correlation_id: str | None = None,
    ) -> None:
        """Stage an event for publishing via the outbox.

        The event is written to the outbox table in the current transaction.
        It will be published to the message broker by the background processor
        after the transaction commits.

        Args:
            event: The domain event to publish
            correlation_id: Override correlation ID for this event

        Note:
            The event is only persisted when the session is committed.
            If the transaction rolls back, the event is discarded.

        Example:
            async with session.begin():
                user = User(email="user@example.com")
                session.add(user)

                publisher = EventPublisher(session)
                await publisher.publish(
                    UserCreatedEvent(user_id=str(user.id), email=user.email)
                )
            # Event and user are committed together
        """
        # Apply correlation ID if not already set
        effective_correlation_id = correlation_id or self._correlation_id
        if effective_correlation_id and not event.correlation_id:
            event = event.with_correlation(effective_correlation_id)

        # Import here to avoid circular imports
        from example_service.infra.events.outbox.models import EventOutbox

        # Create outbox entry
        outbox_entry = EventOutbox(
            event_type=event.event_type,
            event_version=event.event_version,
            payload=json.dumps(event.model_dump(mode="json")),
            correlation_id=event.correlation_id,
            aggregate_type=event.metadata.get("aggregate_type"),
            aggregate_id=event.metadata.get("aggregate_id"),
        )

        self._session.add(outbox_entry)
        self._pending_count += 1

        logger.debug(
            "Event staged in outbox",
            extra={
                "event_type": event.event_type,
                "event_id": event.event_id,
                "correlation_id": event.correlation_id,
            },
        )

    async def publish_many(
        self,
        events: list[DomainEvent],
        *,
        correlation_id: str | None = None,
    ) -> None:
        """Stage multiple events for publishing.

        All events are written to the outbox in the current transaction.
        Useful for publishing related events together.

        Args:
            events: List of domain events to publish
            correlation_id: Optional correlation ID for all events
        """
        if not events:
            return

        from example_service.infra.events.outbox.models import EventOutbox

        entries: list[EventOutbox] = []
        for event in events:
            effective_correlation = correlation_id or self._correlation_id
            if effective_correlation and not event.correlation_id:
                correlated_event = event.with_correlation(effective_correlation)
            else:
                correlated_event = event

            entries.append(
                EventOutbox(
                    event_type=correlated_event.event_type,
                    event_version=correlated_event.event_version,
                    payload=json.dumps(correlated_event.model_dump(mode="json")),
                    correlation_id=correlated_event.correlation_id,
                    aggregate_type=correlated_event.metadata.get("aggregate_type"),
                    aggregate_id=correlated_event.metadata.get("aggregate_id"),
                ),
            )

        add_all = getattr(self._session, "add_all", None)
        if callable(add_all):
            add_all(entries)
        else:
            for entry in entries:
                self._session.add(entry)

        self._pending_count += len(entries)

        logger.debug(
            "Batch of events staged in outbox",
            extra={"count": len(entries), "event_types": [e.event_type for e in events]},
        )

    @property
    def pending_count(self) -> int:
        """Number of events staged but not yet committed."""
        return self._pending_count


def get_event_publisher(
    session: AsyncSession,
    correlation_id: str | None = None,
) -> EventPublisher:
    """Factory function to create an EventPublisher.

    This can be used as a FastAPI dependency:

        @router.post("/users")
        async def create_user(
            session: AsyncSession = Depends(get_db_session),
            correlation_id: str = Depends(get_correlation_id),
        ):
            publisher = get_event_publisher(session, correlation_id)
            ...

    Args:
        session: Database session
        correlation_id: Optional correlation ID

    Returns:
        Configured EventPublisher instance
    """
    return EventPublisher(session, correlation_id=correlation_id)


__all__ = ["EventPublisher", "get_event_publisher"]
