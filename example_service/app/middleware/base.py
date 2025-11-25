"""Base middleware classes for header-based context propagation.

This module provides reusable base classes for middleware that:
1. Extract a value from an incoming request header
2. Generate a default value if the header is missing
3. Store the value in request state
4. Set the value in logging context
5. Add the value to response headers

Both RequestIDMiddleware and CorrelationIDMiddleware inherit from this base,
eliminating code duplication while preserving their specific behaviors.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from starlette.datastructures import MutableHeaders

from example_service.infra.logging.context import clear_log_context, set_log_context

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send


class HeaderContextMiddleware(ABC):
    """Abstract base for header-based context propagation middleware.

    This base class encapsulates the common ASGI middleware pattern for:
    - Extracting values from request headers
    - Generating values when headers are missing
    - Storing values in request state
    - Setting logging context
    - Injecting values into response headers

    Subclasses must define:
    - header_name: The HTTP header to read/write (lowercase)
    - state_key: The key to use in scope["state"]
    - log_context_key: The key to use in logging context
    - generate_value(): Method to generate a value if header is missing

    Optional configuration via class attributes:
    - should_generate_if_missing: Whether to auto-generate (default: True)
    - should_clear_context_on_finish: Whether to clear log context (default: False)

    Optional hooks for subclass customization:
    - on_value_extracted(): Called after value is determined
    - on_response_start(): Called when response starts

    Example:
        class MyIDMiddleware(HeaderContextMiddleware):
            header_name = "x-my-id"
            state_key = "my_id"
            log_context_key = "my_id"

            def generate_value(self) -> str:
                return str(uuid.uuid4())

    Performance: Pure ASGI implementation provides 40-50% better
    performance compared to BaseHTTPMiddleware.
    """

    # Required: Subclasses must define these as class attributes or in __init__
    header_name: str  # Lowercase header name (e.g., "x-request-id")
    state_key: str  # Key for scope["state"] (e.g., "request_id")
    log_context_key: str  # Key for logging context

    # Optional configuration - override as needed
    should_generate_if_missing: bool = True
    should_clear_context_on_finish: bool = False

    def __init__(self, app: ASGIApp) -> None:
        """Initialize middleware with the wrapped ASGI app.

        Args:
            app: The ASGI application to wrap.
        """
        self.app = app
        # Allow subclasses/tests to override logging helpers
        self._set_log_context = getattr(self, "_set_log_context", set_log_context)
        self._clear_log_context = getattr(self, "_clear_log_context", clear_log_context)

    @abstractmethod
    def generate_value(self) -> str:
        """Generate a new value when header is not present.

        Returns:
            A new identifier string (typically a UUID).
        """
        ...

    def on_value_extracted(
        self, scope: Scope, value: str, was_generated: bool
    ) -> None:
        """Hook called after the value is determined.

        Override to add custom logging or processing.

        Args:
            scope: ASGI connection scope.
            value: The extracted or generated value.
            was_generated: True if value was generated, False if from header.
        """
        pass

    def on_response_start(self, scope: Scope, value: str) -> None:
        """Hook called when response starts (before header injection).

        Override to add custom logging or processing.

        Args:
            scope: ASGI connection scope.
            value: The value being added to response.
        """
        pass

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process ASGI request with header context propagation.

        Args:
            scope: ASGI connection scope.
            receive: ASGI receive channel.
            send: ASGI send channel.
        """
        # Only process HTTP requests
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Extract value from header or generate
        value, was_generated = self._extract_or_generate(scope)

        # Store in request state
        state = scope.setdefault("state", {})
        state[self.state_key] = value

        # Set logging context
        if value:
            self._set_log_context(**{self.log_context_key: value})

        # Call hook for custom processing
        if value:
            self.on_value_extracted(scope, value, was_generated)

        # Create send wrapper to inject header in response
        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start" and value:
                headers = MutableHeaders(scope=message)
                headers.append(self.header_name, value)
                self.on_response_start(scope, value)
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            if self.should_clear_context_on_finish:
                self._clear_log_context()

    def _extract_or_generate(self, scope: Scope) -> tuple[str | None, bool]:
        """Extract value from header or generate a new one.

        Args:
            scope: ASGI connection scope.

        Returns:
            Tuple of (value, was_generated) where was_generated is True
            if the value was generated rather than extracted from header.
        """
        # Check if already in state (set by upstream middleware)
        state = scope.get("state", {})
        if existing := state.get(self.state_key):
            return existing, False

        # Extract from headers
        headers = dict(scope.get("headers", []))
        header_bytes = headers.get(self.header_name.encode("latin-1"))

        if header_bytes:
            return header_bytes.decode("latin-1"), False

        # Generate if allowed
        if self.should_generate_if_missing:
            return self.generate_value(), True

        return None, False


def generate_uuid() -> str:
    """Generate a new UUID v4 string.

    Utility function for consistent UUID generation across middleware.

    Returns:
        String representation of a UUID v4.
    """
    return str(uuid.uuid4())
