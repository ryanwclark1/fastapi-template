"""FastAPI dependencies for admin email feature.

Provides Annotated type aliases for clean dependency injection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from example_service.core.dependencies.database import get_async_session
from example_service.features.admin.email.service import EmailAdminService
from example_service.features.email.repository import (
    EmailConfigRepository,
    EmailUsageLogRepository,
    get_email_config_repository,
    get_email_usage_log_repository,
)
from example_service.infra.email import get_enhanced_email_service
from example_service.infra.email.enhanced_service import EnhancedEmailService


# Type aliases for dependencies
SessionDep = Annotated[AsyncSession, Depends(get_async_session)]
EnhancedEmailServiceDep = Annotated[EnhancedEmailService, Depends(get_enhanced_email_service)]
EmailConfigRepositoryDep = Annotated[EmailConfigRepository, Depends(get_email_config_repository)]
EmailUsageLogRepositoryDep = Annotated[EmailUsageLogRepository, Depends(get_email_usage_log_repository)]


async def get_email_admin_service(
    session: SessionDep,
    email_service: EnhancedEmailServiceDep,
    config_repository: EmailConfigRepositoryDep,
    usage_repository: EmailUsageLogRepositoryDep,
) -> AsyncGenerator[EmailAdminService]:
    """Create EmailAdminService with injected dependencies.

    Yields:
        EmailAdminService instance
    """
    service = EmailAdminService(
        session=session,
        email_service=email_service,
        config_repository=config_repository,
        usage_repository=usage_repository,
    )
    yield service


# Service dependency
EmailAdminServiceDep = Annotated[EmailAdminService, Depends(get_email_admin_service)]


__all__ = [
    "EmailAdminServiceDep",
    "EmailConfigRepositoryDep",
    "EmailUsageLogRepositoryDep",
    "EnhancedEmailServiceDep",
    "SessionDep",
    "get_email_admin_service",
]
