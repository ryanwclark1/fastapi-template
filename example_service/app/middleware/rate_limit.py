"""Rate limiting middleware for FastAPI."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import JSONResponse

from example_service.app.middleware.constants import EXEMPT_PATHS
from example_service.core.exceptions import RateLimitException

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette.types import ASGIApp, Message, Receive, Scope, Send

    from example_service.infra.ratelimit.limiter import RateLimiter

logger = logging.getLogger(__name__)


class RateLimitMiddleware:
    """Pure ASGI middleware for rate limiting requests.

    This middleware applies rate limiting to incoming requests based on
    various identifiers (IP address, user ID, API key, etc.).

    This implementation uses pure ASGI pattern for 30-40% better performance
    compared to BaseHTTPMiddleware. It properly handles async Redis operations,
    exception propagation, and response header injection.

    Attributes:
        app: The ASGI application.
        limiter: RateLimiter instance for checking limits.
        default_limit: Default rate limit (requests per window).
        default_window: Default time window in seconds.
        enabled: Whether rate limiting is enabled.
        exempt_paths: List of paths exempt from rate limiting.
        key_func: Function to extract rate limit key from request.

    Example:
            from example_service.infra.cache import get_cache

        redis = get_cache()
        limiter = RateLimiter(redis)

        app.add_middleware(
            RateLimitMiddleware,
            limiter=limiter,
            default_limit=100,
            default_window=60
        )
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
        self.app = app
        self.limiter = limiter
        self.default_limit = default_limit
        self.default_window = default_window
        self.enabled = enabled
        # Use shared exempt paths from constants
        self.exempt_paths = exempt_paths or EXEMPT_PATHS
        self.key_func = key_func or self._default_key_func

        if self.enabled and self.limiter is None:
            raise ValueError("limiter is required when rate limiting is enabled")

    @staticmethod
    def __validate_middleware__(*args, **kwargs) -> None:
        """Eager validation when middleware is registered."""
        enabled = kwargs.get("enabled", True)
        limiter = kwargs.get("limiter")
        if enabled and limiter is None:
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

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """ASGI callable interface.

        Args:
            scope: ASGI scope dictionary.
            receive: ASGI receive channel.
            send: ASGI send channel.
        """
        # Only process HTTP requests
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Early exit if disabled or path is exempt (before any async operations)
        path = scope.get("path", "")
        if not self.enabled or self._is_exempt(path):
            await self.app(scope, receive, send)
            return

        # Construct Request object to use key_func
        # This is lightweight - only parses what we need
        request = Request(scope, receive)

        # Extract rate limit key
        limit_key = self.key_func(request)

        # Rate limit metadata to be added to response headers
        rate_limit_metadata: dict[str, int] | None = None

        try:
            # Check rate limit (async Redis operation)
            allowed, metadata = await self.limiter.check_limit(
                key=limit_key,
                limit=self.default_limit,
                window=self.default_window,
                endpoint=path,
            )

            if not allowed:
                # Rate limit exceeded - raise exception
                # Let the exception handler deal with it
                logger.warning(
                    "Rate limit exceeded",
                    extra={
                        "path": path,
                        "method": scope.get("method", ""),
                        "key": limit_key,
                        "limit": metadata["limit"],
                    },
                )

                raise RateLimitException(
                    detail=f"Rate limit exceeded. Retry after {metadata['retry_after']} seconds",
                    instance=str(request.url),
                    extra=metadata,
                )

            # Store metadata for response headers
            rate_limit_metadata = metadata

            # Track successful Redis operation for protection status
            try:
                from example_service.infra.ratelimit.tracker import (
                    get_rate_limit_tracker,
                )

                tracker = get_rate_limit_tracker()
                if tracker:
                    tracker.record_success()
            except Exception:
                pass  # Don't let tracker errors affect request processing

        except RateLimitException as exc:
            await self._send_rate_limit_response(exc, scope, receive, send)
            return
        except Exception as e:
            # Log error but allow request to proceed (fail-open pattern)
            # This ensures the application continues to function if Redis fails
            # Track the failure in the rate limit state tracker
            try:
                from example_service.infra.ratelimit.tracker import (
                    get_rate_limit_tracker,
                )

                tracker = get_rate_limit_tracker()
                if tracker:
                    tracker.record_failure(str(e))
            except Exception:
                pass  # Don't let tracker errors affect request processing

            logger.error(
                "Rate limit check failed, allowing request (fail-open)",
                extra={
                    "path": path,
                    "key": limit_key,
                    "error": str(e),
                    "protection_status": "degraded",
                },
                exc_info=True,
            )
            # Continue without rate limit metadata
            rate_limit_metadata = None

        # Wrap send to inject rate limit headers
        async def send_with_headers(message: Message) -> None:
            """Send wrapper that injects rate limit headers.

            Args:
                message: ASGI message to send.
            """
            if message["type"] == "http.response.start" and rate_limit_metadata:
                # Inject rate limit headers into response
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"x-ratelimit-limit", str(rate_limit_metadata["limit"]).encode()),
                        (b"x-ratelimit-remaining", str(rate_limit_metadata["remaining"]).encode()),
                        (b"x-ratelimit-reset", str(rate_limit_metadata["reset"]).encode()),
                    ]
                )
                message["headers"] = headers

            await send(message)

        await self.app(scope, receive, send_with_headers)

    async def _send_rate_limit_response(
        self,
        exc: RateLimitException,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        """Send JSON response for rate limit exceptions.

        Args:
            exc: RateLimitException instance.
            send: ASGI send callable.
        """
        metadata = exc.extra or {}
        headers: dict[str, str] = {}

        retry_after = metadata.get("retry_after")
        if retry_after is not None:
            headers["Retry-After"] = str(retry_after)

        if "limit" in metadata:
            headers["X-RateLimit-Limit"] = str(metadata["limit"])
        if "remaining" in metadata:
            headers["X-RateLimit-Remaining"] = str(metadata["remaining"])
        if "reset" in metadata:
            headers["X-RateLimit-Reset"] = str(metadata["reset"])

        response = JSONResponse(
            {
                "detail": exc.detail,
                "type": exc.type,
                "title": exc.title,
                "instance": exc.instance,
                "extra": metadata or None,
            },
            status_code=exc.status_code,
            headers=headers or None,
        )
        await response(scope, receive, send)
