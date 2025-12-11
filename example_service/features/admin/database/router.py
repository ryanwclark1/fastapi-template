"""Admin endpoints for database administration.

This module provides administrative endpoints for:
- Database health monitoring
- Connection pool statistics
- Table and index health metrics
- Active query monitoring
- Admin operation audit logs
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from example_service.core.dependencies.auth import SuperuserDep
from example_service.features.admin.database.dependencies import (
    AdminServiceDep,
    SessionDep,
)
from example_service.features.admin.database.schemas import (
    ActiveQuery,
    AuditLogFilters,
    AuditLogListResponse,
    DatabaseHealth,
    DatabaseStats,
    IndexHealthInfo,
    TableSizeInfo,
)
from example_service.utils.runtime_dependencies import require_runtime_dependency

require_runtime_dependency(SuperuserDep, AdminServiceDep, SessionDep)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/database", tags=["admin-database"])


# =============================================================================
# Health & Statistics Endpoints
# =============================================================================


@router.get(
    "/health",
    response_model=DatabaseHealth,
    summary="Get database health status",
    description="Get comprehensive database health including connection pool, cache hit ratio, and overall status.",
    responses={
        200: {"description": "Health status retrieved successfully"},
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized (requires superuser)"},
        500: {"description": "Internal server error"},
    },
)
async def get_database_health(
    service: AdminServiceDep,
    session: SessionDep,
    user: SuperuserDep,
) -> DatabaseHealth:
    """Get database health status.

    Requires superuser/admin access.

    Returns comprehensive health check including:
    - Overall status (healthy, degraded, unhealthy)
    - Connection pool statistics and utilization
    - Database size metrics
    - Cache hit ratio performance
    - Replication lag (if applicable)
    - Health warnings and recommendations

    Returns:
        DatabaseHealth with status, connection pool, cache ratio, warnings
    """
    return await service.get_health(session, user_id=user.user_id)


@router.get(
    "/stats",
    response_model=DatabaseStats,
    summary="Get database statistics",
    description="Get detailed database metrics including table counts, transaction rates, and cache statistics.",
    responses={
        200: {"description": "Statistics retrieved successfully"},
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized (requires superuser)"},
        500: {"description": "Internal server error"},
    },
)
async def get_database_stats(
    service: AdminServiceDep,
    session: SessionDep,
    user: SuperuserDep,
) -> DatabaseStats:
    """Get database statistics summary.

    Requires superuser/admin access.

    Returns comprehensive database statistics including:
    - Total database size and growth metrics
    - Table and index counts
    - Cache hit ratio and performance metrics
    - Transaction rate statistics
    - Top tables by size
    - Slow query counts

    Returns:
        DatabaseStats with comprehensive metrics and top tables
    """
    return await service.get_stats(session, user_id=user.user_id)


# =============================================================================
# Connection & Query Monitoring
# =============================================================================


@router.get(
    "/connections",
    response_model=list[ActiveQuery],
    summary="List active database connections",
    description="Shows currently active queries with duration and state.",
    responses={
        200: {"description": "Active connections retrieved successfully"},
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized (requires superuser)"},
        500: {"description": "Internal server error"},
    },
)
async def get_active_connections(
    service: AdminServiceDep,
    session: SessionDep,
    user: SuperuserDep,
    limit: Annotated[
        int,
        Query(ge=1, le=500, description="Maximum connections to return"),
    ] = 100,
) -> list[ActiveQuery]:
    """List active database connections.

    Requires superuser/admin access.

    Shows currently executing queries with:
    - Process ID and database user
    - Query state (active, idle, etc.)
    - SQL query text
    - Execution duration
    - Wait events (if blocked)

    Use this for:
    - Identifying long-running queries
    - Troubleshooting performance issues
    - Monitoring database activity

    Args:
        service: Database admin service handling the request.
        session: Database session dependency.
        user: Authenticated superuser performing the request.
        limit: Maximum number of connections to return (1-500, default: 100)

    Returns:
        List of active query information ordered by duration
    """
    return await service.get_connection_info(session, user_id=user.user_id, limit=limit)


# =============================================================================
# Table & Index Health
# =============================================================================


@router.get(
    "/tables/sizes",
    response_model=list[TableSizeInfo],
    summary="Get table sizes",
    description="Get tables sorted by total size with row counts and index sizes.",
    responses={
        200: {"description": "Table sizes retrieved successfully"},
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized (requires superuser)"},
        500: {"description": "Internal server error"},
    },
)
async def get_table_sizes(
    service: AdminServiceDep,
    session: SessionDep,
    user: SuperuserDep,
    limit: Annotated[
        int,
        Query(ge=1, le=100, description="Maximum tables to return"),
    ] = 50,
) -> list[TableSizeInfo]:
    """Get table sizes sorted by total size.

    Requires superuser/admin access.

    Returns detailed size information for each table:
    - Table name and schema
    - Approximate row count
    - Total size (table + indexes)
    - Table data size
    - Index size breakdown

    Useful for:
    - Capacity planning
    - Identifying tables that need archiving
    - Understanding storage distribution
    - Planning maintenance windows

    Args:
        service: Database admin service handling the request.
        session: Database session dependency.
        user: Authenticated superuser performing the request.
        limit: Maximum number of tables to return (1-100, default: 50)

    Returns:
        List of table size information ordered by total size descending
    """
    return await service.get_table_sizes(session, user_id=user.user_id, limit=limit)


@router.get(
    "/indexes/health",
    response_model=list[IndexHealthInfo],
    summary="Get index health",
    description="Get index usage statistics and health metrics.",
    responses={
        200: {"description": "Index health retrieved successfully"},
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized (requires superuser)"},
        500: {"description": "Internal server error"},
    },
)
async def get_index_health(
    service: AdminServiceDep,
    session: SessionDep,
    user: SuperuserDep,
    table_name: Annotated[str | None, Query(description="Filter by table name")] = None,
) -> list[IndexHealthInfo]:
    """Get index health and usage statistics.

    Requires superuser/admin access.

    Returns health metrics for database indexes:
    - Index name and associated table
    - Index size and bloat percentage
    - Number of index scans (usage metric)
    - Validity status
    - Index definition (SQL)

    Use this to:
    - Identify unused indexes (candidates for removal)
    - Detect bloated indexes (need reindexing)
    - Monitor index usage patterns
    - Plan index maintenance

    Args:
        service: Database admin service handling the request.
        session: Database session dependency.
        user: Authenticated superuser performing the request.
        table_name: Optional filter to show indexes for specific table only

    Returns:
        List of index health information with usage statistics
    """
    return await service.get_index_health(
        session,
        user_id=user.user_id,
        table_name=table_name,
    )


# =============================================================================
# Audit Logs
# =============================================================================


@router.get(
    "/audit-logs",
    response_model=AuditLogListResponse,
    summary="Get admin audit logs",
    description="Query admin operation audit logs with filtering and pagination.",
    responses={
        200: {"description": "Audit logs retrieved successfully"},
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized (requires superuser)"},
        500: {"description": "Internal server error"},
    },
)
async def get_audit_logs(
    service: AdminServiceDep,
    session: SessionDep,
    user: SuperuserDep,
    filters: Annotated[AuditLogFilters, Depends()],
) -> AuditLogListResponse:
    """Get admin operation audit logs.

    Requires superuser/admin access.

    Query audit logs of administrative database operations with:
    - Action type filtering (health_check, get_stats, etc.)
    - User ID filtering
    - Date range filtering
    - Pagination support

    Returns detailed audit trail including:
    - Action performed
    - Target (table, database, etc.)
    - User who performed the action
    - Result (success/failure)
    - Duration
    - Additional metadata

    Useful for:
    - Security auditing
    - Compliance reporting
    - Tracking admin activities
    - Troubleshooting issues

    Args:
        service: Database admin service handling the request.
        session: Database session dependency.
        user: Authenticated superuser performing the request.
        filters: Query parameters for filtering and pagination

    Returns:
        Paginated list of admin audit logs
    """
    return await service.get_audit_logs(session, user_id=user.user_id, filters=filters)
