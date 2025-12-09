"""Email configuration management feature.

This package provides API endpoints for:
- Managing tenant email configurations
- Testing email configurations
- Viewing usage statistics and audit logs

Structure:
- models.py: Database models (EmailConfig, EmailUsageLog, EmailAuditLog)
- repository.py: Data access layer
- service.py: Business logic layer
- dependencies.py: FastAPI dependency injection
- schemas.py: Pydantic request/response schemas
- router.py: API endpoints
"""

from __future__ import annotations

from example_service.features.email.dependencies import (
    EmailConfigServiceDep,
    EnhancedEmailServiceDep,
    SessionDep,
)
from example_service.features.email.models import (
    EmailAuditLog,
    EmailConfig,
    EmailProviderType,
    EmailUsageLog,
)
from example_service.features.email.repository import (
    EmailAuditLogRepository,
    EmailConfigRepository,
    EmailUsageLogRepository,
    get_email_audit_log_repository,
    get_email_config_repository,
    get_email_usage_log_repository,
)
from example_service.features.email.router import router
from example_service.features.email.service import EmailConfigService

__all__ = [
    "EmailAuditLog",
    "EmailAuditLogRepository",
    "EmailConfig",
    "EmailConfigRepository",
    "EmailConfigService",
    "EmailConfigServiceDep",
    "EmailProviderType",
    "EmailUsageLog",
    "EmailUsageLogRepository",
    "EnhancedEmailServiceDep",
    "SessionDep",
    "get_email_audit_log_repository",
    "get_email_config_repository",
    "get_email_usage_log_repository",
    "router",
]
