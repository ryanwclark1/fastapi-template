"""Accent-Auth health check provider.

This provider monitors the health of the Accent-Auth service without blocking
application startup. It allows the service to report degraded mode when auth
is unavailable while still serving requests that don't require authentication.
"""

from __future__ import annotations

import logging

from example_service.core.settings import get_auth_settings
from example_service.features.health.base import (
    ComponentHealth,
    ComponentStatus,
    HealthProvider,
)
from example_service.infra.auth.accent_auth import get_accent_auth_client

logger = logging.getLogger(__name__)


class AccentAuthHealthProvider(HealthProvider):
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
        from example_service.features.health.accent_auth_provider import (
            AccentAuthHealthProvider,
        )
        from example_service.features.health.service import get_health_aggregator

        aggregator = get_health_aggregator()
        if aggregator:
            aggregator.add_provider(AccentAuthHealthProvider())
            logger.info("Accent-Auth health provider registered")
    """

    def __init__(self):
        """Initialize Accent-Auth health provider."""
        super().__init__()
        self._settings = get_auth_settings()

    async def check_health(self) -> ComponentHealth:
        """Check Accent-Auth service health.

        Returns:
            ComponentHealth with status:
            - healthy: Service is responding
            - unhealthy: Service is not responding
            - degraded: Service is slow but responding

        Note:
            This does NOT prevent the application from starting or operating.
            Authentication requests will simply fail at request time if the
            service is unavailable.
        """
        if not self._settings.service_url:
            return ComponentHealth(
                name="accent-auth",
                status=ComponentStatus.UNHEALTHY,
                details={"error": "AUTH_SERVICE_URL not configured"},
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
                response = await client._client.head(
                    f"{client.base_url}/api/auth/0.1/token/check",
                    headers={"X-Auth-Token": "health-check"},  # Invalid token is OK
                )
                latency_ms = (time.perf_counter() - start) * 1000

                # We expect 401 (unauthorized) which means the service is up
                # Any response (including 401) means the service is reachable
                if response.status_code in (200, 401, 404):
                    # Determine status based on latency
                    if latency_ms < 100:
                        status = ComponentStatus.HEALTHY
                    else:
                        status = ComponentStatus.DEGRADED

                    return ComponentHealth(
                        name="accent-auth",
                        status=status,
                        details={
                            "url": str(self._settings.service_url),
                            "latency_ms": round(latency_ms, 2),
                            "status_code": response.status_code,
                        },
                    )
                else:
                    return ComponentHealth(
                        name="accent-auth",
                        status=ComponentStatus.UNHEALTHY,
                        details={
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
            return ComponentHealth(
                name="accent-auth",
                status=ComponentStatus.UNHEALTHY,
                details={
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
            return ComponentHealth(
                name="accent-auth",
                status=ComponentStatus.UNHEALTHY,
                details={
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
            return ComponentHealth(
                name="accent-auth",
                status=ComponentStatus.UNHEALTHY,
                details={
                    "url": str(self._settings.service_url),
                    "error": str(e),
                },
            )
