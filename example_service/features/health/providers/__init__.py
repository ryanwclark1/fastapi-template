"""Health check providers.

This module provides a collection of health check providers for monitoring
various infrastructure dependencies. Each provider implements the HealthProvider
protocol and can be registered with the HealthAggregator.

Available Providers:
- DatabaseHealthProvider: PostgreSQL database connectivity
- RedisHealthProvider: Redis cache connectivity
- RabbitMQHealthProvider: RabbitMQ messaging broker
- ExternalServiceHealthProvider: External HTTP services
- S3StorageHealthProvider: S3-compatible storage
- ConsulHealthProvider: Consul service discovery
- DatabasePoolHealthProvider: Database connection pool monitoring
- AccentAuthHealthProvider: Accent-Auth service
- RateLimiterHealthProvider: Rate limiting protection status
- StorageHealthProvider: Storage service (via StorageService)
- TaskTrackerHealthProvider: Task execution tracking system

Protocol & Base Types:
- HealthProvider: Protocol all providers implement
- HealthCheckResult: Result type for health checks
- DEGRADED_LATENCY_THRESHOLD_MS: Default latency threshold

Example:
    >>> from example_service.features.health.providers import (
    ...     DatabaseHealthProvider,
    ...     HealthCheckResult,
    ... )
    >>> from example_service.infra.database.session import engine
    >>>
    >>> provider = DatabaseHealthProvider(engine)
    >>> result = await provider.check_health()
    >>> print(result.status)  # HealthStatus.HEALTHY
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import time
from typing import TYPE_CHECKING

from example_service.core.schemas.common import HealthStatus
from example_service.core.settings.health import ProviderConfig
from example_service.infra.metrics.health import (
    health_check_duration_seconds,
    health_check_status_gauge,
    health_check_status_transitions_total,
    health_check_total,
)

from .accent_auth import AccentAuthHealthProvider
from .consul import ConsulHealthProvider
from .database import DatabaseHealthProvider
from .external import ExternalServiceHealthProvider
from .pool import DatabasePoolHealthProvider
from .protocol import (
    DEGRADED_LATENCY_THRESHOLD_MS,
    HealthCheckResult,
    HealthProvider,
)
from .rabbitmq import RabbitMQHealthProvider
from .rate_limit import RateLimiterHealthProvider
from .redis import RedisHealthProvider
from .s3 import S3StorageHealthProvider
from .storage import StorageHealthProvider
from .task_tracker import TaskTrackerHealthProvider

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_STATUS_GAUGE_VALUES = {
    HealthStatus.HEALTHY: 1.0,
    HealthStatus.DEGRADED: 0.5,
    HealthStatus.UNHEALTHY: 0.0,
}


@asynccontextmanager
async def track_health_check(provider: str) -> AsyncIterator[None]:
    """Measure health check duration for Prometheus histograms."""
    start = time.perf_counter()
    try:
        yield
    finally:
        duration = time.perf_counter() - start
        health_check_duration_seconds.labels(provider=provider).observe(duration)


def record_health_check_result(
    provider: str,
    result: HealthCheckResult,
    previous_status: HealthStatus | None,
) -> None:
    """Update Prometheus metrics for completed health checks."""
    health_check_total.labels(provider=provider, status=result.status.value).inc()
    gauge_value = _STATUS_GAUGE_VALUES.get(result.status, 0.0)
    health_check_status_gauge.labels(provider=provider).set(gauge_value)

    if previous_status is not None and previous_status != result.status:
        health_check_status_transitions_total.labels(
            provider=provider,
            from_status=previous_status.value,
            to_status=result.status.value,
        ).inc()

__all__ = [
    # Protocol and base types
    "DEGRADED_LATENCY_THRESHOLD_MS",
    # Application-specific providers
    "AccentAuthHealthProvider",
    "ConsulHealthProvider",
    # Core infrastructure providers
    "DatabaseHealthProvider",
    "DatabasePoolHealthProvider",
    "ExternalServiceHealthProvider",
    "HealthCheckResult",
    "HealthProvider",
    "ProviderConfig",
    "RabbitMQHealthProvider",
    "RateLimiterHealthProvider",
    "RedisHealthProvider",
    "S3StorageHealthProvider",
    "StorageHealthProvider",
    "TaskTrackerHealthProvider",
    "record_health_check_result",
    "track_health_check",
]
