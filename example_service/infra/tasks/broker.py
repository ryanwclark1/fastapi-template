"""Taskiq broker configuration for background task processing.

This module provides the Taskiq broker setup for executing background tasks
asynchronously. It integrates with FastStream for task distribution and
Redis for result storage.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from taskiq import TaskiqScheduler
from taskiq_faststream import FastStreamBroker
from taskiq_redis import RedisAsyncResultBackend

from example_service.core.settings import settings
from example_service.infra.messaging.broker import broker as rabbitmq_broker

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)

# Initialize Taskiq broker with FastStream transport
# This allows tasks to be distributed via RabbitMQ and results stored in Redis
broker = FastStreamBroker(rabbitmq_broker).with_result_backend(
    RedisAsyncResultBackend(settings.taskiq_result_backend)
)

# Initialize scheduler for cron-like scheduled tasks
scheduler = TaskiqScheduler(broker=broker)


async def get_broker() -> AsyncIterator[FastStreamBroker]:
    """Get the Taskiq broker instance.

    This is a dependency that can be used in FastAPI endpoints
    to access the broker for scheduling tasks.

    Yields:
        Taskiq broker instance.

    Example:
        ```python
        from example_service.infra.tasks.tasks import example_task

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
    It initializes the connection to the result backend.

    Raises:
        ConnectionError: If unable to connect to result backend.
    """
    logger.info(
        "Starting Taskiq broker",
        extra={"result_backend": settings.taskiq_result_backend},
    )

    try:
        await broker.startup()
        logger.info("Taskiq broker started successfully")
    except Exception as e:
        logger.exception("Failed to start Taskiq broker", extra={"error": str(e)})
        raise


async def stop_taskiq() -> None:
    """Stop the Taskiq broker.

    This should be called during application shutdown in the lifespan context.
    It gracefully closes connections to the result backend.
    """
    logger.info("Stopping Taskiq broker")

    try:
        await broker.shutdown()
        logger.info("Taskiq broker stopped successfully")
    except Exception as e:
        logger.exception("Error stopping Taskiq broker", extra={"error": str(e)})
