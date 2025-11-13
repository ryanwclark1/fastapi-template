"""Database session management."""
from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from example_service.core.settings import get_app_settings, get_db_settings
from example_service.utils.retry import retry

logger = logging.getLogger(__name__)

# Load settings
db_settings = get_db_settings()
app_settings = get_app_settings()

# Create async engine with psycopg driver
engine = create_async_engine(
    str(db_settings.database_url) if db_settings.database_url else "sqlite+aiosqlite:///./test.db",
    pool_size=db_settings.pool_size,
    max_overflow=db_settings.max_overflow,
    pool_timeout=db_settings.pool_timeout,
    pool_recycle=db_settings.pool_recycle,
    pool_pre_ping=db_settings.pool_pre_ping,
    echo=db_settings.echo_sql or app_settings.debug,
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
    """Initialize database connection with tenacity-like exponential backoff retry.

    Uses custom @retry decorator that provides:
    - **Max attempts**: 5 retry attempts before failure
    - **Exponential backoff**: delays of 1s, 2s, 4s, 8s, 16s (capped at 30s)
    - **Jitter**: Random 50-150% multiplier to prevent thundering herd
    - **Automatic logging**: Logs each retry attempt with details

    This is essential during application startup when the database might not be
    immediately available (e.g., in containerized/Kubernetes environments where
    the database pod may start after the application pod).

    The retry logic ensures:
    1. Database is available before accepting HTTP requests
    2. Transient network issues don't cause startup failures
    3. Graceful handling of database startup delays

    Raises:
        RetryError: If unable to connect after all 5 retry attempts.
                   Contains the last exception and attempt count.
    """
    logger.info("Initializing database connection with retry")

    try:
        # Test database connection
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

        logger.info(
            "Database connection established successfully",
            extra={"url": str(db_settings.database_url) if db_settings.database_url else "sqlite"},
        )
    except Exception as e:
        logger.error(
            "Failed to connect to database",
            extra={"url": str(db_settings.database_url) if db_settings.database_url else "sqlite", "error": str(e)},
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
