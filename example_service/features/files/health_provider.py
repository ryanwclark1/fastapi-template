"""Storage health provider for S3/MinIO connectivity monitoring.

This module provides a health check provider that verifies S3-compatible
storage connectivity and responsiveness.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from example_service.core.schemas.common import HealthStatus
from example_service.features.health.providers import HealthCheckResult

if TYPE_CHECKING:
    from example_service.infra.storage.client import StorageClient

logger = logging.getLogger(__name__)


class StorageHealthProvider:
    """Health provider for S3-compatible file storage.

    Checks storage connectivity and responsiveness by performing
    a lightweight list operation.

    Example:
        >>> from example_service.infra.storage.client import get_storage_client
        >>> storage_client = get_storage_client()
        >>> if storage_client:
        ...     provider = StorageHealthProvider(storage_client)
        ...     aggregator.add_provider(provider)
    """

    def __init__(
        self,
        storage_client: StorageClient,
        timeout: float = 5.0,
        latency_threshold_ms: float = 1000.0,
    ) -> None:
        """Initialize storage health provider.

        Args:
            storage_client: StorageClient instance
            timeout: Health check timeout in seconds
            latency_threshold_ms: Latency threshold for DEGRADED status
        """
        self._client = storage_client
        self._timeout = timeout
        self._latency_threshold = latency_threshold_ms

    @property
    def name(self) -> str:
        """Return provider name."""
        return "file_storage"

    async def check_health(self) -> HealthCheckResult:
        """Check storage connectivity and responsiveness.

        Returns:
            HealthCheckResult with status, latency, and metadata
        """
        import asyncio

        from example_service.infra.storage.client import StorageClientError

        start_time = time.perf_counter()

        try:
            async with asyncio.timeout(self._timeout):
                # Perform lightweight check - verify bucket exists
                # We use get_file_info with a non-existent key to check connectivity
                # This is cheaper than listing objects
                await self._client.get_file_info("__health_check__")
                # Note: We don't care if the file exists, only that we can connect

            latency_ms = (time.perf_counter() - start_time) * 1000

            # Check if latency is degraded
            if latency_ms > self._latency_threshold:
                return HealthCheckResult(
                    status=HealthStatus.DEGRADED,
                    message=f"Storage responding slowly: {latency_ms:.2f}ms",
                    latency_ms=latency_ms,
                    metadata={
                        "bucket": self._client.settings.bucket,
                        "is_minio": self._client.settings.is_minio,
                    },
                )

            return HealthCheckResult(
                status=HealthStatus.HEALTHY,
                message="Storage operational",
                latency_ms=latency_ms,
                metadata={
                    "bucket": self._client.settings.bucket,
                    "is_minio": self._client.settings.is_minio,
                },
            )

        except TimeoutError:
            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(
                "Storage health check timed out",
                extra={"timeout": self._timeout, "bucket": self._client.settings.bucket},
            )
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Timeout after {self._timeout}s",
                latency_ms=latency_ms,
                metadata={
                    "error": "timeout",
                    "bucket": self._client.settings.bucket,
                },
            )

        except StorageClientError as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(
                "Storage health check failed",
                extra={
                    "error": str(e),
                    "bucket": self._client.settings.bucket,
                },
            )
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Storage error: {e}",
                latency_ms=latency_ms,
                metadata={
                    "error": str(e),
                    "bucket": self._client.settings.bucket,
                },
            )

        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.exception(
                "Unexpected error in storage health check",
                extra={
                    "error": str(e),
                    "bucket": self._client.settings.bucket,
                },
            )
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Unexpected error: {e}",
                latency_ms=latency_ms,
                metadata={
                    "error": str(e),
                    "bucket": self._client.settings.bucket,
                },
            )


__all__ = ["StorageHealthProvider"]
