"""Database dependencies for FastAPI."""
from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from example_service.infra.database import get_async_session

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def get_db() -> AsyncGenerator["AsyncSession", None]:
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
    async with get_async_session() as session:
        yield session
