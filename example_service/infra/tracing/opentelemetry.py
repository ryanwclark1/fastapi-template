"""OpenTelemetry tracing configuration and setup.

Provides distributed tracing for the service with automatic instrumentation
for FastAPI, HTTPX, SQLAlchemy, and psycopg.

Traces are exported via OTLP to collectors like Jaeger, Tempo, or Zipkin.
"""
from __future__ import annotations

import logging
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from example_service.core.settings import get_app_settings, get_otel_settings

logger = logging.getLogger(__name__)
otel_settings = get_otel_settings()
app_settings = get_app_settings()


def setup_tracing() -> None:
    """Configure OpenTelemetry tracing for the service.

    Sets up:
    - OTLP exporter to send traces to collector
    - Resource attributes (service name, version)
    - TracerProvider with batch span processor
    - Automatic instrumentation for FastAPI, HTTPX, SQLAlchemy, psycopg

    This should be called once at application startup, before creating
    the FastAPI app.

    Example:
        ```python
        # app/lifespan.py
        from example_service.infra.tracing.opentelemetry import setup_tracing

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            setup_tracing()  # Setup tracing first
            yield
        ```
    """
    if not otel_settings.enabled or not otel_settings.endpoint:
        logger.info("OpenTelemetry tracing is disabled")
        return

    try:
        # Create resource with service information
        resource = Resource(
            attributes={
                SERVICE_NAME: otel_settings.service_name,
                SERVICE_VERSION: otel_settings.service_version,
                "environment": "production" if not app_settings.debug else "development",
            }
        )

        # Configure OTLP exporter
        otlp_exporter = OTLPSpanExporter(
            endpoint=str(otel_settings.endpoint),
            insecure=otel_settings.insecure,
        )

        # Create tracer provider with batch processor
        tracer_provider = TracerProvider(resource=resource)
        tracer_provider.add_span_processor(BatchSpanProcessor(otlp_exporter))

        # Set global tracer provider
        trace.set_tracer_provider(tracer_provider)

        # Setup automatic instrumentation
        _setup_instrumentations()

        logger.info(
            f"OpenTelemetry tracing configured: endpoint={otel_settings.endpoint}",
            extra={"service": otel_settings.service_name, "endpoint": str(otel_settings.endpoint)},
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

    Instruments:
    - HTTPX: Traces all outgoing HTTP requests
    - SQLAlchemy: Traces all database queries
    - psycopg: Traces PostgreSQL operations
    - FastAPI: Automatically done when app is created

    Note: FastAPI instrumentation happens when you call
    instrument_app(app) after creating the FastAPI instance.
    """
    # Instrument HTTPX for external API calls
    HTTPXClientInstrumentor().instrument()
    logger.debug("HTTPX instrumentation enabled")

    # Instrument SQLAlchemy for database queries
    SQLAlchemyInstrumentor().instrument()
    logger.debug("SQLAlchemy instrumentation enabled")

    # Instrument psycopg for PostgreSQL operations
    PsycopgInstrumentor().instrument()
    logger.debug("psycopg instrumentation enabled")


def instrument_app(app: Any) -> None:
    """Instrument FastAPI application for tracing.

    This should be called after creating the FastAPI app but before
    starting the server.

    Args:
        app: FastAPI application instance.

    Example:
        ```python
        # app/main.py
        from example_service.infra.tracing.opentelemetry import instrument_app

        app = create_app()
        instrument_app(app)  # Add tracing to FastAPI
        ```
    """
    if not otel_settings.enabled:
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
        ```python
        from example_service.infra.tracing.opentelemetry import get_tracer

        tracer = get_tracer(__name__)

        async def process_data(data: dict):
            with tracer.start_as_current_span("process_data") as span:
                span.set_attribute("data.size", len(data))
                # Processing logic here
                return result
        ```
    """
    return trace.get_tracer(name)


def add_span_attributes(attributes: dict[str, Any]) -> None:
    """Add attributes to the current span.

    Args:
        attributes: Dictionary of attributes to add to current span.

    Example:
        ```python
        from example_service.infra.tracing.opentelemetry import add_span_attributes

        async def create_user(user_data: dict):
            add_span_attributes({
                "user.email": user_data["email"],
                "user.role": user_data["role"],
            })
            # Create user logic
        ```
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
        ```python
        from example_service.infra.tracing.opentelemetry import add_span_event

        async def send_notification(user_id: str):
            add_span_event("notification.queued", {
                "user_id": user_id,
                "type": "email"
            })
        ```
    """
    span = trace.get_current_span()
    if span.is_recording():
        span.add_event(name, attributes or {})


def record_exception(exception: Exception) -> None:
    """Record an exception in the current span.

    Args:
        exception: Exception to record.

    Example:
        ```python
        from example_service.infra.tracing.opentelemetry import record_exception

        try:
            await risky_operation()
        except Exception as e:
            record_exception(e)
            raise
        ```
    """
    span = trace.get_current_span()
    if span.is_recording():
        span.record_exception(exception)
        span.set_status(trace.Status(trace.StatusCode.ERROR))
