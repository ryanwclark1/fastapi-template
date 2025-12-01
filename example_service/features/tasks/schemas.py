"""Pydantic schemas for task management API.

This module defines request/response schemas for all task management endpoints.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

from example_service.core.schemas.base import CustomBase


class TaskStatus(str, Enum):
    """Task execution status."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"


class TaskName(str, Enum):
    """Available tasks that can be triggered on-demand.

    These are predefined background tasks that can be manually triggered
    via the API. Each task corresponds to a registered Taskiq task.
    """

    # Backup tasks
    backup_database = "backup_database"

    # Notification tasks
    check_due_reminders = "check_due_reminders"

    # Cache tasks
    warm_cache = "warm_cache"
    invalidate_cache = "invalidate_cache"

    # Export tasks
    export_csv = "export_csv"
    export_json = "export_json"

    # Cleanup tasks
    cleanup_temp_files = "cleanup_temp_files"
    cleanup_old_backups = "cleanup_old_backups"
    cleanup_old_exports = "cleanup_old_exports"
    cleanup_expired_data = "cleanup_expired_data"
    run_all_cleanup = "run_all_cleanup"


# ──────────────────────────────────────────────────────────────
# Task Execution Responses
# ──────────────────────────────────────────────────────────────


class TaskExecutionResponse(CustomBase):
    """Basic task execution information.

    Used for list views where full details aren't needed.
    """

    task_id: str = Field(..., description="Unique task identifier")
    task_name: str = Field(..., description="Name of the task function")
    status: str = Field(..., description="Execution status")
    worker_id: str | None = Field(None, description="Worker that executed the task")
    started_at: str | None = Field(None, description="When execution started (ISO format)")
    finished_at: str | None = Field(None, description="When execution finished (ISO format)")
    duration_ms: int | None = Field(None, description="Execution duration in milliseconds")


class TaskExecutionDetailResponse(TaskExecutionResponse):
    """Full task execution details.

    Includes return values, error information, and task arguments.
    """

    return_value: Any | None = Field(None, description="Task return value (JSON)")
    error_type: str | None = Field(None, description="Exception class name if failed")
    error_message: str | None = Field(None, description="Error message if failed")
    error_traceback: str | None = Field(None, description="Full traceback if failed")
    task_args: Any | None = Field(None, description="Positional arguments passed to task")
    task_kwargs: dict[str, Any] | None = Field(None, description="Keyword arguments passed to task")
    labels: dict[str, Any] | None = Field(None, description="Task labels/metadata")
    retry_count: int = Field(default=0, description="Number of retry attempts")
    queue_name: str | None = Field(None, description="Queue the task was sent to")
    progress: dict[str, Any] | None = Field(None, description="Task progress data")


class RunningTaskResponse(CustomBase):
    """Currently running task information."""

    task_id: str = Field(..., description="Unique task identifier")
    task_name: str = Field(..., description="Name of the task function")
    started_at: str = Field(..., description="When execution started (ISO format)")
    running_for_ms: int = Field(..., description="How long the task has been running")
    worker_id: str | None = Field(None, description="Worker executing the task")


# ──────────────────────────────────────────────────────────────
# Task Search and Filter
# ──────────────────────────────────────────────────────────────


class TaskSearchParams(BaseModel):
    """Query parameters for task search endpoint."""

    task_name: str | None = Field(None, description="Filter by exact task name")
    task_name_like: str | None = Field(None, description="Filter by task name (contains)")
    status: TaskStatus | None = Field(None, description="Filter by status")
    statuses: list[TaskStatus] | None = Field(None, description="Filter by multiple statuses")
    worker_id: str | None = Field(None, description="Filter by worker ID")
    error_type: str | None = Field(None, description="Filter by error type")
    created_after: datetime | None = Field(None, description="Tasks created after this time")
    created_before: datetime | None = Field(None, description="Tasks created before this time")
    min_duration_ms: int | None = Field(None, ge=0, description="Minimum duration in ms")
    max_duration_ms: int | None = Field(None, ge=0, description="Maximum duration in ms")
    order_by: Literal["created_at", "duration_ms", "task_name", "status"] = Field(
        default="created_at",
        description="Field to order results by",
    )
    order_dir: Literal["asc", "desc"] = Field(
        default="desc",
        description="Sort direction",
    )
    limit: int = Field(default=50, ge=1, le=200, description="Maximum results to return")
    offset: int = Field(default=0, ge=0, description="Number of results to skip")


