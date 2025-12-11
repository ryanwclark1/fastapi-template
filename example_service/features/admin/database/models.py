"""Database models for admin database features.

Provides models for:
- AdminAuditLog: Audit trail for administrative database operations
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from example_service.core.database.base import Base, UUIDv7PKMixin
from example_service.utils.runtime_dependencies import require_runtime_dependency

require_runtime_dependency(datetime)


class AdminAuditLog(Base, UUIDv7PKMixin):
    """Audit log for administrative database operations.

    Records administrative actions performed on the database for compliance,
    security auditing, and operational tracking. Unlike the general AuditLog,
    this tracks system-level database operations like VACUUM, REINDEX, ANALYZE, etc.

    Uses UUIDv7 for time-sortable primary keys, making it efficient to query
    recent administrative actions.

    Attributes:
        id: Time-sortable UUID (UUIDv7)
        action: Administrative action type (vacuum_table, reindex, analyze, etc.)
        target: Target resource (table name, index name, database name, etc.)
        user_id: ID of the admin user who performed the action
        tenant_id: Tenant ID if action was tenant-scoped (nullable for global actions)
        result: Operation result (success, failure, dry_run, partial)
        duration_seconds: How long the operation took to complete
        metadata: Additional context (parameters, errors, statistics, etc.)
        created_at: When the action was performed

    Indexes:
        - created_at: For time-range queries
        - action: For filtering by action type
        - user_id: For tracking admin actions by user
        - tenant_id: For filtering by tenant (when applicable)
        - (tenant_id, created_at): Composite for efficient tenant-scoped queries
        - (action, created_at): Composite for efficient action-scoped queries

    Example:
        import uuid
        from datetime import UTC, datetime

        audit = AdminAuditLog(
            id=str(uuid.uuid4()),
            action="vacuum_table",
            target="users",
            user_id="admin_123",
            tenant_id="tenant_abc",
            result="success",
            duration_seconds=45.2,
            metadata={
                "table_name": "users",
                "vacuum_type": "full",
                "pages_removed": 1250,
                "tuples_removed": 50000,
            },
            created_at=datetime.now(UTC),
        )
    """

    __tablename__ = "admin_audit_log"

    # Action type (indexed for filtering by operation type)
    action: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Administrative action performed (vacuum_table, reindex, analyze, etc.)",
    )

    # Target resource
    target: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Target of the action (table, index, database, etc.)",
    )

    # User context (indexed for tracking admin actions by user)
    user_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="ID of the admin user who performed the action",
    )

    # Tenant context (nullable for global operations, indexed for filtering)
    tenant_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="Tenant ID if action was tenant-scoped",
    )

    # Operation result
    result: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Result of the action (success, failure, dry_run, partial)",
    )

    # Performance metrics
    duration_seconds: Mapped[float | None] = mapped_column(
        nullable=True,
        comment="How long the operation took to complete in seconds",
    )

    # Additional context (JSONB for flexible metadata storage)
    # Note: Using 'context_metadata' instead of 'metadata' to avoid conflict with
    # SQLAlchemy's reserved 'metadata' attribute on Base class
    context_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",  # Column name in database remains "metadata"
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
        comment="Additional context and parameters for the action",
    )

    # Timestamp (indexed for time-range queries)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        server_default=func.now(),
        nullable=False,
        index=True,
        comment="When the action was performed",
    )

    # Composite indexes for common query patterns
    __table_args__ = (
        # Tenant + time range queries (most common for tenant-scoped operations)
        Index(
            "ix_admin_audit_log_tenant_created",
            "tenant_id",
            "created_at",
            postgresql_where="tenant_id IS NOT NULL",
        ),
        # Action + time range queries (for filtering by operation type over time)
        Index("ix_admin_audit_log_action_created", "action", "created_at"),
        # User + time range queries (for tracking admin activity)
        Index("ix_admin_audit_log_user_created", "user_id", "created_at"),
    )

    def __repr__(self) -> str:
        """String representation of admin audit log entry."""
        return (
            f"<AdminAuditLog(id={self.id}, action={self.action}, "
            f"target={self.target}, result={self.result})>"
        )


__all__ = ["AdminAuditLog"]
