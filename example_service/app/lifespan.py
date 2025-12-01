"""Application lifespan management."""

from __future__ import annotations

import inspect
import logging
from contextlib import asynccontextmanager
from importlib import import_module
from typing import TYPE_CHECKING

from example_service.core.settings import (
    get_app_settings,
    get_auth_settings,
    get_consul_settings,
    get_db_settings,
    get_logging_settings,
    get_otel_settings,
    get_rabbit_settings,
    get_redis_settings,
    get_storage_settings,
    get_task_settings,
    get_websocket_settings,
)
from example_service.infra.cache.redis import start_cache, stop_cache
from example_service.infra.database.session import close_database, init_database
from example_service.infra.discovery import start_discovery, stop_discovery
from example_service.infra.events.outbox.processor import (
    start_outbox_processor,
    stop_outbox_processor,
)
from example_service.infra.logging.config import setup_logging
from example_service.infra.messaging.broker import start_broker, stop_broker
from example_service.infra.metrics.prometheus import (
    application_info,
    database_pool_max_overflow,
    database_pool_size,
)
from example_service.infra.realtime import (
    start_connection_manager,
    start_event_bridge,
    stop_connection_manager,
    stop_event_bridge,
)
from example_service.infra.tracing.opentelemetry import setup_tracing
from example_service.tasks.tracking import start_tracker, stop_tracker

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from types import ModuleType

    from fastapi import FastAPI

    from example_service.core.settings.rabbit import RabbitSettings
    from example_service.core.settings.redis import RedisSettings

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


