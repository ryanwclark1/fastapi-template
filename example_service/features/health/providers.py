"""Health check providers using Protocol-based architecture.

This module defines the HealthProvider protocol and built-in provider
implementations for common infrastructure dependencies.

The Protocol pattern allows users to create custom health checks without
modifying core code - simply implement the protocol and register with
the HealthAggregator.

Example:
    >>> class MyCustomProvider(HealthProvider):
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

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from example_service.core.schemas.common import HealthStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

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


# =============================================================================
# Built-in Health Providers
# =============================================================================


class DatabaseHealthProvider:
    """Health provider for PostgreSQL database connectivity.

    Executes a simple query to verify database connectivity and measures
    response latency. Marks as DEGRADED if latency exceeds threshold.

    Example:
        >>> from example_service.infra.database.session import engine
        >>> db_provider = DatabaseHealthProvider(engine, timeout=2.0)
        >>> aggregator.add_provider(db_provider)
    """

    def __init__(
        self,
        engine: AsyncEngine,
        timeout: float = 2.0,
        latency_threshold_ms: float = DEGRADED_LATENCY_THRESHOLD_MS,
    ) -> None:
        """Initialize database health provider.

        Args:
            engine: SQLAlchemy async engine instance
            timeout: Health check timeout in seconds
            latency_threshold_ms: Latency threshold for DEGRADED status
        """
        self._engine = engine
        self._timeout = timeout
        self._latency_threshold = latency_threshold_ms

    @property
    def name(self) -> str:
        """Return provider name."""
        return "database"

    async def check_health(self) -> HealthCheckResult:
        """Check database connectivity with timeout."""
        import asyncio

        from sqlalchemy import text

        start_time = time.perf_counter()

        try:
            async with asyncio.timeout(self._timeout):
                async with self._engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))

            latency_ms = (time.perf_counter() - start_time) * 1000

            if latency_ms > self._latency_threshold:
                return HealthCheckResult(
                    status=HealthStatus.DEGRADED,
                    message=f"High latency: {latency_ms:.2f}ms",
                    latency_ms=latency_ms,
                )

            return HealthCheckResult(
                status=HealthStatus.HEALTHY,
                message="Database operational",
                latency_ms=latency_ms,
            )

        except TimeoutError:
            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.warning("Database health check timed out", extra={"timeout": self._timeout})
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Timeout after {self._timeout}s",
                latency_ms=latency_ms,
                metadata={"error": "timeout"},
            )

        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.warning("Database health check failed", extra={"error": str(e)})
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Connection failed: {e}",
                latency_ms=latency_ms,
                metadata={"error": str(e)},
            )


class RedisHealthProvider:
    """Health provider for Redis cache connectivity.

    Example:
        >>> from example_service.infra.cache.redis import RedisCache
        >>> redis_provider = RedisHealthProvider(redis_cache)
        >>> aggregator.add_provider(redis_provider)
    """

    def __init__(self, cache: Any, timeout: float = 2.0) -> None:
        """Initialize Redis health provider.

        Args:
            cache: Redis cache instance with health_check() method
            timeout: Health check timeout in seconds
        """
        self._cache = cache
        self._timeout = timeout

    @property
    def name(self) -> str:
        """Return provider name."""
        return "cache"

    async def check_health(self) -> HealthCheckResult:
        """Check Redis connectivity."""
        import asyncio

        start_time = time.perf_counter()

        try:
            async with asyncio.timeout(self._timeout):
                is_healthy = await self._cache.health_check()

            latency_ms = (time.perf_counter() - start_time) * 1000

            if is_healthy:
                return HealthCheckResult(
                    status=HealthStatus.HEALTHY,
                    message="Cache operational",
                    latency_ms=latency_ms,
                )

            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message="Cache health check returned false",
                latency_ms=latency_ms,
            )

        except TimeoutError:
            latency_ms = (time.perf_counter() - start_time) * 1000
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Timeout after {self._timeout}s",
                latency_ms=latency_ms,
                metadata={"error": "timeout"},
            )

        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.warning("Redis health check failed", extra={"error": str(e)})
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Cache error: {e}",
                latency_ms=latency_ms,
                metadata={"error": str(e)},
            )


class RabbitMQHealthProvider:
    """Health provider for RabbitMQ messaging broker.

    Example:
        >>> rabbit_provider = RabbitMQHealthProvider(
        ...     connection_url="amqp://guest:guest@localhost:5672/"
        ... )
        >>> aggregator.add_provider(rabbit_provider)
    """

    def __init__(self, connection_url: str, timeout: float = 5.0) -> None:
        """Initialize RabbitMQ health provider.

        Args:
            connection_url: AMQP connection URL
            timeout: Connection timeout in seconds
        """
        self._url = connection_url
        self._timeout = timeout

    @property
    def name(self) -> str:
        """Return provider name."""
        return "messaging"

    async def check_health(self) -> HealthCheckResult:
        """Check RabbitMQ connectivity."""
        import aio_pika

        start_time = time.perf_counter()

        try:
            connection = await aio_pika.connect_robust(self._url, timeout=self._timeout)
            await connection.close()

            latency_ms = (time.perf_counter() - start_time) * 1000

            return HealthCheckResult(
                status=HealthStatus.HEALTHY,
                message="Messaging broker operational",
                latency_ms=latency_ms,
            )

        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.warning("RabbitMQ health check failed", extra={"error": str(e)})
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Broker error: {e}",
                latency_ms=latency_ms,
                metadata={"error": str(e)},
            )


class ExternalServiceHealthProvider:
    """Health provider for external HTTP services.

    Checks health by making a GET request to the service's health endpoint.

    Example:
        >>> auth_provider = ExternalServiceHealthProvider(
        ...     name="auth_service",
        ...     base_url="http://auth-service:8080",
        ...     health_path="/health",
        ... )
        >>> aggregator.add_provider(auth_provider)
    """

    def __init__(
        self,
        name: str,
        base_url: str,
        health_path: str = "/health",
        timeout: float = 5.0,
    ) -> None:
        """Initialize external service health provider.

        Args:
            name: Unique identifier for this service
            base_url: Base URL of the external service
            health_path: Path to health endpoint (default: /health)
            timeout: Request timeout in seconds
        """
        self._name = name
        self._base_url = base_url.rstrip("/")
        self._health_path = health_path
        self._timeout = timeout

    @property
    def name(self) -> str:
        """Return provider name."""
        return self._name

    async def check_health(self) -> HealthCheckResult:
        """Check external service health via HTTP."""
        import httpx

        start_time = time.perf_counter()
        url = f"{self._base_url}{self._health_path}"

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url, follow_redirects=True)

            latency_ms = (time.perf_counter() - start_time) * 1000

            if response.status_code == 200:
                return HealthCheckResult(
                    status=HealthStatus.HEALTHY,
                    message=f"{self._name} operational",
                    latency_ms=latency_ms,
                    metadata={"url": url, "status_code": response.status_code},
                )

            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message=f"HTTP {response.status_code}",
                latency_ms=latency_ms,
                metadata={"url": url, "status_code": response.status_code},
            )

        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(
                f"External service {self._name} health check failed",
                extra={"url": url, "error": str(e)},
            )
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Connection failed: {e}",
                latency_ms=latency_ms,
                metadata={"url": url, "error": str(e)},
            )


class S3StorageHealthProvider:
    """Health provider for S3-compatible storage.

    Example:
        >>> from example_service.infra.storage.s3 import S3Client
        >>> s3_provider = S3StorageHealthProvider(s3_client)
        >>> aggregator.add_provider(s3_provider)
    """

    def __init__(self, s3_client: Any, timeout: float = 5.0) -> None:
        """Initialize S3 health provider.

        Args:
            s3_client: S3Client instance with list_objects() method
            timeout: Health check timeout in seconds
        """
        self._client = s3_client
        self._timeout = timeout

    @property
    def name(self) -> str:
        """Return provider name."""
        return "storage"

    async def check_health(self) -> HealthCheckResult:
        """Check S3 storage connectivity."""
        import asyncio

        start_time = time.perf_counter()

        try:
            async with asyncio.timeout(self._timeout):
                await self._client.list_objects(prefix="", max_keys=1)

            latency_ms = (time.perf_counter() - start_time) * 1000

            return HealthCheckResult(
                status=HealthStatus.HEALTHY,
                message="Storage operational",
                latency_ms=latency_ms,
            )

        except TimeoutError:
            latency_ms = (time.perf_counter() - start_time) * 1000
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Timeout after {self._timeout}s",
                latency_ms=latency_ms,
                metadata={"error": "timeout"},
            )

        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.warning("S3 health check failed", extra={"error": str(e)})
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Storage error: {e}",
                latency_ms=latency_ms,
                metadata={"error": str(e)},
            )


__all__ = [
    "DEGRADED_LATENCY_THRESHOLD_MS",
    "DatabaseHealthProvider",
    "ExternalServiceHealthProvider",
    "HealthCheckResult",
    "HealthProvider",
    "RabbitMQHealthProvider",
    "RedisHealthProvider",
    "S3StorageHealthProvider",
]
