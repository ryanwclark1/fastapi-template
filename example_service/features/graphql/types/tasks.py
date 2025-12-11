"""GraphQL types for the Tasks feature.

Provides:
- TaskExecutionType: GraphQL representation of a task execution
- TaskStatsType: Task execution statistics
- ScheduledJobType: Scheduled job information
- DLQEntryType: Dead Letter Queue entry
- Input types for triggering/managing tasks
- Connection types for pagination
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated

import strawberry
from strawberry.scalars import JSON

from example_service.features.graphql.types.base import PageInfoType
from example_service.utils.runtime_dependencies import require_runtime_dependency

require_runtime_dependency(datetime, JSON, PageInfoType)

# --- Enums ---


@strawberry.enum(description="Task execution status")
class TaskStatusEnum(Enum):
    """Task status enum."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"


@strawberry.enum(description="Available tasks that can be triggered")
class TaskNameEnum(Enum):
    """Available task names."""

    BACKUP_DATABASE = "backup_database"
    CHECK_DUE_REMINDERS = "check_due_reminders"
    WARM_CACHE = "warm_cache"
    INVALIDATE_CACHE = "invalidate_cache"
    EXPORT_CSV = "export_csv"
    EXPORT_JSON = "export_json"
    CLEANUP_TEMP_FILES = "cleanup_temp_files"
    CLEANUP_OLD_BACKUPS = "cleanup_old_backups"
    CLEANUP_OLD_EXPORTS = "cleanup_old_exports"
    CLEANUP_EXPIRED_DATA = "cleanup_expired_data"
    RUN_ALL_CLEANUP = "run_all_cleanup"


@strawberry.enum(description="DLQ entry status")
class DLQStatusEnum(Enum):
    """DLQ status enum."""

    PENDING = "pending"
    RETRIED = "retried"
    DISCARDED = "discarded"


# --- Output Types ---


@strawberry.type(description="Task execution information")
class TaskExecutionType:
    """GraphQL type for task execution record."""

    task_id: str = strawberry.field(description="Unique task identifier")
    task_name: str = strawberry.field(description="Name of the task function")
    status: TaskStatusEnum = strawberry.field(description="Execution status")
    worker_id: str | None = strawberry.field(description="Worker that executed the task")
    started_at: datetime | None = strawberry.field(description="When execution started")
    finished_at: datetime | None = strawberry.field(description="When execution finished")
    duration_ms: int | None = strawberry.field(description="Execution duration in milliseconds")


@strawberry.type(description="Full task execution details")
class TaskExecutionDetailType:
    """GraphQL type for full task execution details."""

    task_id: str = strawberry.field(description="Unique task identifier")
    task_name: str = strawberry.field(description="Name of the task function")
    status: TaskStatusEnum = strawberry.field(description="Execution status")
    worker_id: str | None = strawberry.field(description="Worker that executed the task")
    started_at: datetime | None = strawberry.field(description="When execution started")
    finished_at: datetime | None = strawberry.field(description="When execution finished")
    duration_ms: int | None = strawberry.field(description="Execution duration in milliseconds")
    return_value: JSON | None = strawberry.field(description="Task return value")
    error_type: str | None = strawberry.field(description="Exception class name if failed")
    error_message: str | None = strawberry.field(description="Error message if failed")
    error_traceback: str | None = strawberry.field(description="Full traceback if failed")
    task_args: JSON | None = strawberry.field(description="Positional arguments")
    task_kwargs: JSON | None = strawberry.field(description="Keyword arguments")
    labels: JSON | None = strawberry.field(description="Task labels/metadata")
    retry_count: int = strawberry.field(description="Number of retry attempts")
    queue_name: str | None = strawberry.field(description="Queue the task was sent to")
    progress: JSON | None = strawberry.field(description="Task progress data")


@strawberry.type(description="Currently running task information")
class RunningTaskType:
    """GraphQL type for a currently running task."""

    task_id: str = strawberry.field(description="Unique task identifier")
    task_name: str = strawberry.field(description="Name of the task function")
    started_at: datetime = strawberry.field(description="When execution started")
    running_for_ms: int = strawberry.field(description="How long the task has been running")
    worker_id: str | None = strawberry.field(description="Worker executing the task")


@strawberry.type(description="Task execution statistics")
class TaskStatsType:
    """GraphQL type for task statistics."""

    total_count: int = strawberry.field(description="Total tasks in period")
    success_count: int = strawberry.field(description="Successful tasks")
    failure_count: int = strawberry.field(description="Failed tasks")
    running_count: int = strawberry.field(description="Currently running tasks")
    cancelled_count: int = strawberry.field(description="Cancelled tasks")
    avg_duration_ms: float | None = strawberry.field(description="Average duration of successful tasks")
    by_task_name: JSON = strawberry.field(description="Task counts by task name")
    by_status: JSON = strawberry.field(description="Task counts by status")


