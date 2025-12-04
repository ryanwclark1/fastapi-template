"""Request ID middleware for per-request tracking.

Request IDs are unique per HTTP request within this service, useful for
correlating logs and tracing during debugging. Unlike correlation IDs,
request IDs do not persist across service boundaries.

This middleware:
1. Extracts request ID from X-Request-ID header if present
2. Generates a new UUID if header is missing
3. Stores the ID in request.state.request_id
4. Adds the ID to logging context
5. Includes X-Request-ID in response headers
6. Cleans up logging context after request completes
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from example_service.app.middleware.base import HeaderContextMiddleware, generate_uuid

if TYPE_CHECKING:
    from starlette.types import ASGIApp


def clear_log_context() -> None:
    """Proxy to logging context's clear_log_context for easy patching."""
    from example_service.infra.logging.context import clear_log_context as _clear_log_context
    _clear_log_context()


class RequestIDMiddleware(HeaderContextMiddleware):
    """Add unique request ID to all requests for correlation.

    The request ID is either taken from the X-Request-ID header
    or generated as a new UUID if not provided.

    This middleware also sets the request ID in the logging context
    immediately, making it available to all downstream middleware and
    route handlers.

    Performance: Pure ASGI implementation provides 40-50% better
    performance compared to BaseHTTPMiddleware.

    Usage:
        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)

        @app.get("/")
        async def root(request: Request):
            request_id = request.state.request_id
            return {"request_id": request_id}
    """

    header_name = "x-request-id"
    state_key = "request_id"
    log_context_key = "request_id"
    should_clear_context_on_finish = True  # Clean up to prevent context leakage

    def __init__(self, app: ASGIApp) -> None:
        """Initialize the middleware.

        Args:
            app: The ASGI application to wrap.
        """
        # Allow tests to patch the log context clearer by referencing module attribute
        self._clear_log_context = clear_log_context
        super().__init__(app)

    def generate_value(self) -> str:
        """Generate a new UUID v4 for request ID.

        Returns:
            String representation of a UUID v4.
        """
        return generate_uuid()
