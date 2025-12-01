"""Correlation ID middleware for distributed tracing across services.

This middleware handles correlation IDs which are different from request IDs:
- Request ID: Unique per HTTP request (internal to this service)
- Correlation ID: Shared across multiple services in a transaction flow

The correlation ID enables end-to-end tracing across microservices boundaries.

Example flow:
    Client -> Service A (correlation_id=abc, request_id=123)
        -> Service B (correlation_id=abc, request_id=456)
            -> Service C (correlation_id=abc, request_id=789)

All services share correlation_id=abc for end-to-end tracing,
but each has a unique request_id for per-hop debugging.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from starlette.datastructures import MutableHeaders

from example_service.app.middleware.base import HeaderContextMiddleware, generate_uuid
from example_service.infra.logging.context import set_log_context

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)


class CorrelationIDMiddleware(HeaderContextMiddleware):
    """Pure ASGI middleware for correlation ID handling in distributed systems.

    This middleware:
    1. Extracts correlation ID from incoming X-Correlation-ID header
    2. Generates new correlation ID if not present (configurable)
    3. Adds correlation ID to response headers
    4. Sets correlation ID in logging context
    5. Stores correlation ID in request.state for use in HTTP clients

    Performance: Pure ASGI implementation provides 40-50% better performance
    compared to BaseHTTPMiddleware.

    Usage:
        app = FastAPI()
        app.add_middleware(CorrelationIDMiddleware)

        # In downstream HTTP calls
        async def call_service_b(request: Request):
            correlation_id = request.state.correlation_id
            async with httpx.AsyncClient() as client:
                await client.get(
                    "https://service-b/api",
                    headers={"X-Correlation-ID": correlation_id}
                )
    """

    # Default configuration - can be overridden in __init__
    header_name = "x-correlation-id"
    state_key = "correlation_id"
    log_context_key = "correlation_id"

    def __init__(
        self,
        app: ASGIApp,
        header_name: str = "x-correlation-id",
        generate_if_missing: bool = True,
    ) -> None:
        """Initialize correlation ID middleware.

        Args:
            app: The ASGI application.
            header_name: HTTP header name for correlation ID (default: x-correlation-id).
            generate_if_missing: Whether to generate correlation ID if not in request
                                (default: True). Set to False if you want to enforce
                                that clients always provide correlation IDs.
        """
        super().__init__(app)
        self.header_name = header_name.lower()
        self.should_generate_if_missing = generate_if_missing

    def generate_value(self) -> str:
        """Generate a new UUID v4 for correlation ID.

        Returns:
            String representation of a UUID v4.
        """
        return generate_uuid()

    def on_value_extracted(self, scope: Scope, value: str, was_generated: bool) -> None:
        """Log correlation ID source for debugging distributed traces.

        Args:
            scope: ASGI connection scope.
            value: The correlation ID.
            was_generated: True if generated, False if from upstream.
        """
        _ = scope
        if was_generated:
            logger.debug(
                f"Generated new correlation ID: {value}",
                extra={"correlation_id": value},
            )
        else:
            logger.debug(
                f"Correlation ID received from upstream: {value}",
                extra={"correlation_id": value},
            )

    def on_response_start(self, scope: Scope, value: str) -> None:
        """Log when correlation ID is added to response.

        Args:
            scope: ASGI connection scope.
            value: The correlation ID being added.
        """
        _ = scope
        logger.debug(
            f"Added correlation ID to response: {value}",
            extra={"correlation_id": value},
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process ASGI request with correlation ID handling.

        This override adds special error handling to ensure the correlation ID
        is included even in error responses, enabling end-to-end tracing of
        failed requests across services.

        Args:
            scope: ASGI connection scope.
            receive: ASGI receive channel.
            send: ASGI send channel.
        """
        # Only process HTTP requests
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Extract or generate correlation ID
        value, was_generated = self._extract_or_generate(scope)

        # Store in request state
        state = scope.setdefault("state", {})
        state[self.state_key] = value

        # Set logging context
        if value:
            set_log_context(**{self.log_context_key: value})
            self.on_value_extracted(scope, value, was_generated)

        # Track if response has started for error handling
        response_started = False

        async def send_with_correlation_id(message: Message) -> None:
            """Inject correlation ID header into response."""
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                if value:
                    headers = MutableHeaders(scope=message)
                    headers.append(self.header_name, value)
                    self.on_response_start(scope, value)
            await send(message)

        # Process request with error handling for correlation ID
        try:
            await self.app(scope, receive, send_with_correlation_id)
        except Exception:
            # Ensure correlation ID is in error response for tracing
            if value and not response_started:
                header_bytes = self.header_name.encode("latin-1")
                await send(
                    {
                        "type": "http.response.start",
                        "status": 500,
                        "headers": [
                            (header_bytes, value.encode("latin-1")),
                            (b"content-type", b"text/plain; charset=utf-8"),
                        ],
                    }
                )
                await send(
                    {
                        "type": "http.response.body",
                        "body": b"Internal Server Error",
                    }
                )
                logger.exception(
                    "Unhandled exception while processing request",
                    extra={"correlation_id": value},
                )
                # Re-raise in debug mode for stack trace visibility
                app_obj = scope.get("app")
                if getattr(app_obj, "debug", False):
                    raise
                return
            raise


def get_correlation_id_from_request(request) -> str | None:
    """Helper function to extract correlation ID from request.

    Args:
        request: FastAPI Request object.

    Returns:
        Correlation ID if present, None otherwise.

    Example:
        from example_service.app.middleware.correlation_id import (
            get_correlation_id_from_request
        )

        @app.get("/api/v1/example")
        async def example(request: Request):
            correlation_id = get_correlation_id_from_request(request)
            # Use correlation_id when calling downstream services
    """
    return getattr(request.state, "correlation_id", None)
