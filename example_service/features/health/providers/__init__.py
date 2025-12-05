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

# Protocol and base types
from .protocol import (
    DEGRADED_LATENCY_THRESHOLD_MS,
    HealthCheckResult,
    HealthProvider,
)

# Core infrastructure providers
from .database import DatabaseHealthProvider
from .redis import RedisHealthProvider
from .rabbitmq import RabbitMQHealthProvider
from .external import ExternalServiceHealthProvider
from .s3 import S3StorageHealthProvider
from .consul import ConsulHealthProvider
from .pool import DatabasePoolHealthProvider

# Application-specific providers
from .accent_auth import AccentAuthHealthProvider
from .rate_limit import RateLimiterHealthProvider
from .storage import StorageHealthProvider
from .task_tracker import TaskTrackerHealthProvider

# Import ProviderConfig for backward compatibility
from example_service.core.settings.health import ProviderConfig

__all__ = [
    # Protocol and base types
    "DEGRADED_LATENCY_THRESHOLD_MS",
    "HealthCheckResult",
    "HealthProvider",
    "ProviderConfig",
    # Core infrastructure providers
    "DatabaseHealthProvider",
    "RedisHealthProvider",
    "RabbitMQHealthProvider",
    "ExternalServiceHealthProvider",
    "S3StorageHealthProvider",
    "ConsulHealthProvider",
    "DatabasePoolHealthProvider",
    # Application-specific providers
    "AccentAuthHealthProvider",
    "RateLimiterHealthProvider",
    "StorageHealthProvider",
    "TaskTrackerHealthProvider",
]
