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

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from example_service.core.schemas.common import HealthStatus

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine

    from example_service.core.settings.health import ProviderConfig
    from example_service.infra.discovery.client import ConsulClient
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


# =============================================================================
# Provider Configuration
# =============================================================================


@dataclass
class ProviderConfig:
    """Configuration for health check providers.

    Attributes:
        timeout: Health check timeout in seconds
        latency_threshold_ms: Latency threshold for DEGRADED status
        enabled: Whether this provider is enabled
    """

    timeout: float = 5.0
    latency_threshold_ms: float = DEGRADED_LATENCY_THRESHOLD_MS
    enabled: bool = True


# =============================================================================
# Metrics Tracking Helpers
# =============================================================================


@asynccontextmanager
async def track_health_check(provider_name: str) -> AsyncIterator[None]:
    """Context manager to track health check metrics.

    Measures execution duration and records it in Prometheus histogram.

    Usage:
        async with track_health_check("database"):
            result = await check_database()

    Args:
        provider_name: Name of the provider being checked
    """
    from example_service.infra.metrics.health import health_check_duration_seconds

    start = time.perf_counter()
    try:
        yield
    finally:
        duration = time.perf_counter() - start
        health_check_duration_seconds.labels(provider=provider_name).observe(duration)


def record_health_check_result(
    provider_name: str,
    result: HealthCheckResult,
    previous_status: HealthStatus | None = None,
) -> None:
    """Record health check result metrics.

    Updates counters, gauges, and tracks status transitions.

    Args:
        provider_name: Name of the provider
        result: Health check result
        previous_status: Previous status for transition tracking
    """
    from example_service.infra.metrics.health import (
        health_check_status_gauge,
        health_check_status_transitions_total,
        health_check_total,
    )

    # Increment counter
    health_check_total.labels(provider=provider_name, status=result.status.value).inc()

    # Update gauge (1=healthy, 0.5=degraded, 0=unhealthy)
    status_value = {
        HealthStatus.HEALTHY: 1.0,
        HealthStatus.DEGRADED: 0.5,
        HealthStatus.UNHEALTHY: 0.0,
    }.get(result.status, 0.0)

    health_check_status_gauge.labels(provider=provider_name).set(status_value)

    # Track status transitions
    if previous_status is not None and previous_status != result.status:
        health_check_status_transitions_total.labels(
            provider=provider_name,
            from_status=previous_status.value,
            to_status=result.status.value,
        ).inc()


# =============================================================================
# Consul Health Provider
# =============================================================================


