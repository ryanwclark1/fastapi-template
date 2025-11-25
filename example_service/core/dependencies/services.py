"""Service dependencies for FastAPI."""
from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Depends

from example_service.core.dependencies.database import get_db
from example_service.core.services.health import HealthService
from example_service.features.reminders.service import ReminderService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def get_health_service() -> HealthService:
    """Get health check service instance.

    Returns:
        HealthService instance for health checks.

    Example:
        ```python
        @router.get("/health")
        async def health(service: HealthService = Depends(get_health_service)):
            return await service.check_health()
        ```
    """
    return HealthService()


async def get_reminder_service(
    session: "AsyncSession" = Depends(get_db),
) -> ReminderService:
    """Get reminder service wired with a database session."""
    return ReminderService(session)
