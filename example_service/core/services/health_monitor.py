"""Background health monitor for external service availability.

This module provides a background task that periodically checks the health
of external services and updates the ServiceAvailabilityRegistry.

The health monitor:
- Runs health checks at configurable intervals
- Uses service-specific health check implementations
- Updates metrics for observability
- Supports immediate health check triggers via API

Example:
    from example_service.core.services.health_monitor import (
        start_health_monitor,
        stop_health_monitor,
        trigger_health_check,
    )

    # In lifespan startup
    await start_health_monitor()

    # In admin endpoint
    results = await trigger_health_check()

    # In lifespan shutdown
    await stop_health_monitor()
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from typing import Any

from example_service.core.services.availability import (
    ServiceName,
    ServiceStatus,
    get_service_registry,
)

logger = logging.getLogger(__name__)


class HealthMonitor:
    """Background health monitor for external services.

    Periodically checks the health of registered external services and
    updates the ServiceAvailabilityRegistry. Supports pluggable health
    check functions for different service types.

    The monitor uses asyncio to run health checks concurrently, with
    configurable timeouts to prevent slow services from blocking others.

    Example:
        monitor = HealthMonitor(
            check_interval=30.0,
            check_timeout=5.0,
        )

        # Register health checks
        monitor.register_health_check(
            ServiceName.DATABASE,
            check_database_health,
        )

        # Start monitoring
        await monitor.start()

        # ... application runs ...

        # Stop monitoring
        await monitor.stop()
    """

    def __init__(
        self,
        check_interval: float = 30.0,
        check_timeout: float = 5.0,
    ) -> None:
        """Initialize health monitor.

        Args:
            check_interval: Seconds between health check cycles.
            check_timeout: Timeout for individual health checks.
        """
        self._check_interval = check_interval
        self._check_timeout = check_timeout
        self._health_checks: dict[
            ServiceName, Callable[[], Coroutine[Any, Any, bool]]
        ] = {}
        self._task: asyncio.Task | None = None
        self._running = False
        self._stop_event = asyncio.Event()

    def register_health_check(
        self,
        service: ServiceName,
        check_fn: Callable[[], Coroutine[Any, Any, bool]],
    ) -> None:
        """Register a health check function for a service.

        The health check function should:
        - Be async and return True if healthy, False if unhealthy
        - Complete within the check_timeout
        - Not raise exceptions (return False instead)

        Args:
            service: The service to register the check for.
            check_fn: Async function that performs the health check.
        """
        self._health_checks[service] = check_fn
        logger.debug(
            "Registered health check for service",
            extra={"service": service.value},
        )

    async def _check_service(
        self,
        service: ServiceName,
        check_fn: Callable[[], Coroutine[Any, Any, bool]],
    ) -> tuple[ServiceName, bool, str | None]:
        """Execute a single service health check with timeout.

        Args:
            service: The service being checked.
            check_fn: The health check function to execute.

        Returns:
            Tuple of (service, is_healthy, error_message).
        """
        from example_service.infra.metrics.availability import (
            service_health_check_duration_seconds,
            service_health_check_total,
        )

        start_time = time.perf_counter()
        error: str | None = None

        try:
            is_healthy = await asyncio.wait_for(
                check_fn(),
                timeout=self._check_timeout,
            )
            result = "healthy" if is_healthy else "unhealthy"
        except asyncio.TimeoutError:
            is_healthy = False
            error = f"Health check timed out after {self._check_timeout}s"
            result = "timeout"
            logger.warning(
                "Health check timeout",
                extra={"service": service.value, "timeout": self._check_timeout},
            )
        except Exception as e:
            is_healthy = False
            error = str(e)
            result = "unhealthy"
            logger.warning(
                "Health check failed with exception",
                extra={"service": service.value, "error": str(e)},
            )

        duration = time.perf_counter() - start_time

        # Update metrics
        service_health_check_duration_seconds.labels(
            service_name=service.value
        ).observe(duration)
        service_health_check_total.labels(
            service_name=service.value,
            result=result,
        ).inc()

        return service, is_healthy, error

    async def _run_health_checks(self) -> dict[ServiceName, bool]:
        """Run all registered health checks concurrently.

        Returns:
            Dictionary mapping services to health status.
        """
        from example_service.infra.metrics.availability import (
            health_monitor_check_cycle_duration_seconds,
            health_monitor_check_cycle_total,
            update_service_metrics,
        )

        start_time = time.perf_counter()
        registry = get_service_registry()
        results: dict[ServiceName, bool] = {}

        if not self._health_checks:
            logger.debug("No health checks registered")
            return results

        # Run all health checks concurrently
        tasks = [
            self._check_service(service, check_fn)
            for service, check_fn in self._health_checks.items()
        ]
        check_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results and update registry
        for result in check_results:
            if isinstance(result, Exception):
                logger.error(
                    "Health check task failed",
                    extra={"error": str(result)},
                )
                continue

            service, is_healthy, error = result
            results[service] = is_healthy

            # Update registry
            status = await registry.update_health(
                service=service,
                is_healthy=is_healthy,
                error=error,
            )

            # Update all metrics for this service
            update_service_metrics(
                service_name=service.value,
                is_available=status.is_available,
                health_available=status.health_available,
                override_mode=status.override_mode.value,
                consecutive_failures=status.consecutive_failures,
                consecutive_successes=status.consecutive_successes,
            )

        # Update cycle metrics
        duration = time.perf_counter() - start_time
        health_monitor_check_cycle_total.inc()
        health_monitor_check_cycle_duration_seconds.observe(duration)

        logger.debug(
            "Health check cycle completed",
            extra={
                "duration": duration,
                "services_checked": len(results),
                "healthy": sum(1 for v in results.values() if v),
            },
        )

        return results

    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        from example_service.infra.metrics.availability import health_monitor_running_gauge

        logger.info(
            "Health monitor starting",
            extra={
                "check_interval": self._check_interval,
                "check_timeout": self._check_timeout,
                "registered_services": len(self._health_checks),
            },
        )

        health_monitor_running_gauge.set(1)

        try:
            while self._running:
                try:
                    await self._run_health_checks()
                except Exception as e:
                    logger.error(
                        "Health check cycle failed",
                        extra={"error": str(e)},
                    )

                # Wait for next cycle or stop event
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self._check_interval,
                    )
                    # Stop event was set
                    break
                except asyncio.TimeoutError:
                    # Normal timeout, continue to next cycle
                    continue
        finally:
            health_monitor_running_gauge.set(0)
            logger.info("Health monitor stopped")

    async def start(self) -> None:
        """Start the health monitor background task."""
        if self._running:
            logger.warning("Health monitor already running")
            return

        self._running = True
        self._stop_event.clear()

        # Run initial health check immediately
        await self._run_health_checks()

        # Start background monitoring loop
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("Health monitor started")

    async def stop(self) -> None:
        """Stop the health monitor background task."""
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
            self._task = None

        logger.info("Health monitor stopped")

    async def trigger_check(self) -> dict[ServiceName, bool]:
        """Trigger an immediate health check cycle.

        Returns:
            Dictionary mapping services to health status.
        """
        return await self._run_health_checks()

    @property
    def is_running(self) -> bool:
        """Check if health monitor is running."""
        return self._running


# Module-level singleton
_health_monitor: HealthMonitor | None = None


def get_health_monitor() -> HealthMonitor:
    """Get the singleton health monitor instance.

    Returns:
        The global HealthMonitor instance.
    """
    global _health_monitor
    if _health_monitor is None:
        from example_service.core.settings import get_health_settings

        settings = get_health_settings()
        _health_monitor = HealthMonitor(
            check_interval=getattr(settings, "service_check_interval", 30.0),
            check_timeout=getattr(settings, "service_check_timeout", 5.0),
        )
    return _health_monitor


async def start_health_monitor() -> None:
    """Start the singleton health monitor.

    Call this during application startup after registering health checks.
    """
    monitor = get_health_monitor()
    await monitor.start()


async def stop_health_monitor() -> None:
    """Stop the singleton health monitor.

    Call this during application shutdown.
    """
    monitor = get_health_monitor()
    await monitor.stop()


async def trigger_health_check() -> dict[ServiceName, bool]:
    """Trigger an immediate health check cycle.

    Returns:
        Dictionary mapping services to health status.
    """
    monitor = get_health_monitor()
    return await monitor.trigger_check()


def reset_health_monitor() -> None:
    """Reset the singleton health monitor.

    Used for testing to ensure clean state between tests.
    """
    global _health_monitor
    _health_monitor = None


__all__ = [
    "HealthMonitor",
    "get_health_monitor",
    "reset_health_monitor",
    "start_health_monitor",
    "stop_health_monitor",
    "trigger_health_check",
]