class ConsulHealthProvider:
    """Health provider for Consul service discovery.

    Monitors Consul connectivity, leader health, and service registration
    status. Essential for microservices architectures using Consul for
    service discovery.

    Checks performed:
    - **Consul agent connectivity**: Verifies local agent is reachable
    - **Leader election status**: Ensures cluster has an elected leader
    - **Service registration count**: Reports number of registered services
    - **Health check status**: Monitors this service's health in Consul

    Status determination:
    - HEALTHY: All checks pass, latency acceptable
    - DEGRADED: Connected but no leader or high latency
    - UNHEALTHY: Cannot connect to agent or API errors

    Example:
        >>> from example_service.infra.discovery import ConsulClient
        >>> from example_service.core.settings import get_consul_settings
        >>>
        >>> settings = get_consul_settings()
        >>> client = ConsulClient(settings)
        >>> provider = ConsulHealthProvider(
        ...     consul_client=client,
        ...     service_name="example-service",
        ... )
        >>> result = await provider.check_health()
        >>> print(result.status)  # HealthStatus.HEALTHY
    """

    def __init__(
        self,
        consul_client: ConsulClient,
        service_name: str,
        config: ProviderConfig | None = None,
    ) -> None:
        """Initialize Consul health provider.

        Args:
            consul_client: ConsulClient instance for API communication
            service_name: Name of this service in Consul
            config: Optional configuration (timeout, thresholds)
        """
        self._client = consul_client
        self._service_name = service_name
        self._config = config or ProviderConfig()

    @property
    def name(self) -> str:
        """Return provider name."""
        return "consul"

    async def check_health(self) -> HealthCheckResult:
        """Check Consul health.

        Performs multiple checks in parallel:
        1. Agent self info (connectivity)
        2. Leader status (cluster health)
        3. Registered services (registration status)

        Returns:
            HealthCheckResult with Consul status and metadata
        """
        start_time = time.perf_counter()

        try:
            async with asyncio.timeout(self._config.timeout):
                # Run checks in parallel for speed
                agent_info, leader_info, services_info = await asyncio.gather(
                    self._check_agent(),
                    self._check_leader(),
                    self._check_services(),
                    return_exceptions=True,
                )

            latency_ms = (time.perf_counter() - start_time) * 1000

            # Determine overall status from sub-checks
            if isinstance(agent_info, Exception):
                return HealthCheckResult(
                    status=HealthStatus.UNHEALTHY,
                    message=f"Agent unreachable: {agent_info}",
                    latency_ms=latency_ms,
                    metadata={"error": str(agent_info)},
                )

            # Build metadata from successful checks
            metadata: dict[str, Any] = {}

            if not isinstance(agent_info, Exception):
                metadata["agent_address"] = agent_info.get("agent_address", "unknown")
                metadata["datacenter"] = agent_info.get("datacenter", "unknown")

            if not isinstance(leader_info, Exception):
                metadata["leader"] = leader_info.get("leader", "unknown")
                has_leader = bool(leader_info.get("leader"))
            else:
                has_leader = False
                metadata["leader_error"] = str(leader_info)

            if not isinstance(services_info, Exception):
                metadata["services_registered"] = services_info.get("count", 0)
                metadata["service_health"] = services_info.get("service_health", "unknown")
            else:
                metadata["services_error"] = str(services_info)

            # Determine status
            if not has_leader:
                return HealthCheckResult(
                    status=HealthStatus.DEGRADED,
                    message="No Consul leader elected",
                    latency_ms=latency_ms,
                    metadata=metadata,
                )

            if latency_ms > self._config.latency_threshold_ms:
                return HealthCheckResult(
                    status=HealthStatus.DEGRADED,
                    message=f"High latency: {latency_ms:.2f}ms",
                    latency_ms=latency_ms,
                    metadata=metadata,
                )

            return HealthCheckResult(
                status=HealthStatus.HEALTHY,
                message="Consul operational",
                latency_ms=latency_ms,
                metadata=metadata,
            )

        except TimeoutError:
            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(
                "Consul health check timed out",
                extra={"timeout": self._config.timeout, "latency_ms": latency_ms},
            )
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Timeout after {self._config.timeout}s",
                latency_ms=latency_ms,
                metadata={"error": "timeout"},
            )

        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.warning("Consul health check failed", extra={"error": str(e)})
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Check failed: {e}",
                latency_ms=latency_ms,
                metadata={"error": str(e), "error_type": type(e).__name__},
            )

    async def _check_agent(self) -> dict[str, Any]:
        """Check Consul agent connectivity and info.

        Returns:
            Dict with agent address and datacenter
        """
        import httpx

        try:
            response = await self._client._client.get("/v1/agent/self")
            response.raise_for_status()
            data = response.json()

            # Extract key info
            config = data.get("Config", {})
            return {
                "agent_address": config.get("AdvertiseAddr", "unknown"),
                "datacenter": config.get("Datacenter", "unknown"),
            }

        except httpx.HTTPError as e:
            logger.debug("Agent check failed", extra={"error": str(e)})
            raise

    async def _check_leader(self) -> dict[str, Any]:
        """Check Consul leader election status.

        Returns:
            Dict with leader address
        """
        import httpx

        try:
            response = await self._client._client.get("/v1/status/leader")
            response.raise_for_status()

            # Leader is returned as quoted string, e.g., "192.168.1.100:8300"
            leader = response.text.strip('"')
            return {
                "leader": leader if leader else None,
            }

        except httpx.HTTPError as e:
            logger.debug("Leader check failed", extra={"error": str(e)})
            raise

    async def _check_services(self) -> dict[str, Any]:
        """Check registered services and this service's health.

        Returns:
            Dict with service count and health status
        """
        import httpx

        try:
            # Get all registered services
            response = await self._client._client.get("/v1/agent/services")
            response.raise_for_status()
            services = response.json()

            # Check if our service is registered
            service_health = "not_registered"
            for _service_id, service_data in services.items():
                if service_data.get("Service") == self._service_name:
                    service_health = "registered"
                    break

            return {
                "count": len(services),
                "service_health": service_health,
            }

        except httpx.HTTPError as e:
            logger.debug("Services check failed", extra={"error": str(e)})
            raise


# =============================================================================
# Database Pool Health Provider
# =============================================================================


