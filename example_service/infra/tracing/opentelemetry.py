"""OpenTelemetry tracing configuration and setup.

Provides distributed tracing for the service with automatic instrumentation
for FastAPI, HTTPX, SQLAlchemy, and psycopg.

Traces are exported via OTLP to collectors like Jaeger, Tempo, or Zipkin.
"""

from __future__ import annotations

import logging
from typing import Any

from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from example_service.core.settings import get_app_settings, get_otel_settings
from example_service.infra.tracing.exporters import create_observable_otlp_exporter

logger = logging.getLogger(__name__)
otel_settings = get_otel_settings()
app_settings = get_app_settings()


def setup_tracing() -> None:
    """Configure OpenTelemetry tracing for the service.

    Sets up:
    - OTLP exporter with compression, auth headers, and TLS (from settings)
    - Resource attributes with service info and environment detection
    - TracerProvider with configured sampler
    - Batch span processor with performance-tuned settings
    - Automatic instrumentation (respecting toggle settings)

    Uses helper methods from OtelSettings for all configuration,
    making the setup fully settings-driven.

    This should be called once at application startup, before creating
    the FastAPI app.

    Example:
            # app/lifespan.py
        from example_service.infra.tracing.opentelemetry import setup_tracing

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            setup_tracing()  # Setup tracing first
            yield
    """
    if not otel_settings.enabled or not otel_settings.endpoint:
        logger.info("OpenTelemetry tracing is disabled")
        return

    try:
        # Build resource with automatic detection if enabled
        resource_attrs = otel_settings.resource_attributes()

        if otel_settings.enable_resource_detector:
            # Automatically detect host, process, container, k8s attributes
            from opentelemetry.sdk.resources import get_aggregated_resources

            detected_resource = get_aggregated_resources([])
            resource = detected_resource.merge(Resource(attributes=resource_attrs))
        else:
            resource = Resource(attributes=resource_attrs)

        # Configure OTLP exporter with observability wrapper
        otlp_exporter = create_observable_otlp_exporter(
            exporter_type="otlp",
            **otel_settings.exporter_kwargs(),
        )

        # Get configured sampler
        sampler = otel_settings.get_sampler()

        # Create tracer provider with sampler and resource
        tracer_provider = TracerProvider(
            resource=resource,
            sampler=sampler,
        )

        # Add batch processor with performance-tuned settings
        batch_processor = BatchSpanProcessor(
            otlp_exporter,
            **otel_settings.batch_processor_kwargs(),
        )
        tracer_provider.add_span_processor(batch_processor)

        # Set global tracer provider
        trace.set_tracer_provider(tracer_provider)

        # Setup automatic instrumentation (respects toggle settings)
        _setup_instrumentations()

        logger.info(
            "OpenTelemetry tracing configured",
            extra={
                "service": otel_settings.service_name,
                "endpoint": str(otel_settings.endpoint),
                "compression": otel_settings.compression,
                "sampler": otel_settings.sampler_type,
                "sample_rate": otel_settings.sample_rate,
                "batch_schedule_delay_ms": otel_settings.batch_schedule_delay,
                "batch_max_export_size": otel_settings.batch_max_export_batch_size,
            },
        )

    except Exception as e:
        logger.error(
            f"Failed to setup OpenTelemetry tracing: {e}",
            extra={"exception": str(e)},
        )
        # Don't fail startup if tracing fails
        pass


def _setup_instrumentations() -> None:
    """Setup automatic instrumentation for common libraries.

    Respects otel_settings instrumentation toggles to allow selective
    instrumentation based on configuration.

    Instruments (if enabled in settings):
    - HTTPX: Traces all outgoing HTTP requests
    - SQLAlchemy: Traces all database queries
    - psycopg: Traces PostgreSQL operations
    - FastAPI: Automatically done when app is created

    Note: FastAPI instrumentation happens when you call
    instrument_app(app) after creating the FastAPI instance.
    """
    # Instrument HTTPX for external API calls (if enabled)
    if otel_settings.instrument_httpx:
        try:
            HTTPXClientInstrumentor().instrument()
            logger.debug("HTTPX instrumentation enabled")
        except Exception as e:
            logger.warning(f"Failed to instrument HTTPX: {e}")

    # Instrument SQLAlchemy for database queries (if enabled)
    if otel_settings.instrument_sqlalchemy:
        try:
            SQLAlchemyInstrumentor().instrument()
            logger.debug("SQLAlchemy instrumentation enabled")
        except Exception as e:
            logger.warning(f"Failed to instrument SQLAlchemy: {e}")

    # Instrument psycopg for PostgreSQL operations (if enabled)
    if otel_settings.instrument_psycopg:
        try:
            PsycopgInstrumentor().instrument()
            logger.debug("psycopg instrumentation enabled")
        except Exception as e:
            logger.warning(f"Failed to instrument psycopg: {e}")


def instrument_app(app: Any) -> None:
    """Instrument FastAPI application for tracing.

    Respects otel_settings.instrument_fastapi toggle.

    This should be called after creating the FastAPI app but before
    starting the server.

    Args:
        app: FastAPI application instance.

    Example:
            # app/main.py
        from example_service.infra.tracing.opentelemetry import instrument_app

        app = create_app()
        instrument_app(app)  # Add tracing to FastAPI
    """
    if not otel_settings.enabled or not otel_settings.instrument_fastapi:
        return

    try:
        FastAPIInstrumentor.instrument_app(app)
        logger.debug("FastAPI instrumentation enabled")
    except Exception as e:
        logger.warning(
            f"Failed to instrument FastAPI app: {e}",
            extra={"exception": str(e)},
        )


def get_tracer(name: str) -> trace.Tracer:
    """Get a tracer instance for creating custom spans.

    Args:
        name: Tracer name, typically __name__ of the module.

    Returns:
        Tracer instance for creating spans.

    Example:
            from example_service.infra.tracing.opentelemetry import get_tracer

        tracer = get_tracer(__name__)

        async def process_data(data: dict):
            with tracer.start_as_current_span("process_data") as span:
                span.set_attribute("data.size", len(data))
                # Processing logic here
                return result
    """
    return trace.get_tracer(name)


def add_span_attributes(attributes: dict[str, Any]) -> None:
    """Add attributes to the current span.

    Args:
        attributes: Dictionary of attributes to add to current span.

    Example:
            from example_service.infra.tracing.opentelemetry import add_span_attributes

        async def create_user(user_data: dict):
            add_span_attributes({
                "user.email": user_data["email"],
                "user.role": user_data["role"],
            })
            # Create user logic
    """
    span = trace.get_current_span()
    if span.is_recording():
        for key, value in attributes.items():
            span.set_attribute(key, value)


def add_span_event(name: str, attributes: dict[str, Any] | None = None) -> None:
    """Add an event to the current span.

    Args:
        name: Event name.
        attributes: Optional event attributes.

    Example:
            from example_service.infra.tracing.opentelemetry import add_span_event

        async def send_notification(user_id: str):
            add_span_event("notification.queued", {
                "user_id": user_id,
                "type": "email"
            })
    """
    span = trace.get_current_span()
    if span.is_recording():
        span.add_event(name, attributes or {})


def record_exception(exception: Exception) -> None:
    """Record an exception in the current span.

    Args:
        exception: Exception to record.

    Example:
            from example_service.infra.tracing.opentelemetry import record_exception

        try:
            await risky_operation()
        except Exception as e:
            record_exception(e)
            raise
    """
    span = trace.get_current_span()
    if span.is_recording():
        span.record_exception(exception)
        span.set_status(trace.Status(trace.StatusCode.ERROR))
