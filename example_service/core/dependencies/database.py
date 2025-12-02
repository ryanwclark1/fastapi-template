"""Database dependencies for FastAPI route handlers.

This module provides FastAPI-compatible dependencies that wrap infrastructure-level
session management. It bridges the gap between the infrastructure layer and the
presentation layer.

Two-Tier Session Pattern:
-------------------------
This project uses two session getters for different use cases:

1. `get_db_session()` (this module) - FastAPI Dependency
   - Use in route handlers with `Depends(get_db_session)`
   - Session lifecycle tied to HTTP request
   - Automatically closed when request completes

2. `get_async_session()` (infra.database) - General Context Manager
   - Use in CLI commands, background tasks, and scripts
   - Framework-agnostic async context manager
   - Manually managed session lifecycle

Usage Examples:
---------------
FastAPI route handler:
    from example_service.core.dependencies.database import get_db_session

    @router.get("/items")
    async def list_items(session: AsyncSession = Depends(get_db_session)):
        result = await session.execute(select(Item))
        return result.scalars().all()

Background task (non-FastAPI):
    from example_service.infra.database import get_async_session

    async def process_batch():
        async with get_async_session() as session:
            # Use session directly
            ...

Why two getters?
----------------
- Separation of concerns: FastAPI-specific vs. framework-agnostic code
- The dependency version integrates with FastAPI's dependency injection
- The context manager version works anywhere async code runs
- Both ultimately use the same underlying session factory
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from example_service.infra.database import get_async_session


async def get_db_session() -> AsyncGenerator[AsyncSession]:
    """FastAPI dependency for database session.

    Yields:
        Database session that is automatically closed after request.

    Example:
        @router.get("/items")
        async def list_items(session: AsyncSession = Depends(get_db_session)):
            ...
    """
    async with get_async_session() as session:
        yield session
