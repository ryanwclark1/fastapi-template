"""Database session management."""
from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from example_service.core.settings import get_app_settings, get_db_settings
from example_service.utils.retry import retry

logger = logging.getLogger(__name__)

# Global engine instance (created lazily)
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Get or create database engine.
    
    Returns:
        SQLAlchemy async engine.
    """
    global _engine
    
    if _engine is None:
        db_settings = get_db_settings()
        app_settings = get_app_settings()
        
        # Use configured database or fallback to SQLite for testing
        db_url = "sqlite+aiosqlite:///./test.db"
        if db_settings.is_configured:
            db_url = db_settings.get_sqlalchemy_url()
        
        _engine = create_async_engine(
            db_url,
            pool_size=db_settings.pool_size,
            max_overflow=db_settings.max_overflow,
            pool_pre_ping=db_settings.pool_pre_ping,
            pool_recycle=db_settings.pool_recycle,
            echo=db_settings.echo_sql or app_settings.debug,
        )
        logger.info(f"Database engine created: {db_url.split('@')[-1] if '@' in db_url else db_url}")
    
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get or create session factory.
    
    Returns:
        SQLAlchemy async session factory.
    """
    global _session_factory
    
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )
    
    return _session_factory


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
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@retry(max_attempts=5, initial_delay=1.0, exponential_base=2.0)
async def init_database() -> None:
    """Initialize database connection with retry logic.

    This function attempts to connect to the database with exponential backoff.
    Useful for handling cases where the database might not be immediately available
    (e.g., in Docker environments).

    Raises:
        Exception: If database connection fails after all retry attempts.
    """
    db_settings = get_db_settings()
    
    if not db_settings.is_configured:
        logger.info("Database not configured, skipping initialization")
        return
    
    engine = get_engine()
    
    try:
        async with engine.begin() as conn:
            # Test connection
            await conn.execute(text("SELECT 1"))
        logger.info("Database connection successful")
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        raise


async def close_database() -> None:
    """Close database connection and dispose of engine.

    Call this function during application shutdown to cleanly close
    all database connections.
    """
    global _engine, _session_factory
    
    if _engine is not None:
        await _engine.dispose()
        logger.info("Database connection closed")
        _engine = None
        _session_factory = None
