"""Redis-based task execution tracker.

This module provides a Redis implementation of the task tracker interface,
storing task execution data in Redis with configurable TTL.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
import json
import logging
from typing import TYPE_CHECKING, Any, cast

from redis.asyncio import ConnectionPool, Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from example_service.infra.tasks.tracking.base import (
    BaseTaskTracker,
    TaskExecutionDetails,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)


class RedisTaskTracker(BaseTaskTracker):
    """Task execution tracker using Redis storage.

    This tracker stores task execution records in Redis with support for:
    - Configurable TTL for automatic cleanup
    - Sorted sets for efficient time-based queries
    - Hash storage for task details
    - Running task markers for quick status checks

    Redis Key Structure:
    - {prefix}:exec:{task_id} - Hash with full execution details
    - {prefix}:running:{task_id} - String marker for running tasks
    - {prefix}:index:all - Sorted set of all task IDs by timestamp
    - {prefix}:index:name:{name} - Sorted set of task IDs by task name
    - {prefix}:index:status:{status} - Sorted set of task IDs by status

    Example:
            tracker = RedisTaskTracker(
            redis_url="redis://localhost:6379/0",
            key_prefix="taskiq",
            ttl_seconds=86400,  # 24 hours
        )
        await tracker.connect()

        # Record task start
        await tracker.on_task_start("task-123", "backup_database")

        # Get task history
        history = await tracker.get_task_history(limit=100)
    """

    def __init__(
        self,
        redis_url: str,
        *,
        key_prefix: str = "task",
        ttl_seconds: int = 86400,
        running_ttl_seconds: int = 3600,
        max_connections: int = 10,
    ) -> None:
        """Initialize Redis task tracker.

        Args:
            redis_url: Redis connection URL.
            key_prefix: Prefix for all Redis keys.
            ttl_seconds: TTL for execution records (default: 24 hours).
            running_ttl_seconds: TTL for running markers (default: 1 hour).
            max_connections: Maximum Redis connections.
        """
        self.redis_url = redis_url
        self.key_prefix = key_prefix
        self.ttl_seconds = ttl_seconds
        self.running_ttl_seconds = running_ttl_seconds
        self.max_connections = max_connections

        self._pool: ConnectionPool | None = None
        self._client: Redis | None = None

    # Key generation helpers
    def _exec_key(self, task_id: str) -> str:
        return f"{self.key_prefix}:exec:{task_id}"

    def _running_key(self, task_id: str) -> str:
        return f"{self.key_prefix}:running:{task_id}"

    def _index_all_key(self) -> str:
        return f"{self.key_prefix}:index:all"

    def _index_name_key(self, task_name: str) -> str:
        return f"{self.key_prefix}:index:name:{task_name}"

    def _index_status_key(self, status: str) -> str:
        return f"{self.key_prefix}:index:status:{status}"

    async def connect(self) -> None:
        """Establish connection to Redis."""
        logger.info("Connecting to Redis for task tracking")

        try:
            self._pool = ConnectionPool.from_url(
                self.redis_url,
                max_connections=self.max_connections,
                decode_responses=True,
                encoding="utf-8",
            )
            self._client = Redis(connection_pool=self._pool)

            # Test connection
            await self._client.ping()
            logger.info("Task tracking Redis connection established")
        except Exception as e:
            logger.exception(
                "Failed to connect to Redis for task tracking",
                extra={"error": str(e)},
            )
            raise

    async def disconnect(self) -> None:
        """Close Redis connection."""
        logger.info("Disconnecting task tracking Redis")

        if self._client:
            await self._client.close()
            self._client = None

        if self._pool:
            await self._pool.disconnect()
            self._pool = None

        logger.info("Task tracking Redis connection closed")

    @property
    def is_connected(self) -> bool:
        """Check if connected to Redis."""
        return self._client is not None

    @property
    def client(self) -> Redis:
        """Get the Redis client instance."""
        if self._client is None:
            msg = "Task tracker not connected. Call connect() first."
            raise RuntimeError(msg)
        return self._client

    async def on_task_start(
        self,
        task_id: str,
        task_name: str,
        worker_id: str | None = None,
        queue_name: str | None = None,
        task_args: tuple[Any, ...] | None = None,
        task_kwargs: dict[str, Any] | None = None,
        labels: dict[str, Any] | None = None,
    ) -> None:
        """Record task start event."""
        if not self.is_connected:
            return

        now = datetime.now(UTC)
        timestamp = now.timestamp()

        try:
            exec_key = self._exec_key(task_id)
            running_key = self._running_key(task_id)

            # Serialize args/kwargs
            args_str = ""
            if task_args:
                try:
                    args_str = json.dumps(list(task_args), default=str)
                except (TypeError, ValueError):
                    args_str = str(task_args)

            kwargs_str = ""
            if task_kwargs:
                try:
                    kwargs_str = json.dumps(task_kwargs, default=str)
                except (TypeError, ValueError):
                    kwargs_str = str(task_kwargs)

            labels_str = ""
            if labels:
                try:
                    labels_str = json.dumps(labels, default=str)
                except (TypeError, ValueError):
                    labels_str = str(labels)

            exec_data: dict[str, str | int | float | bytes] = {
                "task_id": task_id,
                "task_name": task_name,
                "status": "running",
                "started_at": now.isoformat(),
                "finished_at": "",
                "duration_ms": "",
                "return_value": "",
                "error_message": "",
                "error_type": "",
                "retry_count": "0",
                "worker_id": worker_id or "",
                "queue_name": queue_name or "",
                "task_args": args_str,
                "task_kwargs": kwargs_str,
                "labels": labels_str,
            }

            pipe = self.client.pipeline()

            # Store execution record
            pipe.hset(
                exec_key,
                mapping=cast(
                    "Mapping[str | bytes, bytes | float | int | str]",
                    exec_data,
                ),
            )
            pipe.expire(exec_key, self.ttl_seconds)

            # Set running marker
            pipe.set(running_key, now.isoformat(), ex=self.running_ttl_seconds)

            # Add to indices
            pipe.zadd(self._index_all_key(), {task_id: timestamp})
            pipe.zadd(self._index_name_key(task_name), {task_id: timestamp})
            pipe.zadd(self._index_status_key("running"), {task_id: timestamp})

            await pipe.execute()

            logger.debug(
                "Task started",
                extra={"task_id": task_id, "task_name": task_name},
            )
        except (RedisConnectionError, RedisTimeoutError) as e:
            logger.warning(
                "Failed to record task start",
                extra={"task_id": task_id, "error": str(e)},
            )

    async def on_task_finish(
        self,
        task_id: str,
        status: str,
        return_value: Any | None,
        error: Exception | None,
        duration_ms: int,
    ) -> None:
        """Record task completion event."""
        if not self.is_connected:
            return

        now = datetime.now(UTC)
        timestamp = now.timestamp()

        try:
            exec_key = self._exec_key(task_id)
            running_key = self._running_key(task_id)

            # Get current task data
            task_data = await self.client.hgetall(exec_key)
            if not task_data:
                logger.warning(
                    "Task execution record not found",
                    extra={"task_id": task_id},
                )
                return

            task_name = task_data.get("task_name", "unknown")

            # Serialize return value
            return_value_str = ""
            if return_value is not None:
                try:
                    return_value_str = json.dumps(return_value, default=str)
                except (TypeError, ValueError):
                    return_value_str = str(return_value)

            # Prepare error data
            error_message = ""
            error_type = ""
            if error is not None:
                error_message = str(error)
                error_type = type(error).__name__

            update_data: dict[str, str | int | float | bytes] = {
                "status": status,
                "finished_at": now.isoformat(),
                "duration_ms": str(duration_ms),
                "return_value": return_value_str,
                "error_message": error_message,
                "error_type": error_type,
            }

            pipe = self.client.pipeline()

            # Update execution record
            pipe.hset(
                exec_key,
                mapping=cast(
                    "Mapping[str | bytes, bytes | float | int | str]",
                    update_data,
                ),
            )
            pipe.expire(exec_key, self.ttl_seconds)  # Refresh TTL

            # Remove running marker
            pipe.delete(running_key)

            # Update status indices
            pipe.zrem(self._index_status_key("running"), task_id)
            pipe.zadd(self._index_status_key(status), {task_id: timestamp})

            await pipe.execute()

            logger.debug(
                "Task finished",
                extra={
                    "task_id": task_id,
                    "task_name": task_name,
                    "status": status,
                    "duration_ms": duration_ms,
                },
            )
        except (RedisConnectionError, RedisTimeoutError) as e:
            logger.warning(
                "Failed to record task finish",
                extra={"task_id": task_id, "error": str(e)},
            )

    async def get_running_tasks(self) -> list[dict[str, Any]]:
        """Get all currently running tasks."""
        if not self.is_connected:
            return []

        try:
            task_ids = await self.client.zrevrange(
                self._index_status_key("running"),
                0,
                -1,
            )

            if not task_ids:
                return []

            tasks = []
            for task_id in task_ids:
                exec_key = self._exec_key(task_id)
                task_data = await self.client.hgetall(exec_key)

                if task_data:
                    started_at = task_data.get("started_at", "")
                    running_for_ms = 0
                    if started_at:
                        try:
                            start_time = datetime.fromisoformat(started_at)
                            running_for_ms = int(
                                (datetime.now(UTC) - start_time).total_seconds() * 1000,
                            )
                        except ValueError:
                            pass

                    tasks.append({
                        "task_id": task_data.get("task_id", task_id),
                        "task_name": task_data.get("task_name", "unknown"),
                        "started_at": started_at,
                        "running_for_ms": running_for_ms,
                        "worker_id": task_data.get("worker_id", "") or None,
                    })

            return tasks
        except (RedisConnectionError, RedisTimeoutError) as e:
            logger.warning("Failed to get running tasks", extra={"error": str(e)})
            return []

    def _passes_filters(
        self,
        task_data: dict[str, str],
        *,
        task_name: str | None = None,
        status: str | None = None,
        worker_id: str | None = None,
        error_type: str | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        min_duration_ms: int | None = None,
        max_duration_ms: int | None = None,
    ) -> tuple[bool, int | None]:
        """Check whether task data matches provided filters."""
        if task_name and status and task_data.get("status") != status:
            return False, None
        if worker_id and task_data.get("worker_id") != worker_id:
            return False, None
        if error_type and task_data.get("error_type") != error_type:
            return False, None

        duration_ms = None
        duration_str = task_data.get("duration_ms", "")
        if duration_str:
            with contextlib.suppress(ValueError):
                duration_ms = int(duration_str)

        if min_duration_ms is not None and (
            duration_ms is None or duration_ms < min_duration_ms
        ):
            return False, duration_ms
        if max_duration_ms is not None and (
            duration_ms is None or duration_ms > max_duration_ms
        ):
            return False, duration_ms

        started_at = task_data.get("started_at", "")
        if created_after and started_at and started_at < created_after:
            return False, duration_ms
        if created_before and started_at and started_at > created_before:
            return False, duration_ms

        return True, duration_ms

    async def get_task_history(
        self,
        limit: int = 100,
        offset: int = 0,
        task_name: str | None = None,
        status: str | None = None,
        worker_id: str | None = None,
        error_type: str | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        min_duration_ms: int | None = None,
        max_duration_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        """Get recent task executions with optional filters."""
        if not self.is_connected:
            return []

        try:
            # Determine which index to use (primary filter)
            if task_name:
                index_key = self._index_name_key(task_name)
            elif status:
                index_key = self._index_status_key(status)
            else:
                index_key = self._index_all_key()

            # Get task IDs from index (newest first)
            # Fetch extra to account for secondary filters
            fetch_limit = (
                (offset + limit) * 3
                if any([worker_id, error_type, min_duration_ms, max_duration_ms])
                else offset + limit
            )
            task_ids = await self.client.zrevrange(index_key, 0, fetch_limit - 1)

            if not task_ids:
                return []

            # Fetch and filter execution records
            tasks = []
            skipped = 0

            for task_id in task_ids:
                exec_key = self._exec_key(task_id)
                task_data = await self.client.hgetall(exec_key)

                if not task_data:
                    continue

                matches_filters, duration_ms = self._passes_filters(
                    task_data,
                    task_name=task_name,
                    status=status,
                    worker_id=worker_id,
                    error_type=error_type,
                    created_after=created_after,
                    created_before=created_before,
                    min_duration_ms=min_duration_ms,
                    max_duration_ms=max_duration_ms,
                )

                if not matches_filters:
                    continue

                # Skip offset records
                if skipped < offset:
                    skipped += 1
                    continue

                started_at = task_data.get("started_at", "")

                # Parse return_value
                return_value = None
                return_value_str = task_data.get("return_value", "")
                if return_value_str:
                    try:
                        return_value = json.loads(return_value_str)
                    except (json.JSONDecodeError, TypeError):
                        return_value = return_value_str

                tasks.append({
                    "task_id": task_data.get("task_id", task_id),
                    "task_name": task_data.get("task_name", "unknown"),
                    "status": task_data.get("status", "unknown"),
                    "started_at": started_at,
                    "finished_at": task_data.get("finished_at", "") or None,
                    "duration_ms": duration_ms,
                    "return_value": return_value,
                    "error_message": task_data.get("error_message", "") or None,
                    "error_type": task_data.get("error_type", "") or None,
                    "worker_id": task_data.get("worker_id", "") or None,
                })

                if len(tasks) >= limit:
                    break

            return tasks
        except (RedisConnectionError, RedisTimeoutError) as e:
            logger.warning("Failed to get task history", extra={"error": str(e)})
            return []

    async def count_task_history(
        self,
        task_name: str | None = None,
        status: str | None = None,
        worker_id: str | None = None,
        error_type: str | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        min_duration_ms: int | None = None,
        max_duration_ms: int | None = None,
    ) -> int:
        """Count task executions matching the given filters."""
        if not self.is_connected:
            return 0

        try:
            if task_name:
                index_key = self._index_name_key(task_name)
            elif status:
                index_key = self._index_status_key(status)
            else:
                index_key = self._index_all_key()

            task_ids = await self.client.zrevrange(index_key, 0, -1)
            if not task_ids:
                return 0

            total = 0
            for task_id in task_ids:
                exec_key = self._exec_key(task_id)
                task_data = await self.client.hgetall(exec_key)
                if not task_data:
                    continue

                matches_filters, _ = self._passes_filters(
                    task_data,
                    task_name=task_name,
                    status=status,
                    worker_id=worker_id,
                    error_type=error_type,
                    created_after=created_after,
                    created_before=created_before,
                    min_duration_ms=min_duration_ms,
                    max_duration_ms=max_duration_ms,
                )

                if matches_filters:
                    total += 1

            return total
        except (RedisConnectionError, RedisTimeoutError) as e:
            logger.warning("Failed to count task history", extra={"error": str(e)})
            return 0

    async def get_task_details(self, task_id: str) -> TaskExecutionDetails | None:
        """Get full details for a specific task execution."""
        if not self.is_connected:
            return None

        try:
            exec_key = self._exec_key(task_id)
            task_data = await self.client.hgetall(exec_key)

            if not task_data:
                return None

            # Parse return_value
            return_value = None
            return_value_str = task_data.get("return_value", "")
            if return_value_str:
                try:
                    return_value = json.loads(return_value_str)
                except (json.JSONDecodeError, TypeError):
                    return_value = return_value_str

            # Parse duration
            duration_ms = None
            duration_str = task_data.get("duration_ms", "")
            if duration_str:
                with contextlib.suppress(ValueError):
                    duration_ms = int(duration_str)

            # Parse retry count
            retry_count = 0
            retry_str = task_data.get("retry_count", "0")
            with contextlib.suppress(ValueError):
                retry_count = int(retry_str)

            # Parse args/kwargs/labels
            task_args = None
            args_str = task_data.get("task_args", "")
            if args_str:
                try:
                    task_args = json.loads(args_str)
                except (json.JSONDecodeError, TypeError):
                    task_args = args_str

            task_kwargs = None
            kwargs_str = task_data.get("task_kwargs", "")
            if kwargs_str:
                try:
                    task_kwargs = json.loads(kwargs_str)
                except (json.JSONDecodeError, TypeError):
                    task_kwargs = kwargs_str

            labels = None
            labels_str = task_data.get("labels", "")
            if labels_str:
                try:
                    labels = json.loads(labels_str)
                except (json.JSONDecodeError, TypeError):
                    labels = labels_str

            return {
                "task_id": task_data.get("task_id", task_id),
                "task_name": task_data.get("task_name", "unknown"),
                "status": task_data.get("status", "unknown"),
                "started_at": task_data.get("started_at", ""),
                "finished_at": task_data.get("finished_at", "") or None,
                "duration_ms": duration_ms,
                "return_value": return_value,
                "error_message": task_data.get("error_message", "") or None,
                "error_type": task_data.get("error_type", "") or None,
                "retry_count": retry_count,
                "worker_id": task_data.get("worker_id", "") or None,
                "queue_name": task_data.get("queue_name", "") or None,
                "task_args": task_args,
                "task_kwargs": task_kwargs,
                "labels": labels,
            }
        except (RedisConnectionError, RedisTimeoutError) as e:
            logger.warning(
                "Failed to get task details",
                extra={"task_id": task_id, "error": str(e)},
            )
            return None

    async def get_stats(self, _hours: int = 24) -> dict[str, Any]:
        """Get summary statistics for task executions."""
        if not self.is_connected:
            return {
                "total_count": 0,
                "success_count": 0,
                "failure_count": 0,
                "running_count": 0,
                "cancelled_count": 0,
                "by_task_name": {},
                "avg_duration_ms": None,
            }

        try:
            # Count by status
            running_count = await self.client.zcard(self._index_status_key("running"))
            success_count = await self.client.zcard(self._index_status_key("success"))
            failure_count = await self.client.zcard(self._index_status_key("failure"))
            cancelled_count = await self.client.zcard(
                self._index_status_key("cancelled"),
            )
            total = await self.client.zcard(self._index_all_key())

            # Get counts by task name
            by_task_name: dict[str, int] = {}
            async for key in self.client.scan_iter(
                match=f"{self.key_prefix}:index:name:*",
            ):
                task_name = key.replace(f"{self.key_prefix}:index:name:", "")
                count = await self.client.zcard(key)
                if count > 0:
                    by_task_name[task_name] = count

            # Calculate average duration
            avg_duration_ms: float | None = None
            recent_task_ids = await self.client.zrevrange(
                self._index_status_key("success"),
                0,
                99,  # Sample last 100 successful tasks
            )

            if recent_task_ids:
                durations = []
                for task_id in recent_task_ids:
                    exec_key = self._exec_key(task_id)
                    duration_str = await self.client.hget(exec_key, "duration_ms")
                    if duration_str:
                        with contextlib.suppress(ValueError):
                            durations.append(int(duration_str))

                if durations:
                    avg_duration_ms = sum(durations) / len(durations)

            return {
                "total_count": total,
                "success_count": success_count,
                "failure_count": failure_count,
                "running_count": running_count,
                "cancelled_count": cancelled_count,
                "by_task_name": by_task_name,
                "avg_duration_ms": avg_duration_ms,
            }
        except (RedisConnectionError, RedisTimeoutError) as e:
            logger.warning("Failed to get task stats", extra={"error": str(e)})
            return {
                "total_count": 0,
                "success_count": 0,
                "failure_count": 0,
                "running_count": 0,
                "cancelled_count": 0,
                "by_task_name": {},
                "avg_duration_ms": None,
            }

    async def cancel_task(self, task_id: str) -> bool:
        """Mark a task as cancelled."""
        if not self.is_connected:
            return False

        try:
            exec_key = self._exec_key(task_id)
            task_data = await self.client.hgetall(exec_key)

            if not task_data:
                return False

            current_status = task_data.get("status")
            if current_status not in ("pending", "running"):
                return False  # Can only cancel pending/running tasks

            now = datetime.now(UTC)
            timestamp = now.timestamp()

            pipe = self.client.pipeline()

            # Update status
            pipe.hset(
                exec_key,
                mapping={
                    "status": "cancelled",
                    "finished_at": now.isoformat(),
                },
            )

            # Update indices
            if current_status == "running":
                pipe.zrem(self._index_status_key("running"), task_id)
                pipe.delete(self._running_key(task_id))
            pipe.zadd(self._index_status_key("cancelled"), {task_id: timestamp})

            await pipe.execute()
            return True
        except (RedisConnectionError, RedisTimeoutError) as e:
            logger.warning(
                "Failed to cancel task",
                extra={"task_id": task_id, "error": str(e)},
            )
            return False
