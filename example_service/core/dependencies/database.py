"""Database dependencies for FastAPI."""
from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for database session.

    Yields:
        Database session that is automatically closed after request.

    Example:
        ```python
        @router.get("/items")
        async def list_items(session: AsyncSession = Depends(get_db)):
            ...
        ```
    """
    # TODO: Import session factory from infra.database.session
    # from example_service.infra.database.session import get_async_session
    #
    # async with get_async_session() as session:
    #     yield session

    # Placeholder implementation
    raise NotImplementedError("Database session not configured")
