"""RabbitMQ broker configuration using FastStream.

This module provides the message broker setup for event-driven communication
using FastStream with RabbitMQ. It includes:
- RabbitRouter for FastAPI integration with AsyncAPI docs
- Queue and exchange configuration
- Publisher and subscriber setup
- Automatic lifespan management
- Context manager for safe publishing from Taskiq workers

AsyncAPI Documentation:
- /asyncapi - Interactive documentation UI
- /asyncapi.json - JSON schema download
- /asyncapi.yaml - YAML schema download

Usage Patterns:
- FastAPI endpoints: Use `Depends(get_broker)` - broker is auto-connected
- Taskiq workers: Use `async with broker_context()` to manage lifecycle
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from enum import Enum
import logging
from typing import TYPE_CHECKING, Any

from example_service.app.docs import ensure_asyncapi_template_patched
from example_service.core.settings import get_otel_settings, get_rabbit_settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from faststream.rabbit import RabbitBroker
    from faststream.rabbit.fastapi import RabbitRouter as RabbitRouterType
else:
    RabbitRouterType = Any


class ConnectionState(str, Enum):
    """Connection states for the RabbitMQ broker.

    Attributes:
        DISCONNECTED: Broker is not connected.
        CONNECTING: Broker is attempting to connect.
        CONNECTED: Broker is connected and operational.
        RECONNECTING: Broker is attempting to reconnect after connection loss.
        FAILED: Connection failed and max retries exceeded.
    """

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


otel_settings = get_otel_settings()

logger = logging.getLogger(__name__)

# Get RabbitMQ settings from modular configuration
rabbit_settings = get_rabbit_settings()

# Initialize RabbitMQ router with AsyncAPI documentation
# RabbitRouter wraps RabbitBroker and provides FastAPI integration
router: RabbitRouterType | None = None
broker: RabbitBroker | None = None
_not_configured_logged = False


def _ensure_router_initialized() -> RabbitRouterType | None:
    """Create the RabbitRouter on first use so AsyncAPI template patches apply."""
    global router, broker, _not_configured_logged

    if router is not None:
        return router

    if not rabbit_settings.is_configured:
        if not _not_configured_logged:
            logger.warning("RabbitMQ not configured - messaging features disabled")
            _not_configured_logged = True
        return None

    ensure_asyncapi_template_patched()

    from faststream.rabbit.fastapi import RabbitRouter

    # Build middleware list - conditionally add TelemetryMiddleware if OTel is enabled
    middlewares = []
    if otel_settings.enabled:
        try:
            from faststream.rabbit.opentelemetry import RabbitTelemetryMiddleware

            middlewares.append(RabbitTelemetryMiddleware())
            logger.debug("FastStream RabbitTelemetryMiddleware enabled for distributed tracing")
        except ImportError:
            logger.warning(
                "faststream.rabbit.opentelemetry not available - "
                "install faststream[rabbit] >= 0.5.0 for telemetry support"
            )

    router = RabbitRouter(
        url=rabbit_settings.get_url(),
        graceful_timeout=rabbit_settings.graceful_timeout,
        logger=logger,
        middlewares=middlewares,  # Add telemetry middleware for distributed tracing
        # AsyncAPI documentation configuration
        schema_url="/asyncapi",
        include_in_schema=True,
        description="Event-driven messaging API for the Example Service",
    )
    broker = router.broker
    return router


async def get_broker() -> AsyncIterator[RabbitBroker | None]:
    """Get the RabbitMQ broker instance.

    This is a dependency that can be used in FastAPI endpoints
    to access the broker for publishing messages.

    Yields:
        RabbitMQ broker instance or None if not configured.

    Example:
            @router.post("/publish")
        async def publish_event(
            broker: RabbitBroker = Depends(get_broker)
        ):
            await broker.publish(
                message={"event": "user.created"},
                queue="user-events"
            )
    """
    _ensure_router_initialized()
    yield broker


def get_router() -> RabbitRouterType | None:
    """Get the RabbitMQ router for FastAPI integration.

    Returns:
        RabbitRouter instance or None if not configured.
    """
    return _ensure_router_initialized()


# Initialize router eagerly so handler modules can register subscribers during import.
_ensure_router_initialized()


# Legacy functions for backward compatibility
# Note: With RabbitRouter, lifecycle is managed automatically by FastAPI


async def start_broker() -> None:
    """Start the RabbitMQ broker connection.

    Note: When using RabbitRouter with FastAPI, the broker lifecycle
    is managed automatically. This function is kept for backward
    compatibility and manual startup scenarios.

    The connection is wrapped with a timeout to prevent indefinite blocking
    if RabbitMQ is unavailable. If the broker is already running (from
    RabbitRouter auto-connection), this function will return immediately.
    """
    _ensure_router_initialized()

    if not rabbit_settings.is_configured or broker is None:
        logger.warning("RabbitMQ not configured, skipping broker startup")
        return

    # Check if broker is already running (from RabbitRouter auto-connection)
    if hasattr(broker, "running") and broker.running:
        logger.debug("RabbitMQ broker already running (connected via RabbitRouter)")
        return

    logger.info(
        "Starting RabbitMQ broker",
        extra={
            "url": rabbit_settings.get_url(),
            "connection_timeout": rabbit_settings.connection_timeout,
        },
    )

    try:
        # Wrap connection with timeout to prevent indefinite blocking
        # Use wait_for instead of timeout context for better compatibility
        await asyncio.wait_for(
            broker.start(),
            timeout=rabbit_settings.connection_timeout,
        )
        logger.info("RabbitMQ broker started successfully")
    except TimeoutError:
        error_msg = f"RabbitMQ connection timeout after {rabbit_settings.connection_timeout}s"
        logger.error(
            error_msg,
            extra={
                "url": rabbit_settings.get_url(),
                "connection_timeout": rabbit_settings.connection_timeout,
            },
        )
        raise ConnectionError(error_msg) from None
    except Exception as e:
        logger.exception("Failed to start RabbitMQ broker", extra={"error": str(e)})
        raise


async def stop_broker() -> None:
    """Stop the RabbitMQ broker connection.

    Note: When using RabbitRouter with FastAPI, the broker lifecycle
    is managed automatically. This function is kept for backward
    compatibility and manual shutdown scenarios.
    """
    _ensure_router_initialized()

    if not rabbit_settings.is_configured or broker is None:
        logger.debug("RabbitMQ not configured, skipping broker shutdown")
        return

    logger.info("Stopping RabbitMQ broker")

    try:
        await broker.close()
        logger.info("RabbitMQ broker stopped successfully")
    except Exception as e:
        logger.exception("Error stopping RabbitMQ broker", extra={"error": str(e)})


@asynccontextmanager
async def broker_context() -> AsyncIterator[RabbitBroker | None]:
    """Context manager for safe broker access from Taskiq workers.

    This context manager handles the broker lifecycle for code running
    outside of FastAPI's lifespan (e.g., Taskiq worker tasks). It ensures
    the broker is connected before use and properly closed afterward.

    IMPORTANT: This context manager only closes the broker if it was
    started by this context. If the broker is already running (e.g., from
    FastAPI lifespan), it will NOT close it to avoid disconnecting shared
    connections.

    Yields:
        RabbitBroker instance or None if not configured.

    Example:
            from example_service.infra.messaging.broker import broker_context

        @taskiq_broker.task()
        async def my_task():
            async with broker_context() as broker:
                if broker is not None:
                    await broker.publish(
                        message={"event": "task.completed"},
                        queue="task-events"
                    )

    Note:
        - In FastAPI endpoints, use `Depends(get_broker)` instead
        - The context manager is idempotent - safe to use even if
          broker is already connected (e.g., in tests)
        - Only closes the broker if it was started by this context
    """
    _ensure_router_initialized()

    if not rabbit_settings.is_configured or broker is None:
        logger.warning("RabbitMQ not configured, broker_context yielding None")
        yield None
        return

    # Check if broker is already running (e.g., from FastAPI lifespan)
    was_running = hasattr(broker, "running") and broker.running
    connection_started = False

    try:
        # Only start if not already running to avoid connection leaks
        if not was_running:
            # Wrap connection with timeout to prevent indefinite blocking
            # Use wait_for instead of timeout context for better compatibility
            await asyncio.wait_for(
                broker.start(),
                timeout=rabbit_settings.connection_timeout,
            )
            connection_started = True
            logger.debug("Broker connected via context manager")
        else:
            logger.debug("Broker already running, reusing existing connection")
        yield broker
    except TimeoutError:
        error_msg = f"RabbitMQ connection timeout after {rabbit_settings.connection_timeout}s"
        logger.error(
            error_msg,
            extra={"connection_timeout": rabbit_settings.connection_timeout},
        )
        raise ConnectionError(error_msg) from None
    except Exception as e:
        logger.exception("Failed to connect broker", extra={"error": str(e)})
        raise
    finally:
        # Only close if we started the connection (not if it was already running)
        # This prevents disconnecting shared connections from FastAPI lifespan
        if connection_started and not was_running:
            try:
                await broker.close()
                logger.debug("Broker disconnected via context manager")
            except Exception as e:
                logger.warning("Error closing broker in context manager", extra={"error": str(e)})
        elif was_running:
            logger.debug("Broker was already running, not closing to preserve shared connection")


async def check_broker_health() -> dict[str, Any]:
    """Check RabbitMQ broker health status.

    Returns health information including connection state, broker status,
    and any error details. This can be used by health check endpoints
    to report messaging infrastructure status.

    Returns:
        Dictionary containing:
            - status: Health status ("healthy", "unhealthy", "unavailable", "unknown")
            - state: Connection state (DISCONNECTED, CONNECTING, CONNECTED, etc.)
            - is_connected: Boolean connection status
            - reason: Optional reason for unhealthy/unavailable status

    Example:
        >>> health = await check_broker_health()
        >>> if health["status"] == "healthy":
        ...     print("Broker is operational")
    """
    _ensure_router_initialized()

    if broker is None:
        return {
            "status": "unavailable",
            "state": ConnectionState.DISCONNECTED.value,
            "is_connected": False,
            "reason": "broker_not_configured",
        }

    if not rabbit_settings.is_configured:
        return {
            "status": "unavailable",
            "state": ConnectionState.DISCONNECTED.value,
            "is_connected": False,
            "reason": "rabbitmq_not_enabled",
        }

    try:
        # Check if broker is running
        if hasattr(broker, "running") and broker.running:
            # Check connection state
            if hasattr(broker, "connection") and broker.connection:
                if hasattr(broker.connection, "is_closed") and broker.connection.is_closed:
                    return {
                        "status": "unhealthy",
                        "state": ConnectionState.DISCONNECTED.value,
                        "is_connected": False,
                        "reason": "connection_closed",
                    }
                return {
                    "status": "healthy",
                    "state": ConnectionState.CONNECTED.value,
                    "is_connected": True,
                }
            # Broker running but connection state unknown
            return {
                "status": "healthy",
                "state": ConnectionState.CONNECTED.value,
                "is_connected": True,
            }
        # Broker not running
        return {
            "status": "unhealthy",
            "state": ConnectionState.DISCONNECTED.value,
            "is_connected": False,
            "reason": "broker_not_running",
        }
    except Exception as e:
        logger.exception("Error checking broker health", extra={"error": str(e)})
        return {
            "status": "unhealthy",
            "state": ConnectionState.FAILED.value,
            "is_connected": False,
            "reason": str(e),
        }