@strawberry.type(description="Scheduled job information")
class ScheduledJobType:
    """GraphQL type for a scheduled job."""

    job_id: str = strawberry.field(description="Unique job identifier")
    job_name: str = strawberry.field(description="Job function name")
    next_run_time: datetime | None = strawberry.field(description="When the job will next run")
    trigger_type: str = strawberry.field(description="Trigger type (cron, interval, date)")
    trigger_description: str = strawberry.field(description="Human-readable trigger description")
    is_paused: bool = strawberry.field(description="Whether the job is paused")
    misfire_grace_time: int | None = strawberry.field(description="Misfire grace time in seconds")
    max_instances: int | None = strawberry.field(description="Maximum concurrent instances")


@strawberry.type(description="Dead Letter Queue entry")
class DLQEntryType:
    """GraphQL type for a DLQ entry."""

    task_id: str = strawberry.field(description="Original task ID")
    task_name: str = strawberry.field(description="Name of the failed task")
    args: JSON | None = strawberry.field(description="Positional arguments")
    kwargs: JSON | None = strawberry.field(description="Keyword arguments")
    labels: JSON | None = strawberry.field(description="Task labels")
    error_message: str = strawberry.field(description="Error message from last failure")
    error_type: str = strawberry.field(description="Exception type name")
    retry_count: int = strawberry.field(description="Number of retries attempted")
    failed_at: datetime = strawberry.field(description="When the task finally failed")
    status: DLQStatusEnum = strawberry.field(description="DLQ entry status")


@strawberry.type(description="Task progress information")
class TaskProgressType:
    """GraphQL type for task progress."""

    task_id: str = strawberry.field(description="Task ID")
    percent: float | None = strawberry.field(description="Progress percentage (0-100)")
    message: str | None = strawberry.field(description="Progress message")
    current: int | None = strawberry.field(description="Current item number")
    total: int | None = strawberry.field(description="Total items")
    updated_at: datetime | None = strawberry.field(description="Last update time")
    extra: JSON | None = strawberry.field(description="Additional progress data")


# --- Input Types ---


@strawberry.input(description="Input for triggering a task")
class TriggerTaskInput:
    """Input for triggerTask mutation."""

    task: TaskNameEnum = strawberry.field(description="Task to trigger")
    params: JSON | None = strawberry.field(
        default=None, description="Task-specific parameters",
    )


@strawberry.input(description="Input for cancelling a task")
class CancelTaskInput:
    """Input for cancelTask mutation."""

    task_id: str = strawberry.field(description="ID of the task to cancel")
    reason: str | None = strawberry.field(
        default=None, description="Reason for cancellation",
    )


@strawberry.input(description="Filter for task search")
class TaskSearchFilterInput:
    """Filter input for task search query."""

    task_name: str | None = strawberry.field(
        default=None, description="Filter by exact task name",
    )
    task_name_like: str | None = strawberry.field(
        default=None, description="Filter by task name (contains)",
    )
    status: TaskStatusEnum | None = strawberry.field(
        default=None, description="Filter by status",
    )
    statuses: list[TaskStatusEnum] | None = strawberry.field(
        default=None, description="Filter by multiple statuses",
    )
    worker_id: str | None = strawberry.field(
        default=None, description="Filter by worker ID",
    )
    error_type: str | None = strawberry.field(
        default=None, description="Filter by error type",
    )
    created_after: datetime | None = strawberry.field(
        default=None, description="Tasks created after this time",
    )
    created_before: datetime | None = strawberry.field(
        default=None, description="Tasks created before this time",
    )
    min_duration_ms: int | None = strawberry.field(
        default=None, description="Minimum duration in ms",
    )
    max_duration_ms: int | None = strawberry.field(
        default=None, description="Maximum duration in ms",
    )


@strawberry.input(description="Input for bulk cancel operation")
class BulkCancelInput:
    """Input for bulkCancelTasks mutation."""

    task_ids: list[str] = strawberry.field(description="List of task IDs to cancel")
    reason: str | None = strawberry.field(
        default=None, description="Reason for cancellation",
    )


@strawberry.input(description="Input for bulk retry operation")
class BulkRetryInput:
    """Input for bulkRetryTasks mutation."""

    task_ids: list[str] = strawberry.field(description="List of DLQ task IDs to retry")


# --- Payload Types ---


@strawberry.type(description="Successful task trigger result")
class TriggerTaskSuccess:
    """Success payload for triggerTask mutation."""

    task_id: str = strawberry.field(description="ID of the triggered task")
    task_name: str = strawberry.field(description="Name of the triggered task")
    status: str = strawberry.field(description="Task status (queued)")
    message: str = strawberry.field(description="Status message")


