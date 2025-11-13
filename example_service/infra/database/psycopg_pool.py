"""Alternative database implementation using psycopg native connection pool.

This module provides an alternative to SQLAlchemy's pooling using psycopg's
native AsyncConnectionPool. Use this when you need direct psycopg access without
the ORM layer.

Benefits of psycopg native pool:
- Lower overhead (no ORM layer)
- Direct PostgreSQL features access
- Simpler for raw SQL queries
- Better performance for simple queries

Use SQLAlchemy pool (session.py) when:
- You need ORM features (models, relationships)
- Complex queries benefit from query builder
- Migrations via Alembic

Usage:
    ```python
    from example_service.infra.database.psycopg_pool import get_db_pool, execute_query

    # Get pool instance
    pool = await get_db_pool()

    # Execute query
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            result = await cur.fetchone()

    # Or use helper
    result = await execute_query("SELECT * FROM users WHERE id = %s", (user_id,))
    ```
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from example_service.core.settings import get_db_settings
from example_service.utils.retry import retry

logger = logging.getLogger(__name__)

# Global pool instance
_pool: AsyncConnectionPool | None = None


@retry(
    max_attempts=5,
    initial_delay=1.0,
    max_delay=30.0,
    exponential_base=2.0,
    jitter=True,
)
async def create_pool() -> AsyncConnectionPool:
    """Create and configure psycopg native connection pool.

    Creates an AsyncConnectionPool with settings from PostgresSettings.
    Pool is configured with:
    - min_size: Minimum number of connections to keep
    - max_size: Maximum number of connections allowed
    - max_idle: Maximum idle time before connection recycling
    - timeout: Timeout for acquiring a connection

    Returns:
        Configured AsyncConnectionPool instance.

    Raises:
        ConnectionError: If unable to create pool or connect to database.

    Example:
        ```python
        pool = await create_pool()
        async with pool.connection() as conn:
            # Use connection
            pass
        ```
    """
    db_settings = get_db_settings()

    if not db_settings.database_url:
        raise ValueError("Database URL not configured")

    # Get psycopg-native URL (without +psycopg driver specifier)
    conninfo = db_settings.get_psycopg_url()

    logger.info(
        "Creating psycopg connection pool",
        extra={
            "min_size": db_settings.pg_min_size,
            "max_size": db_settings.pg_max_size,
        },
    )

    try:
        # Create connection pool
        pool = AsyncConnectionPool(
            conninfo=conninfo,
            min_size=db_settings.pg_min_size,
            max_size=db_settings.pg_max_size,
            max_idle=db_settings.pg_max_idle,
            timeout=db_settings.pg_timeout,
            # Configure connection settings
            configure=configure_connection,
        )

        # Wait for pool to be ready
        await pool.wait()

        # Test connection
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")

        logger.info("psycopg connection pool created successfully")
        return pool

    except Exception as e:
        logger.error(f"Failed to create psycopg connection pool: {e}")
        raise


async def configure_connection(conn: AsyncConnection) -> None:
    """Configure individual connections in the pool.

    This function is called for each new connection created by the pool.
    Use it to set connection-specific settings like timezone, encoding, etc.

    Args:
        conn: The connection to configure.

    Example:
        ```python
        async def configure_connection(conn: AsyncConnection) -> None:
            await conn.execute("SET timezone = 'UTC'")
            await conn.execute("SET statement_timeout = '30s'")
        ```
    """
    # Set timezone to UTC
    await conn.execute("SET timezone = 'UTC'")

    # Optional: Set statement timeout
    # await conn.execute("SET statement_timeout = '30s'")

    # Optional: Set application name for pg_stat_activity
    # await conn.execute(f"SET application_name = 'example-service'")


async def get_db_pool() -> AsyncConnectionPool:
    """Get or create the global database connection pool.

    Returns the cached pool instance, creating it if necessary.
    Thread-safe singleton pattern.

    Returns:
        The global AsyncConnectionPool instance.

    Example:
        ```python
        pool = await get_db_pool()
        async with pool.connection() as conn:
            # Use connection
            pass
        ```
    """
    global _pool

    if _pool is None:
        _pool = await create_pool()

    return _pool


async def close_pool() -> None:
    """Close the database connection pool.

    Should be called during application shutdown.
    Closes all connections and releases resources.

    Example:
        ```python
        # In lifespan shutdown
        await close_pool()
        ```
    """
    global _pool

    if _pool is not None:
        logger.info("Closing psycopg connection pool")
        await _pool.close()
        _pool = None
        logger.info("psycopg connection pool closed successfully")


@asynccontextmanager
async def get_connection() -> AsyncGenerator[AsyncConnection, None]:
    """Get a database connection from the pool.

    Context manager that automatically returns the connection to the pool.

    Yields:
        AsyncConnection from the pool.

    Example:
        ```python
        async with get_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT * FROM users")
                users = await cur.fetchall()
        ```
    """
    pool = await get_db_pool()

    async with pool.connection() as conn:
        yield conn


async def execute_query(
    query: str,
    params: tuple[Any, ...] | None = None,
    *,
    fetch_one: bool = False,
    fetch_all: bool = True,
) -> Any:
    """Execute a query and return results.

    Helper function for simple queries. Automatically handles connection
    and cursor management.

    Args:
        query: SQL query to execute.
        params: Query parameters (use %s placeholders).
        fetch_one: Fetch only one result.
        fetch_all: Fetch all results (default).

    Returns:
        Query results (list, tuple, or None).

    Example:
        ```python
        # Fetch all
        users = await execute_query("SELECT * FROM users")

        # Fetch one
        user = await execute_query(
            "SELECT * FROM users WHERE id = %s",
            (user_id,),
            fetch_one=True,
        )

        # Execute without fetching (INSERT/UPDATE/DELETE)
        await execute_query(
            "INSERT INTO users (name, email) VALUES (%s, %s)",
            (name, email),
            fetch_all=False,
        )
        ```
    """
    async with get_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, params)

            if fetch_one:
                return await cur.fetchone()
            elif fetch_all:
                return await cur.fetchall()
            else:
                return None


async def execute_many(
    query: str,
    params_list: list[tuple[Any, ...]],
) -> None:
    """Execute a query multiple times with different parameters.

    Efficient batch execution using executemany.

    Args:
        query: SQL query to execute.
        params_list: List of parameter tuples.

    Example:
        ```python
        await execute_many(
            "INSERT INTO users (name, email) VALUES (%s, %s)",
            [
                ("Alice", "alice@example.com"),
                ("Bob", "bob@example.com"),
                ("Charlie", "charlie@example.com"),
            ],
        )
        ```
    """
    async with get_connection() as conn:
        async with conn.cursor() as cur:
            await cur.executemany(query, params_list)
