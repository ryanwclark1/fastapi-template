"""Rate limit protection status types.

This module defines the status enum and state dataclass for tracking
rate limiting protection health.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


class RateLimitProtectionStatus(str, Enum):
    """Status of rate limiting protection.

    Values:
        ACTIVE: Rate limiting is working normally
        DEGRADED: Redis is unavailable, fail-open mode engaged
        DISABLED: Rate limiting is disabled by configuration
    """

    ACTIVE = "active"
    DEGRADED = "degraded"
    DISABLED = "disabled"


@dataclass
class RateLimitProtectionState:
    """Current state of rate limit protection.

    Attributes:
        status: Current protection status
        since: When this status began
        consecutive_failures: Number of consecutive Redis failures
        last_error: Most recent error message (if any)
    """

    status: RateLimitProtectionStatus
    since: datetime = field(default_factory=lambda: datetime.now(UTC))
    consecutive_failures: int = 0
    last_error: str | None = None


__all__ = [
    "RateLimitProtectionState",
    "RateLimitProtectionStatus",
]
