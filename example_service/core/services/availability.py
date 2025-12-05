"""Service availability registry for external service health tracking.

This module provides a centralized registry for tracking the availability status
of external services that the application depends on. It supports:

- Health check based availability with configurable failure/recovery thresholds
- Admin override modes (force enable/disable) for operational flexibility
- Thread-safe state management with asyncio locks

Architecture:
    ┌─────────────────────────────────────────────────────────────────┐
    │                    Service Availability System                   │
    ├─────────────────────────────────────────────────────────────────┤
    │  ┌──────────────────┐    ┌──────────────────┐                   │
    │  │  Health Monitor  │───>│ Service Registry │<── Admin Override │
    │  │  (Background)    │    │ (State Tracker)  │    (API)          │
    │  └──────────────────┘    └──────────────────┘                   │
    │           │                       │                              │
    │           ▼                       ▼                              │
    │  ┌──────────────────┐    ┌──────────────────┐                   │
    │  │ External Clients │    │ RequireServices  │                   │
    │  │ (is_healthy())   │    │ (FastAPI Depend) │                   │
    │  └──────────────────┘    └──────────────────┘                   │
    └─────────────────────────────────────────────────────────────────┘

Example:
    from example_service.core.services.availability import (
        get_service_registry,
        ServiceName,
    )

    registry = get_service_registry()
    if registry.is_available(ServiceName.DATABASE):
        # Safe to make database calls
        ...
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class ServiceName(str, Enum):
    """External services that the application depends on.

    Add new services here as the application integrates with more
    external dependencies. Each service should have a corresponding
    health check implementation in the health_monitor module.
    """

    DATABASE = "database"
    CACHE = "cache"
    BROKER = "broker"
    STORAGE = "storage"
    AUTH = "auth"
    CONSUL = "consul"


class OverrideMode(str, Enum):
    """Admin override modes for service availability.

    These modes allow operators to manually control service availability
    status, overriding the automatic health check results.

    Modes:
        NONE: No override - use health check results
        FORCE_ENABLE: Mark service as available regardless of health
        FORCE_DISABLE: Mark service as unavailable regardless of health
    """

    NONE = "none"
    FORCE_ENABLE = "force_enable"
    FORCE_DISABLE = "force_disable"


@dataclass
class ServiceStatus:
    """Current status of an external service.

    Tracks both the raw health check result and the effective availability
    after applying admin overrides. Also maintains failure/success counts
    for threshold-based availability decisions.

    Attributes:
        name: The service identifier
        health_available: Raw result from last health check
        override_mode: Current admin override (if any)
        last_check: Timestamp of last health check
        consecutive_failures: Current failure streak count
        consecutive_successes: Current success streak count
        last_error: Most recent error message (if any)
    """

    name: ServiceName
    health_available: bool = False
    override_mode: OverrideMode = OverrideMode.NONE
    last_check: datetime | None = None
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    last_error: str | None = None

    @property
    def is_available(self) -> bool:
        """Get effective availability considering overrides.

        Returns:
            True if service should be considered available for requests.
        """
        if self.override_mode == OverrideMode.FORCE_ENABLE:
            return True
        if self.override_mode == OverrideMode.FORCE_DISABLE:
            return False
        return self.health_available

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses.

        Returns:
            Dictionary with all status fields.
        """
        return {
            "name": self.name.value,
            "is_available": self.is_available,
            "health_available": self.health_available,
            "override_mode": self.override_mode.value,
            "last_check": self.last_check.isoformat() if self.last_check else None,
            "consecutive_failures": self.consecutive_failures,
            "consecutive_successes": self.consecutive_successes,
            "last_error": self.last_error,
        }


