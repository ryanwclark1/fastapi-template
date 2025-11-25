"""Task execution tracking with Redis storage.

This module provides a TaskExecutionTracker that stores task execution
history in Redis. It supports:
- Recording task start/finish events
- Querying task history with filters
- Getting currently running tasks
- Computing statistics

Redis Key Structure:
- task:exec:{task_id} - Hash with full execution details (24h TTL)
- task:running:{task_id} - String marker for running tasks (1h TTL)
- task:index:all - Sorted set of all task IDs by timestamp
- task:index:name:{name} - Sorted set of task IDs by task name
- task:index:status:{status} - Sorted set of task IDs by status
"""
from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from redis.asyncio import ConnectionPool, Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from example_service.core.settings import get_redis_settings

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)
redis_settings = get_redis_settings()


class TaskExecutionTracker:
    """Tracks task execution lifecycle in Redis.

    This class stores task execution records in Redis and provides
    methods to query task history, running tasks, and statistics.

    Example:
        ```python
        tracker = TaskExecutionTracker()
        await tracker.connect()

        # Record task start
        await tracker.on_task_start("task-123", "backup_database")

        # Record task finish
        await tracker.on_task_finish(
            task_id="task-123",
            status="success",
            return_value={"backup_path": "/path/to/backup"},
            error=None,
            duration_ms=5000,
        )

        # Query history
        history = await tracker.get_task_history(limit=100)

        await tracker.disconnect()
        ```
    """

    # Key prefixes
    KEY_PREFIX = "task:"
    EXEC_PREFIX = "task:exec:"
    RUNNING_PREFIX = "task:running:"
    INDEX_ALL = "task:index:all"
    INDEX_NAME_PREFIX = "task:index:name:"
    INDEX_STATUS_PREFIX = "task:index:status:"

    # TTLs
    EXEC_TTL = 86400  # 24 hours for execution records
    RUNNING_TTL = 3600  # 1 hour for running markers (safety cleanup)

    def __init__(self) -> None:
        """Initialize task execution tracker."""
        self._pool: ConnectionPool | None = None
        self._client: Redis | None = None

    async def connect(self) -> None:
        """Establish connection to Redis.

        Raises:
            RedisConnectionError: If unable to connect to Redis.
        """
        if not redis_settings.is_configured:
            logger.warning("Redis not configured - task tracking disabled")
            return

        logger.info("Connecting to Redis for task tracking")

        try:
            self._pool = ConnectionPool.from_url(
                redis_settings.get_url(),
                max_connections=10,
                decode_responses=True,
                encoding="utf-8",
            )
            self._client = Redis(connection_pool=self._pool)

            # Test connection
            await self._client.ping()
            logger.info("Task tracking Redis connection established")
        except Exception as e:
            logger.exception("Failed to connect to Redis for task tracking", extra={"error": str(e)})
            raise

    async def disconnect(self) -> None:
        """Close Redis connection and cleanup resources."""
        logger.info("Disconnecting task tracking Redis")

        if self._client:
            await self._client.aclose()
            self._client = None

        if self._pool:
            await self._pool.aclose()
            self._pool = None

        logger.info("Task tracking Redis connection closed")

    @property
    def client(self) -> Redis:
        """Get the Redis client instance.

        Returns:
            Redis client.

        Raises:
            RuntimeError: If not connected.
        """
        if self._client is None:
            raise RuntimeError("Task tracker not connected. Call connect() first.")
        return self._client

    @property
    def is_connected(self) -> bool:
        """Check if connected to Redis."""
        return self._client is not None

    async def on_task_start(
        self,
        task_id: str,
        task_name: str,
        worker_id: str | None = None,
    ) -> None:
        """Record task start event.

        This creates a running marker and initializes the execution record.

        Args:
            task_id: Unique task identifier.
            task_name: Name of the task function.
            worker_id: Optional worker identifier.
        """
        if not self.is_connected:
            return

        now = datetime.now(UTC)
        timestamp = now.timestamp()

        try:
            # Create execution record hash
            exec_key = f"{self.EXEC_PREFIX}{task_id}"
            running_key = f"{self.RUNNING_PREFIX}{task_id}"

            exec_data = {
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
            }

            pipe = self.client.pipeline()

            # Store execution record
            pipe.hset(exec_key, mapping=exec_data)
            pipe.expire(exec_key, self.EXEC_TTL)

            # Set running marker
            pipe.set(running_key, now.isoformat(), ex=self.RUNNING_TTL)

            # Add to indices
            pipe.zadd(self.INDEX_ALL, {task_id: timestamp})
            pipe.zadd(f"{self.INDEX_NAME_PREFIX}{task_name}", {task_id: timestamp})
            pipe.zadd(f"{self.INDEX_STATUS_PREFIX}running", {task_id: timestamp})

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
        """Record task completion event.

        This updates the execution record and removes the running marker.

        Args:
            task_id: Unique task identifier.
            status: Completion status ("success" or "failure").
            return_value: Task return value (will be JSON serialized).
            error: Exception if task failed.
            duration_ms: Task execution duration in milliseconds.
        """
        if not self.is_connected:
            return

        now = datetime.now(UTC)
        timestamp = now.timestamp()

        try:
            exec_key = f"{self.EXEC_PREFIX}{task_id}"
            running_key = f"{self.RUNNING_PREFIX}{task_id}"

            # Get current task data to find task_name
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

            # Update execution record
            update_data = {
                "status": status,
                "finished_at": now.isoformat(),
                "duration_ms": str(duration_ms),
                "return_value": return_value_str,
                "error_message": error_message,
                "error_type": error_type,
            }

            pipe = self.client.pipeline()

            # Update execution record
            pipe.hset(exec_key, mapping=update_data)
            pipe.expire(exec_key, self.EXEC_TTL)  # Refresh TTL

            # Remove running marker
            pipe.delete(running_key)

            # Update status indices
            pipe.zrem(f"{self.INDEX_STATUS_PREFIX}running", task_id)
            pipe.zadd(f"{self.INDEX_STATUS_PREFIX}{status}", {task_id: timestamp})

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
        """Get all currently running tasks.

        Returns:
            List of running task records.
        """
        if not self.is_connected:
            return []

        try:
            # Get all running task IDs from index
            task_ids = await self.client.zrevrange(
                f"{self.INDEX_STATUS_PREFIX}running",
                0,
                -1,
            )

            if not task_ids:
                return []

            # Fetch execution records
            tasks = []
            for task_id in task_ids:
                exec_key = f"{self.EXEC_PREFIX}{task_id}"
                task_data = await self.client.hgetall(exec_key)

                if task_data:
                    # Calculate running duration
                    started_at = task_data.get("started_at", "")
                    running_for_ms = 0
                    if started_at:
                        try:
                            start_time = datetime.fromisoformat(started_at)
                            running_for_ms = int(
                                (datetime.now(UTC) - start_time).total_seconds() * 1000
                            )
                        except ValueError:
                            pass

                    tasks.append({
                        "task_id": task_data.get("task_id", task_id),
                        "task_name": task_data.get("task_name", "unknown"),
                        "started_at": started_at,
                        "running_for_ms": running_for_ms,
                        "worker_id": task_data.get("worker_id", ""),
                    })

            return tasks
        except (RedisConnectionError, RedisTimeoutError) as e:
            logger.warning("Failed to get running tasks", extra={"error": str(e)})
            return []

    async def get_task_history(
        self,
        limit: int = 100,
        offset: int = 0,
        task_name: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get recent task executions with optional filters.

        Args:
            limit: Maximum number of results.
            offset: Number of results to skip.
            task_name: Filter by task name.
            status: Filter by status ("success" or "failure").

        Returns:
            List of task execution records, newest first.
        """
        if not self.is_connected:
            return []

        try:
            # Determine which index to use
            if task_name:
                index_key = f"{self.INDEX_NAME_PREFIX}{task_name}"
            elif status:
                index_key = f"{self.INDEX_STATUS_PREFIX}{status}"
            else:
                index_key = self.INDEX_ALL

            # Get task IDs from index (newest first)
            start = offset
            end = offset + limit - 1
            task_ids = await self.client.zrevrange(index_key, start, end)

            if not task_ids:
                return []

            # Fetch execution records
            tasks = []
            for task_id in task_ids:
                exec_key = f"{self.EXEC_PREFIX}{task_id}"
                task_data = await self.client.hgetall(exec_key)

                if task_data:
                    # Apply additional filters if both task_name and status specified
                    if task_name and status:
                        if task_data.get("status") != status:
                            continue

                    # Parse return_value back to object
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
                        try:
                            duration_ms = int(duration_str)
                        except ValueError:
                            pass

                    tasks.append({
                        "task_id": task_data.get("task_id", task_id),
                        "task_name": task_data.get("task_name", "unknown"),
                        "status": task_data.get("status", "unknown"),
                        "started_at": task_data.get("started_at", ""),
                        "finished_at": task_data.get("finished_at", "") or None,
                        "duration_ms": duration_ms,
                        "return_value": return_value,
                        "error_message": task_data.get("error_message", "") or None,
                        "error_type": task_data.get("error_type", "") or None,
                    })

            return tasks
        except (RedisConnectionError, RedisTimeoutError) as e:
            logger.warning("Failed to get task history", extra={"error": str(e)})
            return []

    async def get_task_details(self, task_id: str) -> dict[str, Any] | None:
        """Get full details for a specific task execution.

        Args:
            task_id: Task identifier.

        Returns:
            Task execution record or None if not found.
        """
        if not self.is_connected:
            return None

        try:
            exec_key = f"{self.EXEC_PREFIX}{task_id}"
            task_data = await self.client.hgetall(exec_key)

            if not task_data:
                return None

            # Parse return_value back to object
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
                try:
                    duration_ms = int(duration_str)
                except ValueError:
                    pass

            # Parse retry count
            retry_count = 0
            retry_str = task_data.get("retry_count", "0")
            try:
                retry_count = int(retry_str)
            except ValueError:
                pass

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
            }
        except (RedisConnectionError, RedisTimeoutError) as e:
            logger.warning(
                "Failed to get task details",
                extra={"task_id": task_id, "error": str(e)},
            )
            return None

    async def get_stats(self) -> dict[str, Any]:
        """Get summary statistics for task executions.

        Returns:
            Statistics including counts by status and task name.
        """
        if not self.is_connected:
            return {
                "total_24h": 0,
                "success_count": 0,
                "failure_count": 0,
                "running_count": 0,
                "by_task_name": {},
                "avg_duration_ms": None,
            }

        try:
            # Count by status
            running_count = await self.client.zcard(f"{self.INDEX_STATUS_PREFIX}running")
            success_count = await self.client.zcard(f"{self.INDEX_STATUS_PREFIX}success")
            failure_count = await self.client.zcard(f"{self.INDEX_STATUS_PREFIX}failure")
            total = await self.client.zcard(self.INDEX_ALL)

            # Get counts by task name
            by_task_name: dict[str, int] = {}

            # Find all task name indices using SCAN
            async for key in self.client.scan_iter(match=f"{self.INDEX_NAME_PREFIX}*"):
                # Extract task name from key
                task_name = key.replace(self.INDEX_NAME_PREFIX, "")
                count = await self.client.zcard(key)
                if count > 0:
                    by_task_name[task_name] = count

            # Calculate average duration from recent tasks
            avg_duration_ms: float | None = None
            recent_task_ids = await self.client.zrevrange(
                f"{self.INDEX_STATUS_PREFIX}success",
                0,
                99,  # Sample last 100 successful tasks
            )

            if recent_task_ids:
                durations = []
                for task_id in recent_task_ids:
                    exec_key = f"{self.EXEC_PREFIX}{task_id}"
                    duration_str = await self.client.hget(exec_key, "duration_ms")
                    if duration_str:
                        try:
                            durations.append(int(duration_str))
                        except ValueError:
                            pass

                if durations:
                    avg_duration_ms = sum(durations) / len(durations)

            return {
                "total_24h": total,
                "success_count": success_count,
                "failure_count": failure_count,
                "running_count": running_count,
                "by_task_name": by_task_name,
                "avg_duration_ms": avg_duration_ms,
            }
        except (RedisConnectionError, RedisTimeoutError) as e:
            logger.warning("Failed to get task stats", extra={"error": str(e)})
            return {
                "total_24h": 0,
                "success_count": 0,
                "failure_count": 0,
                "running_count": 0,
                "by_task_name": {},
                "avg_duration_ms": None,
            }


# Global tracker instance
_tracker: TaskExecutionTracker | None = None


def get_tracker() -> TaskExecutionTracker | None:
    """Get the global task execution tracker instance.

    Returns:
        Task tracker instance or None if not initialized.
    """
    return _tracker


async def start_tracker() -> None:
    """Initialize the global task execution tracker.

    This should be called during application/worker startup.
    """
    global _tracker
    logger.info("Starting task execution tracker")

    try:
        _tracker = TaskExecutionTracker()
        await _tracker.connect()
        logger.info("Task execution tracker started successfully")
    except Exception as e:
        logger.exception("Failed to start task execution tracker", extra={"error": str(e)})
        # Don't raise - tracking is non-critical functionality


async def stop_tracker() -> None:
    """Close the global task execution tracker.

    This should be called during application/worker shutdown.
    """
    global _tracker
    logger.info("Stopping task execution tracker")

    if _tracker:
        try:
            await _tracker.disconnect()
            _tracker = None
            logger.info("Task execution tracker stopped successfully")
        except Exception as e:
            logger.exception("Error stopping task execution tracker", extra={"error": str(e)})
