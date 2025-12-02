"""Task execution tracking package.

This package provides a backend-agnostic interface for tracking task executions,
supporting both Redis (fast, ephemeral) and PostgreSQL (persistent) backends.

Usage:
    from example_service.tasks.tracking import get_tracker, start_tracker, stop_tracker

    # During application startup
    await start_tracker()

    # Get the tracker instance
    tracker = get_tracker()
    if tracker:
        history = await tracker.get_task_history(limit=100)
        stats = await tracker.get_stats()

    # During application shutdown
    await stop_tracker()
"""

from example_service.tasks.tracking.base import BaseTaskTracker
from example_service.tasks.tracking.factory import (
    create_tracker,
    get_tracker,
    start_tracker,
    stop_tracker,
)
from example_service.tasks.tracking.postgres_tracker import PostgresTaskTracker
from example_service.tasks.tracking.redis_tracker import RedisTaskTracker

# Backward compatibility alias - TaskExecutionTracker was the old name
TaskExecutionTracker = BaseTaskTracker

__all__ = [
    "BaseTaskTracker",
    "PostgresTaskTracker",
    "RedisTaskTracker",
    "TaskExecutionTracker",  # Backward compatibility
    "create_tracker",
    "get_tracker",
    "start_tracker",
    "stop_tracker",
]
