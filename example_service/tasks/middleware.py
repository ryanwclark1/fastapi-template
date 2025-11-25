"""Taskiq middleware for task execution tracking.

This middleware automatically tracks all task executions by hooking into
Taskiq's pre_execute and post_execute lifecycle hooks.

The middleware:
1. Records task start time and metadata in pre_execute
2. Records task completion (success/failure) in post_execute
3. Stores all data in Redis via TaskExecutionTracker
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from taskiq import TaskiqMiddleware

if TYPE_CHECKING:
    from taskiq import TaskiqMessage, TaskiqResult

from example_service.tasks.tracking import get_tracker, start_tracker, stop_tracker

logger = logging.getLogger(__name__)


class TrackingMiddleware(TaskiqMiddleware):
    """Middleware that tracks all task executions in Redis.

    This middleware automatically records:
    - Task start time
    - Task completion time and status
    - Task return value (on success)
    - Error details (on failure)
    - Execution duration

    Example usage:
        ```python
        broker = AioPikaBroker(...)
        broker.add_middlewares(TrackingMiddleware())
        ```

    The tracked data can then be queried via the admin REST API.
    """

    def __init__(self) -> None:
        """Initialize the tracking middleware."""
        super().__init__()
        self._start_times: dict[str, float] = {}

    async def startup(self) -> None:
        """Initialize the tracker on worker startup."""
        logger.info("TrackingMiddleware starting up")
        await start_tracker()

    async def shutdown(self) -> None:
        """Cleanup the tracker on worker shutdown."""
        logger.info("TrackingMiddleware shutting down")
        await stop_tracker()
        self._start_times.clear()

    async def pre_execute(
        self,
        message: "TaskiqMessage",
    ) -> "TaskiqMessage":
        """Record task start event.

        This is called before the task function is executed.

        Args:
            message: The task message containing task_id and task_name.

        Returns:
            The message, unmodified.
        """
        tracker = get_tracker()

        task_id = message.task_id
        task_name = message.task_name

        # Record start time for duration calculation
        self._start_times[task_id] = time.perf_counter()

        if tracker and tracker.is_connected:
            try:
                await tracker.on_task_start(
                    task_id=task_id,
                    task_name=task_name,
                    worker_id=None,  # Could add worker identification later
                )
            except Exception as e:
                # Don't fail the task if tracking fails
                logger.warning(
                    "Failed to record task start",
                    extra={"task_id": task_id, "error": str(e)},
                )

        logger.debug(
            "Task pre_execute tracked",
            extra={"task_id": task_id, "task_name": task_name},
        )

        return message

    async def post_execute(
        self,
        message: "TaskiqMessage",
        result: "TaskiqResult[Any]",
    ) -> None:
        """Record task completion event.

        This is called after the task function completes (success or failure).

        Args:
            message: The task message containing task_id and task_name.
            result: The task result containing return value or error.
        """
        tracker = get_tracker()

        task_id = message.task_id
        task_name = message.task_name

        # Calculate duration
        start_time = self._start_times.pop(task_id, None)
        if start_time:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
        else:
            duration_ms = 0

        # Determine status and extract error/return value
        if result.is_err:
            status = "failure"
            return_value = None
            error = result.error
        else:
            status = "success"
            return_value = result.return_value
            error = None

        if tracker and tracker.is_connected:
            try:
                await tracker.on_task_finish(
                    task_id=task_id,
                    status=status,
                    return_value=return_value,
                    error=error,
                    duration_ms=duration_ms,
                )
            except Exception as e:
                # Don't fail the task if tracking fails
                logger.warning(
                    "Failed to record task finish",
                    extra={"task_id": task_id, "error": str(e)},
                )

        logger.debug(
            "Task post_execute tracked",
            extra={
                "task_id": task_id,
                "task_name": task_name,
                "status": status,
                "duration_ms": duration_ms,
            },
        )
