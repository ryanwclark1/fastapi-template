"""Factory for creating task trackers based on configuration.

This module provides a factory function and global lifecycle management
for task trackers, selecting the appropriate backend based on settings.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from example_service.core.settings import get_db_settings, get_redis_settings, get_task_settings

if TYPE_CHECKING:
    from example_service.tasks.tracking.base import BaseTaskTracker

logger = logging.getLogger(__name__)

# Global tracker instance
_tracker: BaseTaskTracker | None = None


def create_tracker() -> BaseTaskTracker:
    """Create a task tracker based on TASK_RESULT_BACKEND setting.

    This factory function reads the task settings and creates the
    appropriate tracker implementation:
    - "redis": Creates RedisTaskTracker
    - "postgres": Creates PostgresTaskTracker

    Returns:
        A task tracker instance (not yet connected).

    Raises:
        ValueError: If the backend is not recognized.

    Example:
            tracker = create_tracker()
        await tracker.connect()

        # Use the tracker
        await tracker.on_task_start("task-123", "backup_database")

        # Cleanup
        await tracker.disconnect()
    """
    task_settings = get_task_settings()

    if task_settings.is_postgres_backend:
        from example_service.tasks.tracking.postgres_tracker import PostgresTaskTracker

        db_settings = get_db_settings()
        logger.info("Creating PostgreSQL task tracker")

        return PostgresTaskTracker(
            dsn=db_settings.url,
            pool_size=5,
            max_overflow=10,
        )
    else:
        from example_service.tasks.tracking.redis_tracker import RedisTaskTracker

        redis_settings = get_redis_settings()
        logger.info("Creating Redis task tracker")

        return RedisTaskTracker(
            redis_url=redis_settings.url,
            key_prefix=task_settings.redis_key_prefix,
            ttl_seconds=task_settings.redis_result_ttl_seconds,
            max_connections=task_settings.redis_max_connections,
        )


def get_tracker() -> BaseTaskTracker | None:
    """Get the global task execution tracker instance.

    Returns:
        Task tracker instance or None if not initialized.

    Example:
            tracker = get_tracker()
        if tracker and tracker.is_connected:
            history = await tracker.get_task_history(limit=100)
    """
    return _tracker


async def start_tracker() -> None:
    """Initialize the global task execution tracker.

    This should be called during application/worker startup.
    The tracker is only created if tracking is enabled in settings.

    Example:
            # In your application lifespan
        async def lifespan(app: FastAPI):
            await start_tracker()
            yield
            await stop_tracker()
    """
    global _tracker

    task_settings = get_task_settings()

    if not task_settings.tracking_enabled:
        logger.info("Task tracking is disabled")
        return

    logger.info(
        "Starting task execution tracker",
        extra={"backend": task_settings.result_backend},
    )

    try:
        _tracker = create_tracker()
        await _tracker.connect()
        logger.info("Task execution tracker started successfully")
    except Exception as e:
        logger.exception(
            "Failed to start task execution tracker",
            extra={"error": str(e)},
        )
        # Don't raise - tracking is non-critical functionality
        _tracker = None


async def stop_tracker() -> None:
    """Close the global task execution tracker.

    This should be called during application/worker shutdown.

    Example:
            # In your application shutdown
        await stop_tracker()
    """
    global _tracker

    logger.info("Stopping task execution tracker")

    if _tracker:
        try:
            await _tracker.disconnect()
            _tracker = None
            logger.info("Task execution tracker stopped successfully")
        except Exception as e:
            logger.exception(
                "Error stopping task execution tracker",
                extra={"error": str(e)},
            )


__all__ = [
    "create_tracker",
    "get_tracker",
    "start_tracker",
    "stop_tracker",
]
