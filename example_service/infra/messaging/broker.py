"""RabbitMQ broker configuration using FastStream.

This module provides the message broker setup for event-driven communication
using FastStream with RabbitMQ. It includes:
- Broker initialization with connection pooling
- Queue and exchange configuration
- Publisher and subscriber setup
- Integration with FastAPI lifespan
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from faststream.rabbit import RabbitBroker

from example_service.core.settings import get_rabbit_settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)

# Get RabbitMQ settings from modular configuration
rabbit_settings = get_rabbit_settings()

# Initialize RabbitMQ broker
broker = RabbitBroker(
    url=rabbit_settings.get_url() if rabbit_settings.is_configured else None,
    # Connection settings
    max_consumers=rabbit_settings.max_consumers,
    graceful_timeout=rabbit_settings.graceful_timeout,
    # Logging
    logger=logger,
    # Apply prefix to all queues for multi-environment support
    apply_types=True,
) if rabbit_settings.is_configured else None


async def get_broker() -> AsyncIterator[RabbitBroker]:
    """Get the RabbitMQ broker instance.

    This is a dependency that can be used in FastAPI endpoints
    to access the broker for publishing messages.

    Yields:
        RabbitMQ broker instance.

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


async def start_broker() -> None:
    """Start the RabbitMQ broker connection.

    This should be called during application startup in the lifespan context.
    It establishes the connection to RabbitMQ and sets up all queues and exchanges.

    Raises:
        ConnectionError: If unable to connect to RabbitMQ.
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

    This should be called during application shutdown in the lifespan context.
    It gracefully closes the connection to RabbitMQ.
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
