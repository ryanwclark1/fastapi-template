"""Application lifespan management."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from example_service.core.settings import (
    get_app_settings,
    get_db_settings,
    get_otel_settings,
    get_rabbit_settings,
    get_redis_settings,
)
from example_service.infra.cache.redis import start_cache, stop_cache
from example_service.infra.database.session import close_database, init_database
from example_service.infra.logging.config import configure_logging
from example_service.infra.messaging.broker import start_broker, stop_broker
from example_service.infra.tasks.broker import start_taskiq, stop_taskiq
from example_service.infra.tracing.opentelemetry import setup_tracing

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application lifecycle.

    Handles startup and shutdown events for the application including:
    - Logging configuration
    - OpenTelemetry tracing setup
    - Database connections
    - Cache connections
    - Message broker connections

    Args:
        app: FastAPI application instance.

    Yields:
        None during application runtime.
    """
    # Load settings (cached after first call)
    app_settings = get_app_settings()
    db_settings = get_db_settings()
    redis_settings = get_redis_settings()
    rabbit_settings = get_rabbit_settings()
    otel_settings = get_otel_settings()

    # Startup
    configure_logging()
    logger.info(
        "Application starting",
        extra={
            "service": app_settings.service_name,
            "environment": app_settings.environment,
        },
    )

    # Setup OpenTelemetry tracing (must be done early)
    if otel_settings.is_configured:
        setup_tracing()
        logger.info(
            "OpenTelemetry tracing enabled",
            extra={"endpoint": otel_settings.endpoint},
        )

    # Initialize database connection with retry
    if db_settings.is_configured:
        await init_database()
        logger.info("Database connection initialized")

    # Initialize Redis cache
    if redis_settings.is_configured:
        await start_cache()
        logger.info("Redis cache initialized")

    # Initialize RabbitMQ/FastStream broker
    if rabbit_settings.is_configured:
        await start_broker()
        # Import handlers to register subscribers
        import example_service.infra.messaging.handlers  # noqa: F401
        import example_service.infra.messaging.examples.trigger  # noqa: F401

        logger.info("RabbitMQ broker initialized")

        # Initialize Taskiq broker for background tasks (uses same RabbitMQ)
        if redis_settings.is_configured:
            await start_taskiq()
            # Import tasks to register them
            import example_service.infra.tasks.tasks  # noqa: F401
            import example_service.infra.tasks.examples.scheduled_tasks  # noqa: F401
            import example_service.infra.tasks.examples.faststream_integration  # noqa: F401

            logger.info("Taskiq broker initialized")

    logger.info(
        "Application startup complete",
        extra={
            "service": app_settings.service_name,
            "environment": app_settings.environment,
            "tracing_enabled": otel_settings.is_configured,
            "database_enabled": db_settings.is_configured,
            "cache_enabled": redis_settings.is_configured,
            "messaging_enabled": rabbit_settings.is_configured,
        },
    )

    yield

    # Shutdown
    app_settings = get_app_settings()
    db_settings = get_db_settings()
    redis_settings = get_redis_settings()
    rabbit_settings = get_rabbit_settings()

    logger.info(
        "Application shutting down", extra={"service": app_settings.service_name}
    )

    # Close Taskiq broker first (depends on RabbitMQ and Redis)
    if rabbit_settings.is_configured and redis_settings.is_configured:
        await stop_taskiq()
        logger.info("Taskiq broker closed")

    # Close RabbitMQ broker
    if rabbit_settings.is_configured:
        await stop_broker()
        logger.info("RabbitMQ broker closed")

    # Close Redis cache
    if redis_settings.is_configured:
        await stop_cache()
        logger.info("Redis cache closed")

    # Close database connection
    if db_settings.is_configured:
        await close_database()
        logger.info("Database connection closed")

    logger.info("Application shutdown complete")
