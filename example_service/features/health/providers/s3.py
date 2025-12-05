"""S3-compatible storage health check provider.

Monitors S3/MinIO storage connectivity and availability.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from example_service.core.schemas.common import HealthStatus

from .protocol import HealthCheckResult

logger = logging.getLogger(__name__)


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
