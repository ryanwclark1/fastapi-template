"""Rate limiting dependencies for FastAPI routes."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request

from example_service.infra.cache import get_cache
from example_service.infra.ratelimit.limiter import RateLimiter, check_rate_limit

logger = logging.getLogger(__name__)


async def get_rate_limiter() -> RateLimiter:
    """Get rate limiter instance.

    Returns:
        RateLimiter instance using Redis cache.

    Example:
            @router.get("/data")
        async def get_data(
            limiter: Annotated[RateLimiter, Depends(get_rate_limiter)]
        ):
            await check_rate_limit(limiter, "endpoint:get_data", limit=10, window=60)
            return {"data": "value"}
    """
    redis = get_cache()
    return RateLimiter(redis)


def rate_limit(
    limit: int,
    window: int = 60,
    key_func: Callable[[Request], str] | None = None,
) -> Callable:
    """Decorator for applying rate limits to specific endpoints.

    This dependency can be used to apply custom rate limits to individual
    endpoints, overriding any global rate limit middleware.

    Args:
        limit: Number of requests allowed per window.
        window: Time window in seconds.
        key_func: Optional function to extract rate limit key from request.
                 Default uses client IP address.

    Returns:
        Dependency function that enforces the rate limit.

    Example:
            @router.get("/expensive-operation")
        async def expensive_op(
            _: Annotated[None, Depends(rate_limit(limit=5, window=60))]
        ):
            # Only 5 requests per minute allowed
            return {"result": "success"}

        # Or with custom key function
        def user_key(request: Request) -> str:
            user = request.state.user
            return f"user:{user.id}"

        @router.post("/user-action")
        async def user_action(
            _: Annotated[None, Depends(rate_limit(limit=10, window=3600, key_func=user_key))]
        ):
            # 10 requests per hour per user
            return {"status": "ok"}
    """

    async def _rate_limit_dependency(
        request: Request,
        limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    ) -> None:
        """Apply rate limit to the endpoint.

        Args:
            request: The incoming request.
            limiter: Rate limiter instance.

        Raises:
            RateLimitException: If rate limit is exceeded.
        """
        # Determine rate limit key
        if key_func:
            key = key_func(request)
        else:
            # Default: use client IP
            forwarded = request.headers.get("X-Forwarded-For")
            if forwarded:
                client_ip = forwarded.split(",")[0].strip()
            else:
                client_ip = request.client.host if request.client else "unknown"
            key = f"ip:{client_ip}:{request.url.path}"

        # Check rate limit
        metadata = await check_rate_limit(limiter, key, limit, window)

        # Store metadata in request state for access in route handler
        request.state.rate_limit = metadata

    return Depends(_rate_limit_dependency)


def per_user_rate_limit(limit: int, window: int = 60) -> Callable:
    """Rate limit decorator for authenticated endpoints (per user).

    This applies rate limits per authenticated user instead of per IP.
    Requires authentication middleware to set request.state.user.

    Args:
        limit: Number of requests allowed per window.
        window: Time window in seconds.

    Returns:
        Dependency function that enforces the rate limit per user.

    Example:
            @router.post("/user/profile")
        async def update_profile(
            _: Annotated[None, Depends(per_user_rate_limit(limit=20, window=60))],
            user: Annotated[User, Depends(get_current_user)]
        ):
            # 20 updates per minute per user
            return {"status": "updated"}
    """

    def user_key_func(request: Request) -> str:
        """Extract user ID from request state.

        Args:
            request: The incoming request.

        Returns:
            Rate limit key based on user ID.

        Raises:
            ValueError: If user is not authenticated.
        """
        user = getattr(request.state, "user", None)
        if not user:
            raise ValueError("User not authenticated for per-user rate limit")
        return f"user:{user.id}:{request.url.path}"

    return rate_limit(limit=limit, window=window, key_func=user_key_func)


def per_api_key_rate_limit(limit: int, window: int = 60) -> Callable:
    """Rate limit decorator for API key authenticated endpoints.

    This applies rate limits per API key instead of per IP.
    Requires authentication to set request.state.api_key.

    Args:
        limit: Number of requests allowed per window.
        window: Time window in seconds.

    Returns:
        Dependency function that enforces the rate limit per API key.

    Example:
            @router.get("/api/data")
        async def get_api_data(
            _: Annotated[None, Depends(per_api_key_rate_limit(limit=1000, window=3600))],
        ):
            # 1000 requests per hour per API key
            return {"data": "value"}
    """

    def api_key_func(request: Request) -> str:
        """Extract API key from request state.

        Args:
            request: The incoming request.

        Returns:
            Rate limit key based on API key.

        Raises:
            ValueError: If API key is not present.
        """
        api_key = getattr(request.state, "api_key", None)
        if not api_key:
            raise ValueError("API key not present for API key rate limit")
        return f"apikey:{api_key}:{request.url.path}"

    return rate_limit(limit=limit, window=window, key_func=api_key_func)


# Type aliases for cleaner endpoint signatures
RateLimited = Annotated[None, Depends(rate_limit(limit=100, window=60))]
StrictRateLimit = Annotated[None, Depends(rate_limit(limit=10, window=60))]
UserRateLimit = Annotated[None, Depends(per_user_rate_limit(limit=50, window=60))]
