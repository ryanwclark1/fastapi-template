"""Event publishing dependencies for FastAPI route handlers.

This module provides FastAPI-compatible dependencies for publishing domain events
using the transactional outbox pattern.

Usage:
    from example_service.core.dependencies.events import get_event_publisher
    from example_service.core.dependencies.database import get_db_session

    @router.post("/items")
    async def create_item(
        data: ItemCreate,
        session: AsyncSession = Depends(get_db_session),
        publisher: EventPublisher = Depends(get_event_publisher),
    ):
        item = Item(**data.model_dump())
        session.add(item)

        await publisher.publish(ItemCreatedEvent(item_id=str(item.id)))
        await session.commit()

        return item

The event publisher stages events in the outbox table within the same
transaction as domain changes. Events are only published after commit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Request

from example_service.core.dependencies.database import get_db_session
from example_service.core.events import EventPublisher

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _get_correlation_id(request: Request) -> str | None:
    """Extract correlation ID from request state.

    The correlation ID is set by the CorrelationIDMiddleware.
    """
    return getattr(request.state, "correlation_id", None)


async def get_event_publisher(
    session: Annotated[AsyncSession,Depends(get_db_session)],
    request: Request | None = None,  # FastAPI will inject this automatically
) -> EventPublisher:
    """FastAPI dependency for event publisher.

    Creates an EventPublisher bound to the current database session and
    automatically injects the correlation ID from the request.

    The publisher uses the transactional outbox pattern - events are staged
    in the outbox table and only published after the transaction commits.

    Args:
        session: Database session from dependency injection
        request: FastAPI request for correlation ID extraction

    Returns:
        EventPublisher instance ready for publishing events

    Example:
        @router.post("/users")
        async def create_user(
            data: UserCreate,
            session: AsyncSession = Depends(get_db_session),
            publisher: EventPublisher = Depends(get_event_publisher),
        ):
            user = User(**data.model_dump())
            session.add(user)

            await publisher.publish(
                UserCreatedEvent(user_id=str(user.id), email=user.email)
            )

            # Both user and event are committed together
            await session.commit()
            return user
    """
    from example_service.core.events import EventPublisher

    correlation_id = _get_correlation_id(request) if request else None
    return EventPublisher(session, correlation_id=correlation_id)


# Type alias for cleaner dependency injection
EventPublisherDep = Annotated[EventPublisher, Depends(get_event_publisher)]


__all__ = [
    "EventPublisherDep",
    "get_event_publisher",
]