async def _initialize_taskiq_and_scheduler(
    rabbit_settings: RabbitSettings, redis_settings: RedisSettings
) -> tuple[ModuleType | None, ModuleType | None]:
    """Initialize Taskiq broker and APScheduler for background tasks.

    Args:
        rabbit_settings: RabbitMQ settings object with is_configured attribute.
        redis_settings: Redis settings object with is_configured attribute.

    Returns:
        Tuple of (taskiq_module, scheduler_module), either may be None.
    """
    # Early return if dependencies not configured
    if not (rabbit_settings.is_configured and redis_settings.is_configured):
        return None, None

    # Load and start Taskiq broker
    taskiq_module = _load_taskiq_module()
    if taskiq_module is None:
        return None, None

    await taskiq_module.start_taskiq()
    if taskiq_module.broker is None:
        logger.warning("Taskiq broker unavailable, skipping task registration")
        return taskiq_module, None

    # Import tasks to register them with the broker
    import example_service.tasks.scheduler  # noqa: F401
    import example_service.tasks.tasks  # noqa: F401

    logger.info("Taskiq broker initialized (use 'taskiq worker' to run tasks)")

    # Initialize APScheduler (depends on Taskiq)
    scheduler_module = _load_scheduler_module()
    if scheduler_module is None:
        logger.warning("APScheduler unavailable, skipping scheduler startup")
        return taskiq_module, None

    scheduler_module.setup_scheduled_jobs()
    await scheduler_module.start_scheduler()
    logger.info("APScheduler started with scheduled jobs")

    return taskiq_module, scheduler_module


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
    _ = app  # Reserved for future FastAPI state hooks
    # Load settings (cached after first call)
    app_settings = get_app_settings()
    auth_settings = get_auth_settings()
    consul_settings = get_consul_settings()
    db_settings = get_db_settings()
    redis_settings = get_redis_settings()
    storage_settings = get_storage_settings()
    rabbit_settings = get_rabbit_settings()
    otel_settings = get_otel_settings()
    log_settings = get_logging_settings()
    taskiq_module: ModuleType | None = None
    scheduler_module: ModuleType | None = None

    # Startup - Configure logging with settings
    setup_logging(log_settings=log_settings, force=True)
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

    # Initialize Consul service discovery (optional, never blocks startup)
    if consul_settings.is_configured:
        discovery_started = await start_discovery()
        if discovery_started:
            logger.info(
                "Consul service discovery started",
                extra={"consul_url": consul_settings.base_url},
            )
        else:
            logger.warning(
                "Consul service discovery failed to start, continuing without it",
                extra={"consul_url": consul_settings.base_url},
            )

    # Initialize database connection with retry
    if db_settings.is_configured:
        try:
            await init_database()
            logger.info("Database connection initialized")

            # Set database pool configuration gauges for monitoring
            # These are static values set once at startup
            database_pool_size.set(db_settings.pool_size)
            database_pool_max_overflow.set(db_settings.max_overflow)
            logger.debug(
                "Database pool metrics initialized",
                extra={
                    "pool_size": db_settings.pool_size,
                    "max_overflow": db_settings.max_overflow,
                    "pool_timeout": db_settings.pool_timeout,
                    "pool_recycle": db_settings.pool_recycle,
                },
            )
        except Exception as e:
            if db_settings.startup_require_db:
                logger.error(
                    "Database required but unavailable, failing startup",
                    extra={"error": str(e), "startup_require_db": True},
                )
                raise
            else:
                logger.warning(
                    "Database unavailable, continuing in degraded mode",
                    extra={"error": str(e), "startup_require_db": False},
                )

    # Initialize Redis cache
    if redis_settings.is_configured:
        try:
            await start_cache()
            logger.info("Redis cache initialized")

            # Initialize rate limit state tracker for protection observability
            try:
                from example_service.infra.ratelimit import (
                    RateLimitStateTracker,
                    set_rate_limit_tracker,
                )

                rate_limit_tracker = RateLimitStateTracker(
                    failure_threshold=redis_settings.rate_limit_failure_threshold,
                )
                set_rate_limit_tracker(rate_limit_tracker)
                logger.info(
                    "Rate limit state tracker initialized",
                    extra={"failure_threshold": redis_settings.rate_limit_failure_threshold},
                )

                # Register rate limiter health provider with aggregator
                from example_service.features.health.rate_limit_provider import (
                    RateLimiterHealthProvider,
                )
                from example_service.features.health.service import get_health_aggregator

                aggregator = get_health_aggregator()
                if aggregator:
                    aggregator.add_provider(RateLimiterHealthProvider(rate_limit_tracker))
                    logger.info("Rate limiter health provider registered")

                # Register Accent-Auth health provider (optional, never blocks startup)
                if auth_settings.health_checks_enabled and auth_settings.service_url:
                    try:
                        from example_service.features.health.accent_auth_provider import (
                            AccentAuthHealthProvider,
                        )

                        aggregator = get_health_aggregator()
                        if aggregator:
                            aggregator.add_provider(AccentAuthHealthProvider())
                            logger.info(
                                "Accent-Auth health provider registered",
                                extra={"auth_url": str(auth_settings.service_url)},
                            )
                    except Exception as e:
                        logger.warning(
                            "Failed to register Accent-Auth health provider",
                            extra={"error": str(e)},
                        )
            except Exception as e:
                logger.warning(
                    "Failed to initialize rate limit state tracker",
                    extra={"error": str(e)},
                )
        except Exception as e:
            if redis_settings.startup_require_cache:
                logger.error(
                    "Redis cache required but unavailable, failing startup",
                    extra={"error": str(e), "startup_require_cache": True},
                )
                raise
            else:
                logger.warning(
                    "Redis cache unavailable, continuing in degraded mode",
                    extra={"error": str(e), "startup_require_cache": False},
                )
                # Mark rate limiter as disabled when Redis is unavailable
                try:
                    from example_service.infra.ratelimit import (
                        RateLimitStateTracker,
                        set_rate_limit_tracker,
                    )

                    tracker = RateLimitStateTracker()
                    tracker.mark_disabled()
                    set_rate_limit_tracker(tracker)
                except Exception:
                    pass

    # Initialize storage service
    if storage_settings.is_configured:
        try:
            from example_service.infra.storage import get_storage_service

            storage_service = get_storage_service()
            await storage_service.startup()
            logger.info(
                "Storage service initialized",
                extra={
                    "bucket": storage_settings.bucket,
                    "endpoint": storage_settings.endpoint,
                    "health_checks_enabled": storage_settings.health_check_enabled,
                },
            )
        except Exception as e:
            if storage_settings.startup_require_storage:
                logger.error(
                    "Storage service required but unavailable, failing startup",
                    extra={"error": str(e)},
                )
                raise
            else:
                logger.warning(
                    "Storage service unavailable, continuing in degraded mode",
                    extra={"error": str(e)},
                )

    # Initialize task execution tracker (for querying task history via REST API)
    # Supports both Redis and PostgreSQL backends based on TASK_RESULT_BACKEND setting
    task_settings = get_task_settings()
    tracker_started = False
    if task_settings.tracking_enabled:
        # Check if the required backend is configured
        can_start_tracker = (task_settings.is_redis_backend and redis_settings.is_configured) or (
            task_settings.is_postgres_backend and db_settings.is_configured
        )
        if can_start_tracker:
            try:
                await start_tracker()
                tracker_started = True
                logger.info(
                    "Task execution tracker initialized",
                    extra={"backend": task_settings.result_backend},
                )

                # Register task tracker health provider
                try:
                    from example_service.features.health.service import get_health_aggregator
                    from example_service.features.health.task_tracker_provider import (
                        TaskTrackerHealthProvider,
                    )

                    aggregator = get_health_aggregator()
                    if aggregator:
                        aggregator.add_provider(TaskTrackerHealthProvider())
                        logger.info("Task tracker health provider registered")
                except Exception as health_err:
                    logger.warning(
                        "Failed to register task tracker health provider",
                        extra={"error": str(health_err)},
                    )
            except Exception as e:
                logger.warning(
                    "Failed to start task execution tracker",
                    extra={"error": str(e), "backend": task_settings.result_backend},
                )
        else:
            logger.warning(
                "Task tracking enabled but required backend not configured",
                extra={
                    "backend": task_settings.result_backend,
                    "redis_configured": redis_settings.is_configured,
                    "db_configured": db_settings.is_configured,
                },
            )

    # Initialize RabbitMQ/FastStream broker for event-driven messaging
    if rabbit_settings.is_configured:
        await start_broker()
        logger.info("RabbitMQ/FastStream broker initialized")

    # Initialize outbox processor for reliable event publishing
    # Requires both database and RabbitMQ to be available
    if db_settings.is_configured and rabbit_settings.is_configured:
        try:
            await start_outbox_processor()
            logger.info("Event outbox processor started")
        except Exception as e:
            logger.warning(
                "Failed to start outbox processor, events will not be published",
                extra={"error": str(e)},
            )

    # Initialize WebSocket connection manager (requires Redis for horizontal scaling)
    ws_settings = get_websocket_settings()
    websocket_enabled = False
    if ws_settings.enabled:
        try:
            await start_connection_manager()
            websocket_enabled = True
            logger.info("WebSocket connection manager initialized")

            # Start event bridge (requires RabbitMQ)
            if rabbit_settings.is_configured and ws_settings.event_bridge_enabled:
                bridge_started = await start_event_bridge()
                if bridge_started:
                    logger.info("WebSocket event bridge started")
        except Exception as e:
            logger.warning(
                "Failed to start WebSocket manager, realtime features disabled",
                extra={"error": str(e)},
            )

    # Initialize Taskiq broker for background tasks (independent of FastStream)
    # Taskiq uses its own RabbitMQ connection via taskiq-aio-pika
    initialization_result = _initialize_taskiq_and_scheduler(rabbit_settings, redis_settings)
    if inspect.isawaitable(initialization_result):
        initialization = await initialization_result
    else:
        initialization = initialization_result
    if initialization is None:
        initialization = (None, None)
    taskiq_module, scheduler_module = initialization

    logger.info(
        "Application startup complete - listening on %s:%s",
        app_settings.host,
        app_settings.port,
        extra={
            "service": app_settings.service_name,
            "environment": app_settings.environment,
            "tracing_enabled": otel_settings.is_configured,
            "service_discovery_enabled": consul_settings.is_configured,
            "database_enabled": db_settings.is_configured,
            "cache_enabled": redis_settings.is_configured,
            "messaging_enabled": rabbit_settings.is_configured,
            "outbox_enabled": db_settings.is_configured and rabbit_settings.is_configured,
            "websocket_enabled": websocket_enabled,
            "task_tracking_enabled": tracker_started,
            "task_tracking_backend": task_settings.result_backend if tracker_started else None,
            "host": app_settings.host,
            "port": app_settings.port,
        },
    )

    # Log that application is live and ready to serve requests
    logger.info(
        "Application is LIVE and ready to serve requests on http://%s:%s",
        app_settings.host,
        app_settings.port,
        extra={
            "service": app_settings.service_name,
            "host": app_settings.host,
            "port": app_settings.port,
            "environment": app_settings.environment,
            "version": app_settings.version,
        },
    )

    # In debug mode, log important configuration settings
    if app_settings.debug:
        logger.debug(
            "Debug mode: Application configuration",
            extra={
                "service": app_settings.service_name,
                "environment": app_settings.environment,
                "version": app_settings.version,
                "host": app_settings.host,
                "port": app_settings.port,
                "api_prefix": app_settings.api_prefix,
                "docs_enabled": app_settings.docs_enabled,
                "docs_url": app_settings.get_docs_url(),
                "redoc_url": app_settings.get_redoc_url(),
                "openapi_url": app_settings.get_openapi_url(),
                "root_path": app_settings.root_path,
                "debug": app_settings.debug,
                "tracing_enabled": otel_settings.is_configured,
                "database_enabled": db_settings.is_configured,
                "cache_enabled": redis_settings.is_configured,
                "messaging_enabled": rabbit_settings.is_configured,
                "storage_enabled": storage_settings.is_configured,
                "websocket_enabled": websocket_enabled,
                "service_discovery_enabled": consul_settings.is_configured,
                "rate_limiting_enabled": app_settings.enable_rate_limiting,
                "request_size_limit": app_settings.request_size_limit,
                "enable_debug_middleware": app_settings.enable_debug_middleware,
                "strict_csp": app_settings.strict_csp,
            },
        )

    yield

    # Shutdown
    # Note: Settings are still available from startup phase (cached and frozen)
    logger.info("Application shutting down", extra={"service": app_settings.service_name})

    # Stop Consul service discovery first (deregister before dependencies close)
    if consul_settings.is_configured:
        await stop_discovery()
        logger.info("Consul service discovery stopped")

    # Stop APScheduler first (depends on Taskiq for task execution)
    if scheduler_module is not None:
        await scheduler_module.stop_scheduler()
        logger.info("APScheduler stopped")

    # Close Taskiq broker (depends on RabbitMQ and Redis)
    if rabbit_settings.is_configured and redis_settings.is_configured and taskiq_module:
        await taskiq_module.stop_taskiq()
        logger.info("Taskiq broker closed")

    # Stop WebSocket event bridge and connection manager (before RabbitMQ/Redis)
    if ws_settings.enabled and websocket_enabled:
        await stop_event_bridge()
        logger.info("WebSocket event bridge stopped")
        await stop_connection_manager()
        logger.info("WebSocket connection manager stopped")

    # Stop outbox processor (before closing RabbitMQ broker)
    if db_settings.is_configured and rabbit_settings.is_configured:
        await stop_outbox_processor()
        logger.info("Event outbox processor stopped")

    # Close RabbitMQ broker
    if rabbit_settings.is_configured:
        await stop_broker()
        logger.info("RabbitMQ broker closed")

    # Close task execution tracker (before Redis since Redis tracker depends on Redis)
    if tracker_started:
        await stop_tracker()
        logger.info("Task execution tracker closed")

    # Shutdown storage service
    if storage_settings.is_configured:
        try:
            from example_service.infra.storage import get_storage_service

            storage_service = get_storage_service()
            if storage_service.is_ready:
                await storage_service.shutdown()
                logger.info("Storage service shutdown complete")
        except Exception as e:
            logger.warning(
                "Error during storage service shutdown",
                extra={"error": str(e)},
            )

    # Close Redis cache
    if redis_settings.is_configured:
        await stop_cache()
        logger.info("Redis cache closed")

    # Close database connection
    if db_settings.is_configured:
        await close_database()
        logger.info("Database connection closed")

    logger.info("Application shutdown complete")
