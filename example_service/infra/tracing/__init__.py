"""OpenTelemetry tracing infrastructure.

This package provides distributed tracing setup and utilities:
- setup_tracing(): Initialize OpenTelemetry tracing at startup
- instrument_app(): Add tracing to FastAPI applications
- get_tracer(): Get a tracer for creating custom spans
- add_span_attributes(): Add attributes to current span
- add_span_event(): Add events to current span
- record_exception(): Record exceptions in current span
- ObservableSpanExporter: Span exporter with Prometheus metrics
"""

from example_service.infra.tracing.exporters import (
    ExporterState,
    ObservableSpanExporter,
    create_observable_otlp_exporter,
)
from example_service.infra.tracing.opentelemetry import (
    add_span_attributes,
    add_span_event,
    get_tracer,
    instrument_app,
    record_exception,
    setup_tracing,
)

__all__ = [
    "ExporterState",
    # Observable exporters
    "ObservableSpanExporter",
    # Span utilities
    "add_span_attributes",
    "add_span_event",
    "create_observable_otlp_exporter",
    "get_tracer",
    "instrument_app",
    "record_exception",
    # Core setup
    "setup_tracing",
]
