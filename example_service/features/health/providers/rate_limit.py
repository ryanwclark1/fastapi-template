"""Rate limiter health provider for protection status monitoring.

This module provides a health check provider that reports the status
of rate limiting protection (ACTIVE, DEGRADED, or DISABLED).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from example_service.core.schemas.common import HealthStatus

from .protocol import HealthCheckResult

if TYPE_CHECKING:
    from example_service.infra.ratelimit.tracker import RateLimitStateTracker

logger = logging.getLogger(__name__)


class RateLimiterHealthProvider:
    """Health provider for rate limiter protection status.

    Reports the current state of rate limiting protection:
    - HEALTHY when rate limiting is ACTIVE (working normally)
    - DEGRADED when rate limiting is DEGRADED (fail-open engaged)
    - UNHEALTHY when rate limiting is DISABLED (by configuration)

    Example:
        >>> from example_service.infra.ratelimit import get_rate_limit_tracker
        >>> tracker = get_rate_limit_tracker()
        >>> if tracker:
        ...     provider = RateLimiterHealthProvider(tracker)
        ...     aggregator.add_provider(provider)
    """

    def __init__(self, tracker: RateLimitStateTracker) -> None:
        """Initialize the health provider.

        Args:
            tracker: Rate limit state tracker instance.
        """
        self._tracker = tracker

    @property
    def name(self) -> str:
        """Return provider name."""
        return "rate_limiter"

    async def check_health(self) -> HealthCheckResult:
        """Check rate limiter protection health.

        Returns:
            HealthCheckResult with protection status and details.
        """
        from example_service.infra.ratelimit.status import RateLimitProtectionStatus

        state = self._tracker.get_state()

        # Map protection status to health status
        status_map = {
            RateLimitProtectionStatus.ACTIVE: HealthStatus.HEALTHY,
            RateLimitProtectionStatus.DEGRADED: HealthStatus.DEGRADED,
            RateLimitProtectionStatus.DISABLED: HealthStatus.UNHEALTHY,
        }
        health_status = status_map.get(state.status, HealthStatus.UNHEALTHY)

        # Build message based on status
        if state.status == RateLimitProtectionStatus.ACTIVE:
            message = "Rate limiting protection active"
        elif state.status == RateLimitProtectionStatus.DEGRADED:
            message = f"Rate limiting degraded - fail-open mode ({state.consecutive_failures} consecutive failures)"
        else:
            message = "Rate limiting disabled by configuration"

        # Build metadata
        metadata = {
            "protection_status": state.status.value,
            "consecutive_failures": state.consecutive_failures,
            "status_since": state.since.isoformat(),
        }

        if state.last_error:
            metadata["last_error"] = state.last_error

        return HealthCheckResult(
            status=health_status,
            message=message,
            latency_ms=0.0,  # Instant check, no external call
            metadata=metadata,
        )


__all__ = ["RateLimiterHealthProvider"]
