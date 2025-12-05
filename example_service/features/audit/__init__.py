"""Audit logging feature.

Provides comprehensive audit logging for tracking:
- Entity changes (create, update, delete)
- User actions and authentication events
- API access patterns
- Security-relevant operations

Usage:
    from example_service.features.audit import get_audit_service, AuditAction

    # Log an action
    audit_service = get_audit_service()
    await audit_service.log(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="123",
        user_id="user-456",
        new_values={"title": "Meeting"},
    )

    # Use the decorator
    @audited("reminder")
    async def create_reminder(data: ReminderCreate) -> Reminder:
        ...
"""

from __future__ import annotations

from .decorators import AuditContext, audit_action, audited
from .models import AuditAction, AuditLog
from .repository import AuditRepository, get_audit_repository
from .router import router
from .schemas import (
    AuditLogCreate,
    AuditLogQuery,
    AuditLogResponse,
    AuditSummary,
    DangerousActionsResponse,
    EntityAuditHistory,
)
from .service import AuditService, get_audit_service

__all__ = [
    # Enums/Actions
    "AuditAction",
    "AuditContext",
    # Models
    "AuditLog",
    # Schemas
    "AuditLogCreate",
    "AuditLogQuery",
    "AuditLogResponse",
    # Repository
    "AuditRepository",
    # Service
    "AuditService",
    "AuditSummary",
    "DangerousActionsResponse",
    "EntityAuditHistory",
    # Decorators
    "audit_action",
    "audited",
    "get_audit_repository",
    "get_audit_service",
    # Router
    "router",
]
