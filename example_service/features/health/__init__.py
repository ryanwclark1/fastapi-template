"""Health check feature module.

Provides Kubernetes-ready health check endpoints and a pluggable provider
architecture for monitoring application dependencies.

## Endpoints

- `/health/` - Comprehensive health check with dependency status
- `/health/detailed` - Extended health info with latency metrics
- `/health/ready` - Kubernetes readiness probe
- `/health/live` - Kubernetes liveness probe
- `/health/startup` - Kubernetes startup probe
- `/health/history` - Health check history for trend analysis
- `/health/stats` - Aggregated health statistics
- `/health/providers` - List registered providers
- `/health/cache` - Cache status information

## Features

- **Concurrent checks**: All providers checked in parallel with asyncio
- **Result caching**: Configurable TTL to avoid hammering dependencies
- **History tracking**: Rolling history for trend analysis and debugging
- **Statistics**: Uptime percentage, latency averages, per-provider stats

## Quick Start

The health feature works out of the box with auto-configured providers
based on your application settings:

    >>> from example_service.features.health import router
    >>> app.include_router(router, prefix="/api")

## Custom Providers

Create custom health checks by implementing the HealthProvider protocol:

    >>> from example_service.features.health import (
    ...     HealthProvider,
    ...     HealthCheckResult,
    ...     HealthStatus,
    ...     HealthAggregator,
    ... )
    >>>
    >>> class MyServiceProvider:
    ...     @property
    ...     def name(self) -> str:
    ...         return "my_service"
    ...
    ...     async def check_health(self) -> HealthCheckResult:
    ...         # Your health check logic
    ...         return HealthCheckResult(
    ...             status=HealthStatus.HEALTHY,
    ...             message="Service operational",
    ...         )
    >>>
    >>> # Register with aggregator
    >>> aggregator = HealthAggregator()
    >>> aggregator.add_provider(MyServiceProvider())

## Type Aliases for DI

Use type aliases for cleaner route handler signatures:

    >>> from example_service.features.health import HealthServiceDep
    >>>
    >>> @router.get("/status")
    >>> async def status(service: HealthServiceDep):
    ...     return await service.check_health()
"""

from __future__ import annotations

from example_service.core.schemas.common import HealthStatus
from example_service.features.health.aggregator import (
    DEFAULT_CACHE_TTL_SECONDS,
    DEFAULT_CHECK_TIMEOUT_SECONDS,
    DEFAULT_HISTORY_SIZE,
    AggregatedHealthResult,
    HealthAggregator,
    HealthHistoryEntry,
    HealthStats,
    get_global_aggregator,
    set_global_aggregator,
)
from example_service.features.health.providers import (
    DEGRADED_LATENCY_THRESHOLD_MS,
    DatabaseHealthProvider,
    ExternalServiceHealthProvider,
    HealthCheckResult,
    HealthProvider,
    RabbitMQHealthProvider,
    RedisHealthProvider,
    S3StorageHealthProvider,
)
from example_service.features.health.router import router
from example_service.features.health.schemas import (
    CacheInfoResponse,
    ComponentHealthDetail,
    DetailedHealthResponse,
    HealthHistoryResponse,
    HealthResponse,
    HealthStatsResponse,
    LivenessResponse,
    ProvidersResponse,
    ProviderStatsDetail,
    ReadinessResponse,
    StartupResponse,
)
from example_service.features.health.service import (
    HealthAggregatorDep,
    HealthService,
    HealthServiceDep,
    get_health_aggregator,
    get_health_service,
)

__all__ = [
    # Router
    "router",
    # Service & DI
    "HealthService",
    "HealthServiceDep",
    "get_health_service",
    # Aggregator
    "HealthAggregator",
    "HealthAggregatorDep",
    "AggregatedHealthResult",
    "HealthHistoryEntry",
    "HealthStats",
    "get_health_aggregator",
    "get_global_aggregator",
    "set_global_aggregator",
    # Configuration defaults
    "DEFAULT_CACHE_TTL_SECONDS",
    "DEFAULT_CHECK_TIMEOUT_SECONDS",
    "DEFAULT_HISTORY_SIZE",
    # Provider Protocol & Result
    "HealthProvider",
    "HealthCheckResult",
    "HealthStatus",
    "DEGRADED_LATENCY_THRESHOLD_MS",
    # Built-in Providers
    "DatabaseHealthProvider",
    "RedisHealthProvider",
    "RabbitMQHealthProvider",
    "ExternalServiceHealthProvider",
    "S3StorageHealthProvider",
    # Response Schemas
    "HealthResponse",
    "DetailedHealthResponse",
    "ComponentHealthDetail",
    "ReadinessResponse",
    "LivenessResponse",
    "StartupResponse",
    "HealthHistoryResponse",
    "HealthStatsResponse",
    "ProviderStatsDetail",
    "CacheInfoResponse",
    "ProvidersResponse",
]
