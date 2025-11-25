"""Application lifespan management."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib import import_module
from types import ModuleType

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
from example_service.infra.metrics.prometheus import application_info
from example_service.infra.tracing.opentelemetry import setup_tracing

logger = logging.getLogger(__name__)


def _load_taskiq_module() -> ModuleType | None:
    """Import Taskiq broker module lazily to avoid partial initialization."""
    try:
        return import_module("example_service.tasks.broker")
    except ImportError:
        logger.warning("Taskiq optional dependencies missing, skipping Taskiq startup")
        return None


def _load_scheduler_module() -> ModuleType | None:
    """Import APScheduler scheduler module lazily."""
    try:
        return import_module("example_service.tasks.scheduler")
    except ImportError:
        logger.warning("APScheduler dependencies missing, skipping scheduler startup")
        return None


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
    taskiq_module: ModuleType | None = None
    scheduler_module: ModuleType | None = None

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

    # Set application info metric for Prometheus
    application_info.labels(
        version=app_settings.version,
        service=app_settings.service_name,
        environment=app_settings.environment,
    ).set(1)
    logger.info(
        "Application metrics initialized",
        extra={"metrics_endpoint": "/metrics"},
    )

    # Initialize database connection with retry
    if db_settings.is_configured:
        await init_database()
        logger.info("Database connection initialized")

    # Initialize Redis cache
    if redis_settings.is_configured:
        await start_cache()
        logger.info("Redis cache initialized")

    # Initialize RabbitMQ/FastStream broker for event-driven messaging
    if rabbit_settings.is_configured:
        await start_broker()
        logger.info("RabbitMQ/FastStream broker initialized")

    # Initialize Taskiq broker for background tasks (independent of FastStream)
    # Taskiq uses its own RabbitMQ connection via taskiq-aio-pika
    if rabbit_settings.is_configured and redis_settings.is_configured:
        taskiq_module = _load_taskiq_module()
        if taskiq_module is not None:
            await taskiq_module.start_taskiq()
            if taskiq_module.broker is not None:
                # Import tasks to register them with the broker
                import example_service.tasks.scheduler  # noqa: F401
                import example_service.tasks.tasks  # noqa: F401

                logger.info("Taskiq broker initialized (use 'taskiq worker' to run tasks)")

                # Initialize APScheduler for periodic tasks
                scheduler_module = _load_scheduler_module()
                if scheduler_module is not None:
                    scheduler_module.setup_scheduled_jobs()
                    await scheduler_module.start_scheduler()
                    logger.info("APScheduler started with scheduled jobs")
                else:
                    logger.warning("APScheduler unavailable, skipping scheduler startup")
            else:
                logger.warning("Taskiq broker unavailable, skipping task registration")
        else:
            logger.warning("Taskiq module unavailable, skipping Taskiq startup")

    logger.info(
        "Application startup complete - listening on %s:%s",
        app_settings.host,
        app_settings.port,
        extra={
            "service": app_settings.service_name,
            "environment": app_settings.environment,
            "tracing_enabled": otel_settings.is_configured,
            "database_enabled": db_settings.is_configured,
            "cache_enabled": redis_settings.is_configured,
            "messaging_enabled": rabbit_settings.is_configured,
            "host": app_settings.host,
            "port": app_settings.port,
        },
    )

    yield

    # Shutdown
    # Note: Settings are still available from startup phase (cached and frozen)
    logger.info(
        "Application shutting down", extra={"service": app_settings.service_name}
    )

    # Stop APScheduler first (depends on Taskiq for task execution)
    if scheduler_module is not None:
        await scheduler_module.stop_scheduler()
        logger.info("APScheduler stopped")

    # Close Taskiq broker (depends on RabbitMQ and Redis)
    if rabbit_settings.is_configured and redis_settings.is_configured and taskiq_module:
        await taskiq_module.stop_taskiq()
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
