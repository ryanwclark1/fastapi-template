"""Health check service."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from example_service.core.schemas.common import HealthStatus
from example_service.core.services.base import BaseService
from example_service.core.settings import (
    get_app_settings,
    get_auth_settings,
    get_backup_settings,
    get_db_settings,
    get_rabbit_settings,
    get_redis_settings,
)

app_settings = get_app_settings()
db_settings = get_db_settings()
redis_settings = get_redis_settings()
auth_settings = get_auth_settings()
rabbit_settings = get_rabbit_settings()
backup_settings = get_backup_settings()

logger = logging.getLogger(__name__)


class HealthService(BaseService):
    """Service for health checks and status monitoring.

    Provides methods to check the health of the application
    and its dependencies. Implements Kubernetes-ready health checks
    with readiness and liveness probes.
    """

    async def check_health(self) -> dict[str, Any]:
        """Perform comprehensive health check.

        Returns health status with dependency checks suitable for
        monitoring and alerting.

        Returns:
            Health check result with status, timestamp, and dependency checks.

        Example:
                    service = HealthService()
            health = await service.check_health()
            # {
            #   "status": "healthy",
            #   "timestamp": "2025-01-01T00:00:00Z",
            #   "service": "example-service",
            #   "version": "0.1.0",
            #   "checks": {"database": true, "cache": true}
            # }
        """
        # Perform all health checks
        checks = await self._perform_health_checks()

        # Determine overall status
        all_healthy = all(checks.values())
        any_healthy = any(checks.values())

        if all_healthy:
            status = HealthStatus.HEALTHY.value
        elif any_healthy:
            status = HealthStatus.DEGRADED.value
        else:
            status = HealthStatus.UNHEALTHY.value

        return {
            "status": status,
            "timestamp": datetime.now(UTC),
            "service": app_settings.service_name,
            "version": "0.1.0",
            "checks": checks,
        }

    async def readiness(self) -> dict[str, Any]:
        """Kubernetes readiness probe.

        Checks if service is ready to accept traffic. Returns 200 if ready,
        503 if not ready. Kubernetes uses this to determine if pod should
        receive traffic.

        Critical dependencies must pass for service to be ready:
        - Database connection
        - Required external services

        Returns:
            Readiness check result.

        Example:
                    result = await service.readiness()
            if result["ready"]:
                # Service can accept traffic
                pass
        """
        checks = await self._perform_readiness_checks()
        all_ready = all(checks.values())

        return {
            "ready": all_ready,
            "checks": checks,
            "timestamp": datetime.now(UTC),
        }

    async def liveness(self) -> dict[str, Any]:
        """Kubernetes liveness probe.

        Simple check that service is alive and responsive. Returns 200 if alive.
        Kubernetes uses this to determine if pod should be restarted.

        This should be a lightweight check that only verifies the application
        is running and not deadlocked.

        Returns:
            Liveness check result.

        Example:
                    result = await service.liveness()
            # Always returns {"alive": True} if code executes
        """
        return {
            "alive": True,
            "timestamp": datetime.now(UTC),
            "service": app_settings.service_name,
        }

    async def startup(self) -> dict[str, Any]:
        """Kubernetes startup probe.

        Checks if service has completed initialization. Used by Kubernetes
        to know when to start readiness/liveness checks.

        Returns:
            Startup check result.
        """
        # For now, service starts immediately
        # Add initialization checks here if needed
        return {
            "started": True,
            "timestamp": datetime.now(UTC),
        }

    async def _perform_health_checks(self) -> dict[str, bool]:
        """Perform all health checks for dependencies.

        Returns:
            Dictionary of check results.
        """
        checks: dict[str, bool] = {}

        # Database check (if configured)
        if db_settings.health_checks_enabled:
            checks["database"] = await self._check_database()
        else:
            checks["database"] = True  # Disabled in settings, assume healthy

        # Cache check (if configured)
        if redis_settings.health_checks_enabled:
            checks["cache"] = await self._check_cache()
        else:
            checks["cache"] = True  # Disabled, don't fail

        # External services (if configured)
        if auth_settings.service_url and auth_settings.health_checks_enabled:
            checks["auth_service"] = await self._check_external_service(
                "auth",
                str(auth_settings.service_url),
            )
        else:
            checks["auth_service"] = True

        # Messaging check (if configured)
        if rabbit_settings.is_configured:
            checks["messaging"] = await self._check_messaging()
        else:
            checks["messaging"] = True  # Not configured, don't fail

        # Storage check (if configured)
        if backup_settings.is_s3_configured:
            checks["storage"] = await self._check_storage()
        else:
            checks["storage"] = True  # Not configured, don't fail

        return checks

    async def _perform_readiness_checks(self) -> dict[str, bool]:
        """Perform readiness checks for critical dependencies.

        Returns:
            Dictionary of readiness check results.
        """
        checks: dict[str, bool] = {}

        # Database is critical for readiness
        if db_settings.health_checks_enabled:
            checks["database"] = await self._check_database()
        else:
            checks["database"] = True

        # Cache is not critical (service can run without it)
        # External services depend on your requirements

        return checks

    async def _check_database(self) -> bool:
        """Check database connectivity.

        Uses health_check_timeout from PostgresSettings to limit check duration.

        Returns:
            True if database is accessible, False otherwise.
        """
        try:
            # Import here to avoid circular dependencies
            import asyncio

            from sqlalchemy import text

            from example_service.infra.database.session import engine

            async with asyncio.timeout(db_settings.health_check_timeout):
                async with engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
            return True
        except TimeoutError:
            logger.error(
                "Database health check timed out",
                extra={"timeout": db_settings.health_check_timeout},
            )
            return False
        except Exception as e:
            logger.error(f"Database health check failed: {e}", extra={"exception": str(e)})
            return False

    async def _check_cache(self) -> bool:
        """Check cache connectivity.

        Returns:
            True if cache is accessible, False otherwise.
        """
        try:
            from example_service.infra.cache.redis import get_cache

            async for cache in get_cache():
                return await cache.health_check()
            return False
        except Exception as e:
            logger.error(f"Cache health check failed: {e}", extra={"exception": str(e)})
            return False

    async def _check_external_service(self, name: str, url: str) -> bool:
        """Check external service health.

        Args:
            name: Service name for logging.
            url: Service URL.

        Returns:
            True if service is healthy, False otherwise.
        """
        try:
            import httpx

            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{url}/health", follow_redirects=True)
                return response.status_code == 200
        except Exception as e:
            logger.warning(
                f"External service {name} health check failed: {e}",
                extra={"service": name, "url": url, "exception": str(e)},
            )
            return False

    async def _check_messaging(self) -> bool:
        """Check messaging broker (RabbitMQ) connectivity.

        Returns:
            True if messaging broker is accessible, False otherwise.
        """
        try:
            import aio_pika

            connection = await aio_pika.connect_robust(rabbit_settings.get_url(), timeout=5.0)
            await connection.close()
            return True
        except Exception as e:
            logger.warning(
                f"Messaging health check failed: {e}",
                extra={"exception": str(e)},
            )
            return False

    async def _check_storage(self) -> bool:
        """Check storage (S3) connectivity.

        Returns:
            True if storage is accessible, False otherwise.
        """
        try:
            from example_service.infra.storage.s3 import S3Client

            client = S3Client(backup_settings)
            # Try to list objects with a limit to verify connectivity
            # This is a lightweight operation that confirms S3 access
            await client.list_objects(prefix="", max_keys=1)
            return True
        except Exception as e:
            logger.warning(
                f"Storage health check failed: {e}",
                extra={"exception": str(e)},
            )
            return False
