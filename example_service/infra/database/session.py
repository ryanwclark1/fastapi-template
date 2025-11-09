"""Database session management."""
from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from example_service.core.settings import settings
from example_service.utils.retry import retry

logger = logging.getLogger(__name__)

# Create async engine
engine = create_async_engine(
    settings.database_url if settings.database_url else "sqlite+aiosqlite:///./test.db",
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_pre_ping=True,  # Verify connections before using
    echo=settings.debug,  # Log SQL statements in debug mode
)

# Create session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Get async database session.

    Yields:
        Database session that is automatically closed.

    Example:
        ```python
        async with get_async_session() as session:
            result = await session.execute(select(User))
            users = result.scalars().all()
        ```
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


@retry(
    max_attempts=5,
    initial_delay=1.0,
    max_delay=30.0,
    exponential_base=2.0,
    jitter=True,
)
async def init_database() -> None:
    """Initialize database connection with retry logic.

    This function attempts to connect to the database with exponential
    backoff retry. This is useful during application startup when the
    database might not be immediately available (e.g., in containerized
    environments).

    Raises:
        ConnectionError: If unable to connect after all retry attempts.
    """
    logger.info("Initializing database connection with retry")

    try:
        # Test database connection
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

        logger.info(
            "Database connection established successfully",
            extra={"url": settings.database_url},
        )
    except Exception as e:
        logger.error(
            "Failed to connect to database",
            extra={"url": settings.database_url, "error": str(e)},
        )
        raise


async def close_database() -> None:
    """Close database connection and cleanup resources.

    This should be called during application shutdown.
    """
    logger.info("Closing database connection")

    try:
        await engine.dispose()
        logger.info("Database connection closed successfully")
    except Exception as e:
        logger.exception("Error closing database connection", extra={"error": str(e)})
