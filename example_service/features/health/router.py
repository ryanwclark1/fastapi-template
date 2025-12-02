"""Health check API endpoints.

Provides Kubernetes-ready health check endpoints for:
- Liveness probes: /health/live - Is the process alive?
- Readiness probes: /health/ready - Can the service accept traffic?
- Startup probes: /health/startup - Has the service finished initializing?
- Comprehensive health: /health/ - Full health status with dependency checks
- Detailed health: /health/detailed - Extended metrics with latency info
- History: /health/history - Recent health check history
- Statistics: /health/stats - Aggregated health statistics
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Response, status

from example_service.features.health.schemas import (
    CacheInfoResponse,
    DetailedHealthResponse,
    HealthHistoryEntry,
    HealthHistoryResponse,
    HealthResponse,
    HealthStatsResponse,
    LivenessResponse,
    ProtectionDetail,
    ProtectionHealthResponse,
    ProvidersResponse,
    ProviderStatsDetail,
    ReadinessResponse,
    StartupResponse,
)

# Import dependencies at runtime so FastAPI treats them as Depends()
# NOTE: These MUST be outside TYPE_CHECKING for FastAPI to resolve the Annotated[..., Depends(...)] metadata
from example_service.features.health.service import (  # noqa: TC001
    HealthAggregatorDep,
    HealthServiceDep,
)

router = APIRouter(prefix="/health", tags=["health"])


# =============================================================================
# Core Health Endpoints
# =============================================================================


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
async def health_check_detailed(
    service: HealthServiceDep,
    force_refresh: bool = Query(
        default=False,
        description="Bypass cache and run fresh checks",
    ),
) -> DetailedHealthResponse:
    """Detailed health check endpoint with latency metrics.

    Returns extended health information including response latency
    and status messages for each health provider.

    Args:
        force_refresh: If True, bypass cache and run fresh checks

    Returns:
        DetailedHealthResponse with per-provider metrics.
    """
    result = await service.check_health_detailed(force_refresh=force_refresh)
    return DetailedHealthResponse(**result)


# =============================================================================
# Kubernetes Probes
# =============================================================================


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


# =============================================================================
# Security Protection Endpoint
# =============================================================================


@router.get(
    "/protection",
    response_model=ProtectionHealthResponse,
    summary="Security protection health",
    description="Returns status of security protection mechanisms (rate limiting)",
)
async def protection_status(aggregator: HealthAggregatorDep) -> ProtectionHealthResponse:
    """Security protection health endpoint.

    Returns the health status of security protection mechanisms,
    primarily rate limiting. Useful for security dashboards and alerting
    when protection is degraded (fail-open mode) or disabled.

    Returns:
        ProtectionHealthResponse with rate limiter status and details.
    """
    from datetime import UTC, datetime

    from example_service.core.schemas.common import HealthStatus

    # Check rate limiter provider
    rate_limiter_result = await aggregator.check_provider("rate_limiter")

    protections = {}
    overall_status = HealthStatus.HEALTHY

    if rate_limiter_result:
        protections["rate_limiter"] = ProtectionDetail(
            status=rate_limiter_result.status,
            message=rate_limiter_result.message,
            metadata=rate_limiter_result.metadata,
        )
        # Overall status is worst of all protections
        if rate_limiter_result.status == HealthStatus.UNHEALTHY:
            overall_status = HealthStatus.UNHEALTHY
        elif (
            rate_limiter_result.status == HealthStatus.DEGRADED
            and overall_status != HealthStatus.UNHEALTHY
        ):
            overall_status = HealthStatus.DEGRADED
    else:
        # Rate limiter not configured
        protections["rate_limiter"] = ProtectionDetail(
            status=HealthStatus.UNHEALTHY,
            message="Rate limiter not configured",
            metadata={"reason": "provider_not_registered"},
        )
        overall_status = HealthStatus.UNHEALTHY

    return ProtectionHealthResponse(
        status=overall_status,
        timestamp=datetime.now(UTC),
        protections=protections,
    )


# =============================================================================
# History & Statistics Endpoints
# =============================================================================


@router.get(
    "/history",
    response_model=HealthHistoryResponse,
    summary="Health check history",
    description="Returns recent health check results for trend analysis",
)
async def health_history(
    aggregator: HealthAggregatorDep,
    limit: int = Query(default=50, ge=1, le=500, description="Maximum entries to return"),
    provider: str | None = Query(default=None, description="Filter by provider name"),
) -> HealthHistoryResponse:
    """Get health check history.

    Returns a list of recent health check results, useful for
    trend analysis and debugging intermittent issues.

    Args:
        limit: Maximum number of entries to return (most recent first)
        provider: Optional filter to show only specific provider

    Returns:
        HealthHistoryResponse with list of history entries
    """
    entries = aggregator.get_history(limit=limit, provider=provider)

    return HealthHistoryResponse(
        entries=[HealthHistoryEntry(**entry) for entry in entries],
        total_entries=len(entries),
        provider_filter=provider,
    )


@router.get(
    "/stats",
    response_model=HealthStatsResponse,
    summary="Health statistics",
    description="Returns aggregated health statistics from history",
)
async def health_stats(aggregator: HealthAggregatorDep) -> HealthStatsResponse:
    """Get health statistics.

    Returns aggregated statistics from the health check history,
    including uptime percentage, average latency, and per-provider stats.

    Returns:
        HealthStatsResponse with aggregated statistics
    """
    stats = aggregator.get_stats()

    return HealthStatsResponse(
        total_checks=stats.total_checks,
        healthy_count=stats.healthy_count,
        degraded_count=stats.degraded_count,
        unhealthy_count=stats.unhealthy_count,
        uptime_percentage=stats.uptime_percentage,
        avg_duration_ms=stats.avg_duration_ms,
        current_status=stats.current_status.value if stats.current_status else None,
        last_status_change=stats.last_status_change,
        provider_stats={
            name: ProviderStatsDetail(**provider_data)
            for name, provider_data in stats.provider_stats.items()
        },
    )


# =============================================================================
# Diagnostic Endpoints
# =============================================================================


@router.get(
    "/providers",
    response_model=ProvidersResponse,
    summary="List health providers",
    description="Returns list of registered health check providers",
)
async def list_providers(aggregator: HealthAggregatorDep) -> ProvidersResponse:
    """List registered health providers.

    Returns the names of all registered health check providers.
    Useful for debugging and understanding what's being monitored.

    Returns:
        ProvidersResponse with list of provider names
    """
    providers = aggregator.list_providers()
    return ProvidersResponse(providers=providers, count=len(providers))


@router.get(
    "/cache",
    response_model=CacheInfoResponse,
    summary="Cache information",
    description="Returns information about the health check result cache",
)
async def cache_info(aggregator: HealthAggregatorDep) -> CacheInfoResponse:
    """Get cache information.

    Returns the current state of the health check result cache,
    including TTL, age, and validity.

    Returns:
        CacheInfoResponse with cache state information
    """
    info = aggregator.get_cache_info()
    return CacheInfoResponse(**info)


@router.delete(
    "/history",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear health history",
    description="Clears all health check history (admin operation)",
)
async def clear_history(aggregator: HealthAggregatorDep) -> None:
    """Clear health check history.

    Removes all entries from the health check history.
    This is an admin operation useful for testing or after
    resolving issues.
    """
    aggregator.clear_history()


__all__ = ["router"]
