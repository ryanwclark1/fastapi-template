"""Health check aggregator with concurrent checks, caching, and history tracking.

The HealthAggregator is the central component for managing health checks.
It maintains a registry of health providers, runs checks concurrently,
caches results, and tracks health history for trend analysis.

Example:
    >>> from example_service.features.health.aggregator import HealthAggregator
    >>> from example_service.features.health.providers import DatabaseHealthProvider
    >>>
    >>> # Create aggregator with caching and history
    >>> aggregator = HealthAggregator(
    ...     cache_ttl_seconds=30.0,
    ...     history_size=100,
    ... )
    >>> aggregator.add_provider(DatabaseHealthProvider(engine))
    >>>
    >>> # Check all providers (runs concurrently)
    >>> result = await aggregator.check_all()
    >>>
    >>> # Get cached result (no provider calls if within TTL)
    >>> cached = await aggregator.check_all()
    >>>
    >>> # Get health history and stats
    >>> history = aggregator.get_history()
    >>> stats = aggregator.get_stats()
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from example_service.core.schemas.common import HealthStatus
from example_service.features.health.providers import HealthCheckResult, HealthProvider
from example_service.infra.metrics.tracking import update_dependency_health

if TYPE_CHECKING:
    from example_service.core.settings.health import HealthCheckSettings

logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_CACHE_TTL_SECONDS = 10.0
DEFAULT_HISTORY_SIZE = 100
DEFAULT_CHECK_TIMEOUT_SECONDS = 30.0

# Provider name to dependency type mapping for metrics
PROVIDER_TYPE_MAPPING = {
    "database": "database",
    "cache": "cache",
    "redis": "cache",
    "messaging": "queue",
    "rabbitmq": "queue",
    "storage": "storage",
    "s3_storage": "storage",
}


@dataclass
class AggregatedHealthResult:
    """Aggregated health check result from all providers.

    Attributes:
        status: Overall system health status
        checks: Individual provider check results
        timestamp: When the health check was performed
        duration_ms: Total duration of all checks in milliseconds
        from_cache: Whether this result was served from cache
    """

    status: HealthStatus
    checks: dict[str, HealthCheckResult] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    duration_ms: float = 0.0
    from_cache: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses.

        Returns:
            Dictionary with status, checks, timestamp, and duration.
        """
        return {
            "status": self.status.value,
            "checks": {
                name: check.status == HealthStatus.HEALTHY for name, check in self.checks.items()
            },
            "details": {
                name: {
                    "status": check.status.value,
                    "message": check.message,
                    "latency_ms": round(check.latency_ms, 2),
                    **({"metadata": check.metadata} if check.metadata else {}),
                }
                for name, check in self.checks.items()
            },
            "timestamp": self.timestamp,
            "duration_ms": round(self.duration_ms, 2),
            "from_cache": self.from_cache,
        }


@dataclass
class HealthHistoryEntry:
    """A single entry in the health history.

    Attributes:
        timestamp: When the check was performed
        status: Overall health status at that time
        checks: Individual provider statuses
        duration_ms: How long the check took
    """

    timestamp: datetime
    status: HealthStatus
    checks: dict[str, HealthStatus]
    duration_ms: float


@dataclass
class HealthStats:
    """Aggregated health statistics over the history window.

    Attributes:
        total_checks: Number of health checks in history
        healthy_count: Number of healthy checks
        degraded_count: Number of degraded checks
        unhealthy_count: Number of unhealthy checks
        uptime_percentage: Percentage of time system was healthy
        avg_duration_ms: Average check duration
        last_status_change: When status last changed
        current_status: Current health status
        provider_stats: Per-provider statistics
    """

    total_checks: int
    healthy_count: int
    degraded_count: int
    unhealthy_count: int
    uptime_percentage: float
    avg_duration_ms: float
    last_status_change: datetime | None
    current_status: HealthStatus | None
    provider_stats: dict[str, dict[str, Any]]


