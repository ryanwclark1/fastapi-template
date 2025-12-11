"""Metrics middleware for HTTP request instrumentation with trace correlation."""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING, Any

from opentelemetry import trace
from starlette.middleware.base import BaseHTTPMiddleware

from example_service.infra.metrics.prometheus import (
    http_request_duration_seconds,
    http_requests_in_progress,
    http_requests_total,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastapi import Request, Response


class MetricsMiddleware(BaseHTTPMiddleware):
    """Collect HTTP metrics with trace correlation via exemplars.

    This middleware instruments all HTTP requests with Prometheus metrics
    linked to OpenTelemetry traces. Key features:

    - Records request counts, durations, and in-progress requests
    - Links metrics to traces via exemplars (trace IDs)
    - Uses route path templates for low cardinality labels
    - Ensures accurate in-progress gauge tracking with try/finally
    - Adds X-Process-Time header for client-side performance monitoring

    The exemplar pattern enables click-through from Grafana metrics
    to corresponding traces in Tempo for deep debugging.

    Note: This middleware consolidates timing functionality that was
    previously in TimingMiddleware, eliminating duplicate timing measurements.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and collect metrics.

        Args:
            request: Incoming HTTP request.
            call_next: Next middleware/handler in chain.

        Returns:
            Response from the handler.
        """
        # Extract route path template for low cardinality
        # e.g., "/api/v1/reminders/{id}" instead of "/api/v1/reminders/123"
        endpoint = request.url.path
        if hasattr(request, "scope") and "route" in request.scope:
            route = request.scope.get("route")
            if route and hasattr(route, "path"):
                endpoint = route.path

        method = request.method

        # Track in-progress requests
        http_requests_in_progress.labels(method=method, endpoint=endpoint).inc()

        start_time = time.time()
        status_code = 500  # Default to error in case of exception

        try:
            response = await call_next(request)
            status_code = response.status_code

            # Add timing header for client debugging (consolidated from TimingMiddleware)
            duration = time.time() - start_time
            response.headers["X-Process-Time"] = str(duration)

            return response  # type: ignore[no-any-return]
        finally:
            # Calculate duration for metrics (in case of exception before response)
            duration = time.time() - start_time

            # Extract current trace ID for exemplar linking
            span = trace.get_current_span()
            trace_id = None
            if span and span.get_span_context().is_valid:
                # Format as 32-character hex string (128-bit trace ID)
                trace_id = format(span.get_span_context().trace_id, "032x")

            # Record metrics with exemplar linking
            # Exemplars enable click-through from Prometheus/Grafana to Tempo
            if trace_id:
                http_request_duration_seconds.labels(
                    method=method, endpoint=endpoint,
                ).observe(duration, exemplar={"trace_id": trace_id})

                http_requests_total.labels(
                    method=method, endpoint=endpoint, status=status_code,
                ).inc(exemplar={"trace_id": trace_id})
            else:
                # Fallback without exemplar if tracing unavailable
                http_request_duration_seconds.labels(
                    method=method, endpoint=endpoint,
                ).observe(duration)

                http_requests_total.labels(
                    method=method, endpoint=endpoint, status=status_code,
                ).inc()

            # Decrement in-progress gauge
            http_requests_in_progress.labels(method=method, endpoint=endpoint).dec()


def _patch_fastapi_middleware_ordering() -> None:
    """Patch FastAPI to maintain deterministic middleware ordering."""
    try:
        from fastapi import FastAPI
        from starlette.middleware import Middleware

        from example_service.app.middleware.correlation_id import (
            CorrelationIDMiddleware,
        )
        from example_service.app.middleware.rate_limit import RateLimitMiddleware
        from example_service.app.middleware.request_id import RequestIDMiddleware
        from example_service.app.middleware.request_logging import (
            RequestLoggingMiddleware,
        )
        from example_service.app.middleware.security_headers import (
            SecurityHeadersMiddleware,
        )
        from example_service.app.middleware.size_limit import RequestSizeLimitMiddleware
    except Exception:  # pragma: no cover - FastAPI/middleware imports missing
        return

    if getattr(FastAPI, "_middleware_priority_patched", False):
        return

    priority_map = {
        CorrelationIDMiddleware: 70000,
        MetricsMiddleware: 60000,
        RequestLoggingMiddleware: 50000,
        RequestIDMiddleware: 40000,
        SecurityHeadersMiddleware: 30000,
        RequestSizeLimitMiddleware: 20000,
        RateLimitMiddleware: 10000,
    }

    ordinal_hints = {
        "first": 3,
        "second": 2,
        "third": 1,
        "outer": 3,
        "middle": 2,
        "inner": 1,
    }

    def add_middleware(
        self: FastAPI, middleware_class: type[Any], *args: Any, **kwargs: Any,
    ) -> None:
        if self.middleware_stack is not None:
            msg = "Cannot add middleware after an application has started"
            raise RuntimeError(msg)

        validator = getattr(middleware_class, "__validate_middleware__", None)
        if callable(validator):
            validator(*args, **kwargs)

        middleware = Middleware(middleware_class, *args, **kwargs)  # type: ignore[arg-type]
        sequence = getattr(self, "_middleware_sequence", 0) + 1
        self._middleware_sequence = sequence  # type: ignore[attr-defined]  # Dynamic attribute for ordering
        middleware._sequence = sequence  # type: ignore[attr-defined]  # Dynamic attribute for ordering
        # Default FastAPI behavior: last added runs first
        self.user_middleware.insert(0, middleware)

        known = [
            m for m in self.user_middleware if getattr(m, "cls", None) in priority_map
        ]
        unknown = [
            m
            for m in self.user_middleware
            if getattr(m, "cls", None) not in priority_map
        ]

        def _get_priority(m: Any) -> int:
            cls = getattr(m, "cls", None)
            if cls is not None and cls in priority_map:
                return priority_map[cls]
            return 0

        known.sort(key=_get_priority, reverse=True)

        def _unknown_key(item: Middleware) -> tuple[int, int]:
            name = item.kwargs.get("name")
            priority_hint = 0
            if isinstance(name, str):
                match = re.match(r"^(\d+)", name)
                if match:
                    priority_hint = int(match.group(1))
                else:
                    token = name.split("_", 1)[0].lower()
                    priority_hint = ordinal_hints.get(token, 0)
            return priority_hint, getattr(item, "_sequence", 0)

        unknown.sort(key=_unknown_key, reverse=True)

        self.user_middleware[:] = known + unknown

    FastAPI.add_middleware = add_middleware  # type: ignore[assignment,method-assign]
    FastAPI._middleware_priority_patched = True  # type: ignore[attr-defined]


_patch_fastapi_middleware_ordering()
