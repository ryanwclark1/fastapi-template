"""Schemas for database administration endpoints.

This module provides response schemas for:
- Database health monitoring
- Connection pool statistics
- Table and index health information
- Active query monitoring
- Database statistics and metrics
- Admin audit logging
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from example_service.utils.runtime_dependencies import require_runtime_dependency

require_runtime_dependency(datetime)


class DatabaseHealthStatus(str, Enum):
    """Database health status enumeration.

    Indicates overall database health based on connection pool utilization,
    cache hit ratios, replication lag, and other health metrics.
    """

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class ConnectionPoolStats(BaseModel):
    """Statistics for database connection pool.

    Provides real-time metrics about connection pool state including
    active, idle, and total connections for capacity planning and
    performance monitoring.

    Example:
        {
            "active_connections": 8,
            "idle_connections": 12,
            "total_connections": 20,
            "max_connections": 100,
            "utilization_percent": 20.0
        }
    """

    active_connections: int = Field(
        ge=0,
        description="Number of connections currently in use",
    )
    idle_connections: int = Field(
        ge=0,
        description="Number of idle connections in the pool",
    )
    total_connections: int = Field(
        ge=0,
        description="Total number of connections (active + idle)",
    )
    max_connections: int = Field(
        ge=1,
        description="Maximum allowed connections in the pool",
    )
    utilization_percent: float = Field(
        ge=0.0,
        le=100.0,
        description="Percentage of connection pool being utilized",
    )


class DatabaseHealth(BaseModel):
    """Comprehensive database health check response.

    Provides a snapshot of database health including connection pool status,
    database size, cache performance, and replication status.

    Example:
        {
            "status": "healthy",
            "timestamp": "2025-12-10T14:30:00Z",
            "connection_pool": {
                "active_connections": 8,
                "idle_connections": 12,
                "total_connections": 20,
                "max_connections": 100,
                "utilization_percent": 20.0
            },
            "database_size_bytes": 2684354560,
            "database_size_human": "2.5 GB",
            "active_connections_count": 15,
            "cache_hit_ratio": 0.98,
            "replication_lag_seconds": 0.5,
            "warnings": []
        }
    """

    status: DatabaseHealthStatus = Field(
        description="Overall database health status",
    )
    timestamp: datetime = Field(
        description="Timestamp when health check was performed",
    )
    connection_pool: ConnectionPoolStats = Field(
        description="Connection pool statistics",
    )
    database_size_bytes: int = Field(
        ge=0,
        description="Total database size in bytes",
    )
    database_size_human: str = Field(
        description="Human-readable database size (e.g., '2.5 GB')",
    )
    active_connections_count: int = Field(
        ge=0,
        description="Number of active database connections",
    )
    cache_hit_ratio: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Database cache hit ratio (0.0-1.0), higher is better",
    )
    replication_lag_seconds: float | None = Field(
        default=None,
        ge=0.0,
        description="Replication lag in seconds (null if not using replication)",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="List of health warnings or issues detected",
    )


class TableSizeInfo(BaseModel):
    """Information about table size and row count.

    Provides detailed size metrics for a database table including
    row count, total size (table + indexes), and size breakdown.

    Example:
        {
            "table_name": "users",
            "schema_name": "public",
            "row_count": 150000,
            "total_size_bytes": 52428800,
            "total_size_human": "50 MB",
            "table_size_bytes": 41943040,
            "indexes_size_bytes": 10485760
        }
    """

    table_name: str = Field(
        min_length=1,
        max_length=255,
        description="Name of the database table",
    )
    schema_name: str = Field(
        min_length=1,
        max_length=255,
        description="Database schema containing the table",
    )
    row_count: int = Field(
        ge=0,
        description="Approximate number of rows in the table",
    )
    total_size_bytes: int = Field(
        ge=0,
        description="Total size of table including indexes in bytes",
    )
    total_size_human: str = Field(
        description="Human-readable total size (e.g., '50 MB')",
    )
    table_size_bytes: int = Field(
        ge=0,
        description="Size of table data only in bytes",
    )
    indexes_size_bytes: int = Field(
        ge=0,
        description="Total size of all indexes in bytes",
    )


class IndexHealthInfo(BaseModel):
    """Health and performance metrics for database indexes.

    Provides detailed information about index health including size,
    usage statistics, bloat, and validity status for performance
    monitoring and maintenance planning.

    Example:
        {
            "index_name": "idx_users_email",
            "table_name": "users",
            "index_size_bytes": 10485760,
            "index_size_human": "10 MB",
            "index_scans": 45000,
            "bloat_percent": 15.5,
            "is_valid": true,
            "definition": "CREATE INDEX idx_users_email ON users (email)"
        }
    """

    index_name: str = Field(
        min_length=1,
        max_length=255,
        description="Name of the database index",
    )
    table_name: str = Field(
        min_length=1,
        max_length=255,
        description="Table that the index belongs to",
    )
    index_size_bytes: int = Field(
        ge=0,
        description="Size of the index in bytes",
    )
    index_size_human: str = Field(
        description="Human-readable index size (e.g., '10 MB')",
    )
    index_scans: int = Field(
        ge=0,
        description="Number of times the index has been scanned",
    )
    bloat_percent: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="Estimated index bloat percentage (null if unavailable)",
    )
    is_valid: bool = Field(
        description="Whether the index is valid and can be used by queries",
    )
    definition: str = Field(
        description="SQL definition of the index",
    )


class ActiveQuery(BaseModel):
    """Information about an active database query.

    Provides details about currently executing queries including
    duration, state, and wait events for performance monitoring
    and troubleshooting.

    Example:
        {
            "pid": 12345,
            "user": "app_user",
            "database": "production",
            "state": "active",
            "query": "SELECT * FROM users WHERE email = $1",
            "duration_seconds": 2.5,
            "wait_event": "ClientRead"
        }
    """

    pid: int = Field(
        ge=1,
        description="Process ID of the database backend",
    )
    user: str = Field(
        min_length=1,
        max_length=255,
        description="Database user executing the query",
    )
    database: str = Field(
        min_length=1,
        max_length=255,
        description="Database name where query is executing",
    )
    state: str = Field(
        description="Query state (active, idle, idle in transaction, etc.)",
    )
    query: str = Field(
        description="SQL query text being executed",
    )
    duration_seconds: float = Field(
        ge=0.0,
        description="How long the query has been running in seconds",
    )
    wait_event: str | None = Field(
        default=None,
        description="Wait event if query is waiting (null if not waiting)",
    )


class DatabaseStats(BaseModel):
    """Summary statistics for database metrics.

    Provides an overview of database statistics including size,
    object counts, performance metrics, and top tables by size
    for monitoring and capacity planning.

    Example:
        {
            "total_size_bytes": 5368709120,
            "total_size_human": "5.0 GB",
            "table_count": 45,
            "index_count": 123,
            "cache_hit_ratio": 0.98,
            "transaction_rate": 1500.0,
            "top_tables": [...],
            "slow_queries_count": 5
        }
    """

    total_size_bytes: int = Field(
        ge=0,
        description="Total database size in bytes",
    )
    total_size_human: str = Field(
        description="Human-readable total size (e.g., '5.0 GB')",
    )
    table_count: int = Field(
        ge=0,
        description="Total number of tables in the database",
    )
    index_count: int = Field(
        ge=0,
        description="Total number of indexes in the database",
    )
    cache_hit_ratio: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Database cache hit ratio (0.0-1.0), null if unavailable",
    )
    transaction_rate: float = Field(
        ge=0.0,
        description="Transactions per second over recent time window",
    )
    top_tables: list[TableSizeInfo] = Field(
        default_factory=list,
        description="List of largest tables by total size",
    )
    slow_queries_count: int = Field(
        ge=0,
        description="Number of slow queries detected in recent time window",
    )


class AdminAuditLog(BaseModel):
    """Audit log entry for administrative database actions.

    Records administrative actions performed on the database for
    compliance, security auditing, and operational tracking.

    Example:
        {
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "action": "vacuum_table",
            "target": "users",
            "user_id": "admin_user_123",
            "tenant_id": "tenant_abc",
            "result": "success",
            "duration_seconds": 45.2,
            "metadata": {
                "table_name": "users",
                "vacuum_type": "full"
            },
            "created_at": "2025-12-10T14:30:00Z"
        }
    """

    id: str = Field(
        description="Unique audit log entry ID",
    )
    action: str = Field(
        min_length=1,
        max_length=100,
        description="Administrative action performed",
    )
    target: str = Field(
        min_length=1,
        max_length=255,
        description="Target of the action (table, index, database, etc.)",
    )
    user_id: str = Field(
        min_length=1,
        max_length=255,
        description="ID of the user who performed the action",
    )
    tenant_id: str | None = Field(
        default=None,
        max_length=255,
        description="Tenant ID if action was tenant-scoped",
    )
    result: str = Field(
        description="Result of the action (success, failure, partial)",
    )
    duration_seconds: float | None = Field(
        default=None,
        ge=0.0,
        description="How long the action took to complete in seconds",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional context and parameters for the action",
    )
    created_at: datetime = Field(
        description="Timestamp when the action was performed",
    )

    model_config = {"from_attributes": True}


class AuditLogFilters(BaseModel):
    """Query parameters for filtering admin audit logs.

    Provides filtering and pagination options for querying
    administrative audit logs.

    Example:
        {
            "action_type": "vacuum_table",
            "user_id": "admin_user_123",
            "start_date": "2025-12-01T00:00:00Z",
            "end_date": "2025-12-10T23:59:59Z",
            "page": 1,
            "page_size": 50
        }
    """

    action_type: str | None = Field(
        default=None,
        max_length=100,
        description="Filter by specific action type",
    )
    user_id: str | None = Field(
        default=None,
        max_length=255,
        description="Filter by user ID who performed the action",
    )
    start_date: datetime | None = Field(
        default=None,
        description="Filter logs created on or after this date",
    )
    end_date: datetime | None = Field(
        default=None,
        description="Filter logs created on or before this date",
    )
    page: int = Field(
        default=1,
        ge=1,
        description="Page number for pagination (1-indexed)",
    )
    page_size: int = Field(
        default=50,
        ge=1,
        le=100,
        description="Number of items per page (max 100)",
    )


class AuditLogListResponse(BaseModel):
    """Response schema for paginated admin audit log list.

    Example:
        {
            "items": [...],
            "total": 150,
            "page": 1,
            "page_size": 50,
            "total_pages": 3
        }
    """

    items: list[AdminAuditLog] = Field(
        default_factory=list,
        description="List of audit log entries for the current page",
    )
    total: int = Field(
        ge=0,
        description="Total number of audit log entries matching filters",
    )
    page: int = Field(
        ge=1,
        description="Current page number",
    )
    page_size: int = Field(
        ge=1,
        le=100,
        description="Number of items per page",
    )
    total_pages: int = Field(
        ge=0,
        description="Total number of pages available",
    )


__all__ = [
    "ActiveQuery",
    "AdminAuditLog",
    "AuditLogFilters",
    "AuditLogListResponse",
    "ConnectionPoolStats",
    "DatabaseHealth",
    "DatabaseHealthStatus",
    "DatabaseStats",
    "IndexHealthInfo",
    "TableSizeInfo",
]
