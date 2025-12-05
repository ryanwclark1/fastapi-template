"""Health provider for task execution tracker.

This module provides health monitoring for the task tracking system,
which can use either Redis or PostgreSQL as its backend.

Example:
    >>> from example_service.features.health.task_tracker_provider import (
    ...     TaskTrackerHealthProvider,
    ... )
    >>> from example_service.features.health.service import get_health_aggregator
    >>>
    >>> aggregator = get_health_aggregator()
    >>> aggregator.add_provider(TaskTrackerHealthProvider())
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from example_service.core.schemas.common import HealthStatus
from example_service.core.settings.health import ProviderConfig

from .protocol import DEGRADED_LATENCY_THRESHOLD_MS, HealthCheckResult

if TYPE_CHECKING:
    from example_service.infra.tasks.tracking.base import BaseTaskTracker

logger = logging.getLogger(__name__)


class TaskTrackerHealthProvider:
    """Health provider for task execution tracking system.

    Monitors the task tracker's connectivity and responsiveness.
    The tracker can use either Redis or PostgreSQL as its backend,
    determined by the TASK_RESULT_BACKEND setting.

    Checks performed:
    - **Connectivity**: Verifies tracker is connected to its backend
    - **Query capability**: Attempts to retrieve recent task stats
    - **Latency**: Measures response time for degradation detection

    Status determination:
    - HEALTHY: Tracker connected and responding within threshold
    - DEGRADED: Tracker connected but high latency or tracking disabled
    - UNHEALTHY: Tracker not connected or query failed

    Example:
        >>> provider = TaskTrackerHealthProvider(timeout=2.0)
        >>> result = await provider.check_health()
        >>> print(result.status)  # HealthStatus.HEALTHY
        >>> print(result.metadata)
        {
            "backend": "redis",
            "is_connected": True,
            "running_tasks": 2,
            "total_24h": 1440
        }
    """

    def __init__(
        self,
        tracker: BaseTaskTracker | None = None,
        config: ProviderConfig | None = None,
        timeout: float = 2.0,
        latency_threshold_ms: float = DEGRADED_LATENCY_THRESHOLD_MS,
    ) -> None:
        """Initialize task tracker health provider.

        Args:
            tracker: Task tracker instance (defaults to global tracker).
            config: Optional provider configuration.
            timeout: Health check timeout in seconds.
            latency_threshold_ms: Latency threshold for DEGRADED status.
        """
        self._tracker = tracker
        self._config = config or ProviderConfig(
            timeout=timeout,
            latency_threshold_ms=latency_threshold_ms,
        )

    @property
    def name(self) -> str:
        """Return provider name."""
        return "task_tracker"

    def _get_tracker(self) -> BaseTaskTracker | None:
        """Get the task tracker instance.

        Returns the injected tracker or falls back to the global tracker.
        """
        if self._tracker is not None:
            return self._tracker

        from example_service.infra.tasks.tracking import get_tracker

        return get_tracker()

    def _get_backend_name(self) -> str:
        """Get the configured backend name.

        Returns:
            Backend name ('redis' or 'postgres') or 'unknown'.
        """
        try:
            from example_service.core.settings import get_task_settings

            settings = get_task_settings()
            return settings.result_backend
        except Exception:
            return "unknown"

    async def check_health(self) -> HealthCheckResult:
        """Check task tracker health.

        Verifies the tracker is connected and can execute queries.
        Also retrieves basic statistics for the metadata.

        Returns:
            HealthCheckResult with tracker status and metadata.
        """
        import asyncio

        start_time = time.perf_counter()
        backend = self._get_backend_name()

        # Check if tracking is enabled
        try:
            from example_service.core.settings import get_task_settings

            settings = get_task_settings()
            if not settings.tracking_enabled:
                latency_ms = (time.perf_counter() - start_time) * 1000
                return HealthCheckResult(
                    status=HealthStatus.DEGRADED,
                    message="Task tracking is disabled",
                    latency_ms=latency_ms,
                    metadata={
                        "backend": backend,
                        "tracking_enabled": False,
                    },
                )
        except Exception as e:
            logger.debug("Failed to record task tracker health check", exc_info=e)

        # Get tracker
        tracker = self._get_tracker()

        if tracker is None:
            latency_ms = (time.perf_counter() - start_time) * 1000
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message="Task tracker not initialized",
                latency_ms=latency_ms,
                metadata={
                    "backend": backend,
                    "is_connected": False,
                },
            )

        # Check connection status
        if not tracker.is_connected:
            latency_ms = (time.perf_counter() - start_time) * 1000
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message="Task tracker not connected",
                latency_ms=latency_ms,
                metadata={
                    "backend": backend,
                    "is_connected": False,
                },
            )

        # Try to get stats as a health indicator
        try:
            async with asyncio.timeout(self._config.timeout):
                stats = await tracker.get_stats(hours=24)
                running_tasks = await tracker.get_running_tasks()

            latency_ms = (time.perf_counter() - start_time) * 1000

            metadata = {
                "backend": backend,
                "is_connected": True,
                "running_tasks": len(running_tasks),
                "total_24h": stats.get("total_count", 0),
                "success_24h": stats.get("success_count", 0),
                "failure_24h": stats.get("failure_count", 0),
            }

            # Check for high latency
            if latency_ms > self._config.degraded_threshold_ms:
                return HealthCheckResult(
                    status=HealthStatus.DEGRADED,
                    message=f"High latency: {latency_ms:.2f}ms",
                    latency_ms=latency_ms,
                    metadata=metadata,
                )

            return HealthCheckResult(
                status=HealthStatus.HEALTHY,
                message=f"Task tracker operational ({backend})",
                latency_ms=latency_ms,
                metadata=metadata,
            )

        except TimeoutError:
            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(
                "Task tracker health check timed out",
                extra={"timeout": self._config.timeout, "backend": backend},
            )
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Timeout after {self._config.timeout}s",
                latency_ms=latency_ms,
                metadata={
                    "backend": backend,
                    "is_connected": True,
                    "error": "timeout",
                },
            )

        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(
                "Task tracker health check failed",
                extra={"error": str(e), "backend": backend},
            )
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Query failed: {e}",
                latency_ms=latency_ms,
                metadata={
                    "backend": backend,
                    "is_connected": tracker.is_connected,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )


__all__ = ["TaskTrackerHealthProvider"]
