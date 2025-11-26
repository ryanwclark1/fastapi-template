"""Rate limiting infrastructure."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from example_service.infra.ratelimit.limiter import RateLimiter, check_rate_limit
from example_service.infra.ratelimit.status import (
    RateLimitProtectionState,
    RateLimitProtectionStatus,
)
from example_service.infra.ratelimit.tracker import (
    RateLimitStateTracker,
    get_rate_limit_tracker,
    set_rate_limit_tracker,
)

if TYPE_CHECKING:
    from example_service.app.middleware.rate_limit import RateLimitMiddleware

__all__ = [
    "RateLimitMiddleware",
    "RateLimitProtectionState",
    "RateLimitProtectionStatus",
    "RateLimitStateTracker",
    "RateLimiter",
    "check_rate_limit",
    "get_rate_limit_tracker",
    "set_rate_limit_tracker",
]


def __getattr__(name: str) -> Any:
    """Lazily import middleware to avoid circular imports at runtime."""
    if name == "RateLimitMiddleware":
        from example_service.app.middleware.rate_limit import RateLimitMiddleware

        return RateLimitMiddleware
    raise AttributeError(name)
