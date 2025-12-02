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

from .models import AuditAction, AuditLog
from .schemas import AuditLogCreate, AuditLogResponse, AuditLogQuery
from .service import AuditService, get_audit_service
from .decorators import audited, audit_action
from .router import router

__all__ = [
    # Models
    "AuditLog",
    "AuditAction",
    # Schemas
    "AuditLogCreate",
    "AuditLogResponse",
    "AuditLogQuery",
    # Service
    "AuditService",
    "get_audit_service",
    # Decorators
    "audited",
    "audit_action",
    # Router
    "router",
]
