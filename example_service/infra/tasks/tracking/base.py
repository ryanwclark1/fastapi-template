"""Abstract base class for task execution trackers.

This module defines the interface that all task trackers must implement,
enabling backend-agnostic task tracking across Redis and PostgreSQL.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TypedDict


class TaskExecutionDetails(TypedDict, total=False):
    """TypedDict for task execution details returned by trackers.

    This represents the raw task details from the tracking layer.
    All fields are marked as optional (total=False) because:
    1. Some tracker implementations don't provide all fields
    2. Fields may be None for various reasons (e.g., task not finished yet)

    Required fields in practice: task_id, task_name, status, retry_count
    """

    task_id: str
    task_name: str
    status: str
    started_at: str | None  # ISO format datetime string
    finished_at: str | None  # ISO format datetime string
    duration_ms: int | None
    return_value: Any | None
    error_message: str | None
    error_type: str | None
    error_traceback: str | None  # Optional - not all trackers provide this
    retry_count: int
    worker_id: str | None
    queue_name: str | None
    task_args: Any | None
    task_kwargs: dict[str, Any] | None
    labels: dict[str, Any] | None
    progress: dict[str, Any] | None  # Optional - not all trackers provide this


class BaseTaskTracker(ABC):
    """Abstract interface for task execution tracking.

    This class defines the contract for task tracking implementations,
    allowing the application to switch between Redis and PostgreSQL
    backends without changing application code.

    Implementations must handle:
    - Recording task start/finish events
    - Querying task history with filters
    - Retrieving running tasks
    - Computing statistics

    Example:
            class MyTracker(BaseTaskTracker):
            async def connect(self) -> None:
                # Initialize connection
                ...

            async def on_task_start(self, task_id, task_name, ...) -> None:
                # Record task start
                ...
    """

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the backend storage.

        This method should initialize any necessary connections,
        pools, or sessions required for tracking operations.

        Raises:
            ConnectionError: If unable to connect to the backend.
        """
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection to the backend storage.

        This method should cleanly close all connections and
        release any resources held by the tracker.
        """
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Check if the tracker is connected to its backend.

        Returns:
            True if connected and ready for operations, False otherwise.
        """
        ...

    @abstractmethod
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
        """Record task start event.

        This method is called when a task begins execution. It should
        create or update the task record with initial execution data.

        Args:
            task_id: Unique task identifier.
            task_name: Name of the task function.
            worker_id: Optional identifier of the worker executing the task.
            queue_name: Optional name of the queue the task was received from.
            task_args: Positional arguments passed to the task.
            task_kwargs: Keyword arguments passed to the task.
            labels: Task labels/metadata for categorization.
        """
        ...

    @abstractmethod
    async def on_task_finish(
        self,
        task_id: str,
        status: str,
        return_value: Any | None,
        error: Exception | None,
        duration_ms: int,
    ) -> None:
        """Record task completion event.

        This method is called when a task finishes (successfully or with error).
        It should update the task record with completion data.

        Args:
            task_id: Unique task identifier.
            status: Completion status ("success" or "failure").
            return_value: Task return value (will be JSON serialized).
            error: Exception if task failed, None if successful.
            duration_ms: Task execution duration in milliseconds.
        """
        ...

    @abstractmethod
    async def get_running_tasks(self) -> list[dict[str, Any]]:
        """Get all currently running tasks.

        Returns:
            List of running task records with fields:
            - task_id: str
            - task_name: str
            - started_at: str (ISO format)
            - running_for_ms: int
            - worker_id: str | None
        """
        ...

    @abstractmethod
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
        """Get recent task executions with optional filters.

        Args:
            limit: Maximum number of results.
            offset: Number of results to skip.
            task_name: Filter by task name.
            status: Filter by status ("success", "failure", "running").
            worker_id: Filter by worker ID.
            error_type: Filter by error type.
            created_after: Filter for tasks created after this ISO datetime.
            created_before: Filter for tasks created before this ISO datetime.
            min_duration_ms: Filter for tasks with duration >= this value.
            max_duration_ms: Filter for tasks with duration <= this value.

        Returns:
            List of task execution records, newest first.
        """
        ...

    @abstractmethod
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
        """Count task executions matching the given filters.

        Args:
            task_name: Filter by task name.
            status: Filter by status ("success", "failure", "running").
            worker_id: Filter by worker ID.
            error_type: Filter by error type.
            created_after: Filter for tasks created after this ISO datetime.
            created_before: Filter for tasks created before this ISO datetime.
            min_duration_ms: Filter for tasks with duration >= this value.
            max_duration_ms: Filter for tasks with duration <= this value.

        Returns:
            Total number of matching task execution records.
        """
        ...

    @abstractmethod
    async def get_task_details(self, task_id: str) -> TaskExecutionDetails | None:
        """Get full details for a specific task execution.

        Args:
            task_id: Task identifier.

        Returns:
            Task execution record with all fields, or None if not found.
        """
        ...

    @abstractmethod
    async def get_stats(self, hours: int = 24) -> dict[str, Any]:
        """Get summary statistics for task executions.

        Args:
            hours: Number of hours to include in statistics.

        Returns:
            Statistics dictionary with fields:
            - total_count: int
            - success_count: int
            - failure_count: int
            - running_count: int
            - cancelled_count: int
            - by_task_name: dict[str, int]
            - avg_duration_ms: float | None
        """
        ...

    async def cancel_task(self, _task_id: str) -> bool:
        """Mark a task as cancelled.

        This method updates the task status to "cancelled". It does not
        actually stop the task execution - that requires broker-level
        intervention.

        Args:
            task_id: Task identifier.

        Returns:
            True if task was found and cancelled, False otherwise.
        """
        # Default implementation - subclasses can override
        return False
