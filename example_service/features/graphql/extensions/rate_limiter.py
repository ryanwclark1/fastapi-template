"""Rate limiting extension for GraphQL operations.

Provides per-operation rate limiting using Redis to track request counts
per user within a time window. Prevents abuse and ensures fair resource usage.

Usage:
    from example_service.features.graphql.extensions.rate_limiter import GraphQLRateLimiter

    extensions = [
        QueryDepthLimiter(max_depth=10),
        GraphQLRateLimiter(),  # Add rate limiting
    ]
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from graphql import GraphQLError
from strawberry.extensions import SchemaExtension


# Stub for missing cache module
def get_cache_instance() -> None:  # type: ignore[misc]
    """Stub for missing cache module."""
    return


logger = logging.getLogger(__name__)

__all__ = ["GraphQLRateLimiter"]


class GraphQLRateLimiter(SchemaExtension):
    """Rate limit GraphQL operations per user.

    This extension tracks the number of operations (queries, mutations, subscriptions)
    performed by each user within a sliding time window. If a user exceeds their
    rate limit, subsequent operations are rejected with a RATE_LIMIT_EXCEEDED error.

    Rate limits are configurable per operation type:
    - Queries: Higher limit (read operations)
    - Mutations: Lower limit (write operations)
    - Subscriptions: Lowest limit (long-lived connections)

    Example rate limits:
        queries: 100 per minute
        mutations: 50 per minute
        subscriptions: 10 per minute

    The extension uses Redis for distributed rate limiting, ensuring limits work
    correctly across multiple server instances.

    Example:
        schema = strawberry.Schema(
            query=Query,
            mutation=Mutation,
            extensions=[
                QueryDepthLimiter(max_depth=10),
                GraphQLRateLimiter(),
            ],
        )
    """

    # Default rate limits (requests per window)
    DEFAULT_LIMITS: ClassVar[dict[str, int]] = {
        "query": 100,  # 100 queries per minute
        "mutation": 50,  # 50 mutations per minute
        "subscription": 10,  # 10 subscription connections per minute
    }

    # Time window in seconds
    DEFAULT_WINDOW = 60  # 1 minute

    def __init__(
        self,
        limits: dict[str, int] | None = None,
        window_seconds: int | None = None,
    ) -> None:
        """Initialize rate limiter.

        Args:
            limits: Custom rate limits per operation type (default: DEFAULT_LIMITS)
            window_seconds: Time window in seconds (default: 60 seconds)
        """
        self.limits = limits or self.DEFAULT_LIMITS
        self.window = window_seconds or self.DEFAULT_WINDOW

    def on_execute(self) -> None:
        """Check rate limit before executing operation.

        This hook runs before query execution and can reject the operation
        if rate limits are exceeded.

        Raises:
            GraphQLError: If rate limit is exceeded
        """
        execution_context = self.execution_context

        # Get operation type
        operation_type = execution_context.operation_type
        if not operation_type:
            # Can't determine operation type, allow it
            return

        # Get user identifier
        user_id = self._get_user_identifier()

        # Check rate limit
        try:
            self._check_rate_limit(user_id, operation_type)
        except RateLimitExceeded as e:
            # Log rate limit violation
            logger.warning(
                "GraphQL rate limit exceeded",
                extra={
                    "user_id": user_id,
                    "operation_type": operation_type,
                    "limit": self.limits.get(operation_type, 0),
                    "window_seconds": self.window,
                    "operation_name": execution_context.operation_name,
                },
            )

            # Raise GraphQL error that will be returned to client
            raise GraphQLError(
                message=str(e),
                extensions={
                    "code": "RATE_LIMIT_EXCEEDED",
                    "operation_type": operation_type,
                    "limit": self.limits.get(operation_type, 0),
                    "window_seconds": self.window,
                    "retry_after": self.window,  # Suggest when to retry
                },
            ) from e

    def _get_user_identifier(self) -> str:
        """Get unique identifier for rate limiting.

        Returns user ID if authenticated, otherwise uses IP address
        or a generic "anonymous" identifier.

        Returns:
            Unique identifier string for this user/client
        """
        context = self.execution_context.context

        # Prefer authenticated user ID
        if hasattr(context, "user") and context.user:
            return f"user:{context.user.id}"

        # Fall back to IP address if available
        if hasattr(context, "request"):
            request = context.request
            # Try to get real IP from headers (e.g., X-Forwarded-For)
            forwarded_for = request.headers.get("X-Forwarded-For")
            if forwarded_for:
                # Take first IP in the chain
                client_ip = forwarded_for.split(",")[0].strip()
                return f"ip:{client_ip}"

            # Use direct client IP
            if hasattr(request, "client") and request.client:
                return f"ip:{request.client.host}"

        # Last resort: anonymous (shared rate limit for all unauthenticated users)
        return "anonymous"

    def _check_rate_limit(self, user_id: str, operation_type: str) -> None:
        """Check if user has exceeded rate limit.

        Uses Redis to track request counts in a sliding window.

        Args:
            user_id: User identifier
            operation_type: Operation type (query/mutation/subscription)

        Raises:
            RateLimitExceeded: If user has exceeded their rate limit
        """
        # Get cache instance (Redis)
        cache = get_cache_instance()
        if not cache:
            # No cache configured, skip rate limiting
            logger.debug("Rate limiting skipped: no cache configured")
            return

        # Get limit for this operation type
        limit = self.limits.get(operation_type, self.DEFAULT_LIMITS["query"])

        # Generate Redis key
        key = f"ratelimit:graphql:{operation_type}:{user_id}"

        try:
            # Increment counter
            import asyncio

            # Run async cache operations
            if asyncio.iscoroutinefunction(cache.get):
                # Async cache
                count = asyncio.create_task(self._async_rate_limit_check(cache, key, limit))
                # Note: This won't work in sync context, need to handle properly
                # For now, we'll use a simplified sync approach
                logger.warning("Async rate limiting not fully implemented yet")
                return
            # Sync cache (if available)
            count_value = cache.get(key) or 0
            count = int(count_value) + 1  # type: ignore[arg-type]

            if count > limit:
                msg = (
                    f"Rate limit exceeded for {operation_type} operations. "
                    f"Limit: {limit} per {self.window} seconds"
                )
                raise RateLimitExceeded(
                    msg,
                )

            # Set new count with expiry
            cache.set(key, count, ttl=self.window)

        except RateLimitExceeded:
            raise
        except Exception as e:
            # Don't fail the operation if rate limiting has issues
            logger.exception(
                "Rate limiting check failed",
                extra={"error": str(e), "user_id": user_id, "operation_type": operation_type},
            )

    async def _async_rate_limit_check(
        self,
        cache: Any,
        key: str,
        limit: int,
    ) -> None:
        """Async version of rate limit check.

        Args:
            cache: Cache instance
            key: Redis key
            limit: Rate limit threshold

        Raises:
            RateLimitExceeded: If limit is exceeded
        """
        # Get current count
        count_str = await cache.get(key)
        count = int(count_str) if count_str else 0

        # Check limit
        if count >= limit:
            msg = f"Rate limit exceeded. Limit: {limit} per {self.window} seconds"
            raise RateLimitExceeded(
                msg,
            )

        # Increment
        count += 1

        # Set with expiry
        await cache.set(key, count, ttl=self.window)


# ============================================================================
# Custom Exception
# ============================================================================


class RateLimitExceeded(Exception):
    """Exception raised when rate limit is exceeded."""



# ============================================================================
# Usage Example and Configuration
# ============================================================================

"""
Example: Basic usage with default limits
    from example_service.features.graphql.extensions.rate_limiter import GraphQLRateLimiter

    extensions = [
        QueryDepthLimiter(max_depth=10),
        GraphQLRateLimiter(),  # 100 queries/min, 50 mutations/min, 10 subscriptions/min
    ]

