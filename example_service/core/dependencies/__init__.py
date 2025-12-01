"""FastAPI dependencies for route handlers.

This module re-exports commonly used dependencies for cleaner imports.

Usage:
    from example_service.core.dependencies import (
        get_db_session,
        get_event_publisher,
        EventPublisherDep,
    )

    @router.post("/items")
    async def create_item(
        session: AsyncSession = Depends(get_db_session),
        publisher: EventPublisher = Depends(get_event_publisher),
    ):
        ...
"""

from example_service.core.dependencies.database import get_db_session
from example_service.core.dependencies.events import EventPublisherDep, get_event_publisher

__all__ = [
    "get_db_session",
    "get_event_publisher",
    "EventPublisherDep",
]
