"""Database session management with psycopg3 async driver."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, cast

from opentelemetry import trace
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from example_service.core.settings import get_app_settings, get_db_settings
from example_service.infra.metrics.prometheus import (
    database_connections_active,
    database_query_duration_seconds,
)
from example_service.infra.metrics.tracking import track_slow_query
from example_service.utils.retry import retry

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)

# Get settings from modular configuration
db_settings = get_db_settings()
app_settings = get_app_settings()

# Create async engine with psycopg3
engine = create_async_engine(
    db_settings.get_sqlalchemy_url()
    if db_settings.is_configured
    else "sqlite+aiosqlite:///./test.db",
    pool_size=db_settings.pool_size,
    max_overflow=db_settings.max_overflow,
    pool_timeout=db_settings.pool_timeout,
    pool_recycle=db_settings.pool_recycle,
    pool_pre_ping=db_settings.pool_pre_ping,
    echo=db_settings.echo or app_settings.debug,
    # Note: application_name is already included in the connection URL via query parameters
    # in PostgresSettings.url property, so we don't need to pass it here in connect_args.
    # For psycopg3, connection-level parameters should be in the URL, not connect_args.
)

# Create session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)

# Track whether optional ancillary tables (like the event outbox) were ensured
_outbox_table_initialized = False


async def _ensure_event_outbox_table() -> None:
    """Create the event_outbox table if migrations haven't run yet.

    This provides a safety net for environments where Alembic migrations
    aren't executed (e.g., ephemeral preview deployments or local tests
    using a fresh database). The operation is idempotent thanks to
    SQLAlchemy's `checkfirst` guard.
    """
    global _outbox_table_initialized
    if _outbox_table_initialized:
        return

    from example_service.infra.events.outbox.models import EventOutbox

    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: cast("Any", EventOutbox.__table__).create(
                bind=sync_conn, checkfirst=True
            )
        )

    _outbox_table_initialized = True


# ============================================================================
# Database Metrics Instrumentation
# ============================================================================


# Track connection pool events for active connections metric
@event.listens_for(engine.sync_engine.pool, "connect")
def _receive_connect(dbapi_conn: Any, connection_record: Any) -> None:
    """Increment active connections when a new connection is established."""
    _ = dbapi_conn, connection_record
    database_connections_active.inc()
    logger.debug("Database connection established")


@event.listens_for(engine.sync_engine.pool, "close")
def _receive_close(dbapi_conn: Any, connection_record: Any) -> None:
    """Decrement active connections when a connection is closed."""
    _ = dbapi_conn, connection_record
    database_connections_active.dec()
    logger.debug("Database connection closed")


# Track query execution duration with trace correlation
@event.listens_for(engine.sync_engine, "before_cursor_execute")
def _before_cursor_execute(
    conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: Any
) -> None:
    """Record query start time before execution."""
    _ = conn, cursor, statement, parameters, executemany
    context._query_start_time = time.perf_counter()


@event.listens_for(engine.sync_engine, "after_cursor_execute")
def _after_cursor_execute(
    conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: Any
) -> None:
    """Record query duration and link to current trace via exemplar."""
    _ = conn, cursor, parameters, executemany
    # Calculate duration
    duration = time.perf_counter() - context._query_start_time

    # Extract operation type from SQL statement
    # e.g., "SELECT * FROM..." -> "SELECT"
    operation = "UNKNOWN"
    if statement:
        statement_upper = statement.strip().upper()
        if statement_upper.startswith("SELECT"):
            operation = "SELECT"
        elif statement_upper.startswith("INSERT"):
            operation = "INSERT"
        elif statement_upper.startswith("UPDATE"):
            operation = "UPDATE"
        elif statement_upper.startswith("DELETE"):
            operation = "DELETE"
        elif statement_upper.startswith("BEGIN"):
            operation = "BEGIN"
        elif statement_upper.startswith("COMMIT"):
            operation = "COMMIT"
        elif statement_upper.startswith("ROLLBACK"):
            operation = "ROLLBACK"

    # Get current trace ID for exemplar linking
    span = trace.get_current_span()
    trace_id = None
    if span and span.get_span_context().is_valid:
        trace_id = format(span.get_span_context().trace_id, "032x")

    # Record metric with exemplar if trace is available
    if trace_id:
        database_query_duration_seconds.labels(operation=operation).observe(
            duration, exemplar={"trace_id": trace_id}
        )
    else:
        database_query_duration_seconds.labels(operation=operation).observe(duration)

    # Track slow queries (>1 second)
    if duration > 1.0:
        track_slow_query(operation)


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession]:
    """Get async database session.

    Yields:
        Database session that is automatically closed.

    Example:
            async with get_async_session() as session:
            result = await session.execute(select(User))
            users = result.scalars().all()
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


@retry(
    max_attempts=db_settings.startup_retry_attempts,
    initial_delay=db_settings.startup_retry_delay,
    max_delay=30.0,
    exponential_base=2.0,
    jitter=True,
    stop_after_delay=db_settings.startup_retry_timeout,
)
async def init_database() -> None:
    """Initialize database connection with retry logic.

    This function attempts to connect to the database with exponential
    backoff retry. This is useful during application startup when the
    database might not be immediately available (e.g., in containerized
    environments).

    Uses retry settings from PostgresSettings:
    - startup_retry_attempts: Maximum number of connection attempts
    - startup_retry_delay: Initial delay between retries

    Raises:
        ConnectionError: If unable to connect after all retry attempts.
    """
    logger.info(
        "Initializing database connection with retry",
        extra={
            "max_attempts": db_settings.startup_retry_attempts,
            "initial_delay": db_settings.startup_retry_delay,
        },
    )

    try:
        # Test database connection
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

        db_url = (
            db_settings.get_sqlalchemy_url()
            if db_settings.is_configured
            else "sqlite+aiosqlite:///./test.db"
        )
        # Ensure optional tables needed for background processors exist
        await _ensure_event_outbox_table()
        logger.info(
            "Database connection established successfully",
            extra={"url": db_url, "driver": "psycopg3"},
        )
    except Exception as e:
        db_url = (
            db_settings.get_sqlalchemy_url()
            if db_settings.is_configured
            else "sqlite+aiosqlite:///./test.db"
        )
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