class TaskSearchResponse(CustomBase):
    """Response for task search endpoint."""

    items: list[TaskExecutionResponse] = Field(..., description="Task execution records")
    total: int = Field(..., description="Total matching records (for pagination)")
    limit: int = Field(..., description="Requested limit")
    offset: int = Field(..., description="Requested offset")


# ──────────────────────────────────────────────────────────────
# Task Statistics
# ──────────────────────────────────────────────────────────────


class TaskStatsResponse(CustomBase):
    """Task execution statistics."""

    total_count: int = Field(..., description="Total tasks in period")
    success_count: int = Field(..., description="Successful tasks")
    failure_count: int = Field(..., description="Failed tasks")
    running_count: int = Field(..., description="Currently running tasks")
    cancelled_count: int = Field(default=0, description="Cancelled tasks")
    avg_duration_ms: float | None = Field(None, description="Average duration of successful tasks")
    by_task_name: dict[str, int] = Field(
        default_factory=dict,
        description="Task counts by task name",
    )
    by_status: dict[str, int] = Field(
        default_factory=dict,
        description="Task counts by status",
    )


# ──────────────────────────────────────────────────────────────
# Scheduled Jobs
# ──────────────────────────────────────────────────────────────


class ScheduledJobResponse(CustomBase):
    """APScheduler job information."""

    job_id: str = Field(..., description="Unique job identifier")
    job_name: str = Field(..., description="Job function name")
    next_run_time: datetime | None = Field(None, description="When the job will next run")
    trigger_type: str = Field(..., description="Trigger type (cron, interval, date)")
    trigger_description: str = Field(..., description="Human-readable trigger description")
    is_paused: bool = Field(default=False, description="Whether the job is paused")
    misfire_grace_time: int | None = Field(None, description="Misfire grace time in seconds")
    max_instances: int | None = Field(None, description="Maximum concurrent instances")


class ScheduledJobListResponse(CustomBase):
    """Response for scheduled jobs list endpoint."""

    jobs: list[ScheduledJobResponse] = Field(..., description="Scheduled jobs")
    count: int = Field(..., description="Total number of scheduled jobs")


# ──────────────────────────────────────────────────────────────
# Task Cancellation
# ──────────────────────────────────────────────────────────────


class CancelTaskRequest(BaseModel):
    """Request to cancel a task."""

    task_id: str = Field(..., description="ID of the task to cancel")
    reason: str | None = Field(None, max_length=500, description="Reason for cancellation")


class CancelTaskResponse(CustomBase):
    """Response for task cancellation."""

    task_id: str = Field(..., description="Task ID")
    cancelled: bool = Field(..., description="Whether cancellation was successful")
    message: str = Field(..., description="Status message")
    previous_status: str | None = Field(None, description="Status before cancellation")


# ──────────────────────────────────────────────────────────────
# Task Triggering (for manual execution)
# ──────────────────────────────────────────────────────────────


class TriggerTaskRequest(BaseModel):
    """Request to manually trigger a task.

    Use the `task` field to specify which predefined task to run.
    Task-specific parameters can be passed via `params`.

    Example:
        {
            "task": "export_csv",
            "params": {"model": "reminders", "filters": {"status": "active"}}
        }
    """

    task: TaskName = Field(..., description="Task to trigger (from predefined list)")
    params: dict[str, Any] | None = Field(
        None,
        description="Task-specific parameters (varies by task)",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "task": "backup_database",
                    "params": None,
                },
                {
                    "task": "export_csv",
                    "params": {"model": "reminders", "filters": {"status": "active"}},
                },
                {
                    "task": "cleanup_temp_files",
                    "params": {"max_age_hours": 48},
                },
            ]
        }
    }


class TriggerTaskResponse(CustomBase):
    """Response for task triggering."""

    task_id: str = Field(..., description="ID of the triggered task")
    task_name: str = Field(..., description="Name of the triggered task")
    status: str = Field(default="queued", description="Task status (queued)")
    message: str = Field(..., description="Status message")