class DatabasePoolHealthProvider:
    """Health provider for database connection pool monitoring.

    Monitors SQLAlchemy connection pool utilization and alerts when
    pool is nearing exhaustion. Critical for preventing connection
    pool errors under load.

    Status Levels:
    - HEALTHY: Pool utilization < 70% (default degraded threshold)
    - DEGRADED: Pool utilization 70-90% (default unhealthy threshold)
    - UNHEALTHY: Pool utilization > 90%

    For test environments using NullPool, always returns HEALTHY with
    a note in metadata.

    Example:
        >>> from example_service.infra.database.session import engine
        >>> provider = DatabasePoolHealthProvider(
        ...     engine=engine,
        ...     degraded_threshold=0.7,
        ...     unhealthy_threshold=0.9
        ... )
        >>> aggregator.add_provider(provider)
    """

    def __init__(
        self,
        engine: AsyncEngine,
        degraded_threshold: float = 0.7,
        unhealthy_threshold: float = 0.9,
        config: ProviderConfig | None = None,
    ) -> None:
        """Initialize database pool health provider.

        Args:
            engine: SQLAlchemy async engine instance
            degraded_threshold: Pool utilization threshold for DEGRADED status (0.0-1.0)
            unhealthy_threshold: Pool utilization threshold for UNHEALTHY status (0.0-1.0)
            config: Optional configuration (primarily for consistency with other providers)

        Raises:
            ValueError: If thresholds are invalid or degraded >= unhealthy
        """
        if not (0.0 <= degraded_threshold <= 1.0):
            raise ValueError(
                f"degraded_threshold must be between 0.0 and 1.0, got {degraded_threshold}"
            )

        if not (0.0 <= unhealthy_threshold <= 1.0):
            raise ValueError(
                f"unhealthy_threshold must be between 0.0 and 1.0, got {unhealthy_threshold}"
            )

        if degraded_threshold >= unhealthy_threshold:
            raise ValueError(
                f"degraded_threshold ({degraded_threshold}) must be less than "
                f"unhealthy_threshold ({unhealthy_threshold})"
            )

        self._engine = engine
        self._degraded_threshold = degraded_threshold
        self._unhealthy_threshold = unhealthy_threshold
        self._config = config or ProviderConfig()

    @property
    def name(self) -> str:
        """Return provider name."""
        return "database_pool"

    async def check_health(self) -> HealthCheckResult:
        """Check connection pool health.

        Examines the connection pool to determine utilization and
        returns status based on configured thresholds. This is a
        fast, non-blocking check that only reads pool statistics.

        Returns:
            HealthCheckResult with pool metrics in metadata including:
            - pool_size: Total configured pool size
            - checked_out: Connections currently in use
            - checked_in: Idle connections available
            - overflow: Overflow connections (beyond pool_size)
            - utilization_percent: Percentage of pool in use
            - available: Connections available for checkout
            - pool_class: Pool class name (QueuePool, NullPool, etc.)
        """
        start_time = time.perf_counter()

        try:
            # Access the underlying pool
            pool = self._engine.pool

            # Get pool class name
            pool_class = type(pool).__name__

            # Handle NullPool (test environments)
            if pool_class == "NullPool":
                latency_ms = (time.perf_counter() - start_time) * 1000
                return HealthCheckResult(
                    status=HealthStatus.HEALTHY,
                    message="NullPool in use (test environment)",
                    latency_ms=latency_ms,
                    metadata={
                        "pool_class": pool_class,
                        "note": "NullPool creates connections on-demand without pooling",
                    },
                )

            # Collect pool statistics
            # QueuePool and related pool types have these methods
            pool_size = pool.size()  # Total pool size
            checked_out = pool.checkedout()  # Connections in use
            overflow = pool.overflow()  # Overflow connections beyond pool_size
            checked_in = pool.checkedin()  # Idle connections

            # Calculate utilization
            total_capacity = pool_size + overflow
            utilization = 0.0 if total_capacity == 0 else checked_out / total_capacity

            utilization_percent = utilization * 100
            available = checked_in

            latency_ms = (time.perf_counter() - start_time) * 1000

            # Build metadata
            metadata = {
                "pool_size": pool_size,
                "checked_out": checked_out,
                "checked_in": checked_in,
                "overflow": overflow,
                "utilization_percent": round(utilization_percent, 2),
                "available": available,
                "pool_class": pool_class,
            }

            # Determine status based on utilization
            if utilization >= self._unhealthy_threshold:
                return HealthCheckResult(
                    status=HealthStatus.UNHEALTHY,
                    message=f"Pool critically high: {utilization_percent:.1f}% utilized",
                    latency_ms=latency_ms,
                    metadata=metadata,
                )

            if utilization >= self._degraded_threshold:
                return HealthCheckResult(
                    status=HealthStatus.DEGRADED,
                    message=f"Pool utilization elevated: {utilization_percent:.1f}%",
                    latency_ms=latency_ms,
                    metadata=metadata,
                )

            return HealthCheckResult(
                status=HealthStatus.HEALTHY,
                message=f"Pool healthy: {utilization_percent:.1f}% utilized",
                latency_ms=latency_ms,
                metadata=metadata,
            )

        except AttributeError as e:
            # Pool doesn't have expected methods (unexpected pool type)
            latency_ms = (time.perf_counter() - start_time) * 1000
            pool_class = type(pool).__name__ if hasattr(self._engine, "pool") else "unknown"
            logger.warning(
                "Pool health check failed - unsupported pool type",
                extra={"pool_class": pool_class, "error": str(e)},
            )
            return HealthCheckResult(
                status=HealthStatus.HEALTHY,
                message=f"Unsupported pool type: {pool_class}",
                latency_ms=latency_ms,
                metadata={
                    "pool_class": pool_class,
                    "note": "Pool statistics not available for this pool type",
                },
            )

        except Exception as e:
            # Unexpected error accessing pool
            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.exception("Unexpected error in pool health check", extra={"error": str(e)})
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Pool check error: {e}",
                latency_ms=latency_ms,
                metadata={"error": str(e), "error_type": type(e).__name__},
            )


__all__ = [
    "ConsulHealthProvider",
    "DatabaseHealthProvider",
    "DatabasePoolHealthProvider",
    "DEGRADED_LATENCY_THRESHOLD_MS",
    "ExternalServiceHealthProvider",
    "HealthCheckResult",
    "HealthProvider",
    "ProviderConfig",
    "RabbitMQHealthProvider",
    "RedisHealthProvider",
    "S3StorageHealthProvider",
    "record_health_check_result",
    "track_health_check",
]
