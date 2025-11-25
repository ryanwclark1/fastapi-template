"""Service dependencies for FastAPI."""

from __future__ import annotations

from example_service.core.services.health import HealthService


def get_health_service() -> HealthService:
    """Get health check service instance.

    Returns:
        HealthService instance for health checks.

    Example:
            @router.get("/health")
        async def health(service: HealthService = Depends(get_health_service)):
            return await service.check_health()
    """
    return HealthService()


__all__ = ["get_health_service"]
