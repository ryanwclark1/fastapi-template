"""Rate limit state tracker for protection observability.

This module provides a thread-safe state tracker that monitors
rate limiting protection status and surfaces it through metrics
and logging.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime

from example_service.infra.ratelimit.status import (
    RateLimitProtectionState,
    RateLimitProtectionStatus,
)

logger = logging.getLogger(__name__)

# Module-level tracker instance (set during app startup)
_tracker: RateLimitStateTracker | None = None


def get_rate_limit_tracker() -> RateLimitStateTracker | None:
    """Get the global rate limit state tracker.

    Returns:
        The tracker instance, or None if not initialized.
    """
    return _tracker


def set_rate_limit_tracker(tracker: RateLimitStateTracker | None) -> None:
    """Set the global rate limit state tracker.

    Args:
        tracker: The tracker instance to use globally.
    """
    global _tracker
    _tracker = tracker


class RateLimitStateTracker:
    """Thread-safe tracker for rate limit protection status.

    Monitors Redis health and tracks state transitions between
    ACTIVE (working), DEGRADED (fail-open), and DISABLED states.

    Example:
        >>> tracker = RateLimitStateTracker(failure_threshold=3)
        >>> tracker.record_success()  # Redis operation succeeded
        >>> tracker.record_failure("Connection refused")  # Redis failed
        >>> state = tracker.get_state()
        >>> print(state.status)  # RateLimitProtectionStatus.DEGRADED
    """

    def __init__(self, failure_threshold: int = 3) -> None:
        """Initialize the state tracker.

        Args:
            failure_threshold: Number of consecutive failures before
                transitioning from ACTIVE to DEGRADED state.
        """
        self._failure_threshold = failure_threshold
        self._lock = threading.Lock()
        self._state = RateLimitProtectionState(
            status=RateLimitProtectionStatus.ACTIVE,
            since=datetime.now(UTC),
            consecutive_failures=0,
            last_error=None,
        )

    def get_state(self) -> RateLimitProtectionState:
        """Get the current protection state.

        Returns:
            Current state including status, timing, and error info.
        """
        with self._lock:
            return RateLimitProtectionState(
                status=self._state.status,
                since=self._state.since,
                consecutive_failures=self._state.consecutive_failures,
                last_error=self._state.last_error,
            )

    def record_success(self) -> None:
        """Record a successful Redis operation.

        If currently in DEGRADED state, transitions back to ACTIVE
        after a successful operation.
        """
        with self._lock:
            old_status = self._state.status

            # Reset failure count on success
            self._state.consecutive_failures = 0
            self._state.last_error = None

            # Transition from DEGRADED back to ACTIVE on success
            if old_status == RateLimitProtectionStatus.DEGRADED:
                self._state.status = RateLimitProtectionStatus.ACTIVE
                self._state.since = datetime.now(UTC)
                self._log_transition(old_status, RateLimitProtectionStatus.ACTIVE)
                self._update_metrics(RateLimitProtectionStatus.ACTIVE)

    def record_failure(self, error: str) -> None:
        """Record a failed Redis operation.

        Increments failure count and transitions to DEGRADED if
        threshold is exceeded.

        Args:
            error: Error message describing the failure.
        """
        with self._lock:
            old_status = self._state.status
            self._state.consecutive_failures += 1
            self._state.last_error = error

            # Transition to DEGRADED if threshold exceeded and not already degraded
            if (
                old_status == RateLimitProtectionStatus.ACTIVE
                and self._state.consecutive_failures >= self._failure_threshold
            ):
                self._state.status = RateLimitProtectionStatus.DEGRADED
                self._state.since = datetime.now(UTC)
                self._log_transition(old_status, RateLimitProtectionStatus.DEGRADED)
                self._update_metrics(RateLimitProtectionStatus.DEGRADED)

            # Track Redis error in metrics
            self._track_redis_error(error)

    def mark_disabled(self) -> None:
        """Mark rate limiting as disabled by configuration.

        Call this during startup if rate limiting is not enabled.
        """
        with self._lock:
            old_status = self._state.status
            if old_status != RateLimitProtectionStatus.DISABLED:
                self._state.status = RateLimitProtectionStatus.DISABLED
                self._state.since = datetime.now(UTC)
                self._log_transition(old_status, RateLimitProtectionStatus.DISABLED)
                self._update_metrics(RateLimitProtectionStatus.DISABLED)

    def _log_transition(
        self,
        from_status: RateLimitProtectionStatus,
        to_status: RateLimitProtectionStatus,
    ) -> None:
        """Log state transition with structured context."""
        log_extra = {
            "from_status": from_status.value,
            "to_status": to_status.value,
            "consecutive_failures": self._state.consecutive_failures,
            "last_error": self._state.last_error,
        }

        if to_status == RateLimitProtectionStatus.DEGRADED:
            logger.warning(
                "Rate limit protection degraded - fail-open mode engaged",
                extra=log_extra,
            )
        elif to_status == RateLimitProtectionStatus.ACTIVE:
            logger.info(
                "Rate limit protection restored to active",
                extra=log_extra,
            )
        elif to_status == RateLimitProtectionStatus.DISABLED:
            logger.info(
                "Rate limit protection disabled by configuration",
                extra=log_extra,
            )

    def _update_metrics(self, status: RateLimitProtectionStatus) -> None:
        """Update Prometheus metrics for protection status."""
        try:
            from example_service.infra.metrics.tracking import (
                update_rate_limiter_protection_status,
            )

            update_rate_limiter_protection_status(status.value)
        except ImportError:
            # Metrics not available, skip
            pass
        except Exception as e:
            logger.debug(f"Failed to update rate limiter metrics: {e}")

    def _track_redis_error(self, error: str) -> None:
        """Track Redis error in metrics."""
        try:
            from example_service.infra.metrics.tracking import (
                track_rate_limiter_redis_error,
            )

            # Categorize error type
            error_lower = error.lower()
            if "timeout" in error_lower:
                error_type = "timeout"
            elif "connection" in error_lower or "refused" in error_lower:
                error_type = "connection"
            elif "auth" in error_lower:
                error_type = "auth"
            else:
                error_type = "other"

            track_rate_limiter_redis_error(error_type)
        except ImportError:
            # Metrics not available, skip
            pass
        except Exception as e:
            logger.debug(f"Failed to track Redis error metric: {e}")


__all__ = [
    "RateLimitStateTracker",
    "get_rate_limit_tracker",
    "set_rate_limit_tracker",
]
