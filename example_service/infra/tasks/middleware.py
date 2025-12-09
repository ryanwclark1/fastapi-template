"""Taskiq middleware for task execution tracking, metrics, and tracing.

This module provides middleware that hooks into Taskiq's lifecycle:

1. MetricsMiddleware - Records Prometheus metrics for task executions
2. TracingMiddleware - Creates OpenTelemetry spans for distributed tracing
3. TrackingMiddleware - Stores task history in Redis/PostgreSQL
4. TimeoutMiddleware - Enforces task execution timeouts
5. DeduplicationMiddleware - Prevents duplicate task submissions
6. DeadLetterQueueMiddleware - Handles failed tasks after max retries

The middleware chain order matters:
- DeduplicationMiddleware should be first (pre_send) to prevent duplicates
- TimeoutMiddleware wraps execution with timeout
- MetricsMiddleware should come early to capture all executions (including retries)
- TracingMiddleware creates spans that wrap the actual execution
- TrackingMiddleware records the final execution state
- DeadLetterQueueMiddleware handles final failures
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import TYPE_CHECKING, Any

from taskiq import TaskiqMiddleware

if TYPE_CHECKING:
    from taskiq import TaskiqMessage, TaskiqResult

from example_service.core.settings import get_redis_settings, get_task_settings
from example_service.infra.metrics.prometheus import (
    taskiq_task_duration_seconds,
    taskiq_tasks_total,
)
from example_service.infra.tasks.tracking import (
    get_tracker,
    start_tracker,
    stop_tracker,
)
from example_service.infra.tracing.opentelemetry import get_tracer

logger = logging.getLogger(__name__)

# Get settings
task_settings = get_task_settings()


class MetricsMiddleware(TaskiqMiddleware):
    """Middleware that records Prometheus metrics for task executions.

    This middleware uses the existing Prometheus registry from
    example_service.infra.metrics.prometheus, so metrics are exposed
    on the same FastAPI metrics endpoint (no separate server needed).

    Metrics recorded:
    - taskiq_tasks_total: Counter with labels [task_name, status]
    - taskiq_task_duration_seconds: Histogram with labels [task_name]

    Example usage:
        broker = AioPikaBroker(...)
        broker.add_middlewares(MetricsMiddleware())

    Metrics will appear at /metrics alongside other application metrics.
    """

    def __init__(self) -> None:
        """Initialize the metrics middleware."""
        super().__init__()
        self._start_times: dict[str, float] = {}

    async def pre_execute(
        self,
        message: TaskiqMessage,
    ) -> TaskiqMessage:
        """Record task start time for duration calculation.

        Args:
            message: The task message containing task_id and task_name.

        Returns:
            The message, unmodified.
        """
        task_id = message.task_id
        self._start_times[task_id] = time.perf_counter()
        return message

    async def post_execute(
        self,
        message: TaskiqMessage,
        result: TaskiqResult[Any],
    ) -> None:
        """Record task completion metrics.

        Args:
            message: The task message containing task_id and task_name.
            result: The task result containing return value or error.
        """
        task_id = message.task_id
        task_name = message.task_name

        # Calculate duration
        start_time = self._start_times.pop(task_id, None)
        if start_time is not None:
            duration_seconds = time.perf_counter() - start_time
            taskiq_task_duration_seconds.labels(task_name=task_name).observe(
                duration_seconds
            )

        # Record task completion status
        status = "failure" if result.is_err else "success"
        taskiq_tasks_total.labels(task_name=task_name, status=status).inc()

        logger.debug(
            "Task metrics recorded",
            extra={
                "task_id": task_id,
                "task_name": task_name,
                "status": status,
                "duration_seconds": duration_seconds if start_time else None,
            },
        )


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
                    task_args=tuple(message.args) if message.args else None,
                    task_kwargs=message.kwargs if message.kwargs else None,
                    labels=message.labels if message.labels else None,
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
        duration_ms = int((time.perf_counter() - start_time) * 1000) if start_time else 0

        # Determine status and extract error/return value
        if result.is_err:
            status = "failure"
            return_value = None
            error_raw = result.error
            # Convert BaseException to Exception if needed
            error: Exception | None = (
                error_raw
                if isinstance(error_raw, Exception)
                else Exception(str(error_raw))
                if error_raw
                else None
            )
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


class TimeoutMiddleware(TaskiqMiddleware):
    """Middleware that enforces task execution timeouts.

    This middleware wraps task execution in an asyncio timeout, ensuring
    tasks don't run indefinitely. Tasks can specify their own timeout via
    labels, or fall back to the default from settings.

    Example usage:
        broker = AioPikaBroker(...)
        broker.add_middlewares(TimeoutMiddleware())

        # Task with custom timeout (in seconds)
        @broker.task(timeout=60)
        async def quick_task(): ...

        # Or via labels
        @broker.task(labels={"timeout": 120})
        async def medium_task(): ...
    """

    def __init__(self, default_timeout: int | None = None) -> None:
        """Initialize the timeout middleware.

        Args:
            default_timeout: Default timeout in seconds. If not provided,
                            uses TASK_DEFAULT_TIMEOUT_SECONDS from settings.
        """
        super().__init__()
        self._default_timeout = default_timeout or task_settings.default_timeout_seconds
        self._timeouts: dict[str, int] = {}

    async def pre_execute(
        self,
        message: TaskiqMessage,
    ) -> TaskiqMessage:
        """Extract timeout from task labels.

        Args:
            message: The task message containing task_id and labels.

        Returns:
            The message, unmodified.
        """
        task_id = message.task_id

        # Check for timeout in labels
        timeout = self._default_timeout
        if message.labels:
            label_timeout = message.labels.get("timeout")
            if label_timeout is not None:
                try:
                    timeout = int(label_timeout)
                except (ValueError, TypeError):
                    logger.warning(
                        "Invalid timeout label, using default",
                        extra={"task_id": task_id, "label_timeout": label_timeout},
                    )

        self._timeouts[task_id] = timeout
        return message

    async def post_execute(
        self,
        message: TaskiqMessage,
        result: TaskiqResult[Any],
    ) -> None:
        """Clean up timeout tracking.

        Args:
            message: The task message.
            result: The task result.
        """
        self._timeouts.pop(message.task_id, None)


class TimeoutError(Exception):
    """Exception raised when a task exceeds its timeout."""

    def __init__(self, task_id: str, task_name: str, timeout_seconds: int) -> None:
        self.task_id = task_id
        self.task_name = task_name
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"Task '{task_name}' (id={task_id}) timed out after {timeout_seconds} seconds"
        )


class DeduplicationMiddleware(TaskiqMiddleware):
    """Middleware that prevents duplicate task submissions.

    This middleware checks if a task with the same name and arguments
    has been submitted recently. If so, it prevents the duplicate
    from being processed.

    Deduplication is based on a hash of:
    - Task name
    - Positional arguments (JSON serialized)
    - Keyword arguments (JSON serialized)

    Example usage:
        broker = AioPikaBroker(...)
        broker.add_middlewares(DeduplicationMiddleware())

        # Submit task
        await my_task.kiq(user_id=123)  # Executes

        # Submit again within TTL
        await my_task.kiq(user_id=123)  # Skipped (duplicate)

        # Different args = different task
        await my_task.kiq(user_id=456)  # Executes
    """

    def __init__(self, ttl_seconds: int | None = None) -> None:
        """Initialize the deduplication middleware.

        Args:
            ttl_seconds: How long to prevent duplicates (seconds).
                        If not provided, uses TASK_DEDUPLICATION_TTL_SECONDS.
        """
        super().__init__()
        self._ttl = ttl_seconds or task_settings.deduplication_ttl_seconds
        self._redis_client: Any = None
        self._key_prefix = "taskiq:dedup"

    async def startup(self) -> None:
        """Initialize Redis connection for deduplication."""
        if not task_settings.deduplication_enabled:
            logger.info("Task deduplication is disabled")
            return

        redis_settings = get_redis_settings()
        if not redis_settings.is_configured:
            logger.warning("Redis not configured - deduplication disabled")
            return

        try:
            from redis.asyncio import ConnectionPool, Redis

            pool = ConnectionPool.from_url(
                redis_settings.get_url(),
                max_connections=5,
                decode_responses=True,
            )
            self._redis_client = Redis(connection_pool=pool)
            await self._redis_client.ping()
            logger.info("Deduplication middleware initialized")
        except Exception as e:
            logger.warning(
                "Failed to initialize deduplication Redis",
                extra={"error": str(e)},
            )
            self._redis_client = None

    async def shutdown(self) -> None:
        """Close Redis connection."""
        if self._redis_client:
            await self._redis_client.close()
            self._redis_client = None

    def _compute_dedup_key(self, message: TaskiqMessage) -> str:
        """Compute a deduplication key from task message.

        Args:
            message: The task message.

        Returns:
            A unique key for this task + arguments combination.
        """
        # Serialize args and kwargs
        try:
            args_str = json.dumps(message.args, sort_keys=True, default=str)
        except (TypeError, ValueError):
            args_str = str(message.args)

        try:
            kwargs_str = json.dumps(message.kwargs, sort_keys=True, default=str)
        except (TypeError, ValueError):
            kwargs_str = str(message.kwargs)

        # Create hash
        content = f"{message.task_name}:{args_str}:{kwargs_str}"
        hash_val = hashlib.sha256(content.encode()).hexdigest()[:16]

        return f"{self._key_prefix}:{message.task_name}:{hash_val}"

    async def pre_execute(
        self,
        message: TaskiqMessage,
    ) -> TaskiqMessage:
        """Check for duplicate task and mark as processing.

        Args:
            message: The task message.

        Returns:
            The message, unmodified.

        Note:
            If a duplicate is detected, we add a 'skip_execution' label
            that other middleware can check.
        """
        if not self._redis_client or not task_settings.deduplication_enabled:
            return message

        dedup_key = self._compute_dedup_key(message)

        try:
            # Try to set the key (returns True if key was set, False if exists)
            was_set = await self._redis_client.set(
                dedup_key,
                message.task_id,
                nx=True,  # Only set if not exists
                ex=self._ttl,
            )

            if not was_set:
                # Duplicate detected
                existing_task_id = await self._redis_client.get(dedup_key)
                logger.info(
                    "Duplicate task detected, skipping",
                    extra={
                        "task_id": message.task_id,
                        "task_name": message.task_name,
                        "existing_task_id": existing_task_id,
                    },
                )
                # Mark message as duplicate (for tracking purposes)
                if message.labels is None:
                    message.labels = {}
                message.labels["_duplicate"] = True
                message.labels["_original_task_id"] = existing_task_id

        except Exception as e:
            logger.warning(
                "Deduplication check failed",
                extra={"task_id": message.task_id, "error": str(e)},
            )

        return message

    async def post_execute(
        self,
        message: TaskiqMessage,
        result: TaskiqResult[Any],
    ) -> None:
        """Clean up deduplication key after successful execution.

        Args:
            message: The task message.
            result: The task result.
        """
        if not self._redis_client or not task_settings.deduplication_enabled:
            return

        # Don't clean up if this was a duplicate (let original's key expire)
        if message.labels and message.labels.get("_duplicate"):
            return

        # Only clean up on success - let failures be retried
        if not result.is_err:
            dedup_key = self._compute_dedup_key(message)
            try:
                await self._redis_client.delete(dedup_key)
            except Exception as e:
                logger.warning(
                    "Failed to clean up deduplication key",
                    extra={"task_id": message.task_id, "error": str(e)},
                )


class DuplicateTaskError(Exception):
    """Exception raised when a duplicate task is detected."""

    def __init__(self, task_id: str, original_task_id: str) -> None:
        self.task_id = task_id
        self.original_task_id = original_task_id
        super().__init__(
            f"Duplicate task detected: {task_id} duplicates {original_task_id}"
        )


class DeadLetterQueueMiddleware(TaskiqMiddleware):
    """Middleware that handles failed tasks after max retries.

    When a task fails after exhausting all retries, this middleware
    moves it to a Dead Letter Queue (DLQ) for manual inspection and
    potential retry.

    DLQ entries contain:
    - Original task ID and name
    - Task arguments
    - Error information
    - Retry history
    - Timestamp

    Example usage:
        broker = AioPikaBroker(...)
        broker.add_middlewares(DeadLetterQueueMiddleware())

        # Query DLQ via REST API
        GET /api/v1/tasks/dlq
        POST /api/v1/tasks/dlq/{task_id}/retry
    """

    def __init__(self, max_retries: int | None = None) -> None:
        """Initialize the DLQ middleware.

        Args:
            max_retries: Maximum retries before moving to DLQ.
                        If not provided, uses TASK_DLQ_MAX_RETRIES.
        """
        super().__init__()
        self._max_retries = max_retries or task_settings.dlq_max_retries
        self._redis_client: Any = None
        self._key_prefix = "taskiq:dlq"
        self._retry_counts: dict[str, int] = {}

    async def startup(self) -> None:
        """Initialize Redis connection for DLQ."""
        if not task_settings.dlq_enabled:
            logger.info("Dead Letter Queue is disabled")
            return

        redis_settings = get_redis_settings()
        if not redis_settings.is_configured:
            logger.warning("Redis not configured - DLQ disabled")
            return

        try:
            from redis.asyncio import ConnectionPool, Redis

            pool = ConnectionPool.from_url(
                redis_settings.get_url(),
                max_connections=5,
                decode_responses=True,
            )
            self._redis_client = Redis(connection_pool=pool)
            await self._redis_client.ping()
            logger.info("DLQ middleware initialized")
        except Exception as e:
            logger.warning(
                "Failed to initialize DLQ Redis",
                extra={"error": str(e)},
            )
            self._redis_client = None

    async def shutdown(self) -> None:
        """Close Redis connection."""
        if self._redis_client:
            await self._redis_client.close()
            self._redis_client = None
        self._retry_counts.clear()

    def _dlq_entry_key(self, task_id: str) -> str:
        """Get the DLQ entry key."""
        return f"{self._key_prefix}:entry:{task_id}"

    def _dlq_index_key(self) -> str:
        """Get the DLQ index key (sorted set)."""
        return f"{self._key_prefix}:index"

    async def pre_execute(
        self,
        message: TaskiqMessage,
    ) -> TaskiqMessage:
        """Track retry count for the task.

        Args:
            message: The task message.

        Returns:
            The message, unmodified.
        """
        task_id = message.task_id

        # Check if this is a retry
        if message.labels and message.labels.get("_retry_count"):
            try:
                self._retry_counts[task_id] = int(message.labels["_retry_count"])
            except (ValueError, TypeError):
                self._retry_counts[task_id] = 0
        else:
            self._retry_counts[task_id] = 0

        return message

    async def post_execute(
        self,
        message: TaskiqMessage,
        result: TaskiqResult[Any],
    ) -> None:
        """Move task to DLQ if failed after max retries.

        Args:
            message: The task message.
            result: The task result.
        """
        task_id = message.task_id
        retry_count = self._retry_counts.pop(task_id, 0)

        if not result.is_err:
            return  # Success, no DLQ action needed

        if not self._redis_client or not task_settings.dlq_enabled:
            return

        # Check if max retries exceeded
        if retry_count < self._max_retries:
            logger.debug(
                "Task failed, will retry",
                extra={
                    "task_id": task_id,
                    "retry_count": retry_count,
                    "max_retries": self._max_retries,
                },
            )
            return

        # Move to DLQ
        try:
            from datetime import UTC, datetime

            now = datetime.now(UTC)
            timestamp = now.timestamp()

            # Prepare DLQ entry
            error_msg = str(result.error) if result.error else "Unknown error"
            error_type = type(result.error).__name__ if result.error else "Unknown"

            dlq_entry = {
                "task_id": task_id,
                "task_name": message.task_name,
                "args": json.dumps(message.args, default=str),
                "kwargs": json.dumps(message.kwargs, default=str),
                "labels": json.dumps(message.labels, default=str) if message.labels else "{}",
                "error_message": error_msg,
                "error_type": error_type,
                "retry_count": str(retry_count),
                "failed_at": now.isoformat(),
                "status": "pending",  # pending, retried, discarded
            }

            # Store in Redis
            entry_key = self._dlq_entry_key(task_id)
            pipe = self._redis_client.pipeline()
            pipe.hset(entry_key, mapping=dlq_entry)
            pipe.expire(entry_key, task_settings.dlq_retention_seconds)
            pipe.zadd(self._dlq_index_key(), {task_id: timestamp})
            await pipe.execute()

            logger.warning(
                "Task moved to Dead Letter Queue",
                extra={
                    "task_id": task_id,
                    "task_name": message.task_name,
                    "retry_count": retry_count,
                    "error_type": error_type,
                },
            )

        except Exception as e:
            logger.exception(
                "Failed to move task to DLQ",
                extra={"task_id": task_id, "error": str(e)},
            )

    async def get_dlq_entries(
        self,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get DLQ entries.

        Args:
            limit: Maximum number of entries to return.
            offset: Number of entries to skip.
            status: Filter by status (pending, retried, discarded).

        Returns:
            List of DLQ entries.
        """
        if not self._redis_client:
            return []

        try:
            # Get task IDs from index (newest first)
            task_ids = await self._redis_client.zrevrange(
                self._dlq_index_key(),
                offset,
                offset + limit - 1,
            )

            entries = []
            for task_id in task_ids:
                entry_key = self._dlq_entry_key(task_id)
                entry_data = await self._redis_client.hgetall(entry_key)

                if entry_data:
                    # Filter by status if specified
                    if status and entry_data.get("status") != status:
                        continue

                    # Parse JSON fields
                    entry = dict(entry_data)
                    for field in ["args", "kwargs", "labels"]:
                        if entry.get(field):
                            try:
                                entry[field] = json.loads(entry[field])
                            except (json.JSONDecodeError, TypeError):
                                pass

                    entries.append(entry)

            return entries

        except Exception as e:
            logger.warning("Failed to get DLQ entries", extra={"error": str(e)})
            return []

    async def get_dlq_count(self) -> int:
        """Get total number of DLQ entries.

        Returns:
            Count of DLQ entries.
        """
        if not self._redis_client:
            return 0

        try:
            return await self._redis_client.zcard(self._dlq_index_key())
        except Exception:
            return 0

    async def get_dlq_entry(self, task_id: str) -> dict[str, Any] | None:
        """Get a specific DLQ entry.

        Args:
            task_id: The task ID.

        Returns:
            DLQ entry or None if not found.
        """
        if not self._redis_client:
            return None

        try:
            entry_key = self._dlq_entry_key(task_id)
            entry_data = await self._redis_client.hgetall(entry_key)

            if not entry_data:
                return None

            entry = dict(entry_data)
            for field in ["args", "kwargs", "labels"]:
                if entry.get(field):
                    try:
                        entry[field] = json.loads(entry[field])
                    except (json.JSONDecodeError, TypeError):
                        pass

            return entry

        except Exception as e:
            logger.warning(
                "Failed to get DLQ entry",
                extra={"task_id": task_id, "error": str(e)},
            )
            return None

    async def update_dlq_status(
        self,
        task_id: str,
        status: str,
    ) -> bool:
        """Update the status of a DLQ entry.

        Args:
            task_id: The task ID.
            status: New status (pending, retried, discarded).

        Returns:
            True if updated, False otherwise.
        """
        if not self._redis_client:
            return False

        try:
            entry_key = self._dlq_entry_key(task_id)
            exists = await self._redis_client.exists(entry_key)

            if not exists:
                return False

            await self._redis_client.hset(entry_key, "status", status)
            return True

        except Exception as e:
            logger.warning(
                "Failed to update DLQ status",
                extra={"task_id": task_id, "error": str(e)},
            )
            return False

    async def remove_from_dlq(self, task_id: str) -> bool:
        """Remove an entry from the DLQ.

        Args:
            task_id: The task ID.

        Returns:
            True if removed, False otherwise.
        """
        if not self._redis_client:
            return False

        try:
            entry_key = self._dlq_entry_key(task_id)
            pipe = self._redis_client.pipeline()
            pipe.delete(entry_key)
            pipe.zrem(self._dlq_index_key(), task_id)
            await pipe.execute()
            return True

        except Exception as e:
            logger.warning(
                "Failed to remove from DLQ",
                extra={"task_id": task_id, "error": str(e)},
            )
            return False


