"""Redis health check provider.

Checks Redis cache connectivity and availability.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from example_service.core.schemas.common import HealthStatus

from .protocol import HealthCheckResult

logger = logging.getLogger(__name__)


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
