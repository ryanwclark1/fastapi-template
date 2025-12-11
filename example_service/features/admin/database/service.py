"""Service layer for database administration operations.

This service provides business logic for database health monitoring, statistics,
and administrative operations. It sits between the repository (data access) and
the router (HTTP layer), implementing health status determination, rate limiting,
and audit logging.

The service orchestrates repository calls, applies business rules, and transforms
raw database statistics into meaningful health assessments.

Example:
    from example_service.features.admin.database.service import (
        DatabaseAdminService,
        get_database_admin_service,
    )

    service = DatabaseAdminService(repository, settings)
    health = await service.get_health(session, user_id="admin_123")

    if health.status == DatabaseHealthStatus.UNHEALTHY:
        # Alert operations team
        send_alert(health)
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
import time
from typing import TYPE_CHECKING, Any
import uuid

from example_service.core.database.admin_utils import format_bytes
from example_service.core.services.base import BaseService
from example_service.features.admin.database.schemas import (
    ActiveQuery,
    AdminAuditLog,
    AuditLogFilters,
    AuditLogListResponse,
    ConnectionPoolStats,
    DatabaseHealth,
    DatabaseHealthStatus,
    DatabaseStats,
    IndexHealthInfo,
    TableSizeInfo,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from example_service.core.settings.admin import AdminSettings
    from example_service.features.admin.database.repository import (
        DatabaseAdminRepository,
    )


class DatabaseAdminService(BaseService):
    """Service layer for database administration operations.

    Provides business logic for database health monitoring, statistics,
    and administrative operations. Handles health status determination,
    rate limiting, and audit logging.

    This service follows the repository pattern by delegating data access
    to DatabaseAdminRepository while implementing business rules and
    transformations in the service layer.

    Responsibilities:
        - Health status determination based on thresholds
        - Rate limiting for administrative operations
        - Audit logging for compliance
        - Data transformation (dicts -> Pydantic schemas)
        - Business logic for warnings and alerts

    Example:
        service = DatabaseAdminService(repository, settings)
        health = await service.get_health(session, user_id="admin_123")

        if health.status == DatabaseHealthStatus.UNHEALTHY:
            # Critical issues detected
            notify_ops_team(health.warnings)
    """

    def __init__(
        self,
        repository: DatabaseAdminRepository,
        settings: AdminSettings,
    ) -> None:
        """Initialize database admin service with dependencies.

        Args:
            repository: Repository for database queries
            settings: Admin configuration settings
        """
        super().__init__()
        self.repository = repository
        self.settings = settings

        # Simple in-memory rate limiter that tracks timestamps per user/operation.
        self._rate_limiter: dict[str, dict[str, list[float]]] = defaultdict(
            lambda: defaultdict(list),
        )

    async def get_health(
        self,
        session: AsyncSession,
        user_id: str,
    ) -> DatabaseHealth:
        """Get comprehensive database health status with status determination.

        Retrieves database health metrics and applies business rules to determine
        overall health status. Generates warnings for concerning metrics.

        Health status determination:
        - UNHEALTHY: >90% connection pool OR <70% cache hit ratio
        - DEGRADED: >75% connection pool OR <85% cache hit ratio OR warnings present
        - HEALTHY: All metrics within normal range

        Args:
            session: Database session for query execution
            user_id: ID of user requesting health check (for rate limiting)

        Returns:
            DatabaseHealth with status, metrics, and warnings

        Raises:
            HTTPException: 429 if rate limit exceeded

        Example:
            health = await service.get_health(session, "admin_123")
            print(f"Status: {health.status}")
            print(f"Pool utilization: {health.connection_pool.utilization_percent}%")
            for warning in health.warnings:
                print(f"WARNING: {warning}")
        """
        start_time = time.perf_counter()

        # Check rate limit
        await self._check_rate_limit(user_id, "get_health")

        self._lazy.debug(lambda: f"service.get_health({user_id})")

        try:
            # Gather metrics from repository
            pool_stats_dict = await self.repository.get_connection_pool_stats(session)
            db_size = await self.repository.get_database_size(session)
            active_count = await self.repository.get_active_connections_count(session)
            cache_ratio = await self.repository.get_cache_hit_ratio(session)
            replication_lag = await self.repository.get_replication_lag(session)

            # Transform connection pool stats to schema
            pool_utilization = (
                (pool_stats_dict["total_connections"] / pool_stats_dict["max_connections"]) * 100
                if pool_stats_dict["max_connections"] > 0
                else 0.0
            )

            pool_stats = ConnectionPoolStats(
                active_connections=pool_stats_dict["active_connections"],
                idle_connections=pool_stats_dict["idle_connections"],
                total_connections=pool_stats_dict["total_connections"],
                max_connections=pool_stats_dict["max_connections"],
                utilization_percent=round(pool_utilization, 2),
            )

            # Convert cache ratio from percentage (0-100) to ratio (0-1) for comparison
            cache_ratio_pct = cache_ratio if cache_ratio is not None else None

            # Generate warnings based on thresholds
            warnings: list[str] = []

            if pool_utilization > self.settings.connection_pool_warning_threshold:
                warnings.append(
                    f"Connection pool utilization is high: {pool_utilization:.1f}% "
                    f"(threshold: {self.settings.connection_pool_warning_threshold}%)",
                )

            if cache_ratio_pct is not None and cache_ratio_pct < self.settings.cache_hit_ratio_warning_threshold:
                warnings.append(
                    f"Cache hit ratio is low: {cache_ratio_pct:.1f}% "
                    f"(threshold: {self.settings.cache_hit_ratio_warning_threshold}%)",
                )

            if replication_lag is not None and replication_lag > 5.0:
                warnings.append(
                    f"Replication lag is high: {replication_lag:.1f}s",
                )

            # Determine overall health status
            status = self._determine_health_status(
                warnings=warnings,
                connection_utilization=pool_utilization,
                cache_hit_ratio=cache_ratio_pct,
            )

            # Build health response
            health = DatabaseHealth(
                status=status,
                timestamp=datetime.now(UTC),
                connection_pool=pool_stats,
                database_size_bytes=db_size,
                database_size_human=format_bytes(db_size),
                active_connections_count=active_count,
                cache_hit_ratio=cache_ratio_pct / 100 if cache_ratio_pct is not None else None,
                replication_lag_seconds=replication_lag,
                warnings=warnings,
            )

            # Log operation
            duration = time.perf_counter() - start_time
            await self._log_operation(
                session=session,
                action="get_health",
                target="database",
                user_id=user_id,
                result="success",
                duration=duration,
                metadata={
                    "status": status.value,
                    "warnings_count": len(warnings),
                },
            )

            self.logger.info(
                "Database health check completed",
                extra={
                    "user_id": user_id,
                    "status": status.value,
                    "warnings_count": len(warnings),
                    "duration_ms": duration * 1000,
                },
            )

            return health

        except Exception as e:
            duration = time.perf_counter() - start_time
            self.logger.error(
                "Health check failed",
                extra={
                    "operation": "get_health",
                    "user_id": user_id,
                    "error": str(e),
                    "duration_ms": duration * 1000,
                },
                exc_info=True,
            )
            raise

    async def get_stats(
        self,
        session: AsyncSession,
        user_id: str,
    ) -> DatabaseStats:
        """Get detailed database statistics.

        Retrieves comprehensive database statistics including size, object counts,
        performance metrics, and top tables by size.

        Args:
            session: Database session for query execution
            user_id: ID of user requesting stats (for rate limiting)

        Returns:
            DatabaseStats with comprehensive metrics

        Raises:
            HTTPException: 429 if rate limit exceeded

        Example:
            stats = await service.get_stats(session, "admin_123")
            print(f"Database size: {stats.total_size_human}")
            print(f"Tables: {stats.table_count}")
            print(f"Cache hit ratio: {stats.cache_hit_ratio:.2%}")
        """
        start_time = time.perf_counter()

        # Check rate limit
        await self._check_rate_limit(user_id, "get_stats")

        self._lazy.debug(lambda: f"service.get_stats({user_id})")

        try:
            # Gather statistics from repository
            db_size = await self.repository.get_database_size(session)
            summary = await self.repository.get_database_stats_summary(session)
            cache_ratio = await self.repository.get_cache_hit_ratio(session)

            # Get top tables (limit to 10 for stats overview)
            tables_data = await self.repository.get_table_sizes(session, limit=10)

            # Transform table data to schemas
            top_tables = [
                TableSizeInfo(
                    table_name=t["tablename"],
                    schema_name=t["schemaname"],
                    row_count=t["row_count"],
                    total_size_bytes=t["total_bytes"],
                    total_size_human=format_bytes(t["total_bytes"]),
                    table_size_bytes=t["table_bytes"],
                    indexes_size_bytes=t["indexes_bytes"],
                )
                for t in tables_data
            ]

            # Get slow queries count (queries running > 10 seconds)
            active_queries = await self.repository.get_active_queries(session, limit=100)
            slow_queries_count = sum(1 for q in active_queries if q["duration_seconds"] > 10.0)

            # Calculate transaction rate (placeholder - would need historical data)
            # For now, use a simple calculation based on total transactions
            transaction_rate = 0.0
            if summary["total_transactions"] > 0:
                # Estimate: assume stats were collected over 1 hour
                transaction_rate = summary["total_transactions"] / 3600.0

            # Build stats response
            stats = DatabaseStats(
                total_size_bytes=db_size,
                total_size_human=format_bytes(db_size),
                table_count=summary["table_count"],
                index_count=summary["index_count"],
                cache_hit_ratio=cache_ratio / 100 if cache_ratio is not None else None,
                transaction_rate=round(transaction_rate, 2),
                top_tables=top_tables,
                slow_queries_count=slow_queries_count,
            )

            # Log operation
            duration = time.perf_counter() - start_time
            await self._log_operation(
                session=session,
                action="get_stats",
                target="database",
                user_id=user_id,
                result="success",
                duration=duration,
                metadata={
                    "table_count": stats.table_count,
                    "index_count": stats.index_count,
                },
            )

            self.logger.info(
                "Database stats retrieved",
                extra={
                    "user_id": user_id,
                    "table_count": stats.table_count,
                    "index_count": stats.index_count,
                    "duration_ms": duration * 1000,
                },
            )

            return stats

        except Exception as e:
            duration = time.perf_counter() - start_time
            self.logger.error(
                "Get stats failed",
                extra={
                    "operation": "get_stats",
                    "user_id": user_id,
                    "error": str(e),
                    "duration_ms": duration * 1000,
                },
                exc_info=True,
            )
            raise

    async def get_connection_info(
        self,
        session: AsyncSession,
        user_id: str,
        limit: int = 100,
    ) -> list[ActiveQuery]:
        """Get active database connections with query details.

        Retrieves information about currently active queries including
        duration, state, and wait events.

        Args:
            session: Database session for query execution
            user_id: ID of user requesting info (for rate limiting)
            limit: Maximum number of queries to return (default: 100)

        Returns:
            List of ActiveQuery objects with connection details

        Raises:
            HTTPException: 429 if rate limit exceeded

        Example:
            queries = await service.get_connection_info(session, "admin_123", limit=20)
            for query in queries:
                if query.duration_seconds > 30:
                    print(f"Long-running query (PID {query.pid}): {query.query}")
        """
        start_time = time.perf_counter()

        # Check rate limit
        await self._check_rate_limit(user_id, "get_connection_info")

        self._lazy.debug(lambda: f"service.get_connection_info({user_id}, limit={limit})")

        try:
            # Get active queries from repository
            queries_data = await self.repository.get_active_queries(session, limit=limit)

            # Transform to schemas
            active_queries = [
                ActiveQuery(
                    pid=q["pid"],
                    user=q["user"],
                    database=q["database"],
                    state=q["state"],
                    query=q["query"],
                    duration_seconds=round(q["duration_seconds"], 2),
                    wait_event=q["wait_event"],
                )
                for q in queries_data
            ]

            # Log operation
            duration = time.perf_counter() - start_time
            await self._log_operation(
                session=session,
                action="get_connection_info",
                target="database",
                user_id=user_id,
                result="success",
                duration=duration,
                metadata={
                    "query_count": len(active_queries),
                    "limit": limit,
                },
            )

            self.logger.info(
                "Connection info retrieved",
                extra={
                    "user_id": user_id,
                    "query_count": len(active_queries),
                    "duration_ms": duration * 1000,
                },
            )

            return active_queries

        except Exception as e:
            duration = time.perf_counter() - start_time
            self.logger.error(
                "Get connection info failed",
                extra={
                    "operation": "get_connection_info",
                    "user_id": user_id,
                    "error": str(e),
                    "duration_ms": duration * 1000,
                },
                exc_info=True,
            )
            raise

    async def get_table_sizes(
        self,
        session: AsyncSession,
        user_id: str,
        limit: int = 50,
    ) -> list[TableSizeInfo]:
        """Get table sizes sorted by total size.

        Retrieves detailed size information for database tables including
        row counts, table size, and index sizes.

        Args:
            session: Database session for query execution
            user_id: ID of user requesting info (for rate limiting)
            limit: Maximum number of tables to return (default: 50)

        Returns:
            List of TableSizeInfo objects sorted by total size (largest first)

        Raises:
            HTTPException: 429 if rate limit exceeded

        Example:
            tables = await service.get_table_sizes(session, "admin_123", limit=10)
            for table in tables:
                print(f"{table.table_name}: {table.total_size_human} ({table.row_count:,} rows)")
        """
        start_time = time.perf_counter()

        # Check rate limit
        await self._check_rate_limit(user_id, "get_table_sizes")

        self._lazy.debug(lambda: f"service.get_table_sizes({user_id}, limit={limit})")

        try:
            # Get table sizes from repository
            tables_data = await self.repository.get_table_sizes(session, limit=limit)

            # Transform to schemas with human-readable sizes
            tables = [
                TableSizeInfo(
                    table_name=t["tablename"],
                    schema_name=t["schemaname"],
                    row_count=t["row_count"],
                    total_size_bytes=t["total_bytes"],
                    total_size_human=format_bytes(t["total_bytes"]),
                    table_size_bytes=t["table_bytes"],
                    indexes_size_bytes=t["indexes_bytes"],
                )
                for t in tables_data
            ]

            # Log operation
            duration = time.perf_counter() - start_time
            await self._log_operation(
                session=session,
                action="get_table_sizes",
                target="database",
                user_id=user_id,
                result="success",
                duration=duration,
                metadata={
                    "table_count": len(tables),
                    "limit": limit,
                },
            )

            self.logger.info(
                "Table sizes retrieved",
                extra={
                    "user_id": user_id,
                    "table_count": len(tables),
                    "duration_ms": duration * 1000,
                },
            )

            return tables

        except Exception as e:
            duration = time.perf_counter() - start_time
            self.logger.error(
                "Get table sizes failed",
                extra={
                    "operation": "get_table_sizes",
                    "user_id": user_id,
                    "error": str(e),
                    "duration_ms": duration * 1000,
                },
                exc_info=True,
            )
            raise

    async def get_index_health(
        self,
        session: AsyncSession,
        user_id: str,
        table_name: str | None = None,
    ) -> list[IndexHealthInfo]:
        """Get index health and usage statistics.

        Retrieves information about index health including size, usage,
        and validity status for performance monitoring.

        Args:
            session: Database session for query execution
            user_id: ID of user requesting info (for rate limiting)
            table_name: Optional table name to filter indexes

        Returns:
            List of IndexHealthInfo objects with health metrics

        Raises:
            HTTPException: 429 if rate limit exceeded

        Example:
            indexes = await service.get_index_health(session, "admin_123", table_name="users")
            for idx in indexes:
                if not idx.is_valid:
                    print(f"INVALID INDEX: {idx.index_name}")
                if idx.index_scans == 0:
                    print(f"UNUSED INDEX: {idx.index_name}")
        """
        start_time = time.perf_counter()

        # Check rate limit
        await self._check_rate_limit(user_id, "get_index_health")

        self._lazy.debug(lambda: f"service.get_index_health({user_id}, table={table_name})")

        try:
            # Get index health from repository
            indexes_data = await self.repository.get_index_health(
                session,
                table_name=table_name,
            )

            # Transform to schemas with human-readable sizes
            indexes = [
                IndexHealthInfo(
                    index_name=idx["index_name"],
                    table_name=idx["table_name"],
                    index_size_bytes=idx["index_size_bytes"],
                    index_size_human=format_bytes(idx["index_size_bytes"]),
                    index_scans=idx["index_scans"],
                    bloat_percent=None,  # Bloat metrics not available from repository yet
                    is_valid=idx["is_valid"],
                    definition=idx["definition"],
                )
                for idx in indexes_data
            ]

            # Log operation
            duration = time.perf_counter() - start_time
            await self._log_operation(
                session=session,
                action="get_index_health",
                target=table_name or "all_tables",
                user_id=user_id,
                result="success",
                duration=duration,
                metadata={
                    "index_count": len(indexes),
                    "table_name": table_name,
                },
            )

            self.logger.info(
                "Index health retrieved",
                extra={
                    "user_id": user_id,
                    "index_count": len(indexes),
                    "table_name": table_name,
                    "duration_ms": duration * 1000,
                },
            )

            return indexes

        except Exception as e:
            duration = time.perf_counter() - start_time
            self.logger.error(
                "Get index health failed",
                extra={
                    "operation": "get_index_health",
                    "user_id": user_id,
                    "table_name": table_name,
                    "error": str(e),
                    "duration_ms": duration * 1000,
                },
                exc_info=True,
            )
            raise

    async def get_audit_logs(
        self,
        session: AsyncSession,
        user_id: str,
        filters: AuditLogFilters,
    ) -> AuditLogListResponse:
        """Get admin operation audit logs with pagination.

        Retrieves audit logs for administrative operations with filtering
        and pagination support.

        Args:
            session: Database session for query execution
            user_id: ID of user requesting logs (for rate limiting)
            filters: Filtering and pagination parameters

        Returns:
            AuditLogListResponse with paginated audit logs

        Raises:
            HTTPException: 429 if rate limit exceeded

        Example:
            filters = AuditLogFilters(
                action_type="vacuum_table",
                start_date=datetime.now(UTC) - timedelta(days=7),
                page=1,
                page_size=50,
            )
            response = await service.get_audit_logs(session, "admin_123", filters)
            print(f"Showing {len(response.items)} of {response.total} logs")
        """
        start_time = time.perf_counter()

        # Check rate limit
        await self._check_rate_limit(user_id, "get_audit_logs")

        self._lazy.debug(lambda: f"service.get_audit_logs({user_id}, page={filters.page})")

        try:
            # Calculate offset from page number
            offset = (filters.page - 1) * filters.page_size

            # Get audit logs from repository
            result = await self.repository.get_audit_logs(
                session,
                action_type=filters.action_type,
                user_id=filters.user_id,
                tenant_id=None,  # Not tenant-scoped in this context
                start_date=filters.start_date,
                end_date=filters.end_date,
                limit=filters.page_size,
                offset=offset,
            )

            # Transform to schemas
            audit_logs = [
                AdminAuditLog(
                    id=log["id"],
                    action=log["action"],
                    target=log["target"],
                    user_id=log["user_id"],
                    tenant_id=log["tenant_id"],
                    result=log["result"],
                    duration_seconds=log["duration_seconds"],
                    metadata=log["metadata"],
                    created_at=log["created_at"],
                )
                for log in result["items"]
            ]

            # Calculate total pages
            total_pages = (result["total"] + filters.page_size - 1) // filters.page_size

            # Build response
            response = AuditLogListResponse(
                items=audit_logs,
                total=result["total"],
                page=filters.page,
                page_size=filters.page_size,
                total_pages=total_pages,
            )

            # Log operation (don't create audit log for viewing audit logs)
            duration = time.perf_counter() - start_time
            self.logger.info(
                "Audit logs retrieved",
                extra={
                    "user_id": user_id,
                    "page": filters.page,
                    "page_size": filters.page_size,
                    "total": result["total"],
                    "duration_ms": duration * 1000,
                },
            )

            return response

        except Exception as e:
            duration = time.perf_counter() - start_time
            self.logger.error(
                "Get audit logs failed",
                extra={
                    "operation": "get_audit_logs",
                    "user_id": user_id,
                    "error": str(e),
                    "duration_ms": duration * 1000,
                },
                exc_info=True,
            )
            raise

    # Helper methods

    def _determine_health_status(
        self,
        warnings: list[str],
        connection_utilization: float,
        cache_hit_ratio: float | None,
    ) -> DatabaseHealthStatus:
        """Apply thresholds to determine overall health status.

        Uses settings-based thresholds to categorize database health.

        Rules:
        - UNHEALTHY: Connection pool > 90% OR cache hit ratio < 70%
        - DEGRADED: Connection pool > 75% OR cache hit ratio < 85% OR any warnings
        - HEALTHY: All metrics within normal range

        Args:
            warnings: List of warning messages
            connection_utilization: Connection pool utilization percentage (0-100)
            cache_hit_ratio: Cache hit ratio percentage (0-100), or None

        Returns:
            DatabaseHealthStatus enum value
        """
        # Critical conditions (UNHEALTHY)
        if connection_utilization > self.settings.connection_pool_critical_threshold:
            self._lazy.debug(
                lambda: f"UNHEALTHY: connection utilization {connection_utilization:.1f}% > {self.settings.connection_pool_critical_threshold}%",
            )
            return DatabaseHealthStatus.UNHEALTHY

        if cache_hit_ratio is not None and cache_hit_ratio < 70.0:
            self._lazy.debug(
                lambda: f"UNHEALTHY: cache hit ratio {cache_hit_ratio:.1f}% < 70%",
            )
            return DatabaseHealthStatus.UNHEALTHY

        # Warning conditions (DEGRADED)
        if connection_utilization > self.settings.connection_pool_warning_threshold:
            self._lazy.debug(
                lambda: f"DEGRADED: connection utilization {connection_utilization:.1f}% > {self.settings.connection_pool_warning_threshold}%",
            )
            return DatabaseHealthStatus.DEGRADED

        if cache_hit_ratio is not None and cache_hit_ratio < self.settings.cache_hit_ratio_warning_threshold:
            self._lazy.debug(
                lambda: f"DEGRADED: cache hit ratio {cache_hit_ratio:.1f}% < {self.settings.cache_hit_ratio_warning_threshold}%",
            )
            return DatabaseHealthStatus.DEGRADED

        if warnings:
            self._lazy.debug(
                lambda: f"DEGRADED: {len(warnings)} warnings present",
            )
            return DatabaseHealthStatus.DEGRADED

        # All metrics normal (HEALTHY)
        self._lazy.debug(lambda: "HEALTHY: all metrics within normal range")
        return DatabaseHealthStatus.HEALTHY

    async def _check_rate_limit(self, user_id: str, operation: str) -> None:
        """Check if user has exceeded rate limit for operation.

        Uses simple in-memory sliding window rate limiting. Can be upgraded
        to Redis-based rate limiting for distributed deployments.

        Args:
            user_id: User performing the operation
            operation: Operation name being performed

        Raises:
            HTTPException: 429 if rate limit exceeded
        """
        if not self.settings.rate_limit_enabled:
            return

        now = time.time()
        window_seconds = self.settings.rate_limit_window_seconds
        max_ops = self.settings.rate_limit_max_ops

        # Get user's operation history
        user_ops = self._rate_limiter[user_id][operation]

        # Remove timestamps outside the window
        cutoff = now - window_seconds
        user_ops[:] = [ts for ts in user_ops if ts > cutoff]

        # Check if limit exceeded
        if len(user_ops) >= max_ops:
            from fastapi import HTTPException, status

            self.logger.warning(
                "Rate limit exceeded",
                extra={
                    "user_id": user_id,
                    "operation": operation,
                    "count": len(user_ops),
                    "max_ops": max_ops,
                    "window_seconds": window_seconds,
                },
            )

            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded: {max_ops} operations per {window_seconds}s",
            )

        # Record this operation
        user_ops.append(now)

    async def _log_operation(
        self,
        session: AsyncSession,
        action: str,
        target: str,
        user_id: str,
        result: str,
        duration: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Log admin operation to audit table.

        Creates an audit log entry for compliance and operational tracking.

        Args:
            session: Database session for insert
            action: Action performed (e.g., "get_health", "vacuum_table")
            target: Target resource (e.g., "database", table name)
            user_id: User who performed the action
            result: Operation result ("success", "failure", "dry_run")
            duration: How long the operation took (seconds)
            metadata: Additional context and parameters
        """
        try:
            await self.repository.log_admin_action(
                session,
                id=str(uuid.uuid4()),
                action=action,
                target=target,
                user_id=user_id,
                tenant_id=None,  # Not tenant-scoped in this context
                result=result,
                duration_seconds=round(duration, 3),
                metadata=metadata or {},
                created_at=datetime.now(UTC),
            )
        except Exception as e:
            # Don't fail the operation if audit logging fails
            self.logger.error(
                "Failed to log admin operation",
                extra={
                    "action": action,
                    "target": target,
                    "user_id": user_id,
                    "error": str(e),
                },
                exc_info=True,
            )


# Factory function (services are typically created per-request)
def get_database_admin_service(
    repository: DatabaseAdminRepository,
    settings: AdminSettings,
) -> DatabaseAdminService:
    """Get DatabaseAdminService instance.

    Note: Unlike repositories, services are typically created per-request
    via dependency injection rather than as singletons. This function
    provides a simple factory for service creation.

    Args:
        repository: DatabaseAdminRepository instance
        settings: AdminSettings instance

    Returns:
        DatabaseAdminService instance

    Example:
        In FastAPI dependencies:

        def get_service(
            repo: DatabaseAdminRepository = Depends(get_database_admin_repository),
            settings: AdminSettings = Depends(get_admin_settings),
        ) -> DatabaseAdminService:
            return get_database_admin_service(repo, settings)
    """
    return DatabaseAdminService(repository, settings)


__all__ = [
    "DatabaseAdminService",
    "get_database_admin_service",
]
