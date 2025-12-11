"""Repository for database administration operations.

This repository provides access to PostgreSQL system statistics and health metrics
through raw SQL queries. Unlike other repositories, it doesn't operate on ORM models
since it queries PostgreSQL system tables (pg_stat_*, pg_statio_*, etc.).

Security:
    - All queries use parameter binding to prevent SQL injection
    - Statement timeout is set to 30s to prevent long-running queries
    - Query results are returned as dicts, not ORM models
    - NULL values are handled gracefully throughout

Example:
    from example_service.features.admin.database.repository import (
        DatabaseAdminRepository,
        get_database_admin_repository,
    )

    repo = get_database_admin_repository()
    pool_stats = await repo.get_connection_pool_stats(session)
    print(f"Active: {pool_stats['active_connections']}")
"""

from __future__ import annotations

from datetime import UTC, datetime
import logging
import time
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from example_service.infra.logging import get_lazy_logger

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class DatabaseAdminRepository:
    """Repository for database administration queries.

    Provides methods to query PostgreSQL system tables for statistics,
    health metrics, and administrative information. Uses raw SQL queries
    since system tables don't have ORM models.

    This repository does NOT extend BaseRepository[T] because it queries
    PostgreSQL system tables that have no ORM models. It follows repository
    conventions (explicit session passing, lazy logging) while returning
    dictionaries from raw SQL queries.

    Example:
        repo = get_database_admin_repository()
        pool_stats = await repo.get_connection_pool_stats(session)
        cache_ratio = await repo.get_cache_hit_ratio(session)
        tables = await repo.get_table_sizes(session, limit=10)
    """

    def __init__(self) -> None:
        """Initialize repository with loggers."""
        self._logger = logging.getLogger("repository.database_admin")
        self._lazy = get_lazy_logger("repository.database_admin")

    async def _execute_with_timeout(
        self,
        session: AsyncSession,
        query: str,
        params: dict[str, Any] | None = None,
        timeout_seconds: int = 30,
    ) -> Any:
        """Execute raw SQL query with timeout protection.

        Sets a statement-level timeout to prevent long-running administrative
        queries from blocking other operations.

        Args:
            session: Database session for query execution
            query: Raw SQL query string
            params: Query parameters for binding (uses :param syntax)
            timeout_seconds: Statement timeout in seconds (default: 30)

        Returns:
            SQLAlchemy result object with query results

        Raises:
            Exception: Database errors are logged and re-raised
        """
        try:
            # Set statement timeout for this query
            await session.execute(
                text(f"SET LOCAL statement_timeout = '{timeout_seconds}s'"),
            )

            # Execute the actual query
            return await session.execute(text(query), params or {})

        except Exception as e:
            self._logger.error(
                "Database admin query failed",
                extra={
                    "query_preview": query[:100],
                    "error": str(e),
                    "timeout": timeout_seconds,
                },
                exc_info=True,
            )
            raise

    async def get_connection_pool_stats(
        self,
        session: AsyncSession,
    ) -> dict[str, int]:
        """Get connection pool statistics from pg_stat_activity.

        Returns real-time connection counts including active, idle, and total
        connections compared to the configured maximum.

        Args:
            session: Database session for query execution

        Returns:
            Dictionary with connection pool metrics:
                - active_connections: Currently executing queries
                - idle_connections: Not executing queries
                - total_connections: Sum of all connections
                - max_connections: PostgreSQL max_connections setting

        Example:
            stats = await repo.get_connection_pool_stats(session)
            # {
            #     "active_connections": 8,
            #     "idle_connections": 12,
            #     "total_connections": 20,
            #     "max_connections": 100
            # }
        """
        query = """
            SELECT
                COUNT(*) FILTER (WHERE state = 'active') as active_connections,
                COUNT(*) FILTER (WHERE state = 'idle') as idle_connections,
                COUNT(*) as total_connections,
                (SELECT setting::int FROM pg_settings WHERE name = 'max_connections') as max_connections
            FROM pg_stat_activity
            WHERE pid != pg_backend_pid()
        """

        result = await self._execute_with_timeout(session, query)
        row = result.mappings().first()

        if row is None:
            self._logger.warning("No connection pool stats returned")
            return {
                "active_connections": 0,
                "idle_connections": 0,
                "total_connections": 0,
                "max_connections": 0,
            }

        stats = {
            "active_connections": row["active_connections"] or 0,
            "idle_connections": row["idle_connections"] or 0,
            "total_connections": row["total_connections"] or 0,
            "max_connections": row["max_connections"] or 0,
        }

        self._lazy.debug(
            lambda: f"db.get_connection_pool_stats -> active={stats['active_connections']}, total={stats['total_connections']}",
        )
        return stats

    async def get_database_size(self, session: AsyncSession) -> int:
        """Get current database size in bytes.

        Args:
            session: Database session for query execution

        Returns:
            Database size in bytes

        Example:
            size = await repo.get_database_size(session)
            # size = 2684354560 (approximately 2.5 GB)
        """
        query = "SELECT pg_database_size(current_database()) as size_bytes"

        result = await self._execute_with_timeout(session, query)
        row = result.mappings().first()

        if row is None or row["size_bytes"] is None:
            self._logger.warning("Database size query returned no results")
            return 0

        size = int(row["size_bytes"])
        self._lazy.debug(lambda: f"db.get_database_size -> {size} bytes")
        return size

    async def get_active_connections_count(self, session: AsyncSession) -> int:
        """Get count of active database connections.

        Returns only connections that are actively executing queries,
        excluding idle connections and the current backend.

        Args:
            session: Database session for query execution

        Returns:
            Number of active connections

        Example:
            active = await repo.get_active_connections_count(session)
            # active = 15
        """
        query = """
            SELECT COUNT(*) as active_count
            FROM pg_stat_activity
            WHERE state = 'active' AND pid != pg_backend_pid()
        """

        result = await self._execute_with_timeout(session, query)
        row = result.mappings().first()

        if row is None:
            return 0

        count = int(row["active_count"] or 0)
        self._lazy.debug(lambda: f"db.get_active_connections_count -> {count}")
        return count

    async def get_cache_hit_ratio(self, session: AsyncSession) -> float | None:
        """Get database cache hit ratio as a percentage.

        Calculates the ratio of buffer cache hits vs total buffer reads.
        A high ratio (>95%) indicates good cache performance.

        Args:
            session: Database session for query execution

        Returns:
            Cache hit ratio as percentage (0-100), or None if no data available

        Example:
            ratio = await repo.get_cache_hit_ratio(session)
            # ratio = 98.5 (98.5% of reads served from cache)
        """
        query = """
            SELECT
                CASE
                    WHEN sum(heap_blks_read) > 0
                    THEN (sum(heap_blks_hit)::float / (sum(heap_blks_hit) + sum(heap_blks_read))) * 100
                    ELSE NULL
                END as cache_hit_ratio
            FROM pg_statio_user_tables
        """

        result = await self._execute_with_timeout(session, query)
        row = result.mappings().first()

        if row is None or row["cache_hit_ratio"] is None:
            self._lazy.debug(lambda: "db.get_cache_hit_ratio -> no data available")
            return None

        ratio = float(row["cache_hit_ratio"])
        self._lazy.debug(lambda: f"db.get_cache_hit_ratio -> {ratio:.2f}%")
        return ratio

    async def get_table_sizes(
        self,
        session: AsyncSession,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get table sizes ordered by total size (table + indexes).

        Returns detailed size information for the largest tables in the
        public schema, including row counts and index sizes.

        Args:
            session: Database session for query execution
            limit: Maximum number of tables to return (default: 50)

        Returns:
            List of dictionaries with table size information:
                - schemaname: Schema name (typically 'public')
                - tablename: Table name
                - total_bytes: Total size including indexes
                - table_bytes: Table data size only
                - indexes_bytes: Total index size
                - row_count: Approximate row count

        Example:
            tables = await repo.get_table_sizes(session, limit=10)
            # [
            #     {
            #         "schemaname": "public",
            #         "tablename": "users",
            #         "total_bytes": 52428800,
            #         "table_bytes": 41943040,
            #         "indexes_bytes": 10485760,
            #         "row_count": 150000
            #     },
            #     ...
            # ]
        """
        query = """
            SELECT
                schemaname,
                tablename,
                pg_total_relation_size(schemaname||'.'||tablename) as total_bytes,
                pg_relation_size(schemaname||'.'||tablename) as table_bytes,
                pg_total_relation_size(schemaname||'.'||tablename) - pg_relation_size(schemaname||'.'||tablename) as indexes_bytes,
                (SELECT reltuples::bigint
                 FROM pg_class
                 WHERE relname = tablename
                   AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = schemaname)
                ) as row_count
            FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY total_bytes DESC
            LIMIT :limit
        """

        result = await self._execute_with_timeout(session, query, {"limit": limit})
        rows = result.mappings().all()

        tables = [
            {
                "schemaname": row["schemaname"],
                "tablename": row["tablename"],
                "total_bytes": int(row["total_bytes"] or 0),
                "table_bytes": int(row["table_bytes"] or 0),
                "indexes_bytes": int(row["indexes_bytes"] or 0),
                "row_count": int(row["row_count"] or 0),
            }
            for row in rows
        ]

        self._lazy.debug(lambda: f"db.get_table_sizes(limit={limit}) -> {len(tables)} tables")
        return tables

    async def get_index_health(
        self,
        session: AsyncSession,
        *,
        table_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get index health and usage statistics.

        Returns information about index size, usage, and validity.
        Can be filtered to a specific table.

        Args:
            session: Database session for query execution
            table_name: Optional table name to filter indexes (default: all tables)

        Returns:
            List of dictionaries with index health information:
                - index_name: Index name
                - table_name: Table the index belongs to
                - index_size_bytes: Index size in bytes
                - index_scans: Number of times index was scanned
                - is_valid: Whether index is valid and usable
                - definition: SQL definition of the index

        Example:
            indexes = await repo.get_index_health(session, table_name="users")
            # [
            #     {
            #         "index_name": "idx_users_email",
            #         "table_name": "users",
            #         "index_size_bytes": 10485760,
            #         "index_scans": 45000,
            #         "is_valid": True,
            #         "definition": "CREATE INDEX idx_users_email ON users (email)"
            #     },
            #     ...
            # ]
        """
        # Base query
        query_parts = [
            """
            SELECT
                indexrelname as index_name,
                tablename as table_name,
                pg_relation_size(indexrelid) as index_size_bytes,
                idx_scan as index_scans,
                indisvalid as is_valid,
                pg_get_indexdef(indexrelid) as definition
            FROM pg_stat_user_indexes
            WHERE schemaname = 'public'
            """,
        ]

        params: dict[str, Any] = {}

        # Add table filter if specified
        if table_name is not None:
            query_parts.append("AND tablename = :table_name")
            params["table_name"] = table_name

        query_parts.append("ORDER BY pg_relation_size(indexrelid) DESC")

        query = "\n".join(query_parts)

        result = await self._execute_with_timeout(session, query, params)
        rows = result.mappings().all()

        indexes = [
            {
                "index_name": row["index_name"],
                "table_name": row["table_name"],
                "index_size_bytes": int(row["index_size_bytes"] or 0),
                "index_scans": int(row["index_scans"] or 0),
                "is_valid": bool(row["is_valid"]),
                "definition": row["definition"] or "",
            }
            for row in rows
        ]

        self._lazy.debug(
            lambda: f"db.get_index_health(table={table_name}) -> {len(indexes)} indexes",
        )
        return indexes

    async def get_replication_lag(self, session: AsyncSession) -> float | None:
        """Get replication lag in seconds.

        Returns the replication lag if the database is a replica in recovery
        mode. Returns None if not in recovery (i.e., primary database).

        Args:
            session: Database session for query execution

        Returns:
            Replication lag in seconds, or None if not a replica

        Example:
            lag = await repo.get_replication_lag(session)
            # lag = 0.5 (replica is 0.5 seconds behind primary)
            # lag = None (this is the primary database)
        """
        query = """
            SELECT
                CASE
                    WHEN pg_is_in_recovery()
                    THEN EXTRACT(EPOCH FROM (now() - pg_last_xact_replay_timestamp()))
                    ELSE NULL
                END as lag_seconds
        """

        result = await self._execute_with_timeout(session, query)
        row = result.mappings().first()

        if row is None or row["lag_seconds"] is None:
            self._lazy.debug(lambda: "db.get_replication_lag -> not in recovery (primary)")
            return None

        lag = float(row["lag_seconds"])
        self._lazy.debug(lambda: f"db.get_replication_lag -> {lag:.2f}s")
        return lag

    async def get_active_queries(
        self,
        session: AsyncSession,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get currently active database queries.

        Returns information about queries that are currently executing,
        excluding idle connections and the current backend.

        Args:
            session: Database session for query execution
            limit: Maximum number of queries to return (default: 100)

        Returns:
            List of dictionaries with query information:
                - pid: Process ID of the backend
                - user: Database user executing the query
                - database: Database name
                - state: Query state (active, idle in transaction, etc.)
                - query: SQL query text
                - duration_seconds: How long query has been running
                - wait_event: Wait event if query is waiting

        Example:
            queries = await repo.get_active_queries(session, limit=10)
            # [
            #     {
            #         "pid": 12345,
            #         "user": "app_user",
            #         "database": "production",
            #         "state": "active",
            #         "query": "SELECT * FROM users WHERE email = $1",
            #         "duration_seconds": 2.5,
            #         "wait_event": "ClientRead"
            #     },
            #     ...
            # ]
        """
        query = """
            SELECT
                pid,
                usename as user,
                datname as database,
                state,
                query,
                EXTRACT(EPOCH FROM (now() - query_start)) as duration_seconds,
                wait_event
            FROM pg_stat_activity
            WHERE state != 'idle'
                AND pid != pg_backend_pid()
                AND query NOT LIKE '%pg_stat_activity%'
            ORDER BY query_start
            LIMIT :limit
        """

        result = await self._execute_with_timeout(session, query, {"limit": limit})
        rows = result.mappings().all()

        queries = [
            {
                "pid": int(row["pid"]),
                "user": row["user"] or "",
                "database": row["database"] or "",
                "state": row["state"] or "",
                "query": row["query"] or "",
                "duration_seconds": float(row["duration_seconds"] or 0.0),
                "wait_event": row["wait_event"],
            }
            for row in rows
        ]

        self._lazy.debug(lambda: f"db.get_active_queries(limit={limit}) -> {len(queries)} queries")
        return queries

    async def get_database_stats_summary(
        self,
        session: AsyncSession,
    ) -> dict[str, Any]:
        """Get comprehensive database statistics summary.

        Returns aggregate statistics including table counts, index counts,
        transaction counts, and tuple (row) operation counts.

        Args:
            session: Database session for query execution

        Returns:
            Dictionary with database statistics:
                - table_count: Number of tables in public schema
                - index_count: Number of indexes in public schema
                - total_transactions: Total committed + rolled back transactions
                - tup_returned: Rows returned by queries
                - tup_fetched: Rows fetched from tables
                - tup_inserted: Rows inserted
                - tup_updated: Rows updated
                - tup_deleted: Rows deleted

        Example:
            stats = await repo.get_database_stats_summary(session)
            # {
            #     "table_count": 45,
            #     "index_count": 123,
            #     "total_transactions": 1500000,
            #     "tup_returned": 50000000,
            #     "tup_fetched": 25000000,
            #     "tup_inserted": 500000,
            #     "tup_updated": 200000,
            #     "tup_deleted": 10000
            # }
        """
        query = """
            SELECT
                (SELECT count(*) FROM pg_tables WHERE schemaname = 'public') as table_count,
                (SELECT count(*) FROM pg_indexes WHERE schemaname = 'public') as index_count,
                xact_commit + xact_rollback as total_transactions,
                tup_returned,
                tup_fetched,
                tup_inserted,
                tup_updated,
                tup_deleted
            FROM pg_stat_database
            WHERE datname = current_database()
        """

        result = await self._execute_with_timeout(session, query)
        row = result.mappings().first()

        if row is None:
            self._logger.warning("Database stats summary query returned no results")
            return {
                "table_count": 0,
                "index_count": 0,
                "total_transactions": 0,
                "tup_returned": 0,
                "tup_fetched": 0,
                "tup_inserted": 0,
                "tup_updated": 0,
                "tup_deleted": 0,
            }

        stats = {
            "table_count": int(row["table_count"] or 0),
            "index_count": int(row["index_count"] or 0),
            "total_transactions": int(row["total_transactions"] or 0),
            "tup_returned": int(row["tup_returned"] or 0),
            "tup_fetched": int(row["tup_fetched"] or 0),
            "tup_inserted": int(row["tup_inserted"] or 0),
            "tup_updated": int(row["tup_updated"] or 0),
            "tup_deleted": int(row["tup_deleted"] or 0),
        }

        self._lazy.debug(
            lambda: f"db.get_database_stats_summary -> tables={stats['table_count']}, indexes={stats['index_count']}",
        )
        return stats

    async def log_admin_action(
        self,
        session: AsyncSession,
        *,
        id: str,
        action: str,
        target: str,
        user_id: str,
        tenant_id: str | None,
        result: str,
        duration_seconds: float | None,
        metadata: dict[str, Any] | None,
        created_at: datetime | None = None,
    ) -> None:
        """Log an administrative action to the audit log.

        Inserts a record into the admin_audit_log table to track administrative
        database operations for compliance and security auditing.

        Args:
            session: Database session for query execution
            id: Unique UUID for the audit log entry (typically UUIDv7)
            action: Action type (e.g., "vacuum_table", "reindex", "analyze")
            target: Target resource (table name, index name, etc.)
            user_id: ID of the user who performed the action
            tenant_id: Tenant ID if action was tenant-scoped
            result: Operation result ("success", "failure", "dry_run")
            duration_seconds: How long the operation took
            metadata: Additional context (parameters, errors, statistics)
            created_at: When the action was performed (defaults to now)

        Example:
            import uuid
            from datetime import UTC, datetime

            await repo.log_admin_action(
                session,
                id=str(uuid.uuid4()),
                action="vacuum_table",
                target="users",
                user_id="admin_123",
                tenant_id="tenant_abc",
                result="success",
                duration_seconds=45.2,
                metadata={"table_name": "users", "vacuum_type": "full"},
                created_at=datetime.now(UTC),
            )
        """
        query = """
            INSERT INTO admin_audit_log (
                id, action, target, user_id, tenant_id,
                result, duration_seconds, metadata, created_at
            ) VALUES (
                :id, :action, :target, :user_id, :tenant_id,
                :result, :duration_seconds, :metadata, :created_at
            )
        """

        params = {
            "id": id,
            "action": action,
            "target": target,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "result": result,
            "duration_seconds": duration_seconds,
            "metadata": metadata or {},
            "created_at": created_at or datetime.now(UTC),
        }

        start_time = time.perf_counter()

        try:
            await self._execute_with_timeout(session, query, params)
            await session.commit()

            elapsed = time.perf_counter() - start_time
            self._logger.info(
                "Admin action logged",
                extra={
                    "action": action,
                    "target": target,
                    "user_id": user_id,
                    "result": result,
                    "duration_ms": elapsed * 1000,
                },
            )

        except Exception as e:
            await session.rollback()
            self._logger.error(
                "Failed to log admin action",
                extra={
                    "action": action,
                    "target": target,
                    "user_id": user_id,
                    "error": str(e),
                },
                exc_info=True,
            )
            raise

    async def get_audit_logs(
        self,
        session: AsyncSession,
        *,
        action_type: str | None = None,
        user_id: str | None = None,
        tenant_id: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Query admin audit logs with optional filters.

        Retrieves audit log entries with pagination and filtering support.
        Returns both the matching records and total count for pagination.

        Args:
            session: Database session for query execution
            action_type: Filter by action type
            user_id: Filter by user who performed action
            tenant_id: Filter by tenant ID
            start_date: Filter logs created on or after this date
            end_date: Filter logs created on or before this date
            limit: Maximum number of records to return
            offset: Number of records to skip (for pagination)

        Returns:
            Dictionary containing:
                - items: List of audit log entries (as dicts)
                - total: Total count of matching records
                - limit: Limit used
                - offset: Offset used

        Example:
            from datetime import UTC, datetime, timedelta

            end = datetime.now(UTC)
            start = end - timedelta(days=7)

            result = await repo.get_audit_logs(
                session,
                action_type="vacuum_table",
                user_id="admin_123",
                start_date=start,
                end_date=end,
                limit=50,
                offset=0,
            )

            print(f"Found {result['total']} logs, showing {len(result['items'])}")
            for log in result["items"]:
                print(f"{log['created_at']}: {log['action']} on {log['target']}")
        """
        # Build WHERE clauses dynamically based on filters
        where_clauses = []
        params: dict[str, Any] = {}

        if action_type is not None:
            where_clauses.append("action = :action_type")
            params["action_type"] = action_type

        if user_id is not None:
            where_clauses.append("user_id = :user_id")
            params["user_id"] = user_id

        if tenant_id is not None:
            where_clauses.append("tenant_id = :tenant_id")
            params["tenant_id"] = tenant_id

        if start_date is not None:
            where_clauses.append("created_at >= :start_date")
            params["start_date"] = start_date

        if end_date is not None:
            where_clauses.append("created_at <= :end_date")
            params["end_date"] = end_date

        # Build WHERE clause
        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)

        # Count query for total
        count_query = f"""
            SELECT COUNT(*) as total
            FROM admin_audit_log
            {where_sql}
        """

        # Data query with pagination
        data_query = f"""
            SELECT
                id, action, target, user_id, tenant_id,
                result, duration_seconds, metadata, created_at
            FROM admin_audit_log
            {where_sql}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """

        # Add pagination params
        params["limit"] = limit
        params["offset"] = offset

        # Execute count query
        count_result = await self._execute_with_timeout(session, count_query, params)
        count_row = count_result.mappings().first()
        total = int(count_row["total"]) if count_row else 0

        # Execute data query
        data_result = await self._execute_with_timeout(session, data_query, params)
        rows = data_result.mappings().all()

        items = [
            {
                "id": row["id"],
                "action": row["action"],
                "target": row["target"],
                "user_id": row["user_id"],
                "tenant_id": row["tenant_id"],
                "result": row["result"],
                "duration_seconds": row["duration_seconds"],
                "metadata": row["metadata"] or {},
                "created_at": row["created_at"],
            }
            for row in rows
        ]

        self._lazy.debug(
            lambda: f"db.get_audit_logs(filters={len(where_clauses)}) -> {len(items)}/{total}",
        )

        return {
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
        }


# Global singleton instance
_database_admin_repository: DatabaseAdminRepository | None = None


def get_database_admin_repository() -> DatabaseAdminRepository:
    """Get the global DatabaseAdminRepository instance.

    Returns singleton repository instance for dependency injection.

    Returns:
        Singleton DatabaseAdminRepository instance

    Example:
        In FastAPI routes:

        from example_service.features.admin.database.repository import (
            DatabaseAdminRepository,
            get_database_admin_repository,
        )
        from fastapi import Depends

        @router.get("/health")
        async def health_check(
            session: AsyncSession = Depends(get_db_session),
            repo: DatabaseAdminRepository = Depends(get_database_admin_repository),
        ):
            stats = await repo.get_connection_pool_stats(session)
            return {"pool": stats}
    """
    global _database_admin_repository
    if _database_admin_repository is None:
        _database_admin_repository = DatabaseAdminRepository()
    return _database_admin_repository


__all__ = [
    "DatabaseAdminRepository",
    "get_database_admin_repository",
]
