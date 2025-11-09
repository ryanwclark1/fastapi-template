"""RabbitMQ broker configuration using FastStream."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from faststream.rabbit import RabbitBroker

from example_service.core.settings import get_rabbit_settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)

# Global broker instance (created lazily)
_broker: RabbitBroker | None = None


def get_broker_instance() -> RabbitBroker:
    """Get or create RabbitMQ broker instance.
    
    Returns:
        RabbitMQ broker instance.
    """
    global _broker
    
    if _broker is None:
        rabbit_settings = get_rabbit_settings()
        
        if not rabbit_settings.is_configured:
            # Return a dummy broker for testing
            _broker = RabbitBroker(url="amqp://localhost:5672/")
            logger.warning("RabbitMQ not configured, using default")
        else:
            _broker = RabbitBroker(
                url=rabbit_settings.get_url(),
                max_consumers=rabbit_settings.max_consumers,
                graceful_timeout=rabbit_settings.graceful_timeout,
                logger=logger,
                apply_types=True,
            )
            logger.info("RabbitMQ broker initialized")
    
    return _broker


# Expose broker for compatibility
broker = property(lambda self: get_broker_instance())


async def get_broker() -> AsyncIterator[RabbitBroker]:
    """Get the RabbitMQ broker instance as a dependency."""
    yield get_broker_instance()


async def start_broker() -> None:
    """Start the RabbitMQ broker connection."""
    rabbit_settings = get_rabbit_settings()
    
    if not rabbit_settings.is_configured:
        logger.info("RabbitMQ not configured, skipping broker startup")
        return
    
    broker_instance = get_broker_instance()
    await broker_instance.start()
    logger.info("RabbitMQ broker started")


async def stop_broker() -> None:
    """Stop the RabbitMQ broker connection."""
    global _broker
    
    if _broker is not None:
        await _broker.close()
        logger.info("RabbitMQ broker stopped")
        _broker = None
