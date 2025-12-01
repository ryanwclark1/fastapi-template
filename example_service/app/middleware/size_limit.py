"""Request size limit middleware."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send


class RequestSizeLimitMiddleware:
    """Limit the size of incoming requests.

    Pure ASGI middleware implementation for optimal performance.
    Rejects requests that exceed the configured maximum size.
    """

    def __init__(self, app: ASGIApp, max_size: int = 10 * 1024 * 1024) -> None:  # 10MB default
        """Initialize middleware.

        Args:
            app: ASGI application.
            max_size: Maximum request size in bytes.
        """
        self.app = app
        self.max_size = max_size

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process ASGI request and check size limits.

        Args:
            scope: ASGI connection scope.
            receive: ASGI receive callable.
            send: ASGI send callable.
        """
        # Only process HTTP requests
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Check content-length header
        headers = scope.get("headers", [])
        for header_name, header_value in headers:
            if header_name == b"content-length":
                try:
                    content_length = int(header_value.decode())
                    if content_length > self.max_size:
                        # Send 413 error response
                        await send(
                            {
                                "type": "http.response.start",
                                "status": 413,
                                "headers": [[b"content-type", b"application/json"]],
                            }
                        )
                        await send(
                            {
                                "type": "http.response.body",
                                "body": json.dumps(
                                    {
                                        "detail": f"Request size {content_length} exceeds maximum {self.max_size} bytes"
                                    }
                                ).encode(),
                            }
                        )
                        return
                except (ValueError, UnicodeDecodeError):
                    # Invalid content-length header, pass through
                    pass
                break

        # Size is OK or no content-length header, pass through
        await self.app(scope, receive, send)
