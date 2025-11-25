"""Rate limiting infrastructure."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from example_service.infra.ratelimit.limiter import RateLimiter, check_rate_limit

if TYPE_CHECKING:
    from example_service.app.middleware.rate_limit import RateLimitMiddleware

__all__ = [
    "RateLimiter",
    "RateLimitMiddleware",
    "check_rate_limit",
]


def __getattr__(name: str) -> Any:
    """Lazily import middleware to avoid circular imports at runtime."""
    if name == "RateLimitMiddleware":
        from example_service.app.middleware.rate_limit import RateLimitMiddleware

        return RateLimitMiddleware
    raise AttributeError(name)
