"""Core lifespan services: logging, metrics, and OpenTelemetry.

These services run first and have no dependencies.
"""

from __future__ import annotations

import logging

from example_service.infra.logging.config import setup_logging
from example_service.infra.metrics.prometheus import application_info
from example_service.infra.tracing.opentelemetry import setup_tracing

from .registry import lifespan_registry

logger = logging.getLogger(__name__)


@lifespan_registry.register(
    name="core",
    startup_order=1,
)
async def startup_core(
    app_settings: object,
    log_settings: object,
    otel_settings: object,
    **kwargs: object,
) -> None:
    """Initialize core services: logging, metrics, and OpenTelemetry.

    Args:
        app_settings: Application settings
        log_settings: Logging settings
        otel_settings: OpenTelemetry settings
        **kwargs: Additional settings (ignored)
    """
    from example_service.core.settings import AppSettings, LoggingSettings, OTELSettings

    app = (
        AppSettings.model_validate(app_settings)
        if not isinstance(app_settings, AppSettings)
        else app_settings
    )
    log = (
        LoggingSettings.model_validate(log_settings)
        if not isinstance(log_settings, LoggingSettings)
        else log_settings
    )
    otel = (
        OTELSettings.model_validate(otel_settings)
        if not isinstance(otel_settings, OTELSettings)
        else otel_settings
    )

    # Configure logging with settings
    setup_logging(log_settings=log, force=True)
    logger.info(
        "Application starting",
        extra={
            "service": app.service_name,
            "environment": app.environment,
        },
    )

    # Setup OpenTelemetry tracing (must be done early)
    if otel.is_configured:
        setup_tracing()
        logger.info(
            "OpenTelemetry tracing enabled",
            extra={"endpoint": otel.endpoint},
        )

    # Set application info metric for Prometheus
    application_info.labels(
        version=app.version,
        service=app.service_name,
        environment=app.environment,
    ).set(1)
    logger.info(
        "Application metrics initialized",
        extra={"metrics_endpoint": "/metrics"},
    )


@lifespan_registry.register(name="core")
async def shutdown_core(**kwargs: object) -> None:
    """Shutdown core services.

    Args:
        **kwargs: Settings (no cleanup needed for core services)
    """
    logger.debug("Core services shutdown (no cleanup needed)")
