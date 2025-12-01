"""Health check service with provider-based architecture.

This service provides health check functionality using a pluggable provider
architecture. Providers can be registered dynamically at startup, or the
service can auto-configure based on settings.

Example:
    >>> # Auto-configured from settings (default behavior)
    >>> service = HealthService()
    >>> result = await service.check_health()
    >>>
    >>> # With custom aggregator
    >>> aggregator = HealthAggregator()
    >>> aggregator.add_provider(DatabaseHealthProvider(engine))
    >>> service = HealthService(aggregator=aggregator)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from example_service.core.schemas.common import HealthStatus
from example_service.core.services.base import BaseService
from example_service.core.settings import (
    get_app_settings,
    get_auth_settings,
    get_backup_settings,
    get_consul_settings,
    get_db_settings,
    get_health_settings,
    get_rabbit_settings,
    get_redis_settings,
)

if TYPE_CHECKING:
    from example_service.features.health.aggregator import HealthAggregator

logger = logging.getLogger(__name__)


class HealthService(BaseService):
    """Service for health checks and status monitoring.

    Provides methods to check the health of the application and its
    dependencies. Implements Kubernetes-ready health checks with
    readiness, liveness, and startup probes.

    The service can operate in two modes:

    1. **Aggregator mode** (recommended): Pass a configured HealthAggregator
       with registered providers for full control over health checks.

    2. **Auto-configure mode** (default): Automatically creates providers
       based on settings (db, redis, rabbit, etc. with health_checks_enabled).

    Example:
        >>> # Auto-configure from settings
        >>> service = HealthService()
        >>> health = await service.check_health()
        >>>
        >>> # Use with custom aggregator
        >>> from example_service.features.health.aggregator import HealthAggregator
        >>> from example_service.features.health.providers import DatabaseHealthProvider
        >>>
        >>> aggregator = HealthAggregator()
        >>> aggregator.add_provider(DatabaseHealthProvider(engine))
        >>> service = HealthService(aggregator=aggregator)
    """

    def __init__(self, aggregator: HealthAggregator | None = None) -> None:
        """Initialize health service.

        Args:
            aggregator: Optional pre-configured HealthAggregator.
                       If None, auto-configures based on settings.
        """
        super().__init__()
        self._aggregator = aggregator
        self._auto_configured = aggregator is None

        # Load settings
        self._app_settings = get_app_settings()
        self._db_settings = get_db_settings()
        self._redis_settings = get_redis_settings()
        self._auth_settings = get_auth_settings()
        self._rabbit_settings = get_rabbit_settings()
        self._backup_settings = get_backup_settings()
        self._consul_settings = get_consul_settings()
        self._health_settings = get_health_settings()

    def _get_aggregator(self) -> HealthAggregator:
        """Get or create the health aggregator.

        Lazily creates and configures the aggregator on first access
        if not provided in constructor.

        Returns:
            Configured HealthAggregator instance
        """
        if self._aggregator is not None:
            return self._aggregator

        # Import here to avoid circular dependencies
        from example_service.features.health.aggregator import HealthAggregator

        # Create aggregator with health settings
        self._aggregator = HealthAggregator(settings=self._health_settings)
        self._configure_providers()
        return self._aggregator

    def _configure_providers(self) -> None:
        """Auto-configure health providers based on settings."""
        if self._aggregator is None:
            return

        # Database provider
        if self._db_settings.health_checks_enabled and self._health_settings.database.enabled:
            try:
                from example_service.features.health.providers import (
                    DatabaseHealthProvider,
                    DatabasePoolHealthProvider,
                )
                from example_service.infra.database.session import engine

                # Database connectivity check with per-provider configuration
                self._aggregator.add_provider(
                    DatabaseHealthProvider(
                        engine=engine,
                        config=self._health_settings.database,
                    )
                )

                # Database connection pool monitoring
                # Pool health is not critical for readiness - service can start even if pool is stressed
                self._aggregator.add_provider(
                    DatabasePoolHealthProvider(
                        engine=engine,
                        degraded_threshold=0.7,  # Alert at 70% utilization
                        unhealthy_threshold=0.9,  # Critical at 90% utilization
                    )
                )
            except Exception as e:
                logger.warning(f"Could not configure database health provider: {e}")

        # Redis provider
        if self._redis_settings.health_checks_enabled and self._health_settings.cache.enabled:
            try:
                from example_service.features.health.providers import (
                    RedisHealthProvider,
                )
                from example_service.infra.cache.redis import get_redis_cache

                cache = get_redis_cache()
                if cache is not None:
                    self._aggregator.add_provider(
                        RedisHealthProvider(
                            cache=cache,
                            config=self._health_settings.cache,
                        )
                    )
            except Exception as e:
                logger.warning(f"Could not configure Redis health provider: {e}")

        # RabbitMQ provider
        if self._rabbit_settings.is_configured and self._health_settings.rabbitmq.enabled:
            try:
                from example_service.features.health.providers import (
                    RabbitMQHealthProvider,
                )

                self._aggregator.add_provider(
                    RabbitMQHealthProvider(
                        connection_url=self._rabbit_settings.get_url(),
                        config=self._health_settings.rabbitmq,
                    )
                )
            except Exception as e:
                logger.warning(f"Could not configure RabbitMQ health provider: {e}")

        # External auth service provider
        if (
            self._auth_settings.service_url
            and self._auth_settings.health_checks_enabled
            and self._health_settings.accent_auth.enabled
        ):
            try:
                from example_service.features.health.providers import (
                    ExternalServiceHealthProvider,
                )

                self._aggregator.add_provider(
                    ExternalServiceHealthProvider(
                        name="auth_service",
                        base_url=str(self._auth_settings.service_url),
                        config=self._health_settings.accent_auth,
                    )
                )
            except Exception as e:
                logger.warning(f"Could not configure auth service health provider: {e}")

        # S3 storage provider
        if self._backup_settings.is_s3_configured and self._health_settings.s3.enabled:
            try:
                from example_service.features.health.providers import (
                    S3StorageHealthProvider,
                )
                from example_service.infra.storage.s3 import S3Client

                s3_client = S3Client(self._backup_settings)
                self._aggregator.add_provider(
                    S3StorageHealthProvider(
                        s3_client=s3_client,
                        config=self._health_settings.s3,
                    )
                )
            except Exception as e:
                logger.warning(f"Could not configure S3 health provider: {e}")

        # Consul provider (if discovery configured)
        if self._consul_settings.is_configured and self._health_settings.consul.enabled:
            try:
                from example_service.features.health.providers import (
                    ConsulHealthProvider,
                    ProviderConfig,
                )
                from example_service.infra.discovery import get_discovery_service

                # Get the Consul service (may be None if not started yet)
                discovery_service = get_discovery_service()
                if discovery_service is not None and discovery_service._client is not None:
                    # Convert health settings to ProviderConfig
                    config = ProviderConfig(
                        enabled=self._health_settings.consul.enabled,
                        timeout=self._health_settings.consul.timeout,
                        latency_threshold_ms=self._health_settings.consul.degraded_threshold_ms,
                    )

                    self._aggregator.add_provider(
                        ConsulHealthProvider(
                            consul_client=discovery_service._client,
                            service_name=self._app_settings.service_name,
                            config=config,
                        )
                    )
                    logger.info("Consul health provider configured")
                else:
                    logger.debug(
                        "Consul health provider not configured: discovery service not started"
                    )
            except Exception as e:
                logger.warning(f"Could not configure Consul health provider: {e}")

    async def check_health(self) -> dict[str, Any]:
        """Perform comprehensive health check.

        Returns health status with dependency checks suitable for
        monitoring and alerting.

        Returns:
            Health check result with status, timestamp, and dependency checks.

        Example:
            >>> service = HealthService()
            >>> health = await service.check_health()
            >>> # {
            >>> #   "status": "healthy",
            >>> #   "timestamp": "2025-01-01T00:00:00Z",
            >>> #   "service": "example-service",
            >>> #   "version": "0.1.0",
            >>> #   "checks": {"database": true, "cache": true}
            >>> # }
        """
        aggregator = self._get_aggregator()
        providers = aggregator.list_providers()

        if not providers:
            # No providers configured - return basic healthy status
            return {
                "status": HealthStatus.HEALTHY.value,
                "timestamp": datetime.now(UTC),
                "service": self._app_settings.service_name,
                "version": "0.1.0",
                "checks": {},
            }

        # Run all health checks via aggregator
        result = await aggregator.check_all()

        return {
            "status": result.status.value,
            "timestamp": result.timestamp,
            "service": self._app_settings.service_name,
            "version": "0.1.0",
            "checks": {
                name: check.status == HealthStatus.HEALTHY
                for name, check in result.checks.items()
            },
        }

    async def check_health_detailed(self, force_refresh: bool = False) -> dict[str, Any]:
        """Perform health check with detailed provider information.

        Returns extended health information including latency and
        messages for each provider.

        Args:
            force_refresh: If True, bypass cache and run fresh checks.

        Returns:
            Detailed health check result with per-provider metrics.
        """
        aggregator = self._get_aggregator()
        result = await aggregator.check_all(force_refresh=force_refresh)

        return {
            "status": result.status.value,
            "timestamp": result.timestamp,
            "service": self._app_settings.service_name,
            "version": "0.1.0",
            "duration_ms": result.duration_ms,
            "from_cache": result.from_cache,
            "checks": {
                name: {
                    "healthy": check.status == HealthStatus.HEALTHY,
                    "status": check.status.value,
                    "message": check.message,
                    "latency_ms": round(check.latency_ms, 2),
                }
                for name, check in result.checks.items()
            },
        }

    async def readiness(self) -> dict[str, Any]:
        """Kubernetes readiness probe.

        Checks if service is ready to accept traffic. Returns 200 if ready,
        503 if not ready. Kubernetes uses this to determine if pod should
        receive traffic.

        Critical dependencies must pass for service to be ready:
        - Database connection (if configured)

        Returns:
            Readiness check result.

        Example:
            >>> result = await service.readiness()
            >>> if result["ready"]:
            ...     # Service can accept traffic
            ...     pass
        """
        aggregator = self._get_aggregator()

        # Get list of providers marked as critical for readiness
        critical_providers = self._health_settings.list_critical_providers()

        checks: dict[str, bool] = {}

        for name in critical_providers:
            result = await aggregator.check_provider(name)
            if result is not None:
                checks[name] = result.status == HealthStatus.HEALTHY

        # If no critical providers configured, consider ready
        all_ready = all(checks.values()) if checks else True

        return {
            "ready": all_ready,
            "checks": checks,
            "timestamp": datetime.now(UTC),
        }

    async def liveness(self) -> dict[str, Any]:
        """Kubernetes liveness probe.

        Simple check that service is alive and responsive. Returns 200 if alive.
        Kubernetes uses this to determine if pod should be restarted.

        This is a lightweight check that only verifies the application
        is running and not deadlocked.

        Returns:
            Liveness check result.

        Example:
            >>> result = await service.liveness()
            >>> # Always returns {"alive": True} if code executes
        """
        return {
            "alive": True,
            "timestamp": datetime.now(UTC),
            "service": self._app_settings.service_name,
        }

    async def startup(self) -> dict[str, Any]:
        """Kubernetes startup probe.

        Checks if service has completed initialization. Used by Kubernetes
        to know when to start readiness/liveness checks.

        Returns:
            Startup check result.
        """
        return {
            "started": True,
            "timestamp": datetime.now(UTC),
        }

    def get_aggregator(self) -> HealthAggregator:
        """Get the underlying health aggregator.

        Useful for adding custom providers or accessing detailed results.

        Returns:
            The HealthAggregator instance used by this service.
        """
        return self._get_aggregator()


__all__ = ["HealthService"]
