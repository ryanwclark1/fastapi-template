"""Status and health check endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from example_service.core.dependencies.services import get_health_service
from example_service.core.services.health import HealthService
from example_service.features.status.schemas import (
    HealthResponse,
    LivenessResponse,
    ReadinessResponse,
)

router = APIRouter(prefix="/health", tags=["health"])


@router.get(
    "/",
    response_model=HealthResponse,
    summary="Health check",
    description="Check the overall health of the service",
)
async def health_check(
    service: HealthService = Depends(get_health_service),
) -> HealthResponse:
    """Health check endpoint.

    Returns the overall health status of the service including
    version and timestamp information.

    Args:
        service: Health check service instance.

    Returns:
        Health check response with status and metadata.
    """
    result = await service.check_health()
    return HealthResponse(**result)


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness check",
    description="Check if the service is ready to accept requests",
)
async def readiness_check(
    service: HealthService = Depends(get_health_service),
) -> ReadinessResponse:
    """Readiness check endpoint.

    Checks if the service and all its dependencies are ready
    to accept and process requests.

    Args:
        service: Health check service instance.

    Returns:
        Readiness check response with dependency status.
    """
    result = await service.readiness()
    return ReadinessResponse(**result)


@router.get(
    "/live",
    response_model=LivenessResponse,
    summary="Liveness check",
    description="Check if the service is alive and responsive",
)
async def liveness_check(
    service: HealthService = Depends(get_health_service),
) -> LivenessResponse:
    """Liveness check endpoint.

    Simple check to verify the service is running and responsive.
    Used by container orchestration systems to restart unhealthy instances.

    Args:
        service: Health check service instance.

    Returns:
        Liveness check response.
    """
    result = await service.liveness()
    return LivenessResponse(**result)
