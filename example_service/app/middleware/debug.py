"""Debug middleware with distributed tracing support.

This module provides comprehensive debugging capabilities with distributed tracing
support. The middleware automatically adds trace IDs to requests, logs request/response
details, and integrates with the existing logging infrastructure.

Features:
- Automatic trace ID generation and propagation
- Span ID generation for request tracking
- Request/response logging with timing
- Exception tracking with trace context
- Context binding for structured logging
- Feature flags for gradual rollout
- Backward compatible with X-Request-Id

Usage:
    from example_service.app.middleware.debug import DebugMiddleware

    # In FastAPI application setup
    app.add_middleware(
        DebugMiddleware,
        enabled=settings.debug_middleware_enabled,
        log_requests=settings.debug_log_requests,
        log_responses=settings.debug_log_responses,
    )

Example Log Output:
    {
        "timestamp": "2025-01-07T10:30:45.123Z",
        "level": "INFO",
        "message": "Request completed",
        "trace_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "span_id": "12345678",
        "method": "POST",
        "path": "/api/v1/reminders",
        "status_code": 201,
        "duration_ms": 123.45,
        "user_id": "user-123",
        "tenant_id": "tenant-456"
    }

Security Considerations:
- Query parameters are logged by default (disable if sensitive)
- User/tenant IDs are included when available in request.state
- Response bodies are NOT logged (potential PII/sensitive data)
- Trace IDs are propagated but don't expose internal structure
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any
import uuid

from starlette.middleware.base import BaseHTTPMiddleware

from example_service.infra.logging.context import set_log_context

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


class DebugMiddleware(BaseHTTPMiddleware):
    """Debug middleware with distributed tracing and request tracking.

    This middleware provides comprehensive debugging capabilities including:
    - Trace ID generation and propagation (standard distributed tracing)
    - Span ID generation for request-level tracking within a trace
    - Request/response logging with performance timing
    - Exception tracking with full trace context
    - Context enrichment for structured logging
    - Integration with existing logging infrastructure

    The middleware is designed to be backward compatible with X-Request-Id
    and can be enabled via feature flags for gradual rollout.

    Trace vs Span IDs:
    - Trace ID: Identifies an entire distributed transaction across services
    - Span ID: Identifies a specific operation within a trace (this request)

    Attributes:
        enabled: Whether middleware is active (default: True)
        log_requests: Whether to log request details (default: True)
        log_responses: Whether to log response details (default: True)
        log_timing: Whether to log request timing (default: True)
        header_prefix: Header prefix for trace context (default: "X-")

    Security:
        - Query params are logged (disable if sensitive)
        - Request/response bodies are NOT logged (use RequestLoggingMiddleware)
        - User context is only logged if authenticated
        - Tenant context is only logged if multi-tenant mode active
    """

    def __init__(
        self,
        app: ASGIApp,
        enabled: bool = True,
        log_requests: bool = True,
        log_responses: bool = True,
        log_timing: bool = True,
        header_prefix: str = "X-",
    ) -> None:
        """Initialize the debug middleware.

        Args:
            app: The Starlette/FastAPI application
            enabled: Whether middleware is active
            log_requests: Whether to log request details
            log_responses: Whether to log response details
            log_timing: Whether to log timing information
            header_prefix: Prefix for trace headers (X-, Trace-, etc.)

        Example:
            app.add_middleware(
                DebugMiddleware,
                enabled=True,
                log_requests=True,
                log_responses=True,
                log_timing=True,
                header_prefix="X-",
            )
        """
        super().__init__(app)
        self.enabled = enabled
        self.log_requests = log_requests
        self.log_responses = log_responses
        self.log_timing = log_timing
        self.header_prefix = header_prefix

        # Log configuration for operational visibility
        if self.enabled:
            logger.info(
                "DebugMiddleware enabled",
                extra={
                    "log_requests": log_requests,
                    "log_responses": log_responses,
                    "log_timing": log_timing,
                    "header_prefix": header_prefix,
                },
            )

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Process request with debug context and logging.

        This is the main middleware entrypoint that:
        1. Generates or extracts trace/span IDs
        2. Stores IDs in request.state for downstream access
        3. Sets logging context for automatic injection
        4. Logs request details (if enabled)
        5. Tracks timing
        6. Handles exceptions with trace context
        7. Logs response details (if enabled)
        8. Adds trace headers to response

        Args:
            request: Incoming HTTP request
            call_next: Next middleware or endpoint handler

        Returns:
            Response from the handler with trace headers added

        Raises:
            Exception: Re-raises any exception after logging with trace context
        """
        # Skip processing if middleware is disabled
        if not self.enabled:
            return await call_next(request)

        # Generate or extract trace ID (transaction-level identifier)
        trace_id = self._get_or_create_trace_id(request)

        # Generate span ID (request-level identifier within trace)
        span_id = self._generate_span_id()

        # Store trace context in request state for downstream access
        # This allows dependencies, services, etc. to access trace context
        request.state.trace_id = trace_id
        request.state.span_id = span_id

        # Build structured context for logging
        context = self._build_request_context(request, trace_id, span_id)

        # Set logging context for automatic injection into all log records
        # This integrates with ContextInjectingFilter in logging config
        set_log_context(**context)

        # Log request start if enabled
        if self.log_requests:
            logger.info("Request started", extra=context)

        # Track timing using high-precision performance counter
        start_time = time.perf_counter()

        try:
            # Process request through middleware chain and endpoint
            response = await call_next(request)

            # Calculate request duration in milliseconds
            duration_ms = (time.perf_counter() - start_time) * 1000

            # Add trace headers to response for client correlation
            # These headers allow clients to correlate responses with traces
            response.headers[f"{self.header_prefix}Trace-Id"] = trace_id
            response.headers[f"{self.header_prefix}Span-Id"] = span_id

            # Log response if enabled
            if self.log_responses:
                response_context = {
                    **context,
                    "status_code": response.status_code,
                    "duration_ms": round(duration_ms, 2),
                }
                logger.info("Request completed", extra=response_context)

            return response

        except Exception as exc:
            # Calculate duration even for failed requests
            duration_ms = (time.perf_counter() - start_time) * 1000

            # Build error context with trace information
            error_context = {
                **context,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "duration_ms": round(duration_ms, 2),
            }

            # Log exception with full trace context
            # This provides critical debugging information for failures
            logger.exception("Request failed", extra=error_context)

            # Re-raise exception to let exception handlers process it
            # The trace context is now in logs for correlation
            raise

    def _get_or_create_trace_id(self, request: Request) -> str:
        """Get existing trace ID or generate new one.

        Checks for trace ID in the following priority order:
        1. X-Trace-Id header (standard distributed tracing)
        2. X-Request-Id header (backward compatibility)
        3. Generate new UUID v4

        This approach ensures compatibility with existing systems while
        supporting modern distributed tracing standards.

        Args:
            request: HTTP request object

        Returns:
            Trace ID string (UUID format)

        Example:
            # Client sends: X-Trace-Id: a1b2c3d4-e5f6-7890-abcd-ef1234567890
            # Returns: "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

            # Client sends: X-Request-Id: old-format-id
            # Returns: "old-format-id"

            # Client sends nothing
            # Returns: "f47ac10b-58cc-4372-a567-0e02b2c3d479" (generated)
        """
        # Check for standard trace header (preferred)
        trace_id = request.headers.get(f"{self.header_prefix}Trace-Id")
        if trace_id:
            return trace_id

        # Check for legacy request ID header (backward compatibility)
        request_id = request.headers.get(f"{self.header_prefix}Request-Id")
        if request_id:
            return request_id

        # Generate new trace ID using UUID v4
        # UUID v4 provides good randomness and uniqueness guarantees
        return str(uuid.uuid4())

    def _generate_span_id(self) -> str:
        """Generate a unique span ID for this request.

        Span IDs are shorter than trace IDs for efficiency while maintaining
        uniqueness within a trace. They identify a specific operation/request
        within a larger distributed trace.

        Returns:
            8-character hex span ID (e.g., "a1b2c3d4")

        Example:
            _generate_span_id() -> "f47ac10b"
            _generate_span_id() -> "58cc4372"

        Note:
            8 hex chars = 32 bits = 4.3 billion possible values
            This is sufficient for span uniqueness within a trace
        """
        return uuid.uuid4().hex[:8]

    def _build_request_context(
        self, request: Request, trace_id: str, span_id: str,
    ) -> dict[str, Any]:
        """Build structured context for logging.

        Extracts relevant information from the request and builds a
        structured dictionary for logging. This context is automatically
        injected into all log records via ContextInjectingFilter.

        Args:
            request: HTTP request object
            trace_id: Trace identifier
            span_id: Span identifier

        Returns:
            Dictionary with request context including:
            - trace_id: Distributed trace identifier
            - span_id: Request span identifier
            - method: HTTP method (GET, POST, etc.)
            - path: Request path
            - client_host: Client IP address
            - query_params: Query parameters (if present)
            - user_id: User ID (if authenticated)
            - tenant_id: Tenant ID (if multi-tenant)

        Example:
            {
                "trace_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "span_id": "f47ac10b",
                "method": "POST",
                "path": "/api/v1/reminders",
                "client_host": "192.168.1.100",
                "query_params": {"filter": "active"},
                "user_id": "user-123",
                "tenant_id": "tenant-456"
            }
        """
        # Start with core trace and request information
        context: dict[str, Any] = {
            "trace_id": trace_id,
            "span_id": span_id,
            "method": request.method,
            "path": request.url.path,
            "client_host": request.client.host if request.client else None,
        }

        # Add query parameters if present (useful for debugging)
        # Note: May contain sensitive data, disable if needed
        if request.query_params:
            context["query_params"] = dict(request.query_params)

        # Add user context if available (set by auth middleware/dependency)
        # This allows correlating requests with specific users
        if hasattr(request.state, "user_id"):
            context["user_id"] = str(request.state.user_id)

        # Add tenant context if available (set by tenant middleware)
        # This is crucial for multi-tenant debugging and isolation
        if hasattr(request.state, "tenant_id"):
            context["tenant_id"] = str(request.state.tenant_id)

        return context


__all__ = ["DebugMiddleware"]
