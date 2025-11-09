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

from example_service.core.settings import settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)

# Initialize RabbitMQ broker
broker = RabbitBroker(
    url=settings.rabbitmq_url,
    # Connection settings
    max_consumers=10,
    graceful_timeout=15,
    # Logging
    logger=logger,
    # Apply prefix to all queues for multi-environment support
    apply_types=True,
)


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
    logger.info("Starting RabbitMQ broker", extra={"url": settings.rabbitmq_url})

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
    logger.info("Stopping RabbitMQ broker")

    try:
        await broker.close()
        logger.info("RabbitMQ broker stopped successfully")
    except Exception as e:
        logger.exception("Error stopping RabbitMQ broker", extra={"error": str(e)})
