"""External HTTP service health check provider.

Checks health by making GET requests to external service health endpoints.
"""

from __future__ import annotations

import logging
import time

from example_service.core.schemas.common import HealthStatus

from .protocol import HealthCheckResult

logger = logging.getLogger(__name__)


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
