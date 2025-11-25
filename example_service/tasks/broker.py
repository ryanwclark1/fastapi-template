"""Taskiq broker configuration for background task processing.

This module provides two separate Taskiq integrations:

1. **Background Tasks (taskiq-aio-pika)**
   - For executing async background tasks
   - Uses RabbitMQ directly for task distribution
   - Run worker: `taskiq worker example_service.tasks.broker:broker`

2. **Scheduled Message Publishing (taskiq-faststream)**
   - For publishing messages on a schedule (cron-like)
   - Wraps FastStream broker to publish messages at scheduled times
   - Run scheduler: `taskiq scheduler example_service.tasks.broker:stream_scheduler`

Architecture:
- FastStream RabbitRouter: Event-driven messaging (pub/sub handlers)
- taskiq-aio-pika: Background task queue (async jobs)
- taskiq-faststream: Scheduled message publishing (cron jobs that publish to queues)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from example_service.infra.results import RedisAsyncResultBackend

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from taskiq_aio_pika import AioPikaBroker as AioPikaBrokerType
else:
    AioPikaBrokerType = Any

# Import taskiq-aio-pika for background tasks
try:
    from taskiq_aio_pika import AioPikaBroker
except ImportError:
    AioPikaBroker = None

# Import taskiq-faststream for scheduled message publishing
try:
    from taskiq.schedule_sources import LabelScheduleSource
    from taskiq_faststream import BrokerWrapper, StreamScheduler
except ImportError:
    BrokerWrapper = None
    StreamScheduler = None
    LabelScheduleSource = None

from example_service.core.settings import get_rabbit_settings, get_redis_settings

logger = logging.getLogger(__name__)

# Get settings from modular configuration
redis_settings = get_redis_settings()
rabbit_settings = get_rabbit_settings()

# =============================================================================
# Background Task Broker (taskiq-aio-pika)
# =============================================================================
# This broker is for executing background tasks asynchronously.
# Tasks are defined with @broker.task() decorator.
# Run worker: taskiq worker example_service.tasks.broker:broker

broker: AioPikaBrokerType | None = None

if AioPikaBroker is not None and rabbit_settings.is_configured and redis_settings.is_configured:
    from example_service.tasks.middleware import TrackingMiddleware

    broker = (
        AioPikaBroker(
            url=rabbit_settings.get_url(),
            queue_name=rabbit_settings.get_prefixed_queue("taskiq-tasks"),
            declare_exchange=True,
            declare_queues=True,
        )
        .with_result_backend(RedisAsyncResultBackend(redis_settings.get_url()))
        .with_middlewares(
            TrackingMiddleware(),
        )
    )

    logger.info(
        "Taskiq background task broker configured with tracking middleware",
        extra={"queue": rabbit_settings.get_prefixed_queue("taskiq-tasks")},
    )
else:
    if AioPikaBroker is None:
        logger.warning("taskiq-aio-pika not installed - background tasks disabled")
    elif not rabbit_settings.is_configured:
        logger.warning("RabbitMQ not configured - background tasks disabled")
    elif not redis_settings.is_configured:
        logger.warning("Redis not configured - background tasks disabled")


# =============================================================================
# Scheduled Message Publisher (taskiq-faststream)
# =============================================================================
# This wraps the FastStream broker for scheduled message publishing.
# Messages are defined with stream_broker.task(message=..., schedule=[...])
# Run scheduler: taskiq scheduler example_service.tasks.broker:stream_scheduler

stream_broker: Any = None
stream_scheduler: Any = None

if BrokerWrapper is not None and StreamScheduler is not None and LabelScheduleSource is not None:
    # Import FastStream broker to wrap it
    from example_service.infra.messaging.broker import broker as faststream_broker

    if faststream_broker is not None and rabbit_settings.is_configured:
        stream_broker = BrokerWrapper(faststream_broker)
        stream_scheduler = StreamScheduler(
            broker=stream_broker,
            sources=[LabelScheduleSource(stream_broker)],
        )

        logger.info("Taskiq scheduled message publisher configured")
    else:
        logger.warning("FastStream broker not available - scheduled publishing disabled")
else:
    if BrokerWrapper is None:
        logger.debug("taskiq-faststream not installed - scheduled publishing disabled")


async def get_broker() -> AsyncIterator[AioPikaBrokerType | None]:
    """Get the Taskiq background task broker instance.

    This is a dependency that can be used in FastAPI endpoints
    to access the broker for scheduling background tasks.

    Yields:
        Taskiq broker instance.

    Example:
        ```python
        from example_service.tasks.tasks import example_task

        @router.post("/schedule")
        async def schedule_task():
            task = await example_task.kiq(data="test")
            return {"task_id": task.task_id}
        ```
    """
    yield broker


async def start_taskiq() -> None:
    """Start the Taskiq broker.

    This should be called during application startup in the lifespan context.
    It initializes the connection to RabbitMQ and the result backend.

    Note: This only initializes the broker for ENQUEUING tasks from the FastAPI app.
    To actually EXECUTE tasks, you need to run a separate worker process:
        taskiq worker example_service.tasks.broker:broker

    Raises:
        ConnectionError: If unable to connect to RabbitMQ or result backend.
    """
    if broker is None:
        logger.warning("Taskiq broker not configured, skipping startup")
        return

    logger.info("Starting Taskiq broker")

    try:
        await broker.startup()
        logger.info("Taskiq broker started successfully")
    except Exception as e:
        logger.exception("Failed to start Taskiq broker", extra={"error": str(e)})
        raise


async def stop_taskiq() -> None:
    """Stop the Taskiq broker.

    This should be called during application shutdown in the lifespan context.
    It gracefully closes connections to RabbitMQ and the result backend.
    """
    if broker is None:
        logger.debug("Taskiq broker not configured, skipping shutdown")
        return

    logger.info("Stopping Taskiq broker")

    try:
        await broker.shutdown()
        logger.info("Taskiq broker stopped successfully")
    except Exception as e:
        logger.exception("Error stopping Taskiq broker", extra={"error": str(e)})


# =============================================================================
# Task Module Imports
# =============================================================================
# Import all task modules when broker is loaded to ensure tasks are registered.
# This is critical for the worker to discover all tasks.
# The worker imports: taskiq worker example_service.tasks.broker:broker
# So importing here ensures all tasks are available to the worker.

if broker is not None:
    # Import main task modules
    # Import task submodules
    import example_service.tasks.backup.tasks  # noqa: F401
    import example_service.tasks.cache.tasks  # noqa: F401
    import example_service.tasks.cleanup.tasks  # noqa: F401
    import example_service.tasks.export.tasks  # noqa: F401
    import example_service.tasks.notifications.tasks  # noqa: F401
    import example_service.tasks.scheduler  # noqa: F401
    import example_service.tasks.tasks  # noqa: F401

    logger.debug("All task modules imported and registered with broker")
