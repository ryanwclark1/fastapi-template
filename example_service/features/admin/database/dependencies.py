"""Dependency injection for database admin features."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from example_service.core.dependencies.database import get_db_session
from example_service.core.settings import get_admin_settings
from example_service.core.settings.admin import AdminSettings
from example_service.features.admin.database.repository import (
    DatabaseAdminRepository,
    get_database_admin_repository,
)
from example_service.features.admin.database.service import DatabaseAdminService

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

# Type aliases for dependencies
SessionDep = Annotated[AsyncSession, Depends(get_db_session)]
AdminSettingsDep = Annotated[AdminSettings, Depends(get_admin_settings)]
DatabaseAdminRepositoryDep = Annotated[
    DatabaseAdminRepository,
    Depends(get_database_admin_repository),
]


async def get_database_admin_service(
    repository: DatabaseAdminRepositoryDep,
    settings: AdminSettingsDep,
) -> AsyncGenerator[DatabaseAdminService]:
    """Create DatabaseAdminService with injected repository and settings.

    Yields:
        DatabaseAdminService instance with rate limiting and health thresholds
    """
    service = DatabaseAdminService(repository=repository, settings=settings)
    yield service


# Service dependency
AdminServiceDep = Annotated[DatabaseAdminService, Depends(get_database_admin_service)]


# Legacy alias for backwards compatibility (deprecated)
# NOTE: Remove once the repository pattern is fully adopted.
AdminDAODep = DatabaseAdminRepositoryDep


__all__ = [
    "AdminDAODep",  # Deprecated: Use DatabaseAdminRepositoryDep instead
    "AdminServiceDep",
    "AdminSettingsDep",
    "DatabaseAdminRepositoryDep",
    "SessionDep",
    "get_database_admin_repository",
    "get_database_admin_service",
]
