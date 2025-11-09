"""Request size limit middleware."""
from __future__ import annotations

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Limit the size of incoming requests.

    Rejects requests that exceed the configured maximum size.
    """

    def __init__(self, app, max_size: int = 10 * 1024 * 1024):  # 10MB default
        """Initialize middleware.

        Args:
            app: ASGI application.
            max_size: Maximum request size in bytes.
        """
        super().__init__(app)
        self.max_size = max_size

    async def dispatch(self, request: Request, call_next):
        """Check request size before processing.

        Args:
            request: Incoming HTTP request.
            call_next: Next middleware/handler in chain.

        Returns:
            Response or error if request is too large.
        """
        if "content-length" in request.headers:
            content_length = int(request.headers["content-length"])
            if content_length > self.max_size:
                return JSONResponse(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    content={
                        "detail": f"Request size {content_length} exceeds maximum {self.max_size} bytes"
                    },
                )

        return await call_next(request)
