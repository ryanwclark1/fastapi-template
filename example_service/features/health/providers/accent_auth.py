"""Accent-Auth health check provider.

This provider monitors the health of the Accent-Auth service without blocking
application startup. It allows the service to report degraded mode when auth
is unavailable while still serving requests that don't require authentication.

When running within accent-auth service itself, this provider checks database
connectivity directly instead of making HTTP calls to itself.
"""

from __future__ import annotations

import logging
import time

import httpx

from example_service.core.schemas.common import HealthStatus
from example_service.core.settings import get_app_settings, get_auth_settings
from example_service.infra.auth.accent_auth import _is_running_internally
from example_service.infra.database import get_async_session

from .protocol import HealthCheckResult

logger = logging.getLogger(__name__)


class AccentAuthHealthProvider:
    """Health check provider for Accent-Auth service.

    Monitors the availability of the Accent-Auth service. When running within
    accent-auth service itself, checks database connectivity directly. For
    external services, performs lightweight HTTP requests to verify connectivity.

    The health check:
    - Does NOT block application startup
    - Reports degraded mode when auth is unavailable
    - Allows the application to recover automatically when auth comes back

    Example:
        # In lifespan.py startup
        from example_service.features.health.providers import (
            AccentAuthHealthProvider,
        )
        from example_service.features.health.service import get_health_aggregator

        aggregator = get_health_aggregator()
        if aggregator:
            aggregator.add_provider(AccentAuthHealthProvider())
            logger.info("Accent-Auth health provider registered")
    """

    def __init__(self) -> None:
        """Initialize Accent-Auth health provider."""
        self._auth_settings = get_auth_settings()
        self._app_settings = get_app_settings()
        self._is_internal = _is_running_internally()

    @property
    def name(self) -> str:
        """Return provider name."""
        return "accent-auth"

    async def check_health(self) -> HealthCheckResult:
        """Check Accent-Auth service health.

        When running internally, checks database connectivity directly.
        When running externally, performs HTTP health check.

        Returns:
            HealthCheckResult with status:
            - HEALTHY: Service is responding
            - UNHEALTHY: Service is not responding
            - DEGRADED: Service is slow but responding

        Note:
            This does NOT prevent the application from starting or operating.
            Authentication requests will simply fail at request time if the
            service is unavailable.
        """
        if self._is_internal:
            return await self._check_health_internal()
        return await self._check_health_external()

    async def _check_health_internal(self) -> HealthCheckResult:
        """Check health using internal database access.

        Returns:
            HealthCheckResult indicating database connectivity
        """
        start = time.perf_counter()

        try:
            # Simple connectivity check: execute a trivial query
            from sqlalchemy import text

            async with get_async_session() as db_session:
                await db_session.execute(text("SELECT 1"))
                await db_session.commit()

            latency_ms = (time.perf_counter() - start) * 1000

            status = HealthStatus.HEALTHY if latency_ms < 50 else HealthStatus.DEGRADED

            return HealthCheckResult(
                status=status,
                message="Accent-Auth database accessible (internal mode)",
                latency_ms=latency_ms,
                metadata={
                    "mode": "internal",
                    "latency_ms": round(latency_ms, 2),
                    "service_name": self._app_settings.service_name,
                },
            )

        except Exception as e:
            logger.warning(
                "Accent-Auth database health check failed",
                extra={"error": str(e)},
            )
            latency_ms = (time.perf_counter() - start) * 1000
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message="Accent-Auth database not accessible",
                latency_ms=latency_ms,
                metadata={
                    "mode": "internal",
                    "error": str(e),
                    "service_name": self._app_settings.service_name,
                },
            )

    async def _check_health_external(self) -> HealthCheckResult:
        """Check health using HTTP request (external mode).

        Returns:
            HealthCheckResult indicating HTTP service availability
        """
        if not self._auth_settings.service_url:
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message="AUTH_SERVICE_URL not configured",
                metadata={"error": "AUTH_SERVICE_URL not configured"},
            )

        try:
            start = time.perf_counter()

            # Perform a simple HEAD request to check connectivity
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.head(
                    f"{self._auth_settings.service_url}/api/auth/0.1/token/check",
                    headers={"X-Auth-Token": "health-check"},  # Invalid token is OK
                )

            latency_ms = (time.perf_counter() - start) * 1000

            # We expect 401 (unauthorized) which means the service is up
            # Any response (including 401) means the service is reachable
            if response.status_code in (200, 401, 404):
                # Determine status based on latency
                status = (
                    HealthStatus.HEALTHY if latency_ms < 100 else HealthStatus.DEGRADED
                )

                return HealthCheckResult(
                    status=status,
                    message="Accent-Auth service responding",
                    latency_ms=latency_ms,
                    metadata={
                        "mode": "external",
                        "url": str(self._auth_settings.service_url),
                        "latency_ms": round(latency_ms, 2),
                        "status_code": response.status_code,
                    },
                )

            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message="Unexpected status code from Accent-Auth",
                latency_ms=latency_ms,
                metadata={
                    "mode": "external",
                    "url": str(self._auth_settings.service_url),
                    "status_code": response.status_code,
                    "error": "Unexpected status code",
                },
            )

        except httpx.ConnectError as e:
            logger.warning(
                "Accent-Auth connection failed",
                extra={"url": str(self._auth_settings.service_url), "error": str(e)},
            )
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message="Accent-Auth connection failed",
                metadata={
                    "mode": "external",
                    "url": str(self._auth_settings.service_url),
                    "error": "Connection failed",
                    "details": str(e),
                },
            )
        except httpx.TimeoutException as e:
            logger.warning(
                "Accent-Auth request timeout",
                extra={"url": str(self._auth_settings.service_url), "error": str(e)},
            )
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message="Accent-Auth request timeout",
                metadata={
                    "mode": "external",
                    "url": str(self._auth_settings.service_url),
                    "error": "Request timeout",
                    "timeout": self._auth_settings.request_timeout,
                },
            )
        except Exception as e:
            logger.exception(
                "Accent-Auth health check failed",
                extra={"url": str(self._auth_settings.service_url), "error": str(e)},
            )
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message="Accent-Auth health check failed",
                metadata={
                    "mode": "external",
                    "url": str(self._auth_settings.service_url),
                    "error": str(e),
                },
            )
