"""Metrics middleware for HTTP request instrumentation with trace correlation."""
from __future__ import annotations

import time
from typing import Callable

from fastapi import Request, Response
from opentelemetry import trace
from starlette.middleware.base import BaseHTTPMiddleware

from example_service.infra.metrics.prometheus import (
    http_request_duration_seconds,
    http_requests_in_progress,
    http_requests_total,
)


class MetricsMiddleware(BaseHTTPMiddleware):
    """Collect HTTP metrics with trace correlation via exemplars.

    This middleware instruments all HTTP requests with Prometheus metrics
    linked to OpenTelemetry traces. Key features:

    - Records request counts, durations, and in-progress requests
    - Links metrics to traces via exemplars (trace IDs)
    - Uses route path templates for low cardinality labels
    - Ensures accurate in-progress gauge tracking with try/finally

    The exemplar pattern enables click-through from Grafana metrics
    to corresponding traces in Tempo for deep debugging.
    """

    async def dispatch(
        self, request: Request, call_next: Callable
    ) -> Response:
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
            return response
        finally:
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
                    method=method, endpoint=endpoint
                ).observe(duration, exemplar={"trace_id": trace_id})

                http_requests_total.labels(
                    method=method, endpoint=endpoint, status=status_code
                ).inc(exemplar={"trace_id": trace_id})
            else:
                # Fallback without exemplar if tracing unavailable
                http_request_duration_seconds.labels(
                    method=method, endpoint=endpoint
                ).observe(duration)

                http_requests_total.labels(
                    method=method, endpoint=endpoint, status=status_code
                ).inc()

            # Decrement in-progress gauge
            http_requests_in_progress.labels(
                method=method, endpoint=endpoint
            ).dec()
