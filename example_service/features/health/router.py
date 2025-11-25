"""Health check API endpoints.

Provides Kubernetes-ready health check endpoints for:
- Liveness probes: /health/live - Is the process alive?
- Readiness probes: /health/ready - Can the service accept traffic?
- Startup probes: /health/startup - Has the service finished initializing?
- Comprehensive health: /health/ - Full health status with dependency checks
- Detailed health: /health/detailed - Extended metrics with latency info
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from example_service.features.health.schemas import (
    DetailedHealthResponse,
    HealthResponse,
    LivenessResponse,
    ReadinessResponse,
    StartupResponse,
)
from example_service.features.health.service import HealthServiceDep

router = APIRouter(prefix="/health", tags=["health"])


@router.get(
    "/",
    response_model=HealthResponse,
    summary="Comprehensive health check",
    description="Returns the overall health status including all dependency checks",
)
async def health_check(service: HealthServiceDep) -> HealthResponse:
    """Comprehensive health check endpoint.

    Returns the overall health status of the service including
    version, timestamp, and individual dependency health checks
    (database, cache, messaging, storage, external services).

    Returns:
        HealthResponse with status and dependency check results.
    """
    result = await service.check_health()
    return HealthResponse(**result)


@router.get(
    "/detailed",
    response_model=DetailedHealthResponse,
    summary="Detailed health check with metrics",
    description="Returns extended health info including latency per component",
)
async def health_check_detailed(service: HealthServiceDep) -> DetailedHealthResponse:
    """Detailed health check endpoint with latency metrics.

    Returns extended health information including response latency
    and status messages for each health provider.

    Returns:
        DetailedHealthResponse with per-provider metrics.
    """
    result = await service.check_health_detailed()
    return DetailedHealthResponse(**result)


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    status_code=status.HTTP_200_OK,
    responses={
        503: {"description": "Service not ready to accept traffic"},
    },
    summary="Readiness probe (Kubernetes)",
    description="Returns 200 if ready to accept traffic, 503 if not ready",
)
async def readiness_check(
    response: Response,
    service: HealthServiceDep,
) -> ReadinessResponse:
    """Kubernetes readiness probe endpoint.

    Checks if the service and critical dependencies (database) are ready
    to accept and process requests. Kubernetes uses this to determine
    if the pod should receive traffic from the service.

    Returns:
        ReadinessResponse with ready status and critical dependency checks.

    Note:
        Returns HTTP 503 if not ready, causing Kubernetes to temporarily
        remove the pod from the service endpoints.
    """
    result = await service.readiness()

    if not result["ready"]:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(**result)


@router.get(
    "/live",
    response_model=LivenessResponse,
    status_code=status.HTTP_200_OK,
    summary="Liveness probe (Kubernetes)",
    description="Returns 200 if the service process is alive and responsive",
)
async def liveness_check(service: HealthServiceDep) -> LivenessResponse:
    """Kubernetes liveness probe endpoint.

    Simple check to verify the service is running and responsive.
    Kubernetes uses this to determine if the pod should be restarted.

    This endpoint should always return 200 OK unless the service is
    completely unresponsive or deadlocked.

    Returns:
        LivenessResponse indicating the service is alive.
    """
    result = await service.liveness()
    return LivenessResponse(**result)


@router.get(
    "/startup",
    response_model=StartupResponse,
    status_code=status.HTTP_200_OK,
    summary="Startup probe (Kubernetes)",
    description="Indicates if the application has finished starting up",
)
async def startup_check(service: HealthServiceDep) -> StartupResponse:
    """Kubernetes startup probe endpoint.

    Indicates whether the application has finished starting up.
    Kubernetes uses this to know when to start liveness and readiness probes.

    This is particularly useful for slow-starting applications to avoid
    premature restarts during initialization.

    Returns:
        StartupResponse indicating startup completion status.
    """
    result = await service.startup()
    return StartupResponse(**result)


__all__ = ["router"]
