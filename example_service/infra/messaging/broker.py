"""RabbitMQ broker configuration using FastStream.

This module provides the message broker setup for event-driven communication
using FastStream with RabbitMQ. It includes:
- RabbitRouter for FastAPI integration with AsyncAPI docs
- Queue and exchange configuration
- Publisher and subscriber setup
- Automatic lifespan management

AsyncAPI Documentation:
- /asyncapi - Interactive documentation UI
- /asyncapi.json - JSON schema download
- /asyncapi.yaml - YAML schema download
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from example_service.core.settings import get_rabbit_settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from faststream.rabbit import RabbitBroker
    from faststream.rabbit.fastapi import RabbitRouter as RabbitRouterType
else:
    RabbitRouterType = Any

logger = logging.getLogger(__name__)

# Get RabbitMQ settings from modular configuration
rabbit_settings = get_rabbit_settings()

# Initialize RabbitMQ router with AsyncAPI documentation
# RabbitRouter wraps RabbitBroker and provides FastAPI integration
router: RabbitRouterType | None = None
broker: "RabbitBroker | None" = None

if rabbit_settings.is_configured:
    from faststream.rabbit.fastapi import RabbitRouter

    router = RabbitRouter(
        url=rabbit_settings.get_url(),
        graceful_timeout=rabbit_settings.graceful_timeout,
        logger=logger,
        # AsyncAPI documentation configuration
        schema_url="/asyncapi",
        include_in_schema=True,
        description="Event-driven messaging API for the Example Service",
    )
    # Access the underlying broker for direct operations
    broker = router.broker
else:
    logger.warning("RabbitMQ not configured - messaging features disabled")


async def get_broker() -> "AsyncIterator[RabbitBroker | None]":
    """Get the RabbitMQ broker instance.

    This is a dependency that can be used in FastAPI endpoints
    to access the broker for publishing messages.

    Yields:
        RabbitMQ broker instance or None if not configured.

    Example:
        ```python
        @router.post("/publish")
        async def publish_event(
            broker: RabbitBroker = Depends(get_broker)
        ):
            await broker.publish(
                message={"event": "user.created"},
                queue="user-events"
            )
        ```
    """
    yield broker


def get_router() -> RabbitRouterType | None:
    """Get the RabbitMQ router for FastAPI integration.

    Returns:
        RabbitRouter instance or None if not configured.
    """
    return router


# Legacy functions for backward compatibility
# Note: With RabbitRouter, lifecycle is managed automatically by FastAPI

async def start_broker() -> None:
    """Start the RabbitMQ broker connection.

    Note: When using RabbitRouter with FastAPI, the broker lifecycle
    is managed automatically. This function is kept for backward
    compatibility and manual startup scenarios.
    """
    if not rabbit_settings.is_configured or broker is None:
        logger.warning("RabbitMQ not configured, skipping broker startup")
        return

    logger.info("Starting RabbitMQ broker", extra={"url": rabbit_settings.get_url()})

    try:
        await broker.start()
        logger.info("RabbitMQ broker started successfully")
    except Exception as e:
        logger.exception("Failed to start RabbitMQ broker", extra={"error": str(e)})
        raise


async def stop_broker() -> None:
    """Stop the RabbitMQ broker connection.

    Note: When using RabbitRouter with FastAPI, the broker lifecycle
    is managed automatically. This function is kept for backward
    compatibility and manual shutdown scenarios.
    """
    if not rabbit_settings.is_configured or broker is None:
        logger.debug("RabbitMQ not configured, skipping broker shutdown")
        return

    logger.info("Stopping RabbitMQ broker")

    try:
        await broker.close()
        logger.info("RabbitMQ broker stopped successfully")
    except Exception as e:
        logger.exception("Error stopping RabbitMQ broker", extra={"error": str(e)})
