"""Middleware configuration for FastAPI application."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi.middleware.cors import CORSMiddleware

from example_service.app.middleware.base import HeaderContextMiddleware
from example_service.app.middleware.constants import EXEMPT_PATHS
from example_service.app.middleware.correlation_id import CorrelationIDMiddleware
from example_service.app.middleware.metrics import MetricsMiddleware
from example_service.app.middleware.rate_limit import RateLimitMiddleware
from example_service.app.middleware.request_id import RequestIDMiddleware
from example_service.app.middleware.request_logging import (
    PIIMasker,
    RequestLoggingMiddleware,
)
from example_service.app.middleware.security_headers import SecurityHeadersMiddleware
from example_service.app.middleware.size_limit import RequestSizeLimitMiddleware
from example_service.core.settings import (
    get_app_settings,
    get_logging_settings,
    get_otel_settings,
)

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)

__all__ = [
    "CorrelationIDMiddleware",
    "HeaderContextMiddleware",
    "MetricsMiddleware",
    "PIIMasker",
    "RateLimitMiddleware",
    "RequestIDMiddleware",
    "RequestLoggingMiddleware",
    "RequestSizeLimitMiddleware",
    "SecurityHeadersMiddleware",
    "configure_middleware",
]


def configure_middleware(app: FastAPI) -> None:
    """Configure middleware for the application.

    Uses modular settings for CORS and other configuration.
    Middleware execution order (last registered = outermost = first to run):
    1. CORS (outermost)
    2. Rate Limit (optional, early rejection for DDoS protection)
    3. Request Size Limit (early rejection for large payload DoS)
    4. Security Headers (add security headers to all responses)
    5. CorrelationID (transaction-level ID across services, sets logging context)
    6. RequestID (request-level ID per hop, sets logging context)
    7. Request Logging (detailed request/response logging with PII masking)
    8. Metrics (collects metrics + trace correlation + timing header)

    IMPORTANT:
    - Rate limiting and size limits run early for fast rejection
    - CorrelationID runs before RequestID (transaction scope > request scope)
    - Both IDs MUST run before Request Logging so both are available in logs

    Correlation ID vs Request ID:
    - Correlation ID: Shared across all services in a transaction (Service A → B → C)
    - Request ID: Unique per HTTP request (one per service hop)

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

    # Rate limiting middleware (optional, requires Redis)
    # Must be early in the chain for fast rejection before expensive processing
    if app_settings.enable_rate_limiting:
        try:
            from example_service.infra.cache import get_cache
            from example_service.infra.ratelimit import RateLimiter

            redis = get_cache()
            limiter = RateLimiter(redis)

            app.add_middleware(
                RateLimitMiddleware,
                limiter=limiter,
                default_limit=app_settings.rate_limit_per_minute,
                default_window=app_settings.rate_limit_window_seconds,
                exempt_paths=EXEMPT_PATHS,
            )
            logger.info(
                f"Rate limiting enabled: {app_settings.rate_limit_per_minute}/min "
                f"(window: {app_settings.rate_limit_window_seconds}s)"
            )
        except Exception as e:
            logger.error(f"Failed to enable rate limiting: {e}", exc_info=True)
            logger.warning("Continuing without rate limiting")

    # Request size limit middleware (protects against DoS via large payloads)
    # Must be early for fast rejection before reading request body
    if app_settings.enable_request_size_limit:
        app.add_middleware(
            RequestSizeLimitMiddleware,
            max_size=app_settings.request_size_limit,
        )
        logger.info(
            f"Request size limit enabled: {app_settings.request_size_limit} bytes "
            f"({app_settings.request_size_limit / (1024 * 1024):.1f}MB)"
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

    # Correlation ID middleware (for distributed tracing across services)
    # Sets correlation_id in logging context for transaction-level tracking
    # Must run BEFORE RequestID so both IDs are available in correct order
    app.add_middleware(
        CorrelationIDMiddleware,
        header_name="x-correlation-id",
        generate_if_missing=True,  # Generate if not provided by upstream service
    )
    logger.info("Correlation ID middleware enabled")

    # Request ID middleware (for per-request tracking within this service)
    # Sets request_id in logging context for request-level debugging
    # Must run BEFORE logging so request_id is available in logs
    if log_settings.include_request_id:
        app.add_middleware(RequestIDMiddleware)
        logger.info("Request ID middleware enabled")

    # Request/response logging middleware (with PII masking)
    # Only enable in debug mode or when explicitly configured
    # IMPORTANT: Runs AFTER RequestIDMiddleware so logs contain request_id
    if app_settings.debug or log_settings.level == "DEBUG":
        app.add_middleware(
            RequestLoggingMiddleware,
            log_request_body=True,
            log_response_body=False,  # Expensive, enable only when debugging
            max_body_size=10000,  # 10KB
        )
        logger.info("Request logging middleware enabled")

    # Metrics middleware (with trace correlation via exemplars + timing header)
    # Note: Consolidates timing functionality from old TimingMiddleware
    if otel_settings.is_configured:
        app.add_middleware(MetricsMiddleware)
        logger.info("Metrics middleware enabled with trace correlation and timing header")