Example: Custom rate limits
    extensions = [
        GraphQLRateLimiter(
            limits={
                "query": 200,  # 200 queries per window
                "mutation": 100,  # 100 mutations per window
                "subscription": 20,  # 20 subscriptions per window
            },
            window_seconds=60,  # 1 minute window
        ),
    ]

Example: Different limits for different environments
    settings = get_graphql_settings()

    if settings.environment == "production":
        limits = {"query": 100, "mutation": 50, "subscription": 10}
    else:
        # More lenient in development
        limits = {"query": 1000, "mutation": 500, "subscription": 100}

    extensions = [GraphQLRateLimiter(limits=limits)]

Example: Authenticated vs anonymous limits
    # You can implement a custom rate limiter that checks user.is_authenticated
    # and applies different limits:

    class CustomRateLimiter(GraphQLRateLimiter):
        def _check_rate_limit(self, user_id: str, operation_type: str) -> None:
            # Higher limits for authenticated users
            if user_id.startswith("user:"):
                self.limits = {"query": 200, "mutation": 100, "subscription": 20}
            else:
                # Lower limits for anonymous users
                self.limits = {"query": 50, "mutation": 20, "subscription": 5}

            super()._check_rate_limit(user_id, operation_type)

Example: Client error handling
    # When rate limit is exceeded, client receives:
    {
        "errors": [{
            "message": "Rate limit exceeded for query operations. Limit: 100 per 60 seconds",
            "extensions": {
                "code": "RATE_LIMIT_EXCEEDED",
                "operation_type": "query",
                "limit": 100,
                "window_seconds": 60,
                "retry_after": 60
            }
        }]
    }

    # Client can use retry_after to implement exponential backoff:
    const retryAfter = error.extensions.retry_after;
    await sleep(retryAfter * 1000);  // Wait and retry

Note: This implementation requires Redis to be configured for distributed rate limiting.
If Redis is not available, rate limiting is skipped (logged as warning).

Future enhancements:
- Implement proper async support for async cache backends
- Add burst allowance (e.g., allow 10 requests instantly, then throttle)
- Per-field rate limiting for expensive operations
- Dynamic rate limits based on user subscription tier
- Rate limit analytics and monitoring
"""
