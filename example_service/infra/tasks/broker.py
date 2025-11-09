"""Taskiq broker configuration for background tasks."""
from __future__ import annotations

import logging

from taskiq import TaskiqScheduler
from taskiq_faststream import BrokerWrapper, StreamScheduler
from taskiq_redis import RedisAsyncResultBackend

from example_service.core.settings import get_rabbit_settings, get_redis_settings

logger = logging.getLogger(__name__)

# Global broker and scheduler (created lazily)
_broker: BrokerWrapper | None = None
_scheduler: TaskiqScheduler | None = None


def get_taskiq_broker() -> BrokerWrapper:
    """Get or create Taskiq broker instance.
    
    Returns:
        Taskiq FastStream broker wrapper.
    """
    global _broker
    
    if _broker is None:
        from example_service.infra.messaging.broker import get_broker_instance
        
        rabbit_settings = get_rabbit_settings()
        redis_settings = get_redis_settings()
        
        # Get the FastStream broker
        faststream_broker = get_broker_instance()
        
        # Create result backend if Redis is configured
        result_backend = None
        if redis_settings.is_configured:
            result_backend = RedisAsyncResultBackend(redis_settings.get_url())
        
        # Create Taskiq broker wrapping FastStream
        _broker = BrokerWrapper(faststream_broker, result_backend=result_backend)
        logger.info("Taskiq broker initialized")
    
    return _broker


def get_taskiq_scheduler() -> TaskiqScheduler:
    """Get or create Taskiq scheduler instance.
    
    Returns:
        Taskiq scheduler.
    """
    global _scheduler
    
    if _scheduler is None:
        broker = get_taskiq_broker()
        _scheduler = StreamScheduler(broker=broker)
        logger.info("Taskiq scheduler initialized")
    
    return _scheduler


# Expose broker for compatibility
broker = property(lambda self: get_taskiq_broker())


def get_broker() -> BrokerWrapper:
    """Get Taskiq broker instance (compatibility function)."""
    return get_taskiq_broker()


async def start_taskiq() -> None:
    """Start the Taskiq broker."""
    rabbit_settings = get_rabbit_settings()
    
    if not rabbit_settings.is_configured:
        logger.info("RabbitMQ not configured, skipping Taskiq startup")
        return
    
    broker_instance = get_taskiq_broker()
    await broker_instance.startup()
    logger.info("Taskiq broker started")


async def stop_taskiq() -> None:
    """Stop the Taskiq broker."""
    global _broker, _scheduler
    
    if _broker is not None:
        await _broker.shutdown()
        logger.info("Taskiq broker stopped")
        _broker = None
        _scheduler = None
