"""Admin API endpoints for task management.

Provides endpoints to:
- List scheduled jobs and their status
- Trigger background tasks on-demand
- Pause/resume scheduled jobs
- View task execution history and statistics
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from example_service.features.admin.schemas import (
    RunningTaskResponse,
    TaskExecutionResponse,
    TaskStatsResponse,
)
from example_service.features.admin.service import (
    AdminService,
    BrokerNotConfiguredError,
    JobNotFoundError,
    TaskName,
    TaskNotFoundError,
    TrackerNotAvailableError,
    get_admin_service,
)

router = APIRouter(prefix="/admin", tags=["Admin"])


# =============================================================================
# Request/Response Schemas
# =============================================================================


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


# =============================================================================
# Scheduled Job Endpoints
# =============================================================================


@router.get(
    "/tasks/scheduled",
    response_model=list[JobStatusResponse],
    summary="List scheduled jobs",
    description="Get status of all scheduled background jobs.",
)
async def list_scheduled_jobs(
    service: AdminService = Depends(get_admin_service),
) -> list[dict]:
    """List all scheduled jobs with their next run times."""
    return service.list_scheduled_jobs()


@router.post(
    "/tasks/scheduled/pause",
    summary="Pause a scheduled job",
    description="Pause a scheduled job by its ID.",
)
async def pause_scheduled_job(
    request: JobActionRequest,
    service: AdminService = Depends(get_admin_service),
) -> dict:
    """Pause a scheduled job."""
    try:
        return service.pause_job(request.job_id)
    except JobNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


@router.post(
    "/tasks/scheduled/resume",
    summary="Resume a paused job",
    description="Resume a previously paused scheduled job.",
)
async def resume_scheduled_job(
    request: JobActionRequest,
    service: AdminService = Depends(get_admin_service),
) -> dict:
    """Resume a paused scheduled job."""
    try:
        return service.resume_job(request.job_id)
    except JobNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


# =============================================================================
# Task Triggering Endpoint
# =============================================================================


@router.post(
    "/tasks/trigger",
    response_model=TriggerTaskResponse,
    summary="Trigger a task",
    description="Trigger a background task for immediate execution.",
)
async def trigger_task(
    request: TriggerTaskRequest,
    service: AdminService = Depends(get_admin_service),
) -> TriggerTaskResponse:
    """Trigger a background task on-demand.

    The task will be queued for execution by a Taskiq worker.
    Make sure a worker is running: `taskiq worker example_service.tasks.broker:broker`
    """
    try:
        result = await service.trigger_task(request.task, request.params)
        return TriggerTaskResponse(**result)
    except BrokerNotConfiguredError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger task: {e}",
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
    service: AdminService = Depends(get_admin_service),
) -> list[TaskExecutionResponse]:
    """Get recent task executions.

    Returns task execution records from the last 24 hours, newest first.
    Use filters to narrow down results by task name or status.
    """
    try:
        history = await service.get_task_history(
            limit=limit,
            offset=offset,
            task_name=task_name,
            status=task_status,
        )
        return [TaskExecutionResponse(**task) for task in history]
    except TrackerNotAvailableError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e


@router.get(
    "/tasks/running",
    response_model=list[RunningTaskResponse],
    summary="Get running tasks",
    description="Get all currently executing tasks.",
)
async def get_running_tasks(
    service: AdminService = Depends(get_admin_service),
) -> list[RunningTaskResponse]:
    """Get currently running tasks.

    Returns information about tasks that are currently being executed
    by workers, including how long they have been running.
    """
    try:
        running = await service.get_running_tasks()
        return [RunningTaskResponse(**task) for task in running]
    except TrackerNotAvailableError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e


@router.get(
    "/tasks/stats",
    response_model=TaskStatsResponse,
    summary="Get task statistics",
    description="Get aggregate statistics about task executions.",
)
async def get_task_stats(
    service: AdminService = Depends(get_admin_service),
) -> TaskStatsResponse:
    """Get task execution statistics.

    Returns aggregate statistics including:
    - Total executions in last 24 hours
    - Counts by status (success, failure, running)
    - Counts by task name
    - Average execution duration
    """
    try:
        stats = await service.get_task_stats()
        return TaskStatsResponse(
            total_24h=stats["total_24h"],
            success_count=stats["success_count"],
            failure_count=stats["failure_count"],
            running_count=stats["running_count"],
            by_task_name=stats["by_task_name"],
            avg_duration_ms=stats["avg_duration_ms"],
        )
    except TrackerNotAvailableError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e


@router.get(
    "/tasks/{task_id}",
    response_model=TaskExecutionResponse,
    summary="Get task details",
    description="Get full execution details for a specific task.",
)
async def get_task_details(
    task_id: str,
    service: AdminService = Depends(get_admin_service),
) -> TaskExecutionResponse:
    """Get details for a specific task execution.

    Returns full execution details including return value or error information.
    """
    try:
        task = await service.get_task_details(task_id)
        return TaskExecutionResponse(**task)
    except TrackerNotAvailableError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e
    except TaskNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
