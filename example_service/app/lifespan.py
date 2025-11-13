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
    """Manage application lifecycle with tenacity-like retry and graceful error handling.

    **Startup Phase**:
    Handles startup events for the application including:
    - Logging configuration
    - OpenTelemetry tracing setup
    - Database connections (with exponential backoff retry - FAIL-FAST if critical)
    - Cache connections (with error handling - CONTINUE if optional)
    - Message broker connections (with error handling - CONTINUE if optional)

    **Retry Strategy**:
    - Database initialization uses @retry decorator: 5 attempts, 1-30s delays with jitter
    - Ensures database availability before accepting HTTP requests
    - Prevents cascading failures in containerized environments

    **Shutdown Phase**:
    Gracefully closes all connections with error handling to ensure
    clean shutdown even if individual components fail to close properly.

    Args:
        app: FastAPI application instance.

    Yields:
        None during application runtime.

    Raises:
        Exception: Re-raises database initialization failures (fail-fast pattern).
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

    # Initialize database connection with exponential backoff retry
    # Uses @retry decorator: 5 attempts, 1s-30s delays with jitter
    # Ensures database is available before accepting requests (fail-fast)
    if db_settings.is_configured:
        try:
            await init_database()
            logger.info(
                "Database connection initialized successfully",
                extra={
                    "driver": "psycopg",
                    "pool_size": db_settings.pool_size,
                    "max_overflow": db_settings.max_overflow,
                    "pool_pre_ping": db_settings.pool_pre_ping,
                },
            )
        except Exception as e:
            logger.error(
                "Failed to initialize database after all retry attempts",
                extra={"error": str(e), "error_type": type(e).__name__},
            )
            # Re-raise to prevent startup with broken database
            # Application should fail-fast if database is required
            raise

    # Initialize Redis cache with error handling
    if redis_settings.is_configured:
        try:
            await start_cache()
            logger.info(
                "Redis cache initialized successfully",
                extra={"pool_size": redis_settings.pool_size},
            )
        except Exception as e:
            logger.error(
                "Failed to initialize Redis cache",
                extra={"error": str(e), "error_type": type(e).__name__},
            )
            # Cache failure may not be critical - decide based on requirements
            # For now, log and continue (optional component)
            pass

    # Initialize RabbitMQ/FastStream broker with error handling
    if rabbit_settings.is_configured:
        try:
            await start_broker()
            # Import handlers to register subscribers
            import example_service.infra.messaging.handlers  # noqa: F401

            logger.info("RabbitMQ broker initialized successfully")

            # Initialize Taskiq broker for background tasks (uses same RabbitMQ)
            await start_taskiq()
            # Import tasks to register them
            import example_service.infra.tasks.tasks  # noqa: F401

            logger.info("Taskiq broker initialized successfully")
        except Exception as e:
            logger.error(
                "Failed to initialize RabbitMQ/Taskiq broker",
                extra={"error": str(e), "error_type": type(e).__name__},
            )
            # Message broker failure may not be critical - decide based on requirements
            # For now, log and continue (optional component)
            pass

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

    # Graceful shutdown with error handling for each component
    # Close Taskiq broker first (depends on RabbitMQ)
    if rabbit_settings.is_configured:
        try:
            await stop_taskiq()
            logger.info("Taskiq broker closed successfully")
        except Exception as e:
            logger.error(
                "Error closing Taskiq broker",
                extra={"error": str(e), "error_type": type(e).__name__},
            )

    # Close RabbitMQ broker
    if rabbit_settings.is_configured:
        try:
            await stop_broker()
            logger.info("RabbitMQ broker closed successfully")
        except Exception as e:
            logger.error(
                "Error closing RabbitMQ broker",
                extra={"error": str(e), "error_type": type(e).__name__},
            )

    # Close Redis cache
    if redis_settings.is_configured:
        try:
            await stop_cache()
            logger.info("Redis cache closed successfully")
        except Exception as e:
            logger.error(
                "Error closing Redis cache",
                extra={"error": str(e), "error_type": type(e).__name__},
            )

    # Close database connection (SQLAlchemy engine dispose)
    if db_settings.is_configured:
        try:
            await close_database()
            logger.info("Database connection closed successfully")
        except Exception as e:
            logger.error(
                "Error closing database connection",
                extra={"error": str(e), "error_type": type(e).__name__},
            )

    logger.info(
        "Application shutdown complete",
        extra={"service": app_settings.service_name},
    )
