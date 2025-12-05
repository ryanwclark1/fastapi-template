"""Health check protocol and base types.

This module defines the HealthProvider protocol that all health check
providers must implement, along with the HealthCheckResult type.

The Protocol pattern allows users to create custom health checks without
modifying core code - simply implement the protocol and register with
the HealthAggregator.

Example:
    >>> class MyCustomProvider:
    ...     @property
    ...     def name(self) -> str:
    ...         return "my_service"
    ...
    ...     async def check_health(self) -> HealthCheckResult:
    ...         # Custom health check logic
    ...         return HealthCheckResult(
    ...             status=HealthStatus.HEALTHY,
    ...             message="Service operational",
    ...         )
    ...
    >>> aggregator.add_provider(MyCustomProvider())
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from example_service.core.schemas.common import HealthStatus

# Latency threshold for degraded status (milliseconds)
DEGRADED_LATENCY_THRESHOLD_MS = 1000.0


@dataclass
class HealthCheckResult:
    """Result from a single health check.

    Attributes:
        status: Health status (HEALTHY, DEGRADED, UNHEALTHY)
        message: Human-readable status message
        latency_ms: Check duration in milliseconds
        metadata: Additional provider-specific metadata
    """

    status: HealthStatus
    message: str = ""
    latency_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class HealthProvider(Protocol):
    """Protocol for health check providers.

    Implement this protocol to create custom health checks that can be
    registered with the HealthAggregator.

    The @runtime_checkable decorator allows isinstance() checks against
    the protocol, useful for validation during provider registration.

    Example:
        >>> class RedisHealthProvider:
        ...     def __init__(self, redis_client):
        ...         self._client = redis_client
        ...
        ...     @property
        ...     def name(self) -> str:
        ...         return "redis"
        ...
        ...     async def check_health(self) -> HealthCheckResult:
        ...         try:
        ...             await self._client.ping()
        ...             return HealthCheckResult(
        ...                 status=HealthStatus.HEALTHY,
        ...                 message="Redis connected",
        ...             )
        ...         except Exception as e:
        ...             return HealthCheckResult(
        ...                 status=HealthStatus.UNHEALTHY,
        ...                 message=f"Redis error: {e}",
        ...             )
    """

    @property
    def name(self) -> str:
        """Unique identifier for this health check.

        Returns:
            Short, descriptive name (e.g., "database", "redis", "auth_service")
        """
        ...

    async def check_health(self) -> HealthCheckResult:
        """Perform the health check.

        Returns:
            HealthCheckResult with status, message, and optional metadata
        """
        ...
