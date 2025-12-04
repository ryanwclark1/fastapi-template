"""Database session management with psycopg3 async driver."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, cast

from opentelemetry import trace
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker as _async_sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine as _create_async_engine

from example_service.core.settings import get_app_settings, get_db_settings
from example_service.infra.metrics.prometheus import (
    database_connections_active,
    database_pool_checkedout,
    database_pool_checkout_time_seconds,
    database_pool_checkout_timeout_total,
    database_pool_invalidations_total,
    database_pool_overflow,
    database_pool_recycles_total,
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
engine = _create_async_engine(
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
AsyncSessionLocal = _async_sessionmaker(
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


# ============================================================================
# Pool Checkout/Checkin Metrics
# ============================================================================

# Store checkout start time in connection_record.info for timing
@event.listens_for(engine.sync_engine.pool, "checkout")
def _receive_checkout(
    dbapi_conn: Any, connection_record: Any, connection_proxy: Any
) -> None:
    """Track connection checkout from pool.

    Records checkout time and tracks overflow connections.
    The checkout time is stored to calculate wait time on checkin.
    """
    _ = dbapi_conn, connection_proxy

    # Record checkout start time for duration calculation
    connection_record.info["checkout_start"] = time.perf_counter()

    # Increment checked out connections
    database_pool_checkedout.inc()

    # Check if this is an overflow connection
    pool = engine.sync_engine.pool
    if hasattr(pool, "overflow") and pool.overflow() > 0:
        database_pool_overflow.set(pool.overflow())

    logger.debug("Connection checked out from pool")


@event.listens_for(engine.sync_engine.pool, "checkin")
def _receive_checkin(dbapi_conn: Any, connection_record: Any) -> None:
    """Track connection checkin to pool.

    Records the total time the connection was checked out and
    decrements the checkout counter.
    """
    _ = dbapi_conn

    # Calculate checkout duration if start time was recorded
    checkout_start = connection_record.info.pop("checkout_start", None)
    if checkout_start is not None:
        checkout_duration = time.perf_counter() - checkout_start
        database_pool_checkout_time_seconds.observe(checkout_duration)

    # Decrement checked out connections
    database_pool_checkedout.dec()

    # Update overflow gauge
    pool = engine.sync_engine.pool
    if hasattr(pool, "overflow"):
        database_pool_overflow.set(max(0, pool.overflow()))

    logger.debug("Connection checked in to pool")


# ============================================================================
# Pool Invalidation and Recycle Metrics
# ============================================================================


@event.listens_for(engine.sync_engine.pool, "invalidate")
def _receive_invalidate(
    dbapi_conn: Any, connection_record: Any, exception: Any
) -> None:
    """Track connection invalidation.

    Called when a connection is permanently removed from the pool,
    typically due to an error or explicit invalidation.
    """
    _ = dbapi_conn, connection_record

    reason = "error" if exception else "explicit"
    database_pool_invalidations_total.labels(reason=reason).inc()
    logger.debug("Connection invalidated", extra={"reason": reason})


@event.listens_for(engine.sync_engine.pool, "soft_invalidate")
def _receive_soft_invalidate(
    dbapi_conn: Any, connection_record: Any, exception: Any
) -> None:
    """Track soft connection invalidation.

    Called when a connection is marked for recycling but not
    immediately removed. It will be recycled on next checkout.
    """
    _ = dbapi_conn, connection_record, exception

    database_pool_invalidations_total.labels(reason="soft").inc()
    logger.debug("Connection soft-invalidated (will recycle)")


@event.listens_for(engine.sync_engine.pool, "reset")
def _receive_reset(dbapi_conn: Any, connection_record: Any) -> None:
    """Track connection reset events.

    Called when a connection is returned to the pool and reset
    to a clean state (rollback, etc.). We track recycles here
    when the connection age exceeds pool_recycle.
    """
    _ = dbapi_conn

    # Check if connection was recycled due to age
    if connection_record.info.get("_was_recycled"):
        database_pool_recycles_total.inc()
        connection_record.info.pop("_was_recycled", None)


# ============================================================================
# Checkout Timeout Detection
# ============================================================================
# Note: SQLAlchemy raises TimeoutError when pool_timeout is exceeded.
# We catch this in the session context manager and track it there.
# This marker helps identify when a checkout was attempted but timed out.


def track_checkout_timeout() -> None:
    """Increment the checkout timeout counter.

    Call this when a TimeoutError is caught during session acquisition.
    """
    database_pool_checkout_timeout_total.inc()
    logger.warning("Database pool checkout timeout")


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


__all__ = [
    "AsyncSessionLocal",
    "async_sessionmaker",
    "close_database",
    "create_async_engine",
    "engine",
    "get_async_session",
    "init_database",
]

# Re-export for convenience
create_async_engine = _create_async_engine
async_sessionmaker = _async_sessionmaker


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
