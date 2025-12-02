"""Middleware configuration for FastAPI application.

This module provides a centralized middleware configuration system that ensures
consistent middleware stack across all environments with proper ordering.

The middleware stack includes:
- Debug: Comprehensive debugging with trace context (optional)
- Request ID: Request tracking for distributed tracing
- Security Headers: HTTP security headers and protections
- Metrics: Request metrics collection and observability
- CORS: Cross-Origin Resource Sharing (development only)
- Trusted Host: Host header validation (production only)
- Rate Limiting: DDoS protection via rate limits (optional)
- Request Logging: Detailed logging with PII masking (debug only)
- Size Limit: Payload size protection (optional)
- N+1 Detection: SQL query pattern detection (optional)

Middleware order is critical for correct request processing. This module
documents and enforces the correct order.

Example Usage:
    from example_service.app.middleware import configure_middleware
    from example_service.core.settings import get_settings

    # In FastAPI application setup
    settings = get_settings()
    configure_middleware(app, settings)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from example_service.app.middleware.base import HeaderContextMiddleware
from example_service.app.middleware.correlation_id import CorrelationIDMiddleware
from example_service.app.middleware.debug import DebugMiddleware
from example_service.app.middleware.i18n import I18nMiddleware, create_i18n_middleware
from example_service.app.middleware.metrics import MetricsMiddleware
from example_service.app.middleware.n_plus_one_detection import (
    NPlusOneDetectionMiddleware,
    QueryNormalizer,
    QueryPattern,
    setup_n_plus_one_monitoring,
)
from example_service.app.middleware.rate_limit import RateLimitMiddleware
from example_service.app.middleware.request_id import RequestIDMiddleware
from example_service.app.middleware.request_logging import (
    PIIMasker,
    RequestLoggingMiddleware,
)
from example_service.app.middleware.security_headers import SecurityHeadersMiddleware
from example_service.app.middleware.size_limit import RequestSizeLimitMiddleware
from example_service.app.middleware.tenant import (
    HeaderTenantStrategy,
    JWTClaimTenantStrategy,
    PathPrefixTenantStrategy,
    SubdomainTenantStrategy,
    TenantIdentificationStrategy,
    TenantMiddleware,
    clear_tenant_context,
    get_tenant_context,
    require_tenant,
    set_tenant_context,
)

if TYPE_CHECKING:
    from fastapi import FastAPI

    from example_service.core.settings import Settings

logger = logging.getLogger(__name__)

__all__ = [
    # Core middleware
    "CorrelationIDMiddleware",
    "DebugMiddleware",
    "HeaderContextMiddleware",
    "HeaderTenantStrategy",
    "I18nMiddleware",
    "JWTClaimTenantStrategy",
    "MetricsMiddleware",
    "NPlusOneDetectionMiddleware",
    "PIIMasker",
    "PathPrefixTenantStrategy",
    "QueryNormalizer",
    "QueryPattern",
    "RateLimitMiddleware",
    "RequestIDMiddleware",
    "RequestLoggingMiddleware",
    "RequestSizeLimitMiddleware",
    "SecurityHeadersMiddleware",
    "SubdomainTenantStrategy",
    "TenantIdentificationStrategy",
    # Tenant middleware
    "TenantMiddleware",
    "clear_tenant_context",
    # Configuration
    "configure_middleware",
    "create_i18n_middleware",
    "get_tenant_context",
    "require_tenant",
    "set_tenant_context",
    "setup_n_plus_one_monitoring",
]


def configure_middleware(app: FastAPI, settings: Settings) -> None:
    """Configure all middleware for the FastAPI application.

    This function centralizes middleware configuration and ensures
    consistent middleware stack across all environments.

    Middleware Order (Critical for Request Processing):
    ====================================================
    Middleware is applied in REVERSE order (last added = first to execute).
    The order below represents EXECUTION order (outermost to innermost):

    1. Debug Middleware (optional - first to capture all requests)
       - Adds comprehensive debugging with trace IDs and request logging
       - Only enabled when APP_ENABLE_DEBUG_MIDDLEWARE=true
       - Must be first to capture complete request/response lifecycle

    2. Request ID Middleware
       - Generates unique request IDs for tracing individual requests
       - Should be early so subsequent middleware can access request ID
       - Sets request_id in logging context for all downstream logs

    3. Security Headers Middleware
       - Adds HTTP security headers to all responses
       - Production-aware (stricter in production, relaxed for docs)
       - Protects against XSS, clickjacking, MIME sniffing, etc.

    4. Metrics Middleware
       - Collects HTTP request metrics for observability
       - Tracks request duration, status codes, and trace correlation
       - Adds X-Process-Time header with request duration

    5. CORS Middleware (development only)
       - Handles cross-origin requests for browser-based clients
       - Only enabled in debug mode (APP_DEBUG=true)
       - Configure origins via APP_CORS_ORIGINS

    6. Trusted Host Middleware (production only)
       - Validates Host header to prevent host header attacks
       - Only enabled in production (APP_DEBUG=false)
       - Configure allowed hosts via APP_ALLOWED_HOSTS

    7. Rate Limit Middleware (optional)
       - Protects against DDoS attacks via rate limiting
       - Requires Redis connection
       - Only enabled when APP_ENABLE_RATE_LIMITING=true

    8. Request Logging Middleware (debug only)
       - Logs detailed request/response information with PII masking
       - Only enabled in debug mode or when LOG_LEVEL=DEBUG
       - Expensive operation - use only for debugging

    9. Size Limit Middleware (optional)
       - Protects against large payload DoS attacks
       - Rejects requests exceeding APP_REQUEST_SIZE_LIMIT
       - Only enabled when APP_ENABLE_REQUEST_SIZE_LIMIT=true

    10. N+1 Detection Middleware (optional)
        - Detects N+1 query patterns in SQLAlchemy queries
        - Must be configured separately via setup_n_plus_one_monitoring()
        - Development tool - not recommended for production

    Environment Variables:
    =====================
    Core Settings:
        APP_DEBUG: Enable debug mode (default: false)
        APP_ENVIRONMENT: Environment name (development|staging|production|test)

    Middleware Toggles:
        APP_ENABLE_DEBUG_MIDDLEWARE: Enable debug middleware (default: false)
        APP_ENABLE_RATE_LIMITING: Enable rate limiting (default: false)
        APP_ENABLE_REQUEST_SIZE_LIMIT: Enable size limit (default: true)

    CORS Configuration (development only):
        APP_CORS_ORIGINS: Allowed origins (JSON array or comma-separated)
        APP_CORS_ALLOW_CREDENTIALS: Allow credentials (default: true)
        APP_CORS_ALLOW_METHODS: Allowed methods (default: ["*"])
        APP_CORS_ALLOW_HEADERS: Allowed headers (default: ["*"])

    Trusted Host Configuration (production only):
        APP_ALLOWED_HOSTS: Allowed host headers (JSON array or comma-separated)

    Rate Limiting Configuration:
        APP_RATE_LIMIT_PER_MINUTE: Requests per minute (default: 100)
        APP_RATE_LIMIT_WINDOW_SECONDS: Window size in seconds (default: 60)

    Security Configuration:
        APP_STRICT_CSP: Use strict CSP (default: true)
        APP_DISABLE_DOCS: Disable API docs (default: false)

    Logging Configuration:
        LOG_LEVEL: Logging level (default: INFO)
        LOG_INCLUDE_REQUEST_ID: Include request ID in logs (default: true)

    Args:
        app: FastAPI application instance
        settings: Unified settings instance with all configuration domains

    Raises:
        Exception: If rate limiting is enabled but Redis connection fails
                  (logs error and continues without rate limiting)

    Example:
        >>> from fastapi import FastAPI
        >>> from example_service.core.settings import get_settings
        >>> from example_service.app.middleware import configure_middleware
        >>>
        >>> app = FastAPI()
        >>> settings = get_settings()
        >>> configure_middleware(app, settings)

    Notes:
        - Authentication is handled at endpoint level via dependency injection
          (see example_service.core.dependencies.accent_auth)
        - Tracing is handled automatically via FastAPIInstrumentor in lifespan
          (see example_service.app.lifespan)
        - N+1 detection requires separate setup via setup_n_plus_one_monitoring()
    """
    # Extract domain settings from unified settings
    app_settings = settings.app
    log_settings = settings.logging
    otel_settings = settings.otel

    logger.info(
        "Configuring middleware stack",
        extra={
            "environment": app_settings.environment,
            "debug": app_settings.debug,
            "service": app_settings.service_name,
        },
    )

    # 1. Debug Middleware (optional, first to capture all requests)
    # Adds comprehensive debugging with trace IDs and request logging
    if app_settings.enable_debug_middleware:
        # DebugMiddleware extends BaseHTTPMiddleware which is compatible with FastAPI
        app.add_middleware(
            DebugMiddleware,
            enabled=True,
            log_requests=app_settings.debug_log_requests,
            log_responses=app_settings.debug_log_responses,
            log_timing=app_settings.debug_log_timing,
            header_prefix=app_settings.debug_header_prefix,
        )
        logger.info(
            "DebugMiddleware enabled",
            extra={
                "log_requests": app_settings.debug_log_requests,
                "log_responses": app_settings.debug_log_responses,
                "log_timing": app_settings.debug_log_timing,
                "header_prefix": app_settings.debug_header_prefix,
            },
        )

    # 2. Request ID Middleware
    # Generates unique request IDs for tracing individual requests
    # This should be added early so subsequent middleware can access request ID
    if log_settings.include_request_id:
        app.add_middleware(RequestIDMiddleware)
        logger.info("RequestIDMiddleware enabled")

    # 3. Security Headers Middleware
    # Adds security headers to all responses (production-aware)
    # Use strict CSP only when docs are disabled; docs need inline/eval for bundles
    docs_enabled = not app_settings.disable_docs
    use_strict_csp = not docs_enabled and app_settings.strict_csp and not app_settings.debug
    csp_directives = (
        SecurityHeadersMiddleware._strict_csp_directives()
        if use_strict_csp
        else SecurityHeadersMiddleware._default_csp_directives()
    )

    app.add_middleware(
        SecurityHeadersMiddleware,
        enable_hsts=not app_settings.debug,  # Disable HSTS in debug mode
        hsts_max_age=app_settings.hsts_max_age,
        hsts_include_subdomains=True,
        hsts_preload=False,
        enable_csp=True,
        csp_directives=csp_directives,
        enable_frame_options=True,
        frame_options="DENY",
        enable_xss_protection=True,
        enable_content_type_options=True,
        enable_referrer_policy=True,
        referrer_policy="strict-origin-when-cross-origin",
        enable_permissions_policy=True,
    )
    csp_mode = (
        "strict (no unsafe-inline/eval)"
        if use_strict_csp
        else "relaxed (docs-compatible, AsyncAPI/Swagger)"
    )
    logger.info(f"SecurityHeadersMiddleware enabled with {csp_mode} CSP")

    # 4. Metrics Middleware
    # Collects HTTP request metrics for observability
    if otel_settings.is_configured:
        app.add_middleware(MetricsMiddleware)
        logger.info("MetricsMiddleware enabled with trace correlation and timing header")

    # 5. CORS Middleware (development only)
    # Configure CORS for development environments
    if app_settings.debug:
        cors_origins = app_settings.cors_origins or ["*"]
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=app_settings.cors_allow_credentials,
            allow_methods=app_settings.cors_allow_methods,
            allow_headers=app_settings.cors_allow_headers,
            max_age=app_settings.cors_max_age,
        )
        logger.info(f"CORSMiddleware enabled for development with origins: {cors_origins}")

    # 6. Trusted Host Middleware (production only)
    # Validates host headers to prevent host header attacks
    if not app_settings.debug:
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=app_settings.allowed_hosts,
        )
        logger.info(
            f"TrustedHostMiddleware enabled for production with hosts: {app_settings.allowed_hosts}"
        )

    # 7. Rate Limiting Middleware (optional, requires Redis)
    # Must be early in the chain for fast rejection before expensive processing
    # Note: Rate limiter middleware requires async context, so it's disabled here.
    # Rate limiting should be done via dependencies in routes instead.
    # See example_service.core.dependencies.ratelimit for per-route rate limiting.
    if app_settings.enable_rate_limiting:
        logger.warning(
            "Rate limiting middleware is disabled. Use per-route dependencies instead. "
            "See example_service.core.dependencies.ratelimit"
        )

    # 8. Request Logging Middleware (debug only)
    # Logs detailed request/response information with PII masking
    # Only enable in debug mode or when explicitly configured
    if app_settings.debug or log_settings.level == "DEBUG":
        app.add_middleware(
            RequestLoggingMiddleware,
            log_request_body=True,
            log_response_body=False,  # Expensive, enable only when debugging
            max_body_size=10000,  # 10KB
        )
        logger.info("RequestLoggingMiddleware enabled")

    # 9. Size Limit Middleware (optional)
    # Protects against DoS via large payloads
    # Must be early for fast rejection before reading request body
    if app_settings.enable_request_size_limit:
        app.add_middleware(
            RequestSizeLimitMiddleware,
            max_size=app_settings.request_size_limit,
        )
        logger.info(
            f"RequestSizeLimitMiddleware enabled: {app_settings.request_size_limit} bytes "
            f"({app_settings.request_size_limit / (1024 * 1024):.1f}MB)"
        )

    # 10. Correlation ID Middleware (for distributed tracing across services)
    # Sets correlation_id in logging context for transaction-level tracking
    # Note: This is separate from Request ID (correlation = transaction, request = per-hop)
    app.add_middleware(
        CorrelationIDMiddleware,
        header_name="x-correlation-id",
        generate_if_missing=True,  # Generate if not provided by upstream service
    )
    logger.info("CorrelationIDMiddleware enabled")

    # Note: N+1 detection middleware must be configured separately via
    # setup_n_plus_one_monitoring() (see example_service/app/middleware/n_plus_one_detection.py)
    # This is a development tool and should not be enabled in production.

    # Note: Authentication is handled at the endpoint level via dependency injection
    # (see example_service/core/dependencies/accent_auth) for better testability and granularity.

    # Note: Tracing middleware is handled automatically via FastAPIInstrumentor in lifespan
    # (see example_service/app/lifespan.py)

    logger.info(
        "All middleware configured successfully",
        extra={
            "middleware_count": len(app.user_middleware),
            "environment": app_settings.environment,
        },
    )
