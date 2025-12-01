"""Observable span exporters with Prometheus metrics instrumentation.

This module provides wrapper classes for OpenTelemetry span exporters that
add comprehensive metrics for monitoring export health and performance.

The ObservableSpanExporter wraps any SpanExporter and tracks:
- Spans exported (success/failure counts)
- Export duration (latency histogram)
- Batch sizes
- Exporter state (healthy/degraded/failing)
- Last successful export timestamp

Example:
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from example_service.infra.tracing.exporters import ObservableSpanExporter

    # Wrap the OTLP exporter
    base_exporter = OTLPSpanExporter(endpoint="http://tempo:4317")
    observable_exporter = ObservableSpanExporter(base_exporter, exporter_type="otlp")
"""

from __future__ import annotations

import logging
import time
from collections import deque
from enum import IntEnum
from typing import TYPE_CHECKING, Any

from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from example_service.infra.metrics.prometheus import (
    otel_export_batch_size,
    otel_export_duration_seconds,
    otel_export_retries_total,
    otel_exporter_state,
    otel_last_successful_export_timestamp,
    otel_spans_dropped_total,
    otel_spans_exported_total,
    otel_spans_failed_total,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from opentelemetry.sdk.trace import ReadableSpan

logger = logging.getLogger(__name__)


class ExporterState(IntEnum):
    """State values for the otel_exporter_state gauge."""

    UNKNOWN = 0
    HEALTHY = 1
    DEGRADED = 2
    FAILING = 3


class ObservableSpanExporter(SpanExporter):
    """Span exporter wrapper that adds Prometheus metrics instrumentation.

    This wrapper intercepts all export calls and records:
    - Success/failure counts
    - Export latency
    - Batch sizes
    - Exporter health state based on rolling success rate

    The wrapper maintains a rolling window of recent export results to
    calculate the exporter state:
    - HEALTHY: ≥95% success rate
    - DEGRADED: 50-95% success rate
    - FAILING: <50% success rate

    Attributes:
        exporter: The wrapped SpanExporter instance.
        exporter_type: Label value for metrics (e.g., "otlp", "jaeger").
        state_window_size: Number of recent exports to track for state calculation.
    """

    def __init__(
        self,
        exporter: SpanExporter,
        exporter_type: str = "otlp",
        state_window_size: int = 100,
    ) -> None:
        """Initialize the observable exporter wrapper.

        Args:
            exporter: The underlying SpanExporter to wrap.
            exporter_type: Label value for Prometheus metrics.
            state_window_size: Number of recent export results to track
                for calculating exporter state (default: 100).
        """
        self._exporter = exporter
        self._exporter_type = exporter_type
        self._state_window_size = state_window_size

        # Rolling window of export results (True=success, False=failure)
        self._recent_results: deque[bool] = deque(maxlen=state_window_size)

        # Initialize state gauge
        otel_exporter_state.labels(exporter_type=self._exporter_type).set(ExporterState.UNKNOWN)

        logger.debug(
            "ObservableSpanExporter initialized",
            extra={"exporter_type": exporter_type, "state_window_size": state_window_size},
        )

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Export spans with metrics instrumentation.

        Records:
        - Batch size
        - Export duration
        - Success/failure counts
        - Updates exporter state based on result

        Args:
            spans: Sequence of spans to export.

        Returns:
            SpanExportResult from the underlying exporter.
        """
        batch_size = len(spans)

        # Record batch size
        otel_export_batch_size.labels(exporter_type=self._exporter_type).observe(batch_size)

        # Track export duration
        start_time = time.perf_counter()

        try:
            result = self._exporter.export(spans)
            duration = time.perf_counter() - start_time

            # Record duration
            otel_export_duration_seconds.labels(exporter_type=self._exporter_type).observe(duration)

            # Handle result
            if result == SpanExportResult.SUCCESS:
                self._record_success(batch_size)
            else:
                self._record_failure(batch_size, "export_failed")

            return result

        except Exception as e:
            duration = time.perf_counter() - start_time
            otel_export_duration_seconds.labels(exporter_type=self._exporter_type).observe(duration)

            # Classify error type
            error_type = self._classify_error(e)
            self._record_failure(batch_size, error_type)

            logger.warning(
                f"Span export failed: {e}",
                extra={
                    "exporter_type": self._exporter_type,
                    "error_type": error_type,
                    "batch_size": batch_size,
                    "duration": duration,
                },
            )

            # Re-raise to let BatchSpanProcessor handle retry logic
            raise

    def _record_success(self, span_count: int) -> None:
        """Record a successful export and update state."""
        otel_spans_exported_total.labels(exporter_type=self._exporter_type).inc(span_count)
        otel_last_successful_export_timestamp.labels(exporter_type=self._exporter_type).set(
            time.time()
        )

        self._recent_results.append(True)
        self._update_state()

    def _record_failure(self, span_count: int, error_type: str) -> None:
        """Record a failed export and update state."""
        otel_spans_failed_total.labels(
            exporter_type=self._exporter_type, error_type=error_type
        ).inc(span_count)

        self._recent_results.append(False)
        self._update_state()

    def _update_state(self) -> None:
        """Update exporter state gauge based on recent success rate."""
        if not self._recent_results:
            state = ExporterState.UNKNOWN
        else:
            success_count = sum(1 for r in self._recent_results if r)
            success_rate = success_count / len(self._recent_results)

            if success_rate >= 0.95:
                state = ExporterState.HEALTHY
            elif success_rate >= 0.50:
                state = ExporterState.DEGRADED
            else:
                state = ExporterState.FAILING

        otel_exporter_state.labels(exporter_type=self._exporter_type).set(state)

    def _classify_error(self, error: Exception) -> str:
        """Classify an exception into an error type label.

        Args:
            error: The exception that occurred.

        Returns:
            A string label for the error type.
        """
        error_name = type(error).__name__

        # Map common errors to categories
        if "timeout" in error_name.lower() or "Timeout" in str(error):
            return "timeout"
        elif "connection" in error_name.lower() or "Connection" in str(error):
            return "connection_error"
        elif "unavailable" in str(error).lower():
            return "service_unavailable"
        elif "permission" in str(error).lower() or "auth" in str(error).lower():
            return "auth_error"
        else:
            return "unknown"

    def shutdown(self) -> None:
        """Shutdown the underlying exporter."""
        self._exporter.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Force flush the underlying exporter.

        Args:
            timeout_millis: Timeout in milliseconds.

        Returns:
            True if flush succeeded, False otherwise.
        """
        return self._exporter.force_flush(timeout_millis)

    def record_dropped_spans(self, count: int) -> None:
        """Record spans dropped due to queue overflow.

        Call this from the BatchSpanProcessor's on_end callback when
        spans are dropped due to queue exhaustion.

        Args:
            count: Number of spans dropped.
        """
        otel_spans_dropped_total.labels(exporter_type=self._exporter_type).inc(count)

    def record_retry(self) -> None:
        """Record an export retry attempt.

        Call this when the export is being retried.
        """
        otel_export_retries_total.labels(exporter_type=self._exporter_type).inc()


def create_observable_otlp_exporter(
    exporter_type: str = "otlp",
    state_window_size: int = 100,
    **otlp_kwargs: Any,
) -> ObservableSpanExporter:
    """Create an observable OTLP span exporter.

    Convenience function that creates an OTLPSpanExporter and wraps it
    with ObservableSpanExporter.

    Args:
        exporter_type: Label value for metrics (default: "otlp").
        state_window_size: Number of recent exports to track for state.
        **otlp_kwargs: Arguments passed to OTLPSpanExporter.

    Returns:
        ObservableSpanExporter wrapping an OTLPSpanExporter.

    Example:
        exporter = create_observable_otlp_exporter(
            endpoint="http://tempo:4317",
            insecure=True,
        )
    """
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

    base_exporter = OTLPSpanExporter(**otlp_kwargs)
    return ObservableSpanExporter(
        base_exporter,
        exporter_type=exporter_type,
        state_window_size=state_window_size,
    )
