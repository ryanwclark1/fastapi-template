"""Health check provider for S3/MinIO storage service.

Provides health monitoring for the storage service with:
- Connectivity checks via HEAD request to health check object
- Latency tracking with degraded threshold
- Detailed metadata about storage configuration
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from example_service.core.schemas.common import HealthStatus
from .protocol import DEGRADED_LATENCY_THRESHOLD_MS, HealthCheckResult

if TYPE_CHECKING:
    from example_service.infra.storage.service import StorageService


class StorageHealthProvider:
    """Health check provider for storage service.

    Implements the HealthProvider protocol to integrate with the
    application's health aggregator.

    The health check performs a lightweight operation (HEAD request)
    to verify S3 connectivity without transferring data.

    Example:
        >>> from example_service.infra.storage.service import get_storage_service
        >>> from example_service.features.health.storage_provider import (
        ...     StorageHealthProvider,
        ... )
        >>> from example_service.features.health.service import get_health_aggregator
        >>>
        >>> storage = get_storage_service()
        >>> provider = StorageHealthProvider(storage)
        >>> aggregator = get_health_aggregator()
        >>> if aggregator:
        ...     aggregator.add_provider(provider)
    """

    def __init__(
        self,
        storage_service: StorageService,
        timeout: float = 5.0,
        latency_threshold_ms: float = DEGRADED_LATENCY_THRESHOLD_MS,
    ) -> None:
        """Initialize the storage health provider.

        Args:
            storage_service: The storage service instance to check
            timeout: Timeout in seconds for health check operations
            latency_threshold_ms: Latency threshold for DEGRADED status
        """
        self._storage = storage_service
        self._timeout = timeout
        self._latency_threshold = latency_threshold_ms

    @property
    def name(self) -> str:
        """Unique identifier for this health check.

        Returns:
            Provider name used in health check responses
        """
        return "storage"

    async def check_health(self) -> HealthCheckResult:
        """Check storage service connectivity and responsiveness.

        Performs a lightweight health check operation to verify that the
        storage service is available and responding within acceptable
        latency thresholds.

        Status determination:
        - HEALTHY: Service is ready and responding within latency threshold
        - DEGRADED: Service is responding but latency exceeds threshold
        - UNHEALTHY: Service is not ready, timed out, or encountered errors

        Returns:
            HealthCheckResult with status, message, latency, and metadata
        """
        start_time = time.perf_counter()

        # Check if service is initialized
        if not self._storage.is_ready:
            latency_ms = (time.perf_counter() - start_time) * 1000
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message="Storage service not initialized",
                latency_ms=latency_ms,
                metadata={
                    "is_ready": False,
                    "reason": "not_initialized",
                },
            )

        try:
            async with asyncio.timeout(self._timeout):
                # Perform health check via the storage service
                is_healthy = await self._storage.health_check()

            latency_ms = (time.perf_counter() - start_time) * 1000

            if not is_healthy:
                return HealthCheckResult(
                    status=HealthStatus.UNHEALTHY,
                    message="Storage health check failed",
                    latency_ms=latency_ms,
                    metadata=self._get_metadata(is_healthy=False),
                )

            # Check for degraded performance
            if latency_ms > self._latency_threshold:
                return HealthCheckResult(
                    status=HealthStatus.DEGRADED,
                    message=f"High latency: {latency_ms:.2f}ms",
                    latency_ms=latency_ms,
                    metadata=self._get_metadata(is_healthy=True, latency_ms=latency_ms),
                )

            return HealthCheckResult(
                status=HealthStatus.HEALTHY,
                message="Storage service operational",
                latency_ms=latency_ms,
                metadata=self._get_metadata(is_healthy=True, latency_ms=latency_ms),
            )

        except TimeoutError:
            latency_ms = (time.perf_counter() - start_time) * 1000
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Timeout after {self._timeout}s",
                latency_ms=latency_ms,
                metadata={
                    **self._get_metadata(is_healthy=False),
                    "error": "timeout",
                    "timeout_seconds": self._timeout,
                },
            )

        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Health check error: {e}",
                latency_ms=latency_ms,
                metadata={
                    **self._get_metadata(is_healthy=False),
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )

    def _get_metadata(
        self,
        is_healthy: bool,
        latency_ms: float | None = None,
    ) -> dict[str, Any]:
        """Build metadata dictionary for health check result.

        Args:
            is_healthy: Whether the health check passed
            latency_ms: Optional latency measurement in milliseconds

        Returns:
            Dictionary containing health check metadata including:
            - is_ready: Whether the storage service is initialized
            - is_healthy: Whether the health check passed
            - bucket: S3 bucket name (if settings available)
            - endpoint: S3 endpoint URL (if settings available)
            - region: S3 region (if settings available)
            - is_minio: Whether using MinIO (if settings available)
            - latency_ms: Health check latency (if provided)
            - latency_threshold_ms: Configured latency threshold (if latency provided)
        """
        metadata: dict[str, Any] = {
            "is_ready": self._storage.is_ready,
            "is_healthy": is_healthy,
        }

        # Add settings info if available
        if self._storage._settings:
            settings = self._storage._settings
            metadata.update({
                "bucket": settings.bucket,
                "endpoint": settings.endpoint,
                "region": settings.region,
                "is_minio": settings.is_minio,
            })

        if latency_ms is not None:
            metadata["latency_ms"] = round(latency_ms, 2)
            metadata["latency_threshold_ms"] = self._latency_threshold

        return metadata


__all__ = [
    "StorageHealthProvider",
]
