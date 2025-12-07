"""Application lifespan management.

This module provides the main lifespan context manager that orchestrates
all service startup and shutdown using the modular lifecycle system.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from typing import TYPE_CHECKING

# Import all lifespan modules to register their hooks
from example_service.app.lifespan import (
    ai,
    cache,
    core,
    database,
    discovery,
    health,
    messaging,
    outbox,
    storage,
    task_tracking,
    tasks,
    websocket,
)
from example_service.app.lifespan.ai import get_ai_infrastructure_started
from example_service.app.lifespan.health import get_health_monitor_started
from example_service.app.lifespan.registry import lifespan_registry
from example_service.app.lifespan.task_tracking import get_tracker_started
from example_service.app.lifespan.websocket import get_websocket_enabled
from example_service.core.settings import (
    get_ai_settings,
    get_app_settings,
    get_auth_settings,
    get_consul_settings,
    get_db_settings,
    get_health_settings,
    get_logging_settings,
    get_mock_settings,
    get_otel_settings,
    get_rabbit_settings,
    get_redis_settings,
    get_storage_settings,
    get_task_settings,
    get_websocket_settings,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi import FastAPI

# Ensure modules are imported (for side effects - hook registration)
_ = (
    ai,
    cache,
    core,
    database,
    discovery,
    health,
    messaging,
    outbox,
    storage,
    task_tracking,
    tasks,
    websocket,
)

logger = logging.getLogger(__name__)

# Module-level state for health check dependencies (preserved for backward compatibility)
_health_service: object | None = None
_service_clients: dict[str, object] = {}


def get_health_service() -> object | None:
    """Get the health service instance.

    Returns:
        HealthService instance or None if not initialized.
    """
    return _health_service


def get_all_service_clients() -> dict[str, object]:
    """Get all service client instances.

    Returns:
        Dictionary mapping service names to client instances.
    """
    return _service_clients


def get_service_client(name: str) -> object | None:
    """Get a service client instance by name.

    Args:
        name: Service client name (e.g., 'auth', 'confd', 'calld').

    Returns:
        Service client instance or None if not initialized.
    """
    return _service_clients.get(name)


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

    # Load all settings (cached after first call)
    app_settings = get_app_settings()
    auth_settings = get_auth_settings()
    consul_settings = get_consul_settings()
    db_settings = get_db_settings()
    redis_settings = get_redis_settings()
    storage_settings = get_storage_settings()
    rabbit_settings = get_rabbit_settings()
    otel_settings = get_otel_settings()
    log_settings = get_logging_settings()
    mock_settings = get_mock_settings()
    task_settings = get_task_settings()
    ws_settings = get_websocket_settings()
    health_settings = get_health_settings()
    ai_settings = get_ai_settings()

    # Prepare settings dictionary for registry
    settings_dict = {
        "app_settings": app_settings,
        "auth_settings": auth_settings,
        "consul_settings": consul_settings,
        "db_settings": db_settings,
        "redis_settings": redis_settings,
        "storage_settings": storage_settings,
        "rabbit_settings": rabbit_settings,
        "otel_settings": otel_settings,
        "log_settings": log_settings,
        "mock_settings": mock_settings,
        "task_settings": task_settings,
        "ws_settings": ws_settings,
        "health_settings": health_settings,
        "ai_settings": ai_settings,
    }

    # Execute all startup hooks in dependency order
    await lifespan_registry.startup(**settings_dict)

    # Log startup completion with all service states
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
            "outbox_enabled": db_settings.is_configured
            and rabbit_settings.is_configured,
            "websocket_enabled": get_websocket_enabled(),
            "task_tracking_enabled": get_tracker_started(),
            "task_tracking_backend": task_settings.result_backend
            if get_tracker_started()
            else None,
            "service_availability_enabled": get_health_monitor_started(),
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
                "websocket_enabled": get_websocket_enabled(),
                "service_discovery_enabled": consul_settings.is_configured,
                "rate_limiting_enabled": app_settings.enable_rate_limiting,
                "request_size_limit": app_settings.request_size_limit,
                "enable_debug_middleware": app_settings.enable_debug_middleware,
                "strict_csp": app_settings.strict_csp,
                "service_availability_enabled": get_health_monitor_started(),
            },
        )

    yield

    # Shutdown
    logger.info(
        "Application shutting down", extra={"service": app_settings.service_name}
    )

    # Execute all shutdown hooks in reverse order
    await lifespan_registry.shutdown(**settings_dict)

    logger.info("Application shutdown complete")


__all__ = [
    "get_all_service_clients",
    "get_health_service",
    "get_service_client",
    "lifespan",
]
