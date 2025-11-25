"""Redis-backed rate limiting implementation using token bucket algorithm."""

from __future__ import annotations

import hashlib
import logging
import time
from typing import TYPE_CHECKING

from example_service.core.exceptions import RateLimitException
from example_service.infra.metrics.tracking import (
    track_rate_limit_check,
    track_rate_limit_hit,
    update_rate_limit_remaining,
)

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class RateLimiter:
    """Redis-backed rate limiter using token bucket algorithm.

    The token bucket algorithm allows for burst traffic while maintaining
    an average rate limit. Tokens are added to the bucket at a fixed rate,
    and each request consumes one token. If no tokens are available, the
    request is rate limited.

    Attributes:
        redis: Redis client instance.
        key_prefix: Prefix for Redis keys.
        default_limit: Default number of requests allowed per window.
        default_window: Default time window in seconds.

    Example:
            limiter = RateLimiter(redis_client)

        # Check rate limit for a user
        await limiter.check_limit(
            key="user:123",
            limit=100,
            window=60  # 100 requests per minute
        )
    """

    def __init__(
        self,
        redis: Redis,
        key_prefix: str = "ratelimit",
        default_limit: int = 100,
        default_window: int = 60,
    ) -> None:
        """Initialize rate limiter.

        Args:
            redis: Redis client instance.
            key_prefix: Prefix for Redis keys (default: "ratelimit").
            default_limit: Default number of requests per window (default: 100).
            default_window: Default time window in seconds (default: 60).
        """
        self.redis = redis
        self.key_prefix = key_prefix
        self.default_limit = default_limit
        self.default_window = default_window

    def _make_key(self, identifier: str) -> str:
        """Create Redis key for rate limit tracking.

        Args:
            identifier: Unique identifier for the rate limit (e.g., user ID, IP).

        Returns:
            Redis key with prefix.
        """
        # Hash long identifiers to keep key size reasonable
        if len(identifier) > 50:
            identifier = hashlib.sha256(identifier.encode()).hexdigest()[:16]
        return f"{self.key_prefix}:{identifier}"

    async def check_limit(
        self,
        key: str,
        limit: int | None = None,
        window: int | None = None,
        cost: int = 1,
        endpoint: str = "unknown",
    ) -> tuple[bool, dict[str, int]]:
        """Check if request is within rate limit using token bucket algorithm.

        This uses a sliding window implementation with Redis for distributed
        rate limiting across multiple instances.

        Args:
            key: Unique identifier for rate limiting (user ID, IP, API key, etc.).
            limit: Number of requests allowed per window (uses default if None).
            window: Time window in seconds (uses default if None).
            cost: Number of tokens to consume (default: 1).
            endpoint: API endpoint being rate limited (default: "unknown").

        Returns:
            Tuple of (is_allowed, metadata) where metadata contains:
                - limit: The rate limit
                - remaining: Tokens remaining
                - reset: Unix timestamp when limit resets
                - retry_after: Seconds to wait before retrying (if limited)

        Raises:
            RateLimitException: If rate limit is exceeded.

        Example:
                    allowed, meta = await limiter.check_limit("user:123", limit=100, window=60)
            if not allowed:
                print(f"Rate limited. Retry after {meta['retry_after']} seconds")
        """
        limit = limit or self.default_limit
        window = window or self.default_window

        redis_key = self._make_key(key)
        now = time.time()

        try:
            # Use Lua script for atomic operations
            # This implements a sliding window rate limiter
            lua_script = """
            local key = KEYS[1]
            local limit = tonumber(ARGV[1])
            local window = tonumber(ARGV[2])
            local now = tonumber(ARGV[3])
            local cost = tonumber(ARGV[4])

            -- Remove old entries outside the window
            redis.call('ZREMRANGEBYSCORE', key, 0, now - window)

            -- Count current requests in window
            local current = redis.call('ZCARD', key)

            if current + cost <= limit then
                -- Add new request(s) with current timestamp as score
                for i = 1, cost do
                    redis.call('ZADD', key, now, now .. ':' .. i)
                end
                -- Set expiry on the key
                redis.call('EXPIRE', key, window)
                return {1, limit - (current + cost)}
            else
                return {0, 0}
            end
            """

            # Execute Lua script
            result = await self.redis.eval(
                lua_script,
                1,
                redis_key,
                limit,
                window,
                now,
                cost,
            )

            allowed = bool(result[0])
            remaining = int(result[1])

            # Calculate reset time (end of current window)
            reset = int(now + window)

            metadata = {
                "limit": limit,
                "remaining": remaining,
                "reset": reset,
                "retry_after": window if not allowed else 0,
            }

            # Track rate limit check
            track_rate_limit_check(endpoint=endpoint, allowed=allowed)

            # Update remaining tokens gauge
            update_rate_limit_remaining(key=key, endpoint=endpoint, remaining=remaining)

            if not allowed:
                # Track rate limit hit
                track_rate_limit_hit(endpoint=endpoint, limit_type="key")
                logger.warning(
                    "Rate limit exceeded",
                    extra={
                        "key": key,
                        "limit": limit,
                        "window": window,
                        "remaining": remaining,
                    },
                )

            return allowed, metadata

        except Exception as e:
            # If Redis is unavailable, log error and allow request
            # This ensures the application continues to function
            logger.error(
                "Rate limit check failed, allowing request",
                extra={"key": key, "error": str(e)},
                exc_info=True,
            )
            return True, {
                "limit": limit,
                "remaining": limit - 1,
                "reset": int(now + window),
                "retry_after": 0,
            }

    async def reset_limit(self, key: str) -> bool:
        """Reset rate limit for a specific key.

        Args:
            key: The identifier to reset.

        Returns:
            True if reset was successful.

        Example:
                    await limiter.reset_limit("user:123")
        """
        redis_key = self._make_key(key)
        try:
            await self.redis.delete(redis_key)
            logger.info(f"Rate limit reset for key: {key}")
            return True
        except Exception:
            logger.error(f"Failed to reset rate limit for key: {key}", exc_info=True)
            return False

    async def get_limit_info(self, key: str, window: int | None = None) -> dict[str, int]:
        """Get current rate limit information without consuming tokens.

        Args:
            key: The identifier to check.
            window: Time window in seconds (uses default if None).

        Returns:
            Dictionary containing limit information:
                - limit: The rate limit
                - remaining: Tokens remaining
                - reset: Unix timestamp when limit resets
                - current: Current number of requests in window

        Example:
                    info = await limiter.get_limit_info("user:123")
            print(f"Remaining: {info['remaining']}/{info['limit']}")
        """
        limit = self.default_limit
        window = window or self.default_window

        redis_key = self._make_key(key)
        now = time.time()

        try:
            # Remove old entries
            await self.redis.zremrangebyscore(redis_key, 0, now - window)

            # Count current requests
            current = await self.redis.zcard(redis_key)

            return {
                "limit": limit,
                "remaining": max(0, limit - current),
                "reset": int(now + window),
                "current": current,
            }
        except Exception as e:
            logger.error(
                "Failed to get rate limit info",
                extra={"key": key, "error": str(e)},
                exc_info=True,
            )
            return {
                "limit": limit,
                "remaining": limit,
                "reset": int(now + window),
                "current": 0,
            }


async def check_rate_limit(
    limiter: RateLimiter,
    key: str,
    limit: int | None = None,
    window: int | None = None,
    cost: int = 1,
    endpoint: str = "unknown",
) -> dict[str, int]:
    """Check rate limit and raise exception if exceeded.

    This is a convenience function that checks the rate limit and
    automatically raises RateLimitException if exceeded.

    Args:
        limiter: RateLimiter instance.
        key: Unique identifier for rate limiting.
        limit: Number of requests allowed per window.
        window: Time window in seconds.
        cost: Number of tokens to consume.
        endpoint: API endpoint being rate limited (default: "unknown").

    Returns:
        Metadata dict containing limit, remaining, reset, and retry_after.

    Raises:
        RateLimitException: If rate limit is exceeded.

    Example:
            try:
            meta = await check_rate_limit(limiter, "user:123", limit=100, window=60)
            # Request allowed, continue processing
        except RateLimitException as e:
            # Handle rate limit error
            pass
    """
    allowed, metadata = await limiter.check_limit(key, limit, window, cost, endpoint)

    if not allowed:
        raise RateLimitException(
            detail=f"Rate limit exceeded. Try again in {metadata['retry_after']} seconds",
            extra=metadata,
        )

    return metadata
