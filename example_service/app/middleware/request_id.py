"""Request ID middleware for distributed tracing."""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from starlette.datastructures import MutableHeaders

from example_service.infra.logging.context import clear_log_context, set_log_context

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send


class RequestIDMiddleware:
    """Add unique request ID to all requests for correlation.

    The request ID is either taken from the X-Request-ID header
    or generated as a new UUID if not provided.

    This middleware also sets the request ID in the logging context
    immediately, making it available to all downstream middleware and
    route handlers.

    This is a pure ASGI middleware implementation for 40-50% better
    performance compared to BaseHTTPMiddleware.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Initialize the middleware.

        Args:
            app: The ASGI application to wrap.
        """
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process ASGI request and add request ID with context.

        Args:
            scope: ASGI connection scope.
            receive: ASGI receive channel.
            send: ASGI send channel.
        """
        # Only process HTTP requests
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Extract or generate request ID
        headers = dict(scope.get("headers", []))
        request_id = headers.get(b"x-request-id")
        if request_id:
            request_id = request_id.decode("latin-1")
        else:
            request_id = str(uuid.uuid4())

        # Store in scope state
        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["request_id"] = request_id

        # Set log context immediately before calling app
        # This makes request_id available to all downstream middleware
        set_log_context(request_id=request_id)

        async def send_with_request_id(message: dict) -> None:
            """Wrap send to inject X-Request-ID header in response.

            Args:
                message: ASGI message to send.
            """
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.append("X-Request-ID", request_id)

            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            # Clean up context to prevent leakage between requests
            clear_log_context()