@strawberry.type(description="Error result from a task operation")
class TaskOperationError:
    """Error payload for task mutations."""

    code: str = strawberry.field(description="Error code")
    message: str = strawberry.field(description="Human-readable error message")


TriggerTaskPayload = Annotated[
    TriggerTaskSuccess | TaskOperationError,
    strawberry.union(name="TriggerTaskPayload", description="Result of trigger task mutation"),
]


@strawberry.type(description="Cancel task result")
class CancelTaskResult:
    """Result for cancelTask mutation."""

    task_id: str = strawberry.field(description="Task ID")
    cancelled: bool = strawberry.field(description="Whether cancellation was successful")
    message: str = strawberry.field(description="Status message")
    previous_status: TaskStatusEnum | None = strawberry.field(description="Status before cancellation")


@strawberry.type(description="Retry DLQ task result")
class RetryDLQResult:
    """Result for retryDLQTask mutation."""

    original_task_id: str = strawberry.field(description="Original task ID")
    new_task_id: str = strawberry.field(description="New task ID for the retry")
    task_name: str = strawberry.field(description="Task name")
    status: str = strawberry.field(description="New task status")
    message: str = strawberry.field(description="Status message")


@strawberry.type(description="Bulk operation result for a single item")
class BulkOperationItemResult:
    """Result for a single item in a bulk operation."""

    task_id: str = strawberry.field(description="Task ID")
    success: bool = strawberry.field(description="Whether the operation succeeded")
    message: str = strawberry.field(description="Status message")
    previous_status: TaskStatusEnum | None = strawberry.field(description="Previous status")


@strawberry.type(description="Bulk cancel operation result")
class BulkCancelResult:
    """Result for bulkCancelTasks mutation."""

    total_requested: int = strawberry.field(description="Total tasks requested to cancel")
    successful: int = strawberry.field(description="Number of successfully cancelled tasks")
    failed: int = strawberry.field(description="Number of failed cancellations")
    results: list[BulkOperationItemResult] = strawberry.field(description="Individual results")


@strawberry.type(description="Bulk retry operation result")
class BulkRetryResult:
    """Result for bulkRetryTasks mutation."""

    total_requested: int = strawberry.field(description="Total tasks requested to retry")
    successful: int = strawberry.field(description="Number of successfully retried tasks")
    failed: int = strawberry.field(description="Number of failed retries")
    results: list[BulkOperationItemResult] = strawberry.field(description="Individual results")


# --- Connection Types ---


@strawberry.type(description="Edge containing a task execution and its cursor")
class TaskExecutionEdge:
    """Edge wrapper for paginated task executions."""

    node: TaskExecutionType = strawberry.field(description="The task execution")
    cursor: str = strawberry.field(description="Cursor for this item")


@strawberry.type(description="Paginated connection of task executions")
class TaskExecutionConnection:
    """GraphQL Connection for cursor-paginated task executions."""

    edges: list[TaskExecutionEdge] = strawberry.field(description="List of edges")
    page_info: PageInfoType = strawberry.field(description="Pagination metadata")
    total: int = strawberry.field(description="Total matching records")


@strawberry.type(description="Edge containing a DLQ entry and its cursor")
class DLQEntryEdge:
    """Edge wrapper for paginated DLQ entries."""

    node: DLQEntryType = strawberry.field(description="The DLQ entry")
    cursor: str = strawberry.field(description="Cursor for this item")


@strawberry.type(description="Paginated connection of DLQ entries")
class DLQConnection:
    """GraphQL Connection for cursor-paginated DLQ entries."""

    edges: list[DLQEntryEdge] = strawberry.field(description="List of edges")
    page_info: PageInfoType = strawberry.field(description="Pagination metadata")
    total: int = strawberry.field(description="Total DLQ entries")


__all__ = [
    "BulkCancelInput",
    "BulkCancelResult",
    "BulkOperationItemResult",
    "BulkRetryInput",
    "BulkRetryResult",
    "CancelTaskInput",
    "CancelTaskResult",
    "DLQConnection",
    "DLQEntryEdge",
    "DLQEntryType",
    "DLQStatusEnum",
    "RetryDLQResult",
    "RunningTaskType",
    "ScheduledJobType",
    "TaskExecutionConnection",
    "TaskExecutionDetailType",
    "TaskExecutionEdge",
    "TaskExecutionType",
    "TaskNameEnum",
    "TaskOperationError",
    "TaskProgressType",
    "TaskSearchFilterInput",
    "TaskStatsType",
    "TaskStatusEnum",
    "TriggerTaskInput",
    "TriggerTaskPayload",
    "TriggerTaskSuccess",
]