class HealthAggregator:
    """Aggregate health status from multiple providers with advanced features.

    Features:
    - **Concurrent checks**: All providers are checked in parallel using asyncio
    - **Result caching**: Avoid hammering dependencies with configurable TTL
    - **History tracking**: Keep rolling history for trend analysis
    - **Statistics**: Calculate uptime, avg latency, per-provider stats

    Example:
        >>> aggregator = HealthAggregator(
        ...     cache_ttl_seconds=30.0,  # Cache results for 30 seconds
        ...     history_size=100,         # Keep last 100 check results
        ... )
        >>>
        >>> # Register providers at startup
        >>> aggregator.add_provider(DatabaseHealthProvider(engine))
        >>> aggregator.add_provider(RedisHealthProvider(redis_cache))
        >>>
        >>> # Check all providers (concurrent)
        >>> result = await aggregator.check_all()
        >>>
        >>> # Force fresh check (bypass cache)
        >>> fresh = await aggregator.check_all(force_refresh=True)
        >>>
        >>> # Get statistics
        >>> stats = aggregator.get_stats()
        >>> print(f"Uptime: {stats.uptime_percentage:.1f}%")
    """

    def __init__(
        self,
        settings: HealthCheckSettings | None = None,
        cache_ttl_seconds: float | None = None,
        history_size: int | None = None,
        check_timeout_seconds: float | None = None,
    ) -> None:
        """Initialize the health aggregator.

        Args:
            settings: Optional HealthCheckSettings for configuration (recommended)
            cache_ttl_seconds: How long to cache results (legacy, use settings instead)
            history_size: Maximum number of history entries to keep (legacy, use settings instead)
            check_timeout_seconds: Timeout for the entire check_all operation (legacy, use settings instead)

        Note:
            If settings is provided, it takes precedence over individual parameters.
            Legacy parameters are maintained for backward compatibility.
        """
        from example_service.core.settings.health import HealthCheckSettings

        # Use settings if provided, otherwise use legacy parameters or defaults
        if settings is not None:
            self._cache_ttl = settings.cache_ttl_seconds
            self._check_timeout = settings.global_timeout
            history_max = settings.history_size
            self._settings = settings
        else:
            self._cache_ttl = (
                cache_ttl_seconds if cache_ttl_seconds is not None else DEFAULT_CACHE_TTL_SECONDS
            )
            self._check_timeout = (
                check_timeout_seconds
                if check_timeout_seconds is not None
                else DEFAULT_CHECK_TIMEOUT_SECONDS
            )
            history_max = history_size if history_size is not None else DEFAULT_HISTORY_SIZE
            # Create settings from legacy parameters
            self._settings = HealthCheckSettings(
                cache_ttl_seconds=self._cache_ttl,
                history_size=history_max,
                global_timeout=self._check_timeout,
            )

        self._providers: dict[str, HealthProvider] = {}

        # Caching
        self._cached_result: AggregatedHealthResult | None = None
        self._cache_timestamp: float = 0.0

        # History tracking
        self._history: deque[HealthHistoryEntry] = deque(maxlen=history_max)
        self._history_size = history_max
        self._last_status: HealthStatus | None = None
        self._last_status_change: datetime | None = None

        # Per-provider status tracking for transitions
        self._provider_last_status: dict[str, HealthStatus] = {}

    def add_provider(self, provider: HealthProvider) -> None:
        """Register a health check provider.

        Args:
            provider: Object implementing HealthProvider protocol

        Raises:
            TypeError: If provider doesn't implement HealthProvider protocol
            ValueError: If provider with same name already registered
        """
        if not isinstance(provider, HealthProvider):
            raise TypeError(
                f"Provider must implement HealthProvider protocol, got {type(provider).__name__}"
            )

        if provider.name in self._providers:
            raise ValueError(f"Provider '{provider.name}' already registered")

        self._providers[provider.name] = provider
        logger.info("Registered health provider", extra={"provider": provider.name})

    def remove_provider(self, name: str) -> bool:
        """Remove a health check provider by name.

        Args:
            name: Name of the provider to remove

        Returns:
            True if provider was removed, False if not found
        """
        if name in self._providers:
            del self._providers[name]
            # Invalidate cache when providers change
            self._invalidate_cache()
            logger.info("Removed health provider", extra={"provider": name})
            return True
        return False

    def list_providers(self) -> list[str]:
        """List all registered provider names.

        Returns:
            List of provider names
        """
        return list(self._providers.keys())

    async def check_all(self, force_refresh: bool = False) -> AggregatedHealthResult:
        """Run health checks on all registered providers concurrently.

        Args:
            force_refresh: Bypass cache and run fresh checks

        Returns:
            AggregatedHealthResult with overall status and individual checks
        """
        # Check cache first (unless force refresh)
        if not force_refresh and self._is_cache_valid():
            cached = self._get_cached_result()
            if cached is not None:
                return cached

        start_time = time.perf_counter()

        # Run all provider checks concurrently
        checks = await self._run_concurrent_checks()

        # Determine overall status
        overall_status = self._determine_overall_status(checks)
        duration_ms = (time.perf_counter() - start_time) * 1000
        timestamp = datetime.now(UTC)

        result = AggregatedHealthResult(
            status=overall_status,
            checks=checks,
            timestamp=timestamp,
            duration_ms=duration_ms,
            from_cache=False,
        )

        # Update cache
        self._update_cache(result)

        # Record in history
        self._record_history(result)

        # Track status changes
        self._track_status_change(overall_status, timestamp)

        return result

    async def _run_concurrent_checks(self) -> dict[str, HealthCheckResult]:
        """Run all provider health checks concurrently.

        Returns:
            Dictionary of provider name to check result
        """
        if not self._providers:
            return {}

        async def check_provider(
            name: str, provider: HealthProvider
        ) -> tuple[str, HealthCheckResult]:
            """Run a single provider check with error handling and metrics tracking."""
            from example_service.features.health.providers import (
                record_health_check_result,
                track_health_check,
            )

            try:
                # Track health check duration with new metrics
                async with track_health_check(name):
                    result = await provider.check_health()

                # Get previous status for transition tracking
                previous_status = self._provider_last_status.get(name)

                # Record health check result with all metrics
                record_health_check_result(name, result, previous_status)

                # Update last status
                self._provider_last_status[name] = result.status

                # Also track with legacy dependency metrics
                dependency_type = PROVIDER_TYPE_MAPPING.get(name, "api")
                is_healthy = result.status == HealthStatus.HEALTHY
                update_dependency_health(name, dependency_type, is_healthy)

                return name, result
            except Exception as e:
                from example_service.infra.metrics.health import health_check_errors_total

                logger.exception("Health check failed for provider", extra={"provider": name})

                # Record error metric
                health_check_errors_total.labels(provider=name, error_type=type(e).__name__).inc()

                # Update legacy metrics for failed check
                dependency_type = PROVIDER_TYPE_MAPPING.get(name, "api")
                update_dependency_health(name, dependency_type, False)

                result = HealthCheckResult(
                    status=HealthStatus.UNHEALTHY,
                    message=f"Check error: {e}",
                    metadata={"error": str(e), "error_type": type(e).__name__},
                )

                # Record unhealthy result
                previous_status = self._provider_last_status.get(name)
                record_health_check_result(name, result, previous_status)
                self._provider_last_status[name] = result.status

                return name, result

        # Create tasks for all providers
        tasks = [check_provider(name, provider) for name, provider in self._providers.items()]

        # Run all checks concurrently with overall timeout
        try:
            async with asyncio.timeout(self._check_timeout):
                results = await asyncio.gather(*tasks, return_exceptions=True)
        except TimeoutError:
            logger.error(
                "Health check timed out",
                extra={"timeout": self._check_timeout, "providers": list(self._providers.keys())},
            )
            # Return unhealthy for all providers on timeout
            return {
                name: HealthCheckResult(
                    status=HealthStatus.UNHEALTHY,
                    message=f"Check timed out after {self._check_timeout}s",
                    metadata={"error": "timeout"},
                )
                for name in self._providers
            }

        # Process results
        checks: dict[str, HealthCheckResult] = {}
        for result in results:
            if isinstance(result, Exception):
                # This shouldn't happen due to error handling in check_provider,
                # but handle it just in case
                logger.exception("Unexpected error in health check", exc_info=result)
                continue
            if isinstance(result, tuple) and len(result) == 2:
                name, check_result = result
                checks[name] = check_result

        return checks

    async def check_provider(self, name: str) -> HealthCheckResult | None:
        """Run health check on a specific provider.

        Args:
            name: Name of the provider to check

        Returns:
            HealthCheckResult or None if provider not found
        """
        from example_service.features.health.providers import (
            record_health_check_result,
            track_health_check,
        )

        provider = self._providers.get(name)
        if provider is None:
            return None

        try:
            # Track health check duration with new metrics
            async with track_health_check(name):
                result = await provider.check_health()

            # Get previous status for transition tracking
            previous_status = self._provider_last_status.get(name)

            # Record health check result with all metrics
            record_health_check_result(name, result, previous_status)

            # Update last status
            self._provider_last_status[name] = result.status

            # Also track with legacy dependency metrics
            dependency_type = PROVIDER_TYPE_MAPPING.get(name, "api")
            is_healthy = result.status == HealthStatus.HEALTHY
            update_dependency_health(name, dependency_type, is_healthy)

            return result
        except Exception as e:
            from example_service.infra.metrics.health import health_check_errors_total

            logger.exception("Health check failed for provider", extra={"provider": name})

            # Record error metric
            health_check_errors_total.labels(provider=name, error_type=type(e).__name__).inc()

            # Update legacy metrics for failed check
            dependency_type = PROVIDER_TYPE_MAPPING.get(name, "api")
            update_dependency_health(name, dependency_type, False)

            result = HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Check error: {e}",
                metadata={"error": str(e)},
            )

            # Record unhealthy result
            previous_status = self._provider_last_status.get(name)
            record_health_check_result(name, result, previous_status)
            self._provider_last_status[name] = result.status

            return result

    # =========================================================================
    # Caching
    # =========================================================================

    def _is_cache_valid(self) -> bool:
        """Check if cached result is still valid."""
        if self._cache_ttl <= 0:
            return False
        if self._cached_result is None:
            return False
        age = time.monotonic() - self._cache_timestamp
        return age < self._cache_ttl

    def _get_cached_result(self) -> AggregatedHealthResult | None:
        """Get cached result with from_cache flag set."""
        if self._cached_result is None:
            return None

        # Return a copy with from_cache=True
        return AggregatedHealthResult(
            status=self._cached_result.status,
            checks=self._cached_result.checks,
            timestamp=self._cached_result.timestamp,
            duration_ms=self._cached_result.duration_ms,
            from_cache=True,
        )

    def _update_cache(self, result: AggregatedHealthResult) -> None:
        """Update the cached result."""
        self._cached_result = result
        self._cache_timestamp = time.monotonic()

    def _invalidate_cache(self) -> None:
        """Invalidate the cached result."""
        self._cached_result = None
        self._cache_timestamp = 0.0

    def get_cache_info(self) -> dict[str, Any]:
        """Get information about the cache state.

        Returns:
            Dictionary with cache TTL, validity, and age.
        """
        age = time.monotonic() - self._cache_timestamp if self._cache_timestamp > 0 else None
        return {
            "ttl_seconds": self._cache_ttl,
            "is_valid": self._is_cache_valid(),
            "age_seconds": round(age, 2) if age is not None else None,
            "has_cached_result": self._cached_result is not None,
        }

    # =========================================================================
    # History Tracking
    # =========================================================================

    def _record_history(self, result: AggregatedHealthResult) -> None:
        """Record a health check result in history."""
        entry = HealthHistoryEntry(
            timestamp=result.timestamp,
            status=result.status,
            checks={name: check.status for name, check in result.checks.items()},
            duration_ms=result.duration_ms,
        )
        self._history.append(entry)

    def _track_status_change(self, status: HealthStatus, timestamp: datetime) -> None:
        """Track when status changes."""
        if self._last_status != status:
            self._last_status_change = timestamp
            if self._last_status is not None:
                logger.info(
                    "Health status changed",
                    extra={
                        "previous": self._last_status.value,
                        "current": status.value,
                    },
                )
            self._last_status = status

    def get_history(
        self,
        limit: int | None = None,
        provider: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get health check history.

        Args:
            limit: Maximum number of entries to return (most recent first)
            provider: Filter to specific provider

        Returns:
            List of history entries as dictionaries
        """
        entries = list(self._history)
        entries.reverse()  # Most recent first

        if limit is not None:
            entries = entries[:limit]

        result = []
        for entry in entries:
            item = {
                "timestamp": entry.timestamp.isoformat(),
                "status": entry.status.value,
                "duration_ms": round(entry.duration_ms, 2),
            }

            if provider is not None:
                if provider in entry.checks:
                    item["provider_status"] = entry.checks[provider].value
                else:
                    continue  # Skip entries without this provider
            else:
                item["checks"] = {name: status.value for name, status in entry.checks.items()}  # type: ignore[assignment]

            result.append(item)

        return result

    def get_stats(self) -> HealthStats:
        """Calculate health statistics from history.

        Returns:
            HealthStats with uptime, averages, and per-provider stats
        """
        if not self._history:
            return HealthStats(
                total_checks=0,
                healthy_count=0,
                degraded_count=0,
                unhealthy_count=0,
                uptime_percentage=100.0,
                avg_duration_ms=0.0,
                last_status_change=self._last_status_change,
                current_status=self._last_status,
                provider_stats={},
            )

        entries = list(self._history)
        total = len(entries)

        # Count statuses
        healthy = sum(1 for e in entries if e.status == HealthStatus.HEALTHY)
        degraded = sum(1 for e in entries if e.status == HealthStatus.DEGRADED)
        unhealthy = sum(1 for e in entries if e.status == HealthStatus.UNHEALTHY)

        # Calculate averages
        uptime = ((healthy + degraded) / total) * 100 if total > 0 else 100.0
        avg_duration = sum(e.duration_ms for e in entries) / total if total > 0 else 0.0

        # Per-provider stats
        provider_stats: dict[str, dict[str, Any]] = {}
        all_providers: set[str] = set()
        for entry in entries:
            all_providers.update(entry.checks.keys())

        for provider_name in all_providers:
            provider_entries = [e for e in entries if provider_name in e.checks]
            if not provider_entries:
                continue

            p_total = len(provider_entries)
            p_healthy = sum(
                1 for e in provider_entries if e.checks[provider_name] == HealthStatus.HEALTHY
            )
            p_degraded = sum(
                1 for e in provider_entries if e.checks[provider_name] == HealthStatus.DEGRADED
            )
            p_unhealthy = sum(
                1 for e in provider_entries if e.checks[provider_name] == HealthStatus.UNHEALTHY
            )

            provider_stats[provider_name] = {
                "total_checks": p_total,
                "healthy_count": p_healthy,
                "degraded_count": p_degraded,
                "unhealthy_count": p_unhealthy,
                "uptime_percentage": round(((p_healthy + p_degraded) / p_total) * 100, 2),
            }

        return HealthStats(
            total_checks=total,
            healthy_count=healthy,
            degraded_count=degraded,
            unhealthy_count=unhealthy,
            uptime_percentage=round(uptime, 2),
            avg_duration_ms=round(avg_duration, 2),
            last_status_change=self._last_status_change,
            current_status=self._last_status,
            provider_stats=provider_stats,
        )

    def clear_history(self) -> None:
        """Clear all health check history."""
        self._history.clear()
        self._last_status = None
        self._last_status_change = None

    # =========================================================================
    # Status Determination
    # =========================================================================

    def _determine_overall_status(self, checks: dict[str, HealthCheckResult]) -> HealthStatus:
        """Determine overall status from individual check results.

        Args:
            checks: Dictionary of check results

        Returns:
            Aggregated HealthStatus
        """
        if not checks:
            return HealthStatus.HEALTHY

        statuses = [check.status for check in checks.values()]

        if any(s == HealthStatus.UNHEALTHY for s in statuses):
            return HealthStatus.UNHEALTHY

        if any(s == HealthStatus.DEGRADED for s in statuses):
            return HealthStatus.DEGRADED

        return HealthStatus.HEALTHY


# =============================================================================
# Global Instance & Dependency Helpers
# =============================================================================

_global_aggregator: HealthAggregator | None = None


def get_global_aggregator() -> HealthAggregator:
    """Get the global health aggregator instance.

    Returns:
        Global HealthAggregator instance

    Note:
        Returns a new aggregator if not configured.
        Configure via set_global_aggregator() at app startup.
    """
    global _global_aggregator
    if _global_aggregator is None:
        _global_aggregator = HealthAggregator()
    return _global_aggregator


def set_global_aggregator(aggregator: HealthAggregator) -> None:
    """Set the global health aggregator instance.

    Call this at app startup after configuring providers.

    Args:
        aggregator: Configured HealthAggregator instance
    """
    global _global_aggregator
    _global_aggregator = aggregator


__all__ = [
    "AggregatedHealthResult",
    "DEFAULT_CACHE_TTL_SECONDS",
    "DEFAULT_CHECK_TIMEOUT_SECONDS",
    "DEFAULT_HISTORY_SIZE",
    "HealthAggregator",
    "HealthHistoryEntry",
    "HealthStats",
    "get_global_aggregator",
    "set_global_aggregator",
]