class ProgressTrackingMiddleware(TaskiqMiddleware):
    """Middleware that enables task progress tracking.

    This middleware provides a mechanism for tasks to report their
    progress, which can be queried via the API. Progress is stored
    in Redis with automatic expiration.

    Example usage:
        @broker.task
        async def long_task(context: Context):
            for i in range(100):
                await process_item(i)
                await context.update_progress(
                    percent=i + 1,
                    message=f"Processing item {i + 1}/100"
                )

    Progress structure:
        {
            "percent": 45,
            "message": "Processing item 45/100",
            "current": 45,
            "total": 100,
            "updated_at": "2024-01-15T10:30:00Z"
        }
    """

    def __init__(self, throttle_ms: int | None = None) -> None:
        """Initialize the progress tracking middleware.

        Args:
            throttle_ms: Minimum interval between progress updates.
                        If not provided, uses TASK_PROGRESS_UPDATE_THROTTLE_MS.
        """
        super().__init__()
        self._throttle_ms = throttle_ms or task_settings.progress_update_throttle_ms
        self._redis_client: Any = None
        self._key_prefix = "taskiq:progress"
        self._last_updates: dict[str, float] = {}

    async def startup(self) -> None:
        """Initialize Redis connection for progress tracking."""
        if not task_settings.progress_tracking_enabled:
            logger.info("Progress tracking is disabled")
            return

        redis_settings = get_redis_settings()
        if not redis_settings.is_configured:
            logger.warning("Redis not configured - progress tracking disabled")
            return

        try:
            from redis.asyncio import ConnectionPool, Redis

            pool = ConnectionPool.from_url(
                redis_settings.get_url(),
                max_connections=5,
                decode_responses=True,
            )
            self._redis_client = Redis(connection_pool=pool)
            await self._redis_client.ping()
            logger.info("Progress tracking middleware initialized")
        except Exception as e:
            logger.warning(
                "Failed to initialize progress tracking Redis",
                extra={"error": str(e)},
            )
            self._redis_client = None

    async def shutdown(self) -> None:
        """Close Redis connection."""
        if self._redis_client:
            await self._redis_client.close()
            self._redis_client = None
        self._last_updates.clear()

    def _progress_key(self, task_id: str) -> str:
        """Get the progress key for a task."""
        return f"{self._key_prefix}:{task_id}"

    async def update_progress(
        self,
        task_id: str,
        percent: float | None = None,
        message: str | None = None,
        current: int | None = None,
        total: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> bool:
        """Update task progress.

        Args:
            task_id: The task ID.
            percent: Progress percentage (0-100).
            message: Progress message.
            current: Current item number.
            total: Total items.
            extra: Additional progress data.

        Returns:
            True if updated, False otherwise (throttled or error).
        """
        if not self._redis_client or not task_settings.progress_tracking_enabled:
            return False

        # Check throttle
        now = time.time() * 1000
        last_update = self._last_updates.get(task_id, 0)
        if now - last_update < self._throttle_ms:
            return False

        try:
            from datetime import UTC, datetime

            progress_data = {
                "task_id": task_id,
                "updated_at": datetime.now(UTC).isoformat(),
            }

            if percent is not None:
                progress_data["percent"] = min(100, max(0, percent))
            if message is not None:
                progress_data["message"] = message
            if current is not None:
                progress_data["current"] = current
            if total is not None:
                progress_data["total"] = total
            if extra:
                progress_data["extra"] = json.dumps(extra, default=str)

            progress_key = self._progress_key(task_id)
            await self._redis_client.hset(progress_key, mapping=progress_data)
            await self._redis_client.expire(progress_key, 3600)  # 1 hour TTL

            self._last_updates[task_id] = now
            return True

        except Exception as e:
            logger.warning(
                "Failed to update progress",
                extra={"task_id": task_id, "error": str(e)},
            )
            return False

    async def get_progress(self, task_id: str) -> dict[str, Any] | None:
        """Get task progress.

        Args:
            task_id: The task ID.

        Returns:
            Progress data or None if not found.
        """
        if not self._redis_client:
            return None

        try:
            progress_key = self._progress_key(task_id)
            progress_data = await self._redis_client.hgetall(progress_key)

            if not progress_data:
                return None

            # Parse numeric fields
            result = dict(progress_data)
            for field in ["percent", "current", "total"]:
                if field in result:
                    try:
                        result[field] = float(result[field]) if field == "percent" else int(result[field])
                    except (ValueError, TypeError):
                        pass

            # Parse extra data
            if "extra" in result:
                try:
                    result["extra"] = json.loads(result["extra"])
                except (json.JSONDecodeError, TypeError):
                    pass

            return result

        except Exception as e:
            logger.warning(
                "Failed to get progress",
                extra={"task_id": task_id, "error": str(e)},
            )
            return None

    async def clear_progress(self, task_id: str) -> bool:
        """Clear task progress.

        Args:
            task_id: The task ID.

        Returns:
            True if cleared, False otherwise.
        """
        if not self._redis_client:
            return False

        try:
            progress_key = self._progress_key(task_id)
            await self._redis_client.delete(progress_key)
            self._last_updates.pop(task_id, None)
            return True

        except Exception as e:
            logger.warning(
                "Failed to clear progress",
                extra={"task_id": task_id, "error": str(e)},
            )
            return False

    async def post_execute(
        self,
        message: TaskiqMessage,
        result: TaskiqResult[Any],
    ) -> None:
        """Set final progress on task completion.

        Args:
            message: The task message.
            result: The task result.
        """
        if not self._redis_client or not task_settings.progress_tracking_enabled:
            return

        task_id = message.task_id

        # Set final progress
        if result.is_err:
            await self.update_progress(
                task_id,
                message="Task failed",
                extra={"status": "failed", "error": str(result.error)},
            )
        else:
            await self.update_progress(
                task_id,
                percent=100,
                message="Completed",
                extra={"status": "completed"},
            )


# Global middleware instances for use by the service layer
_dlq_middleware: DeadLetterQueueMiddleware | None = None
_progress_middleware: ProgressTrackingMiddleware | None = None


def get_dlq_middleware() -> DeadLetterQueueMiddleware | None:
    """Get the global DLQ middleware instance."""
    return _dlq_middleware


def set_dlq_middleware(middleware: DeadLetterQueueMiddleware) -> None:
    """Set the global DLQ middleware instance."""
    global _dlq_middleware
    _dlq_middleware = middleware


def get_progress_middleware() -> ProgressTrackingMiddleware | None:
    """Get the global progress middleware instance."""
    return _progress_middleware


def set_progress_middleware(middleware: ProgressTrackingMiddleware) -> None:
    """Set the global progress middleware instance."""
    global _progress_middleware
    _progress_middleware = middleware
