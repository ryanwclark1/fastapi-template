"""FastAPI dependencies for email feature.

Provides Annotated type aliases for clean dependency injection in route handlers.

Example usage:
    from example_service.features.email.dependencies import (
        EmailConfigServiceDep,
        SessionDep,
    )

    @router.get("/configs/{tenant_id}")
    async def get_config(
        tenant_id: str,
        session: SessionDep,
        service: EmailConfigServiceDep,
    ) -> EmailConfigResponse:
        config = await service.get_config(tenant_id)
        ...
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from example_service.core.dependencies.database import get_async_session
from example_service.features.email.repository import (
    EmailAuditLogRepository,
    EmailConfigRepository,
    EmailUsageLogRepository,
    get_email_audit_log_repository,
    get_email_config_repository,
    get_email_usage_log_repository,
)
from example_service.features.email.service import EmailConfigService
from example_service.infra.email import get_enhanced_email_service
from example_service.infra.email.enhanced_service import EnhancedEmailService

# Database session dependency
SessionDep = Annotated[AsyncSession, Depends(get_async_session)]

# Infrastructure service dependency
EnhancedEmailServiceDep = Annotated[EnhancedEmailService, Depends(get_enhanced_email_service)]

# Repository dependencies
EmailConfigRepositoryDep = Annotated[EmailConfigRepository, Depends(get_email_config_repository)]
EmailUsageLogRepositoryDep = Annotated[EmailUsageLogRepository, Depends(get_email_usage_log_repository)]
EmailAuditLogRepositoryDep = Annotated[EmailAuditLogRepository, Depends(get_email_audit_log_repository)]


async def get_email_config_service(
    session: SessionDep,
    email_service: EnhancedEmailServiceDep,
    config_repository: EmailConfigRepositoryDep,
    usage_repository: EmailUsageLogRepositoryDep,
    audit_repository: EmailAuditLogRepositoryDep,
) -> AsyncGenerator[EmailConfigService]:
    """Create EmailConfigService with injected dependencies.

    This factory function creates a service instance with all required
    dependencies injected by FastAPI's dependency injection system.

    Yields:
        EmailConfigService instance configured with session and repositories
    """
    service = EmailConfigService(
        session=session,
        email_service=email_service,
        config_repository=config_repository,
        usage_repository=usage_repository,
        audit_repository=audit_repository,
    )
    yield service


# Service dependency - use this in route handlers
EmailConfigServiceDep = Annotated[EmailConfigService, Depends(get_email_config_service)]


__all__ = [
    "EmailAuditLogRepositoryDep",
    "EmailConfigRepositoryDep",
    "EmailConfigServiceDep",
    "EmailUsageLogRepositoryDep",
    "EnhancedEmailServiceDep",
    "SessionDep",
    "get_email_config_service",
]
