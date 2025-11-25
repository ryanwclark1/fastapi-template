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

from example_service.infra.tracing.opentelemetry import get_tracer, record_exception
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
            broker = AioPikaBroker(...)
        broker.add_middlewares(TrackingMiddleware())

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
        message: TaskiqMessage,
    ) -> TaskiqMessage:
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
        message: TaskiqMessage,
        result: TaskiqResult[Any],
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


class TracingMiddleware(TaskiqMiddleware):
    """Middleware that creates distributed traces for all task executions.

    This middleware integrates Taskiq background tasks with OpenTelemetry
    distributed tracing, making tasks visible in trace visualizers like
    Jaeger, Tempo, or Zipkin.

    For each task execution, it:
    - Creates a span with the tracer name "taskiq.worker"
    - Sets span attributes for task.id and task.name
    - Records exceptions if the task fails
    - Properly ends the span on completion

    Example usage:
        broker = AioPikaBroker(...)
        broker.add_middlewares(TracingMiddleware())

    The spans will appear in your distributed tracing UI with full
    context propagation from HTTP requests through background tasks.
    """

    def __init__(self) -> None:
        """Initialize the tracing middleware."""
        super().__init__()
        self._tracer = get_tracer("taskiq.worker")
        # Store spans keyed by task_id since we need them across pre/post execute
        self._spans: dict[str, Any] = {}

    async def pre_execute(
        self,
        message: TaskiqMessage,
    ) -> TaskiqMessage:
        """Create and start a span for the task execution.

        This is called before the task function is executed.

        Args:
            message: The task message containing task_id and task_name.

        Returns:
            The message, unmodified.
        """
        task_id = message.task_id
        task_name = message.task_name

        # Create and start a new span for this task
        span = self._tracer.start_span(
            name=f"task.{task_name}",
            attributes={
                "task.id": task_id,
                "task.name": task_name,
            },
        )

        # Store the span so we can end it in post_execute
        self._spans[task_id] = span

        logger.debug(
            "Task span created",
            extra={
                "task_id": task_id,
                "task_name": task_name,
                "span_id": span.get_span_context().span_id if span.is_recording() else None,
            },
        )

        return message

    async def post_execute(
        self,
        message: TaskiqMessage,
        result: TaskiqResult[Any],
    ) -> None:
        """End the span and record any exceptions.

        This is called after the task function completes (success or failure).

        Args:
            message: The task message containing task_id and task_name.
            result: The task result containing return value or error.
        """
        task_id = message.task_id
        task_name = message.task_name

        # Retrieve the span we created in pre_execute
        span = self._spans.pop(task_id, None)

        if span is None:
            logger.warning(
                "No span found for task in post_execute",
                extra={"task_id": task_id, "task_name": task_name},
            )
            return

        try:
            # Record exception if task failed
            if result.is_err and result.error is not None:
                # Record the exception in the span
                if isinstance(result.error, Exception):
                    span.record_exception(result.error)
                else:
                    # If error is not an Exception, create a generic one
                    span.record_exception(Exception(str(result.error)))

                # Set span status to error
                from opentelemetry import trace

                span.set_status(trace.Status(trace.StatusCode.ERROR))

                span.set_attribute("task.status", "failure")
            else:
                span.set_attribute("task.status", "success")

            logger.debug(
                "Task span ended",
                extra={
                    "task_id": task_id,
                    "task_name": task_name,
                    "status": "failure" if result.is_err else "success",
                },
            )

        finally:
            # Always end the span, even if recording the exception failed
            span.end()
