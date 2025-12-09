"""Audit log Pydantic schemas.

Provides request/response schemas for the audit logging API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, TypedDict
from uuid import UUID

from pydantic import BaseModel, Field

from .models import AuditAction


class AuditLogCreate(BaseModel):
    """Schema for creating an audit log entry."""

    action: AuditAction = Field(description="Type of action performed")
    entity_type: str = Field(
        min_length=1,
        max_length=100,
        description="Type of entity affected",
    )
    entity_id: str | None = Field(
        default=None,
        max_length=255,
        description="ID of the affected entity",
    )
    user_id: str | None = Field(
        default=None,
        max_length=255,
        description="User who performed the action",
    )
    actor_roles: list[str] | None = Field(
        default=None,
        description="Roles the user had at time of action (for compliance audits)",
    )
    tenant_id: str | None = Field(
        default=None,
        max_length=255,
        description="Tenant context",
    )
    old_values: dict[str, Any] | None = Field(
        default=None,
        description="Previous state",
    )
    new_values: dict[str, Any] | None = Field(
        default=None,
        description="New state",
    )
    ip_address: str | None = Field(
        default=None,
        max_length=45,
        description="Client IP address",
    )
    user_agent: str | None = Field(
        default=None,
        max_length=500,
        description="Client user agent",
    )
    request_id: str | None = Field(
        default=None,
        max_length=100,
        description="Request correlation ID",
    )
    endpoint: str | None = Field(
        default=None,
        max_length=255,
        description="API endpoint path",
    )
    method: str | None = Field(
        default=None,
        max_length=10,
        description="HTTP method",
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Additional context data",
        validation_alias="context_data",
        serialization_alias="metadata",
    )
    success: bool = Field(
        default=True,
        description="Whether the action succeeded",
    )
    error_message: str | None = Field(
        default=None,
        description="Error details if action failed",
    )
    duration_ms: int | None = Field(
        default=None,
        ge=0,
        description="Action duration in milliseconds",
    )

    model_config = {"populate_by_name": True}


class AuditLogResponse(BaseModel):
    """Schema for audit log response."""

    id: UUID = Field(description="Unique audit log ID")
    timestamp: datetime = Field(description="When the action occurred")
    action: str = Field(description="Type of action performed")
    entity_type: str = Field(description="Type of entity affected")
    entity_id: str | None = Field(description="ID of the affected entity")
    user_id: str | None = Field(description="User who performed the action")
    actor_roles: list[str] = Field(default_factory=list, description="Roles user had at time of action")
    tenant_id: str | None = Field(description="Tenant context")
    old_values: dict[str, Any] | None = Field(description="Previous state")
    new_values: dict[str, Any] | None = Field(description="New state")
    changes: dict[str, Any] | None = Field(description="Changed fields")
    ip_address: str | None = Field(description="Client IP address")
    user_agent: str | None = Field(description="Client user agent")
    request_id: str | None = Field(description="Request correlation ID")
    endpoint: str | None = Field(description="API endpoint path")
    method: str | None = Field(description="HTTP method")
    metadata: dict[str, Any] | None = Field(
        description="Additional context",
        validation_alias="context_data",
        serialization_alias="metadata",
    )
    success: bool = Field(description="Whether the action succeeded")
    error_message: str | None = Field(description="Error details if failed")
    duration_ms: int | None = Field(description="Action duration in milliseconds")

    model_config = {"from_attributes": True, "populate_by_name": True}


class AuditLogQuery(BaseModel):
    """Schema for querying audit logs."""

    # Filters
    entity_type: str | None = Field(
        default=None,
        description="Filter by entity type",
    )
    entity_id: str | None = Field(
        default=None,
        description="Filter by entity ID",
    )
    user_id: str | None = Field(
        default=None,
        description="Filter by user ID",
    )
    tenant_id: str | None = Field(
        default=None,
        description="Filter by tenant ID",
    )
    action: AuditAction | None = Field(
        default=None,
        description="Filter by action type",
    )
    actions: list[AuditAction] | None = Field(
        default=None,
        description="Filter by multiple action types",
    )
    success: bool | None = Field(
        default=None,
        description="Filter by success status",
    )
    request_id: str | None = Field(
        default=None,
        description="Filter by request ID",
    )

    # Time range
    start_time: datetime | None = Field(
        default=None,
        description="Start of time range",
    )
    end_time: datetime | None = Field(
        default=None,
        description="End of time range",
    )

    # Pagination
    limit: int = Field(
        default=50,
        ge=1,
        le=1000,
        description="Maximum results to return",
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Number of results to skip",
    )

    # Sorting
    order_by: str = Field(
        default="timestamp",
        description="Field to sort by",
    )
    order_desc: bool = Field(
        default=True,
        description="Sort in descending order",
    )


class AuditLogListResponse(BaseModel):
    """Schema for paginated audit log list response."""

    items: list[AuditLogResponse] = Field(description="Audit log entries")
    total: int = Field(description="Total number of matching entries")
    limit: int = Field(description="Results per page")
    offset: int = Field(description="Current offset")
    has_more: bool = Field(description="Whether more results exist")


class AuditSummary(BaseModel):
    """Summary statistics for audit logs."""

    total_entries: int = Field(description="Total audit log entries")
    actions_count: dict[str, int] = Field(description="Count by action type")
    entity_types_count: dict[str, int] = Field(description="Count by entity type")
    success_rate: float = Field(description="Percentage of successful actions")
    unique_users: int = Field(description="Number of unique users")
    dangerous_actions_count: int = Field(
        default=0,
        description="Number of dangerous actions (deletes, revokes, suspensions)",
    )
    time_range_start: datetime | None = Field(description="Earliest entry")
    time_range_end: datetime | None = Field(description="Latest entry")


class DangerousActionsResponse(BaseModel):
    """Response for dangerous actions query."""

    items: list[AuditLogResponse] = Field(description="Dangerous audit log entries")
    total: int = Field(description="Total number of matching entries")
    limit: int = Field(description="Results per page")
    offset: int = Field(description="Current offset")
    has_more: bool = Field(description="Whether more results exist")


class EntityAuditHistory(BaseModel):
    """Audit history for a specific entity."""

    entity_type: str = Field(description="Entity type")
    entity_id: str = Field(description="Entity ID")
    entries: list[AuditLogResponse] = Field(description="Audit entries")
    created_at: datetime | None = Field(description="When entity was created")
    created_by: str | None = Field(description="Who created the entity")
    last_modified_at: datetime | None = Field(description="Last modification time")
    last_modified_by: str | None = Field(description="Who last modified")
    total_changes: int = Field(description="Total number of changes")


class AuditSummaryStats(TypedDict):
    """TypedDict for audit repository summary statistics.

    This represents the raw statistics returned by the repository layer,
    which differs from AuditSummary (used in the service/API layer) in that
    it includes success_count and time_range tuple instead of success_rate
    and separate time_range fields.
    """

    total_entries: int
    actions_count: dict[str, int]
    entity_types_count: dict[str, int]
    success_count: int
    unique_users: int
    time_range: tuple[datetime | None, datetime | None]
