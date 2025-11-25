"""Rate limiting middleware for FastAPI."""
from __future__ import annotations

import logging
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from example_service.core.exceptions import RateLimitException
from example_service.infra.ratelimit.limiter import RateLimiter

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware for rate limiting requests.

    This middleware applies rate limiting to incoming requests based on
    various identifiers (IP address, user ID, API key, etc.).

    Attributes:
        limiter: RateLimiter instance for checking limits.
        default_limit: Default rate limit (requests per window).
        default_window: Default time window in seconds.
        enabled: Whether rate limiting is enabled.
        exempt_paths: List of paths exempt from rate limiting.
        key_func: Function to extract rate limit key from request.

    Example:
        ```python
        from example_service.infra.cache import get_cache

        redis = get_cache()
        limiter = RateLimiter(redis)

        app.add_middleware(
            RateLimitMiddleware,
            limiter=limiter,
            default_limit=100,
            default_window=60
        )
        ```
    """

    def __init__(
        self,
        app: ASGIApp,
        limiter: RateLimiter | None = None,
        default_limit: int = 100,
        default_window: int = 60,
        enabled: bool = True,
        exempt_paths: list[str] | None = None,
        key_func: Callable[[Request], str] | None = None,
    ) -> None:
        """Initialize rate limit middleware.

        Args:
            app: The ASGI application.
            limiter: RateLimiter instance (required if enabled=True).
            default_limit: Default rate limit (requests per window).
            default_window: Default time window in seconds.
            enabled: Whether rate limiting is enabled.
            exempt_paths: List of paths to exempt from rate limiting.
            key_func: Custom function to extract rate limit key from request.
                     Default uses client IP address.
        """
        super().__init__(app)
        self.limiter = limiter
        self.default_limit = default_limit
        self.default_window = default_window
        self.enabled = enabled
        self.exempt_paths = exempt_paths or [
            "/health",
            "/health/",
            "/health/ready",
            "/health/live",
            "/health/startup",
            "/metrics",
            "/docs",
            "/redoc",
            "/openapi.json",
        ]
        self.key_func = key_func or self._default_key_func

        if self.enabled and self.limiter is None:
            raise ValueError("limiter is required when rate limiting is enabled")

    @staticmethod
    def _default_key_func(request: Request) -> str:
        """Default function to extract rate limit key from request.

        Uses client IP address as the rate limit key. In production,
        you may want to use X-Forwarded-For header or a custom identifier.

        Args:
            request: The incoming request.

        Returns:
            Rate limit key (client IP).
        """
        # Get client IP (handles proxy headers)
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            # Take the first IP in the chain
            client_ip = forwarded.split(",")[0].strip()
        else:
            client_ip = request.client.host if request.client else "unknown"

        return f"ip:{client_ip}"

    def _is_exempt(self, path: str) -> bool:
        """Check if path is exempt from rate limiting.

        Args:
            path: Request path.

        Returns:
            True if path is exempt.
        """
        return any(path.startswith(exempt_path) for exempt_path in self.exempt_paths)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Response]
    ) -> Response:
        """Apply rate limiting to request.

        Args:
            request: The incoming request.
            call_next: The next middleware or route handler.

        Returns:
            Response, possibly with rate limit headers.

        Raises:
            RateLimitException: If rate limit is exceeded.
        """
        # Skip if disabled or path is exempt
        if not self.enabled or self._is_exempt(request.url.path):
            return await call_next(request)

        # Extract rate limit key
        limit_key = self.key_func(request)

        try:
            # Check rate limit
            allowed, metadata = await self.limiter.check_limit(
                key=limit_key,
                limit=self.default_limit,
                window=self.default_window,
            )

            if not allowed:
                # Rate limit exceeded
                logger.warning(
                    "Rate limit exceeded",
                    extra={
                        "path": request.url.path,
                        "method": request.method,
                        "key": limit_key,
                        "limit": metadata["limit"],
                    },
                )

                raise RateLimitException(
                    detail=f"Rate limit exceeded. Retry after {metadata['retry_after']} seconds",
                    instance=str(request.url),
                    extra=metadata,
                )

            # Process request
            response = await call_next(request)

            # Add rate limit headers
            response.headers["X-RateLimit-Limit"] = str(metadata["limit"])
            response.headers["X-RateLimit-Remaining"] = str(metadata["remaining"])
            response.headers["X-RateLimit-Reset"] = str(metadata["reset"])

            return response

        except RateLimitException:
            # Re-raise rate limit exceptions
            raise
        except Exception as e:
            # Log error but allow request to proceed
            logger.error(
                "Rate limit check failed, allowing request",
                extra={
                    "path": request.url.path,
                    "key": limit_key,
                    "error": str(e),
                },
                exc_info=True,
            )
            return await call_next(request)
