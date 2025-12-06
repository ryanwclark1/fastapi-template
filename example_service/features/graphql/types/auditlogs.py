"""GraphQL types for audit logs.

Provides Strawberry GraphQL types for audit log queries with full Pydantic integration.
Audit logs are read-only and created automatically by the system.

Auto-generated from Pydantic schemas:
- AuditLogType: Auto-generated from AuditLogResponse
"""

from __future__ import annotations

import strawberry

from example_service.features.audit.models import AuditAction as ModelAuditAction
from example_service.features.audit.schemas import AuditLogResponse
from example_service.features.graphql.types.base import PageInfoType
from example_service.features.graphql.types.pydantic_bridge import (
    pydantic_field,
    pydantic_type,
)

# ============================================================================
# Enums
# ============================================================================


# Use the model's AuditAction enum directly
AuditAction = strawberry.enum(ModelAuditAction, description="Audit action types")

# ============================================================================
# Audit Log Type (Output)
# ============================================================================


@pydantic_type(model=AuditLogResponse, description="An audit log entry tracking a system action")
class AuditLogType:
    """Audit log type auto-generated from AuditLogResponse Pydantic schema.

    Audit logs provide:
    - Complete action history with before/after state
    - User and tenant context for compliance
    - Request correlation via request_id
    - Performance tracking via duration_ms
    - Error details for failed operations

    All fields are auto-generated from the Pydantic AuditLogResponse schema.
    """

    # Override ID field
    id: strawberry.ID = pydantic_field(description="Unique identifier for the audit log")

    # Override old_values, new_values, changes, metadata as JSON
    @strawberry.field(description="Previous state (for updates/deletes)")
    def old_values(self) -> strawberry.scalars.JSON | None:
        """Get old values as JSON."""
        if hasattr(self, "_old_values"):
            return self._old_values
        return None

    @strawberry.field(description="New state (for creates/updates)")
    def new_values(self) -> strawberry.scalars.JSON | None:
        """Get new values as JSON."""
        if hasattr(self, "_new_values"):
            return self._new_values
        return None

    @strawberry.field(description="Changed fields with old/new values")
    def changes(self) -> strawberry.scalars.JSON | None:
        """Get changes as JSON."""
        if hasattr(self, "_changes"):
            return self._changes
        return None

    @strawberry.field(description="Additional context data")
    def metadata(self) -> strawberry.scalars.JSON | None:
        """Get metadata as JSON."""
        if hasattr(self, "_metadata"):
            return self._metadata
        return None

    # Computed fields
    @strawberry.field(description="Whether this action modified data")
    def is_mutation(self) -> bool:
        """Check if this action was a data mutation.

        Returns:
            True if action was create, update, delete, or bulk operation
        """
        if hasattr(self, "action"):
            mutation_actions = {
                ModelAuditAction.CREATE.value,
                ModelAuditAction.UPDATE.value,
                ModelAuditAction.DELETE.value,
                ModelAuditAction.BULK_CREATE.value,
                ModelAuditAction.BULK_UPDATE.value,
                ModelAuditAction.BULK_DELETE.value,
            }
            return self.action in mutation_actions
        return False


# ============================================================================
# Edge and Connection Types for Pagination
# ============================================================================


@strawberry.type(description="Edge containing an audit log node and cursor")
class AuditLogEdge:
    """Edge in a Relay-style connection."""

    node: AuditLogType
    cursor: str


@strawberry.type(description="Paginated list of audit logs")
class AuditLogConnection:
    """Relay-style connection for audit log pagination."""

    edges: list[AuditLogEdge]
    page_info: PageInfoType


__all__ = [
    # Enums
    "AuditAction",
    "AuditLogConnection",
    # Pagination
    "AuditLogEdge",
    # Types
    "AuditLogType",
]
