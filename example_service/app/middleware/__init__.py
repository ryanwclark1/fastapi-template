"""Middleware configuration for FastAPI application."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi.middleware.cors import CORSMiddleware

from example_service.app.middleware.request_id import RequestIDMiddleware
from example_service.app.middleware.size_limit import RequestSizeLimitMiddleware
from example_service.app.middleware.timing import TimingMiddleware
from example_service.core.settings import get_app_settings, get_logging_settings

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)

__all__ = [
    "RequestIDMiddleware",
    "RequestSizeLimitMiddleware",
    "TimingMiddleware",
    "configure_middleware",
]


def configure_middleware(app: FastAPI) -> None:
    """Configure middleware for the application.

    Uses modular settings for CORS and other configuration.

    Args:
        app: FastAPI application instance.
    """
    app_settings = get_app_settings()
    log_settings = get_logging_settings()

    # CORS middleware (configure origins from settings)
    cors_origins = app_settings.cors_origins or ["*"]
    logger.info(f"Configuring CORS with origins: {cors_origins}")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=app_settings.cors_allow_credentials,
        allow_methods=app_settings.cors_allow_methods,
        allow_headers=app_settings.cors_allow_headers,
        max_age=3600,
    )

    # Custom middleware
    if log_settings.include_request_id:
        app.add_middleware(RequestIDMiddleware)

    if log_settings.log_slow_requests:
        app.add_middleware(TimingMiddleware)
