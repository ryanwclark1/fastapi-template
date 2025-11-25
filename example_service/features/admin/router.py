"""Admin API endpoints for task management.

Provides endpoints to:
- List scheduled jobs and their status
- Trigger background tasks on-demand
- Pause/resume scheduled jobs
- View task execution history and statistics
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from example_service.features.admin.schemas import (
    RunningTaskResponse,
    TaskExecutionResponse,
    TaskStatsResponse,
)
from example_service.tasks import get_job_status, get_tracker, pause_job, resume_job
from example_service.tasks.broker import broker

router = APIRouter(prefix="/admin", tags=["Admin"])


class TaskName(str, Enum):
    """Available tasks that can be triggered on-demand."""

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


class TriggerTaskRequest(BaseModel):
    """Request body for triggering a task."""

    task: TaskName
    params: dict[str, Any] | None = None


class TriggerTaskResponse(BaseModel):
    """Response after triggering a task."""

    task_id: str
    task_name: str
    status: str
    message: str


class JobStatusResponse(BaseModel):
    """Scheduled job status."""

    id: str
    name: str
    next_run_time: str | None
    trigger: str


class JobActionRequest(BaseModel):
    """Request for pausing/resuming a job."""

    job_id: str


@router.get(
    "/tasks/scheduled",
    response_model=list[JobStatusResponse],
    summary="List scheduled jobs",
    description="Get status of all scheduled background jobs.",
)
async def list_scheduled_jobs() -> list[dict]:
    """List all scheduled jobs with their next run times."""
    return get_job_status()


@router.post(
    "/tasks/trigger",
    response_model=TriggerTaskResponse,
    summary="Trigger a task",
    description="Trigger a background task for immediate execution.",
)
async def trigger_task(request: TriggerTaskRequest) -> TriggerTaskResponse:
    """Trigger a background task on-demand.

    The task will be queued for execution by a Taskiq worker.
    Make sure a worker is running: `taskiq worker example_service.tasks.broker:broker`
    """
    if broker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Task broker not configured",
        )

    params = request.params or {}

    try:
        match request.task:
            # Backup tasks
            case TaskName.backup_database:
                from example_service.tasks.backup.tasks import backup_database

                task_handle = await backup_database.kiq()

            # Notification tasks
            case TaskName.check_due_reminders:
                from example_service.tasks.notifications.tasks import check_due_reminders

                task_handle = await check_due_reminders.kiq()

            # Cache tasks
            case TaskName.warm_cache:
                from example_service.tasks.cache.tasks import warm_cache

                task_handle = await warm_cache.kiq()

            case TaskName.invalidate_cache:
                from example_service.tasks.cache.tasks import invalidate_cache_pattern

                pattern = params.get("pattern", "*")
                task_handle = await invalidate_cache_pattern.kiq(pattern=pattern)

            # Export tasks
            case TaskName.export_csv:
                from example_service.tasks.export.tasks import export_data_csv

                model_name = params.get("model", "reminders")
                filters = params.get("filters")
                task_handle = await export_data_csv.kiq(
                    model_name=model_name,
                    filters=filters,
                )

            case TaskName.export_json:
                from example_service.tasks.export.tasks import export_data_json

                model_name = params.get("model", "reminders")
                filters = params.get("filters")
                task_handle = await export_data_json.kiq(
                    model_name=model_name,
                    filters=filters,
                )

            # Cleanup tasks
            case TaskName.cleanup_temp_files:
                from example_service.tasks.cleanup.tasks import cleanup_temp_files

                max_age = params.get("max_age_hours", 24)
                task_handle = await cleanup_temp_files.kiq(max_age_hours=max_age)

            case TaskName.cleanup_old_backups:
                from example_service.tasks.cleanup.tasks import cleanup_old_backups

                task_handle = await cleanup_old_backups.kiq()

            case TaskName.cleanup_old_exports:
                from example_service.tasks.cleanup.tasks import cleanup_old_exports

                max_age = params.get("max_age_hours", 48)
                task_handle = await cleanup_old_exports.kiq(max_age_hours=max_age)

            case TaskName.cleanup_expired_data:
                from example_service.tasks.cleanup.tasks import cleanup_expired_data

                retention = params.get("retention_days", 30)
                task_handle = await cleanup_expired_data.kiq(retention_days=retention)

            case TaskName.run_all_cleanup:
                from example_service.tasks.cleanup.tasks import run_all_cleanup

                task_handle = await run_all_cleanup.kiq()

            case _:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unknown task: {request.task}",
                )

        return TriggerTaskResponse(
            task_id=task_handle.task_id,
            task_name=request.task.value,
            status="queued",
            message=f"Task '{request.task.value}' queued for execution",
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger task: {e}",
        ) from e


@router.post(
    "/tasks/scheduled/pause",
    summary="Pause a scheduled job",
    description="Pause a scheduled job by its ID.",
)
async def pause_scheduled_job(request: JobActionRequest) -> dict:
    """Pause a scheduled job."""
    try:
        pause_job(request.job_id)
        return {"status": "paused", "job_id": request.job_id}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job not found or cannot be paused: {e}",
        ) from e


@router.post(
    "/tasks/scheduled/resume",
    summary="Resume a paused job",
    description="Resume a previously paused scheduled job.",
)
async def resume_scheduled_job(request: JobActionRequest) -> dict:
    """Resume a paused scheduled job."""
    try:
        resume_job(request.job_id)
        return {"status": "resumed", "job_id": request.job_id}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job not found or cannot be resumed: {e}",
        ) from e


# =============================================================================
# Task Execution History Endpoints
# =============================================================================


@router.get(
    "/tasks/history",
    response_model=list[TaskExecutionResponse],
    summary="Get task execution history",
    description="Get recent task executions with optional filters.",
)
async def get_task_history(
    limit: int = Query(default=100, ge=1, le=500, description="Max results"),
    offset: int = Query(default=0, ge=0, description="Results to skip"),
    task_name: str | None = Query(default=None, description="Filter by task name"),
    task_status: Literal["success", "failure"] | None = Query(
        default=None, alias="status", description="Filter by status"
    ),
) -> list[TaskExecutionResponse]:
    """Get recent task executions.

    Returns task execution records from the last 24 hours, newest first.
    Use filters to narrow down results by task name or status.
    """
    tracker = get_tracker()
    if tracker is None or not tracker.is_connected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Task tracking not available",
        )

    history = await tracker.get_task_history(
        limit=limit,
        offset=offset,
        task_name=task_name,
        status=task_status,
    )

    # Convert to response models
    return [
        TaskExecutionResponse(
            task_id=task["task_id"],
            task_name=task["task_name"],
            status=task["status"],
            started_at=datetime.fromisoformat(task["started_at"]),
            finished_at=(
                datetime.fromisoformat(task["finished_at"])
                if task.get("finished_at")
                else None
            ),
            duration_ms=task.get("duration_ms"),
            return_value=task.get("return_value"),
            error_message=task.get("error_message"),
            error_type=task.get("error_type"),
        )
        for task in history
    ]


@router.get(
    "/tasks/running",
    response_model=list[RunningTaskResponse],
    summary="Get running tasks",
    description="Get all currently executing tasks.",
)
async def get_running_tasks() -> list[RunningTaskResponse]:
    """Get currently running tasks.

    Returns information about tasks that are currently being executed
    by workers, including how long they have been running.
    """
    tracker = get_tracker()
    if tracker is None or not tracker.is_connected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Task tracking not available",
        )

    running = await tracker.get_running_tasks()

    return [
        RunningTaskResponse(
            task_id=task["task_id"],
            task_name=task["task_name"],
            started_at=datetime.fromisoformat(task["started_at"]),
            running_for_ms=task["running_for_ms"],
            worker_id=task.get("worker_id") or None,
        )
        for task in running
    ]


@router.get(
    "/tasks/stats",
    response_model=TaskStatsResponse,
    summary="Get task statistics",
    description="Get aggregate statistics about task executions.",
)
async def get_task_stats() -> TaskStatsResponse:
    """Get task execution statistics.

    Returns aggregate statistics including:
    - Total executions in last 24 hours
    - Counts by status (success, failure, running)
    - Counts by task name
    - Average execution duration
    """
    tracker = get_tracker()
    if tracker is None or not tracker.is_connected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Task tracking not available",
        )

    stats = await tracker.get_stats()

    return TaskStatsResponse(
        total_24h=stats["total_24h"],
        success_count=stats["success_count"],
        failure_count=stats["failure_count"],
        running_count=stats["running_count"],
        by_task_name=stats["by_task_name"],
        avg_duration_ms=stats["avg_duration_ms"],
    )


@router.get(
    "/tasks/{task_id}",
    response_model=TaskExecutionResponse,
    summary="Get task details",
    description="Get full execution details for a specific task.",
)
async def get_task_details(task_id: str) -> TaskExecutionResponse:
    """Get details for a specific task execution.

    Returns full execution details including return value or error information.
    """
    tracker = get_tracker()
    if tracker is None or not tracker.is_connected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Task tracking not available",
        )

    task = await tracker.get_task_details(task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task execution not found: {task_id}",
        )

    return TaskExecutionResponse(
        task_id=task["task_id"],
        task_name=task["task_name"],
        status=task["status"],
        started_at=datetime.fromisoformat(task["started_at"]),
        finished_at=(
            datetime.fromisoformat(task["finished_at"])
            if task.get("finished_at")
            else None
        ),
        duration_ms=task.get("duration_ms"),
        return_value=task.get("return_value"),
        error_message=task.get("error_message"),
        error_type=task.get("error_type"),
    )
