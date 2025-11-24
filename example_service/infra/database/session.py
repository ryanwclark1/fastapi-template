"""Database session management with psycopg3 async driver."""
from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from example_service.core.settings import get_app_settings, get_db_settings
from example_service.utils.retry import retry

logger = logging.getLogger(__name__)

# Get settings from modular configuration
db_settings = get_db_settings()
app_settings = get_app_settings()

# Create async engine with psycopg3
engine = create_async_engine(
    db_settings.get_sqlalchemy_url() if db_settings.is_configured else "sqlite+aiosqlite:///./test.db",
    pool_size=db_settings.pool_size,
    max_overflow=db_settings.max_overflow,
    pool_timeout=db_settings.pool_timeout,
    pool_recycle=db_settings.pool_recycle,
    pool_pre_ping=db_settings.pool_pre_ping,
    echo=db_settings.echo_sql or app_settings.debug,
    # psycopg3 specific connection arguments
    connect_args={
        "server_settings": {
            "application_name": app_settings.service_name,
        },
    } if db_settings.is_configured else {},
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

        db_url = db_settings.get_sqlalchemy_url() if db_settings.is_configured else "sqlite+aiosqlite:///./test.db"
        logger.info(
            "Database connection established successfully",
            extra={"url": db_url, "driver": "psycopg3"},
        )
    except Exception as e:
        db_url = db_settings.get_sqlalchemy_url() if db_settings.is_configured else "sqlite+aiosqlite:///./test.db"
        logger.error(
            "Failed to connect to database",
            extra={"url": db_url, "error": str(e)},
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
