"""Middleware configuration for FastAPI application."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi.middleware.cors import CORSMiddleware

from example_service.app.middleware.metrics import MetricsMiddleware
from example_service.app.middleware.request_id import RequestIDMiddleware
from example_service.app.middleware.request_logging import (
    PIIMasker,
    RequestLoggingMiddleware,
)
from example_service.app.middleware.security_headers import SecurityHeadersMiddleware
from example_service.app.middleware.size_limit import RequestSizeLimitMiddleware
from example_service.app.middleware.timing import TimingMiddleware
from example_service.core.settings import (
    get_app_settings,
    get_logging_settings,
    get_otel_settings,
)

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)

__all__ = [
    "MetricsMiddleware",
    "PIIMasker",
    "RequestIDMiddleware",
    "RequestLoggingMiddleware",
    "RequestSizeLimitMiddleware",
    "SecurityHeadersMiddleware",
    "TimingMiddleware",
    "configure_middleware",
]


def configure_middleware(app: FastAPI) -> None:
    """Configure middleware for the application.

    Uses modular settings for CORS and other configuration.
    Middleware execution order (last registered = outermost = first to run):
    1. CORS (outermost)
    2. Security Headers (add security headers to all responses)
    3. Request Logging (detailed request/response logging with PII masking)
    4. RequestID (provides context for metrics/logging)
    5. Metrics (collects request metrics with trace correlation)
    6. Timing (adds performance headers)

    Args:
        app: FastAPI application instance.
    """
    app_settings = get_app_settings()
    log_settings = get_logging_settings()
    otel_settings = get_otel_settings()

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

    # Security headers middleware (protects against common vulnerabilities)
    app.add_middleware(
        SecurityHeadersMiddleware,
        enable_hsts=not app_settings.debug,  # Disable HSTS in debug mode
        hsts_max_age=31536000,  # 1 year
        hsts_include_subdomains=True,
        hsts_preload=False,
        enable_csp=True,
        enable_frame_options=True,
        frame_options="DENY",
        enable_xss_protection=True,
        enable_content_type_options=True,
        enable_referrer_policy=True,
        referrer_policy="strict-origin-when-cross-origin",
        enable_permissions_policy=True,
    )
    logger.info("Security headers middleware enabled")

    # Request/response logging middleware (with PII masking)
    # Only enable in debug mode or when explicitly configured
    if app_settings.debug or log_settings.log_level == "DEBUG":
        app.add_middleware(
            RequestLoggingMiddleware,
            log_request_body=True,
            log_response_body=False,  # Expensive, enable only when debugging
            max_body_size=10000,  # 10KB
        )
        logger.info("Request logging middleware enabled")

    # Custom middleware (order matters - see docstring above)
    if log_settings.include_request_id:
        app.add_middleware(RequestIDMiddleware)

    # Metrics middleware (with trace correlation via exemplars)
    if otel_settings.is_configured:
        app.add_middleware(MetricsMiddleware)
        logger.info("Metrics middleware enabled with trace correlation")

    if log_settings.log_slow_requests:
        app.add_middleware(TimingMiddleware)
