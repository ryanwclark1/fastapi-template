"""Audit log database models.

Provides the AuditLog model for storing audit trail entries with:
- Entity identification (type, id)
- Action tracking (create, update, delete, etc.)
- User and tenant context
- Before/after state capture
- Request metadata (IP, user agent)
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from example_service.core.database.base import Base, UUIDv7PKMixin


class AuditAction(StrEnum):
    """Audit action types."""

    # CRUD operations
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"

    # Bulk operations
    BULK_CREATE = "bulk_create"
    BULK_UPDATE = "bulk_update"
    BULK_DELETE = "bulk_delete"

    # Export/Import
    EXPORT = "export"
    IMPORT = "import"

    # Authentication
    LOGIN = "login"
    LOGOUT = "logout"
    LOGIN_FAILED = "login_failed"
    PASSWORD_CHANGE = "password_change"
    TOKEN_REFRESH = "token_refresh"

    # Authorization
    PERMISSION_DENIED = "permission_denied"
    ACL_CHECK = "acl_check"

    # System operations
    ARCHIVE = "archive"
    RESTORE = "restore"
    PURGE = "purge"


class AuditLog(Base, UUIDv7PKMixin):
    """Audit log entry for tracking all significant actions.

    Uses UUIDv7 for time-sortable primary keys, making it efficient
    to query recent audit logs.

    Attributes:
        id: Time-sortable UUID (UUIDv7)
        timestamp: When the action occurred (indexed)
        action: Type of action (create, update, delete, etc.)
        entity_type: Type of entity affected (e.g., "reminder", "user")
        entity_id: ID of the affected entity
        user_id: ID of the user who performed the action
        tenant_id: Tenant context (for multi-tenant systems)
        old_values: JSON of previous state (for updates/deletes)
        new_values: JSON of new state (for creates/updates)
        changes: JSON of changed fields only (computed)
        ip_address: Client IP address
        user_agent: Client user agent string
        request_id: Request correlation ID
        metadata: Additional context data
        success: Whether the action succeeded
        error_message: Error details if action failed

    Example:
        audit = AuditLog(
            action=AuditAction.UPDATE,
            entity_type="reminder",
            entity_id="123e4567-e89b-12d3-a456-426614174000",
            user_id="user-456",
            old_values={"title": "Old Title"},
            new_values={"title": "New Title"},
            changes={"title": {"old": "Old Title", "new": "New Title"}},
        )
    """

    __tablename__ = "audit_logs"

    # Timestamp (indexed for efficient time-range queries)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        server_default=func.now(),
        nullable=False,
        index=True,
        comment="When the action occurred",
    )

    # Action type
    action: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="Type of action performed",
    )

    # Entity identification
    entity_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Type of entity affected",
    )
    entity_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="ID of the affected entity",
    )

    # User context
    user_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="User who performed the action",
    )
    tenant_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="Tenant context",
    )

    # State tracking
    old_values: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Previous state (for updates/deletes)",
    )
    new_values: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="New state (for creates/updates)",
    )
    changes: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Changed fields with old/new values",
    )

    # Request context
    ip_address: Mapped[str | None] = mapped_column(
        String(45),  # IPv6 max length
        nullable=True,
        comment="Client IP address",
    )
    user_agent: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="Client user agent",
    )
    request_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
        comment="Request correlation ID",
    )
    endpoint: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="API endpoint path",
    )
    method: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
        comment="HTTP method",
    )

    # Additional metadata
    metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Additional context data",
    )

    # Result tracking
    success: Mapped[bool] = mapped_column(
        default=True,
        nullable=False,
        comment="Whether the action succeeded",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Error details if action failed",
    )

    # Duration tracking
    duration_ms: Mapped[int | None] = mapped_column(
        nullable=True,
        comment="Action duration in milliseconds",
    )

    # Composite indexes for common query patterns
    __table_args__ = (
        # Query by entity
        Index("ix_audit_entity", "entity_type", "entity_id"),
        # Query by user and time
        Index("ix_audit_user_time", "user_id", "timestamp"),
        # Query by tenant and time
        Index("ix_audit_tenant_time", "tenant_id", "timestamp"),
        # Query by action and entity
        Index("ix_audit_action_entity", "action", "entity_type"),
    )

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"<AuditLog(id={self.id}, action={self.action}, "
            f"entity_type={self.entity_type}, entity_id={self.entity_id})>"
        )

    @classmethod
    def compute_changes(
        cls,
        old_values: dict[str, Any] | None,
        new_values: dict[str, Any] | None,
    ) -> dict[str, dict[str, Any]] | None:
        """Compute the changes dictionary from old and new values.

        Args:
            old_values: Previous state.
            new_values: New state.

        Returns:
            Dictionary of changed fields with old/new values.
        """
        if old_values is None or new_values is None:
            return None

        changes = {}
        all_keys = set(old_values.keys()) | set(new_values.keys())

        for key in all_keys:
            old_val = old_values.get(key)
            new_val = new_values.get(key)
            if old_val != new_val:
                changes[key] = {"old": old_val, "new": new_val}

        return changes if changes else None
