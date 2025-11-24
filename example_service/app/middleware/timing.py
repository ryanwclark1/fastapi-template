"""Timing middleware for request performance monitoring."""
from __future__ import annotations

import time

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


class TimingMiddleware(BaseHTTPMiddleware):
    """Add timing information to responses.

    Measures request processing time and adds it to response headers
    for performance monitoring and debugging.
    """

    async def dispatch(self, request: Request, call_next):
        """Process request and add timing.

        Args:
            request: Incoming HTTP request.
            call_next: Next middleware/handler in chain.

        Returns:
            Response with X-Process-Time header added.
        """
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = str(process_time)
        return response