class ServiceAvailabilityRegistry:
    """Thread-safe registry for tracking external service availability.

    This singleton class maintains the availability state for all registered
    external services. It is updated by the HealthMonitor and queried by
    the require_services dependency.

    The registry supports:
    - Thread-safe updates via asyncio locks
    - Admin overrides that bypass health check results
    - Configurable failure/recovery thresholds

    Example:
        registry = get_service_registry()

        # Check if a service is available
        if registry.is_available(ServiceName.DATABASE):
            ...

        # Update health check result
        await registry.update_health(
            ServiceName.DATABASE,
            is_healthy=True,
            error=None,
        )

        # Set admin override
        await registry.set_override(
            ServiceName.DATABASE,
            OverrideMode.FORCE_ENABLE,
        )
    """

    def __init__(
        self,
        failure_threshold: int = 2,
        recovery_threshold: int = 1,
    ) -> None:
        """Initialize the service availability registry.

        Args:
            failure_threshold: Consecutive failures before marking unavailable.
            recovery_threshold: Consecutive successes before marking available.
        """
        self._failure_threshold = failure_threshold
        self._recovery_threshold = recovery_threshold
        self._services: dict[ServiceName, ServiceStatus] = {}
        self._lock = asyncio.Lock()
        self._initialized = False

        # Initialize all known services as unavailable
        for service in ServiceName:
            self._services[service] = ServiceStatus(name=service)

    async def update_health(
        self,
        service: ServiceName,
        is_healthy: bool,
        error: str | None = None,
    ) -> ServiceStatus:
        """Update health check result for a service.

        Applies failure/recovery threshold logic to determine when
        to actually change the availability status. This prevents
        flapping due to transient failures.

        Args:
            service: The service to update.
            is_healthy: Result of the health check.
            error: Error message if health check failed.

        Returns:
            Updated ServiceStatus.
        """
        async with self._lock:
            status = self._services[service]
            previous_available = status.health_available

            # Update timestamps and error
            status.last_check = datetime.now(timezone.utc)
            status.last_error = error if not is_healthy else None

            if is_healthy:
                # Reset failure count, increment success count
                status.consecutive_failures = 0
                status.consecutive_successes += 1

                # Check recovery threshold
                if (
                    not status.health_available
                    and status.consecutive_successes >= self._recovery_threshold
                ):
                    status.health_available = True
                    logger.info(
                        "Service recovered after %d consecutive successes",
                        status.consecutive_successes,
                        extra={"service": service.value},
                    )
            else:
                # Reset success count, increment failure count
                status.consecutive_successes = 0
                status.consecutive_failures += 1

                # Check failure threshold
                if (
                    status.health_available
                    and status.consecutive_failures >= self._failure_threshold
                ):
                    status.health_available = False
                    logger.warning(
                        "Service marked unavailable after %d consecutive failures",
                        status.consecutive_failures,
                        extra={"service": service.value, "error": error},
                    )

            # Track status transitions for metrics
            if previous_available != status.health_available:
                from example_service.infra.metrics.availability import (
                    service_status_transitions_total,
                )

                service_status_transitions_total.labels(
                    service_name=service.value,
                    from_status="available" if previous_available else "unavailable",
                    to_status="available" if status.health_available else "unavailable",
                ).inc()

            return status

    async def set_override(
        self,
        service: ServiceName,
        mode: OverrideMode,
    ) -> ServiceStatus:
        """Set admin override for a service.

        Args:
            service: The service to override.
            mode: The override mode to set.

        Returns:
            Updated ServiceStatus.
        """
        async with self._lock:
            status = self._services[service]
            previous_mode = status.override_mode
            status.override_mode = mode

            if previous_mode != mode:
                logger.info(
                    "Service override changed from %s to %s",
                    previous_mode.value,
                    mode.value,
                    extra={"service": service.value},
                )

                # Update metrics
                from example_service.infra.metrics.availability import (
                    service_override_mode_gauge,
                )

                override_value = {"none": 0, "force_enable": 1, "force_disable": -1}.get(
                    mode.value, 0
                )
                service_override_mode_gauge.labels(service_name=service.value).set(
                    override_value
                )

            return status

    def is_available(self, service: ServiceName) -> bool:
        """Check if a service is available.

        This is a synchronous method for use in dependencies.
        It checks the cached status without acquiring locks.

        Args:
            service: The service to check.

        Returns:
            True if service is considered available.
        """
        status = self._services.get(service)
        if status is None:
            return False
        return status.is_available

    def get_status(self, service: ServiceName) -> ServiceStatus | None:
        """Get current status for a service.

        Args:
            service: The service to get status for.

        Returns:
            ServiceStatus or None if service not registered.
        """
        return self._services.get(service)

    def get_all_statuses(self) -> dict[ServiceName, ServiceStatus]:
        """Get status for all registered services.

        Returns:
            Dictionary mapping service names to their statuses.
        """
        return dict(self._services)

    async def mark_all_available(self) -> None:
        """Mark all services as available.

        Used during startup when services haven't been health-checked yet
        but we want to assume they're available.
        """
        async with self._lock:
            for status in self._services.values():
                status.health_available = True
                status.consecutive_successes = 1
            self._initialized = True

    @property
    def is_initialized(self) -> bool:
        """Check if registry has been initialized with health checks."""
        return self._initialized


# Module-level singleton
_registry: ServiceAvailabilityRegistry | None = None


@lru_cache(maxsize=1)
def get_service_registry() -> ServiceAvailabilityRegistry:
    """Get the singleton service availability registry.

    Returns:
        The global ServiceAvailabilityRegistry instance.
    """
    global _registry
    if _registry is None:
        from example_service.core.settings import get_health_settings

        settings = get_health_settings()
        _registry = ServiceAvailabilityRegistry(
            failure_threshold=getattr(settings, "service_failure_threshold", 2),
            recovery_threshold=getattr(settings, "service_recovery_threshold", 1),
        )
    return _registry


def reset_service_registry() -> None:
    """Reset the singleton registry.

    Used for testing to ensure clean state between tests.
    """
    global _registry
    _registry = None
    get_service_registry.cache_clear()


__all__ = [
    "OverrideMode",
    "ServiceAvailabilityRegistry",
    "ServiceName",
    "ServiceStatus",
    "get_service_registry",
    "reset_service_registry",
]
