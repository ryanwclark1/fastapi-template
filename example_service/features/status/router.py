"""Status and health check endpoints.

Provides Kubernetes-ready health check endpoints for:
- Liveness probes: /health/live
- Readiness probes: /health/ready
- Startup probes: /health/startup
- Comprehensive health: /health/
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from example_service.core.dependencies.services import get_health_service
from example_service.core.services.health import HealthService
from example_service.features.status.schemas import (
    HealthResponse,
    LivenessResponse,
    ReadinessResponse,
    StartupResponse,
)

router = APIRouter(prefix="/health", tags=["health"])


@router.get(
    "/",
    response_model=HealthResponse,
    summary="Health check",
    description="Check the overall health of the service",
)
async def health_check(
    service: Annotated[HealthService, Depends(get_health_service)],
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
    status_code=status.HTTP_200_OK,
    responses={
        503: {"description": "Service not ready"},
    },
    summary="Readiness probe (Kubernetes)",
    description="Kubernetes readiness probe - returns 200 if ready, 503 if not ready",
)
async def readiness_check(
    response: Response,
    service: Annotated[HealthService, Depends(get_health_service)],
) -> ReadinessResponse:
    """Kubernetes readiness probe endpoint.

    Checks if the service and critical dependencies are ready
    to accept and process requests.

    Kubernetes uses this to determine if the pod should receive traffic:
    - Returns 200 OK if service is ready
    - Returns 503 Service Unavailable if not ready

    Args:
        response: FastAPI response object for setting status code.
        service: Health check service instance.

    Returns:
        Readiness check response with dependency status.
    """
    result = await service.readiness()

    # Set appropriate HTTP status code for Kubernetes
    if not result["ready"]:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(**result)


@router.get(
    "/live",
    response_model=LivenessResponse,
    status_code=status.HTTP_200_OK,
    summary="Liveness probe (Kubernetes)",
    description="Kubernetes liveness probe - always returns 200 if service is responsive",
)
async def liveness_check(
    service: Annotated[HealthService, Depends(get_health_service)],
) -> LivenessResponse:
    """Kubernetes liveness probe endpoint.

    Simple check to verify the service is running and responsive.
    Kubernetes uses this to determine if the pod should be restarted.

    This endpoint should always return 200 OK unless the service is
    completely unresponsive or deadlocked.

    Args:
        service: Health check service instance.

    Returns:
        Liveness check response.
    """
    result = await service.liveness()
    return LivenessResponse(**result)


@router.get(
    "/startup",
    response_model=StartupResponse,
    status_code=status.HTTP_200_OK,
    summary="Startup probe (Kubernetes)",
    description="Kubernetes startup probe - indicates if application has started",
)
async def startup_check(
    service: Annotated[HealthService, Depends(get_health_service)],
) -> StartupResponse:
    """Kubernetes startup probe endpoint.

    Indicates whether the application has finished starting up.
    Kubernetes uses this to know when to start liveness and readiness probes.

    This is particularly useful for slow-starting applications to avoid
    premature restarts during initialization.

    Args:
        service: Health check service instance.

    Returns:
        Startup check response.
    """
    result = await service.startup()
    return StartupResponse(**result)
