"""Application lifespan management.

This module provides a single, well-organized lifespan context manager that
handles startup and shutdown of all application services. Services are
initialized in dependency order and only when configured.

Startup Order:
1. Core (logging, metrics, tracing) - always runs first
2. Service Discovery (Consul) - optional, never blocks
3. Database (PostgreSQL) - conditional on configuration
4. Cache (Redis) - conditional on configuration
5. Storage (S3/MinIO) - conditional on configuration
6. Messaging (RabbitMQ) - conditional on configuration
7. Task Tracking - requires database or cache
8. Outbox Processor - requires database and messaging
9. Background Tasks (Taskiq/APScheduler) - requires messaging and cache
10. WebSocket - requires cache and messaging
11. Health Monitor - runs after dependent services
12. AI Pipeline - optional infrastructure

Shutdown Order: Reverse of startup (what starts first, shuts down last)
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from importlib import import_module
import logging
from typing import TYPE_CHECKING

from example_service.core.settings import (
    get_ai_settings,
    get_app_settings,
    get_auth_settings,
    get_consul_settings,
    get_db_settings,
    get_health_settings,
    get_logging_settings,
    get_otel_settings,
    get_rabbit_settings,
    get_redis_settings,
    get_storage_settings,
    get_task_settings,
    get_websocket_settings,
)
from example_service.infra.discovery import start_discovery, stop_discovery
from example_service.infra.logging.config import setup_logging
from example_service.infra.metrics.prometheus import (
    application_info,
    database_pool_max_overflow,
    database_pool_size,
)
from example_service.infra.tracing.opentelemetry import setup_tracing

# Lazy imports to avoid circular dependencies
# These are imported within functions when needed:
# - example_service.infra.database.session
# - example_service.infra.cache.redis
# - example_service.infra.storage
# - example_service.infra.messaging.broker
# - example_service.infra.tasks.tracking
# - example_service.infra.events.outbox.processor
# - example_service.infra.realtime
# - example_service.infra.ai

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from types import ModuleType

    from fastapi import FastAPI

logger = logging.getLogger(__name__)

# =============================================================================
# Module-level state for service tracking
# =============================================================================

_websocket_enabled = False
_tracker_started = False
_health_monitor_started = False
_ai_infrastructure_started = False
_taskiq_module: ModuleType | None = None
_scheduler_module: ModuleType | None = None


def get_websocket_enabled() -> bool:
    """Check if WebSocket was successfully started."""
    return _websocket_enabled


def get_tracker_started() -> bool:
    """Check if task tracker was successfully started."""
    return _tracker_started


def get_health_monitor_started() -> bool:
    """Check if health monitor was successfully started."""
    return _health_monitor_started


def get_ai_infrastructure_started() -> bool:
    """Check if AI infrastructure was successfully started."""
    return _ai_infrastructure_started


# =============================================================================
# Startup functions - organized by service
# =============================================================================


async def _startup_core() -> None:
    """Initialize core services: logging, metrics, and OpenTelemetry."""
    app = get_app_settings()
    log = get_logging_settings()
    otel = get_otel_settings()

    # Configure logging
    setup_logging(log_settings=log, force=True)
    logger.info(
        "Application starting",
        extra={"service": app.service_name, "environment": app.environment},
    )

    # Setup OpenTelemetry tracing
    if otel.is_configured:
        setup_tracing()
        logger.info("OpenTelemetry tracing enabled", extra={"endpoint": otel.endpoint})

    # Set application info metric
    application_info.labels(
        version=app.version,
        service=app.service_name,
        environment=app.environment,
    ).set(1)
    logger.info("Application metrics initialized", extra={"metrics_endpoint": "/metrics"})


async def _startup_discovery() -> None:
    """Initialize Consul service discovery (optional, never blocks)."""
    settings = get_consul_settings()

    if settings.is_configured:
        discovery_started = await start_discovery()
        if discovery_started:
            logger.info(
                "Consul service discovery started",
                extra={"consul_url": settings.base_url},
            )
        else:
            logger.warning(
                "Consul service discovery failed to start, continuing without it",
                extra={"consul_url": settings.base_url},
            )


async def _startup_database() -> None:
    """Initialize database connection."""
    from example_service.infra.database.session import init_database

    db = get_db_settings()

    if not db.is_configured:
        return

    try:
        await init_database()
        logger.info("Database connection initialized")

        # Set pool metrics
        database_pool_size.set(db.pool_size)
        database_pool_max_overflow.set(db.max_overflow)
        logger.debug(
            "Database pool metrics initialized",
            extra={
                "pool_size": db.pool_size,
                "max_overflow": db.max_overflow,
                "pool_timeout": db.pool_timeout,
                "pool_recycle": db.pool_recycle,
            },
        )
    except Exception as e:
        if db.startup_require_db:
            logger.exception(
                "Database required but unavailable, failing startup",
                extra={"error": str(e), "startup_require_db": True},
            )
            raise
        logger.warning(
            "Database unavailable, continuing in degraded mode",
            extra={"error": str(e), "startup_require_db": False},
        )


def _init_rate_limiter(redis_settings: object, auth_settings: object) -> None:
    """Initialize rate limit tracker and health providers."""
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

    # Register rate limiter health provider
    from example_service.features.health.providers import RateLimiterHealthProvider
    from example_service.features.health.service import get_health_aggregator

    aggregator = get_health_aggregator()
    if aggregator:
        aggregator.add_provider(RateLimiterHealthProvider(rate_limit_tracker))
        logger.info("Rate limiter health provider registered")

    # Register auth health provider (optional)
    if auth_settings.health_checks_enabled and auth_settings.service_url:
        _register_auth_health_provider(aggregator, auth_settings)


def _register_auth_health_provider(aggregator: object, auth_settings: object) -> None:
    """Register Accent-Auth health provider if configured."""
    try:
        from example_service.features.health.providers import AccentAuthHealthProvider

        if aggregator:
            aggregator.add_provider(AccentAuthHealthProvider())
            logger.info(
                "Accent-Auth health provider registered",
                extra={"auth_url": str(auth_settings.service_url)},
            )
    except ImportError:
        logger.debug("AccentAuthHealthProvider not available")


def _mark_rate_limiter_disabled() -> None:
    """Mark rate limiter as disabled when Redis is unavailable."""
    try:
        from example_service.infra.ratelimit import (
            RateLimitStateTracker,
            set_rate_limit_tracker,
        )

        tracker = RateLimitStateTracker()
        tracker.mark_disabled()
        set_rate_limit_tracker(tracker)
    except ImportError:
        logger.debug("Rate limiter module not available")


async def _startup_cache() -> None:
    """Initialize Redis cache and rate limiting."""
    from example_service.infra.cache.redis import start_cache

    redis = get_redis_settings()
    auth = get_auth_settings()

    if not redis.is_configured:
        return

    try:
        await start_cache()
        logger.info("Redis cache initialized")

        # Initialize rate limiter
        try:
            _init_rate_limiter(redis, auth)
        except ImportError as e:
            logger.warning("Rate limiter dependencies not available: %s", e)
    except ConnectionError as e:
        if redis.startup_require_cache:
            logger.exception(
                "Redis cache required but unavailable, failing startup",
                extra={"startup_require_cache": True},
            )
            raise
        logger.warning(
            "Redis cache unavailable, continuing in degraded mode",
            extra={"error": str(e), "startup_require_cache": False},
        )
        _mark_rate_limiter_disabled()
    except OSError as e:
        if redis.startup_require_cache:
            logger.exception(
                "Redis cache required but unavailable, failing startup",
                extra={"startup_require_cache": True},
            )
            raise
        logger.warning(
            "Redis cache unavailable, continuing in degraded mode",
            extra={"error": str(e), "startup_require_cache": False},
        )
        _mark_rate_limiter_disabled()


async def _startup_storage() -> None:
    """Initialize storage service (S3/MinIO)."""
    settings = get_storage_settings()

    if not settings.is_configured:
        return

    try:
        from example_service.infra.storage import get_storage_service

        storage_service = get_storage_service()
        await storage_service.startup()
        logger.info(
            "Storage service initialized",
            extra={
                "bucket": settings.bucket,
                "endpoint": settings.endpoint,
                "health_checks_enabled": settings.health_check_enabled,
            },
        )
    except Exception as e:
        if settings.startup_require_storage:
            logger.exception(
                "Storage service required but unavailable, failing startup",
            )
            raise
        logger.warning(
            "Storage service unavailable, continuing in degraded mode",
            extra={"error": str(e)},
        )


async def _startup_messaging() -> None:
    """Initialize RabbitMQ/FastStream broker."""
    from example_service.infra.messaging.broker import start_broker

    settings = get_rabbit_settings()

    if not settings.is_configured:
        return

    try:
        await start_broker()
        logger.info("RabbitMQ/FastStream broker initialized")
    except Exception as e:
        if settings.startup_require_rabbit:
            logger.exception(
                "RabbitMQ required but unavailable, failing startup",
            )
            raise
        logger.warning(
            "RabbitMQ unavailable, continuing in degraded mode",
            extra={"error": str(e), "startup_require_rabbit": False},
        )


async def _startup_task_tracking() -> None:
    """Initialize task execution tracker."""
    global _tracker_started

    from example_service.infra.tasks.tracking import start_tracker

    task = get_task_settings()
    redis = get_redis_settings()
    db = get_db_settings()

    _tracker_started = False

    if not task.tracking_enabled:
        return

    # Check if required backend is configured
    can_start = (task.is_redis_backend and redis.is_configured) or (
        task.is_postgres_backend and db.is_configured
    )
    if not can_start:
        logger.warning(
            "Task tracking enabled but required backend not configured",
            extra={
                "backend": task.result_backend,
                "redis_configured": redis.is_configured,
                "db_configured": db.is_configured,
            },
        )
        return

    try:
        await start_tracker()
        _tracker_started = True
        logger.info(
            "Task execution tracker initialized",
            extra={"backend": task.result_backend},
        )

        # Register health provider
        try:
            from example_service.features.health.providers import (
                TaskTrackerHealthProvider,
            )
            from example_service.features.health.service import get_health_aggregator

            aggregator = get_health_aggregator()
            if aggregator:
                aggregator.add_provider(TaskTrackerHealthProvider())
                logger.info("Task tracker health provider registered")
        except Exception as e:
            logger.warning(
                "Failed to register task tracker health provider",
                extra={"error": str(e)},
            )
    except Exception as e:
        logger.warning(
            "Failed to start task execution tracker",
            extra={"error": str(e), "backend": task.result_backend},
        )


async def _startup_outbox() -> None:
    """Initialize event outbox processor."""
    from example_service.infra.events.outbox.processor import start_outbox_processor

    db = get_db_settings()
    rabbit = get_rabbit_settings()

    if not (db.is_configured and rabbit.is_configured):
        return

    try:
        await start_outbox_processor()
        logger.info("Event outbox processor started")
    except Exception as e:
        logger.warning(
            "Failed to start outbox processor, events will not be published",
            extra={"error": str(e)},
        )


async def _startup_tasks() -> None:
    """Initialize Taskiq broker and APScheduler."""
    global _taskiq_module, _scheduler_module

    result = await _initialize_taskiq_and_scheduler()
    if result:
        _taskiq_module, _scheduler_module = result


async def _initialize_taskiq_and_scheduler() -> tuple[ModuleType | None, ModuleType | None] | None:
    """Initialize Taskiq broker and APScheduler for background tasks."""
    rabbit = get_rabbit_settings()
    redis = get_redis_settings()

    if not (rabbit.is_configured and redis.is_configured):
        return None

    # Load Taskiq broker
    try:
        taskiq_module = import_module("example_service.infra.tasks.broker")
    except ImportError:
        logger.warning("Taskiq optional dependencies missing, skipping Taskiq startup")
        return None

    await taskiq_module.start_taskiq()
    if taskiq_module.broker is None:
        logger.warning("Taskiq broker unavailable, skipping task registration")
        return taskiq_module, None

    # Register workers
    import example_service.workers.tasks  # noqa: F401

    logger.info("Taskiq broker initialized (use 'taskiq worker' to run tasks)")

    # Load APScheduler
    try:
        scheduler_module = import_module("example_service.infra.tasks.scheduler")
    except ImportError:
        logger.warning("APScheduler dependencies missing, skipping scheduler startup")
        return taskiq_module, None

    scheduler_module.setup_scheduled_jobs()
    await scheduler_module.start_scheduler()
    logger.info("APScheduler started with scheduled jobs")

    return taskiq_module, scheduler_module


async def _startup_websocket() -> None:
    """Initialize WebSocket connection manager and event bridge."""
    global _websocket_enabled

    from example_service.infra.realtime import (
        start_connection_manager,
        start_event_bridge,
    )

    ws = get_websocket_settings()
    rabbit = get_rabbit_settings()

    _websocket_enabled = False

    if not ws.enabled:
        return

    try:
        await start_connection_manager()
        _websocket_enabled = True
        logger.info("WebSocket connection manager initialized")

        # Start event bridge if RabbitMQ is configured
        if rabbit.is_configured and ws.event_bridge_enabled:
            bridge_started = await start_event_bridge()
            if bridge_started:
                logger.info("WebSocket event bridge started")
    except Exception as e:
        logger.warning(
            "Failed to start WebSocket manager, realtime features disabled",
            extra={"error": str(e)},
        )


async def _startup_health_monitor() -> None:
    """Initialize service availability health monitor."""
    global _health_monitor_started

    health = get_health_settings()
    db = get_db_settings()
    redis = get_redis_settings()
    rabbit = get_rabbit_settings()
    storage = get_storage_settings()

    _health_monitor_started = False

    if not health.service_availability_enabled:
        return

    try:
        from example_service.core.services.availability import (
            ServiceName,
            get_service_registry,
        )
        from example_service.core.services.health_monitor import get_health_monitor

        health_monitor = get_health_monitor()

        # Register health checks for configured services
        if db.is_configured:

            async def check_database() -> bool:
                try:
                    from example_service.infra.database.session import get_async_engine

                    engine = get_async_engine()
                    if engine:
                        async with engine.connect() as conn:
                            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
                        return True
                except Exception:
                    pass
                return False

            health_monitor.register_health_check(ServiceName.DATABASE, check_database)

        if redis.is_configured:

            async def check_cache() -> bool:
                try:
                    from example_service.infra.cache.redis import get_redis_client

                    client = await get_redis_client()
                    if client:
                        await client.ping()
                        return True
                except Exception:
                    pass
                return False

            health_monitor.register_health_check(ServiceName.CACHE, check_cache)

        if rabbit.is_configured:

            async def check_broker() -> bool:
                try:
                    from example_service.infra.messaging.broker import broker

                    if broker is not None:
                        return broker._connection is not None
                except Exception:
                    pass
                return False

            health_monitor.register_health_check(ServiceName.BROKER, check_broker)

        if storage.is_configured:

            async def check_storage() -> bool:
                try:
                    from example_service.infra.storage import get_storage_service

                    storage_service = get_storage_service()
                    is_ready = storage_service.is_ready
                except Exception:
                    return False
                else:
                    return is_ready

            health_monitor.register_health_check(ServiceName.STORAGE, check_storage)

        # Start background health monitor
        await health_monitor.start()
        _health_monitor_started = True
        logger.info(
            "Service availability health monitor started",
            extra={
                "check_interval": health.service_check_interval,
                "check_timeout": health.service_check_timeout,
            },
        )

        # Mark services as initially available
        registry = get_service_registry()
        await registry.mark_all_available()

    except Exception as e:
        logger.warning(
            "Failed to start service availability health monitor",
            extra={"error": str(e)},
        )


async def _startup_ai() -> None:
    """Initialize AI pipeline infrastructure."""
    global _ai_infrastructure_started

    settings = get_ai_settings()

    _ai_infrastructure_started = False

    if not settings.enable_pipeline_api:
        return

    try:
        from example_service.infra.ai import start_ai_infrastructure

        _ai_infrastructure_started = await start_ai_infrastructure(settings)
        if _ai_infrastructure_started:
            logger.info(
                "AI pipeline infrastructure started",
                extra={
                    "tracing": settings.enable_pipeline_tracing,
                    "metrics": settings.enable_pipeline_metrics,
                    "budget_enforcement": settings.enable_budget_enforcement,
                },
            )
    except Exception as e:
        logger.warning(
            "Failed to start AI pipeline infrastructure",
            extra={"error": str(e)},
        )


# =============================================================================
# Shutdown functions - organized by service (reverse order of startup)
# =============================================================================


async def _shutdown_ai() -> None:
    """Stop AI pipeline infrastructure."""
    global _ai_infrastructure_started

    if not _ai_infrastructure_started:
        return

    try:
        from example_service.infra.ai import stop_ai_infrastructure

        await stop_ai_infrastructure()
        logger.info("AI pipeline infrastructure stopped")
    except Exception as e:
        logger.warning(
            "Error stopping AI pipeline infrastructure",
            extra={"error": str(e)},
        )


async def _shutdown_health_monitor() -> None:
    """Stop service availability health monitor."""
    global _health_monitor_started

    if not _health_monitor_started:
        return

    try:
        from example_service.core.services.health_monitor import stop_health_monitor

        await stop_health_monitor()
        logger.info("Service availability health monitor stopped")
    except Exception as e:
        logger.warning(
            "Error stopping service availability health monitor",
            extra={"error": str(e)},
        )


async def _shutdown_websocket() -> None:
    """Stop WebSocket connection manager and event bridge."""
    global _websocket_enabled

    from example_service.infra.realtime import (
        stop_connection_manager,
        stop_event_bridge,
    )

    ws = get_websocket_settings()

    if not (ws.enabled and _websocket_enabled):
        return

    await stop_event_bridge()
    logger.info("WebSocket event bridge stopped")
    await stop_connection_manager()
    logger.info("WebSocket connection manager stopped")


async def _shutdown_tasks() -> None:
    """Stop Taskiq broker and APScheduler."""
    global _taskiq_module, _scheduler_module

    rabbit = get_rabbit_settings()
    redis = get_redis_settings()

    # Stop APScheduler first
    if _scheduler_module is not None:
        await _scheduler_module.stop_scheduler()
        logger.info("APScheduler stopped")

    # Stop Taskiq broker
    if rabbit.is_configured and redis.is_configured and _taskiq_module:
        await _taskiq_module.stop_taskiq()
        logger.info("Taskiq broker closed")


async def _shutdown_outbox() -> None:
    """Stop event outbox processor."""
    from example_service.infra.events.outbox.processor import stop_outbox_processor

    db = get_db_settings()
    rabbit = get_rabbit_settings()

    if not (db.is_configured and rabbit.is_configured):
        return

    await stop_outbox_processor()
    logger.info("Event outbox processor stopped")


async def _shutdown_task_tracking() -> None:
    """Stop task execution tracker."""
    global _tracker_started

    from example_service.infra.tasks.tracking import stop_tracker

    if not _tracker_started:
        return

    await stop_tracker()
    logger.info("Task execution tracker closed")


async def _shutdown_messaging() -> None:
    """Close RabbitMQ broker."""
    from example_service.infra.messaging.broker import stop_broker

    settings = get_rabbit_settings()

    if not settings.is_configured:
        return

    await stop_broker()
    logger.info("RabbitMQ broker closed")


async def _shutdown_storage() -> None:
    """Shutdown storage service."""
    settings = get_storage_settings()

    if not settings.is_configured:
        return

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


async def _shutdown_cache() -> None:
    """Close Redis cache."""
    from example_service.infra.cache.redis import stop_cache

    redis = get_redis_settings()

    if not redis.is_configured:
        return

    await stop_cache()
    logger.info("Redis cache closed")


async def _shutdown_database() -> None:
    """Close database connection."""
    from example_service.infra.database.session import close_database

    db = get_db_settings()

    if not db.is_configured:
        return

    await close_database()
    logger.info("Database connection closed")


async def _shutdown_discovery() -> None:
    """Stop Consul service discovery."""
    settings = get_consul_settings()

    if not settings.is_configured:
        return

    await stop_discovery()
    logger.info("Consul service discovery stopped")


async def _shutdown_core() -> None:
    """Shutdown core services (no cleanup needed)."""
    logger.debug("Core services shutdown (no cleanup needed)")


# =============================================================================
# Main lifespan context manager
# =============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application lifecycle.

    Handles startup and shutdown events for the application including:
    - Logging configuration
    - OpenTelemetry tracing setup
    - Database connections
    - Cache connections
    - Message broker connections
    - Background task systems
    - WebSocket connections
    - Health monitoring
    - AI pipeline infrastructure

    Args:
        app: FastAPI application instance.

    Yields:
        None during application runtime.
    """
    _ = app  # Reserved for future FastAPI state hooks

    # =========================================================================
    # STARTUP PHASE - Initialize services in dependency order
    # =========================================================================

    # 1. Core services (logging, metrics, tracing)
    await _startup_core()

    # 2. Service discovery (optional, never blocks)
    await _startup_discovery()

    # 3. Database connection
    await _startup_database()

    # 4. Cache (Redis)
    await _startup_cache()

    # 5. Storage (S3/MinIO)
    await _startup_storage()

    # 6. Messaging (RabbitMQ)
    await _startup_messaging()

    # 7. Task tracking (requires database or cache)
    await _startup_task_tracking()

    # 8. Outbox processor (requires database and messaging)
    await _startup_outbox()

    # 9. Background tasks (Taskiq/APScheduler)
    await _startup_tasks()

    # 10. WebSocket (requires cache and messaging)
    await _startup_websocket()

    # 11. Health monitor (after dependent services)
    await _startup_health_monitor()

    # 12. AI pipeline
    await _startup_ai()

    # =========================================================================
    # Log startup completion
    # =========================================================================

    app_settings = get_app_settings()
    otel_settings = get_otel_settings()
    consul_settings = get_consul_settings()
    db_settings = get_db_settings()
    redis_settings = get_redis_settings()
    rabbit_settings = get_rabbit_settings()
    task_settings = get_task_settings()

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
            "websocket_enabled": _websocket_enabled,
            "task_tracking_enabled": _tracker_started,
            "task_tracking_backend": task_settings.result_backend if _tracker_started else None,
            "service_availability_enabled": _health_monitor_started,
            "host": app_settings.host,
            "port": app_settings.port,
        },
    )

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

    # Debug mode configuration logging
    if app_settings.debug:
        storage_settings = get_storage_settings()
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
                "websocket_enabled": _websocket_enabled,
                "service_discovery_enabled": consul_settings.is_configured,
                "rate_limiting_enabled": app_settings.enable_rate_limiting,
                "request_size_limit": app_settings.request_size_limit,
                "enable_debug_middleware": app_settings.enable_debug_middleware,
                "strict_csp": app_settings.strict_csp,
                "service_availability_enabled": _health_monitor_started,
            },
        )

    # =========================================================================
    # APPLICATION RUNTIME
    # =========================================================================

    yield

    # =========================================================================
    # SHUTDOWN PHASE - Close services in reverse order
    # =========================================================================

    logger.info("Application shutting down", extra={"service": app_settings.service_name})

    # 12. AI pipeline
    await _shutdown_ai()

    # 11. Health monitor
    await _shutdown_health_monitor()

    # 10. WebSocket
    await _shutdown_websocket()

    # 9. Background tasks
    await _shutdown_tasks()

    # 8. Outbox processor
    await _shutdown_outbox()

    # 7. Task tracking
    await _shutdown_task_tracking()

    # 6. Messaging
    await _shutdown_messaging()

    # 5. Storage
    await _shutdown_storage()

    # 4. Cache
    await _shutdown_cache()

    # 3. Database
    await _shutdown_database()

    # 2. Service discovery
    await _shutdown_discovery()

    # 1. Core
    await _shutdown_core()

    logger.info("Application shutdown complete")


__all__ = [
    "get_ai_infrastructure_started",
    "get_health_monitor_started",
    "get_tracker_started",
    "get_websocket_enabled",
    "lifespan",
]
