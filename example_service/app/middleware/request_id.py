"""Request ID middleware for distributed tracing."""
from __future__ import annotations

import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Add unique request ID to all requests for correlation.

    The request ID is either taken from the X-Request-ID header
    or generated as a new UUID if not provided.
    """

    async def dispatch(self, request: Request, call_next):
        """Process request and add request ID.

        Args:
            request: Incoming HTTP request.
            call_next: Next middleware/handler in chain.

        Returns:
            Response with X-Request-ID header added.
        """
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
