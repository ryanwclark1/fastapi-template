"""Accent-Auth health check provider.

This provider monitors the health of the Accent-Auth service without blocking
application startup. It allows the service to report degraded mode when auth
is unavailable while still serving requests that don't require authentication.
"""

from __future__ import annotations

import logging

from example_service.core.schemas.common import HealthStatus
from example_service.core.settings import get_auth_settings
from example_service.infra.auth.accent_auth import get_accent_auth_client

from .protocol import HealthCheckResult

logger = logging.getLogger(__name__)


class AccentAuthHealthProvider:
    """Health check provider for Accent-Auth service.

    Monitors the availability of the Accent-Auth service by performing
    lightweight HEAD requests to verify connectivity. Does not require
    a valid token.

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
        self._settings = get_auth_settings()

    @property
    def name(self) -> str:
        """Return provider name."""
        return "accent-auth"

    async def check_health(self) -> HealthCheckResult:
        """Check Accent-Auth service health.

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
        if not self._settings.service_url:
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message="AUTH_SERVICE_URL not configured",
                metadata={"error": "AUTH_SERVICE_URL not configured"},
            )

        client = get_accent_auth_client()

        try:
            # Use async context manager for proper resource cleanup
            async with client:
                # Perform a simple HEAD request to check connectivity
                # This doesn't require authentication and is very fast
                import time

                import httpx

                start = time.perf_counter()
                if client._client is None:
                    return HealthCheckResult(
                        status=HealthStatus.UNHEALTHY,
                        message="Accent-Auth client not initialized",
                        metadata={"error": "Client not initialized"},
                    )
                response = await client._client.head(
                    f"{client.base_url}/api/auth/0.1/token/check",
                    headers={"X-Auth-Token": "health-check"},  # Invalid token is OK
                )
                latency_ms = (time.perf_counter() - start) * 1000

                # We expect 401 (unauthorized) which means the service is up
                # Any response (including 401) means the service is reachable
                if response.status_code in (200, 401, 404):
                    # Determine status based on latency
                    status = HealthStatus.HEALTHY if latency_ms < 100 else HealthStatus.DEGRADED

                    return HealthCheckResult(
                        status=status,
                        message="Accent-Auth service responding",
                        latency_ms=latency_ms,
                        metadata={
                            "url": str(self._settings.service_url),
                            "latency_ms": round(latency_ms, 2),
                            "status_code": response.status_code,
                        },
                    )
                return HealthCheckResult(
                    status=HealthStatus.UNHEALTHY,
                    message="Unexpected status code from Accent-Auth",
                    latency_ms=latency_ms,
                    metadata={
                        "url": str(self._settings.service_url),
                        "status_code": response.status_code,
                        "error": "Unexpected status code",
                    },
                )

        except httpx.ConnectError as e:
            logger.warning(
                "Accent-Auth connection failed",
                extra={"url": str(self._settings.service_url), "error": str(e)},
            )
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message="Accent-Auth connection failed",
                metadata={
                    "url": str(self._settings.service_url),
                    "error": "Connection failed",
                    "details": str(e),
                },
            )
        except httpx.TimeoutException as e:
            logger.warning(
                "Accent-Auth request timeout",
                extra={"url": str(self._settings.service_url), "error": str(e)},
            )
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message="Accent-Auth request timeout",
                metadata={
                    "url": str(self._settings.service_url),
                    "error": "Request timeout",
                    "timeout": self._settings.request_timeout,
                },
            )
        except Exception as e:
            logger.error(
                "Accent-Auth health check failed",
                extra={"url": str(self._settings.service_url), "error": str(e)},
            )
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message="Accent-Auth health check failed",
                metadata={
                    "url": str(self._settings.service_url),
                    "error": str(e),
                },
            )
