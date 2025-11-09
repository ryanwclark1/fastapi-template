"""Application lifespan management."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from example_service.core.settings import settings
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
    # Startup
    configure_logging()
    logger.info("Application starting", extra={"service": settings.service_name})

    # Setup OpenTelemetry tracing (must be done early)
    if settings.enable_tracing:
        setup_tracing()
        logger.info("OpenTelemetry tracing enabled")

    # Initialize database connection with retry
    if settings.database_url:
        await init_database()
        logger.info("Database connection initialized")

    # Initialize Redis cache
    if settings.redis_url:
        await start_cache()
        logger.info("Redis cache initialized")

    # Initialize RabbitMQ/FastStream broker
    if settings.rabbitmq_url:
        await start_broker()
        # Import handlers to register subscribers
        import example_service.infra.messaging.handlers  # noqa: F401

        logger.info("RabbitMQ broker initialized")

    # Initialize Taskiq broker for background tasks
    if settings.taskiq_broker_url:
        await start_taskiq()
        # Import tasks to register them
        import example_service.infra.tasks.tasks  # noqa: F401

        logger.info("Taskiq broker initialized")

    logger.info(
        "Application startup complete",
        extra={
            "service": settings.service_name,
            "tracing_enabled": settings.enable_tracing,
            "metrics_enabled": settings.enable_metrics,
        },
    )

    yield

    # Shutdown
    logger.info("Application shutting down", extra={"service": settings.service_name})

    # Close database connection
    if settings.database_url:
        await close_database()
        logger.info("Database connection closed")

    # Close Redis cache
    if settings.redis_url:
        await stop_cache()
        logger.info("Redis cache closed")

    # Close RabbitMQ broker
    if settings.rabbitmq_url:
        await stop_broker()
        logger.info("RabbitMQ broker closed")

    # Close Taskiq broker
    if settings.taskiq_broker_url:
        await stop_taskiq()
        logger.info("Taskiq broker closed")

    logger.info("Application shutdown complete")
