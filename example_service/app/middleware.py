"""Middleware configuration for FastAPI application."""
from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING

from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from fastapi import FastAPI


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Add request ID to all requests for tracing."""

    async def dispatch(self, request: Request, call_next):
        """Process request and add request ID.

        Args:
            request: Incoming request.
            call_next: Next middleware/handler.

        Returns:
            Response with X-Request-ID header.
        """
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class TimingMiddleware(BaseHTTPMiddleware):
    """Add timing information to responses."""

    async def dispatch(self, request: Request, call_next):
        """Process request and add timing.

        Args:
            request: Incoming request.
            call_next: Next middleware/handler.

        Returns:
            Response with X-Process-Time header.
        """
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = str(process_time)
        return response


def configure_middleware(app: FastAPI) -> None:
    """Configure middleware for the application.

    Args:
        app: FastAPI application instance.
    """
    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # TODO: Configure allowed origins
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        max_age=3600,
    )

    # Custom middleware
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(TimingMiddleware)
