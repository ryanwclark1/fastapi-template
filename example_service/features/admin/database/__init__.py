"""Database administration feature module.

This module provides administrative functionality for monitoring and
managing the database, including:
- Health monitoring and diagnostics
- Connection pool statistics
- Table and index health metrics
- Active query monitoring
- Database statistics and reporting
- Administrative audit logging

Components:
-----------
- models: ORM models for admin audit logging
- repository: Data access layer for database admin operations
- schemas: Pydantic models for request/response data
- dependencies: FastAPI dependency injection for repositories and services
- service: Business logic layer for database admin features
- router: FastAPI routes for database admin endpoints
"""

from .dependencies import AdminServiceDep, get_database_admin_service
from .models import AdminAuditLog as AdminAuditLogModel
from .repository import DatabaseAdminRepository, get_database_admin_repository
from .router import router
from .schemas import (
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
from .service import DatabaseAdminService

__all__ = [
    "ActiveQuery",
    "AdminAuditLog",
    "AdminAuditLogModel",
    "AdminServiceDep",
    "AuditLogFilters",
    "AuditLogListResponse",
    "ConnectionPoolStats",
    "DatabaseAdminRepository",
    "DatabaseAdminService",
    "DatabaseHealth",
    "DatabaseHealthStatus",
    "DatabaseStats",
    "IndexHealthInfo",
    "TableSizeInfo",
    "get_database_admin_repository",
    "get_database_admin_service",
    "router",
]
