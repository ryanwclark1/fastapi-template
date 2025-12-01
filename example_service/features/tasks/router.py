"""Task management API router.

This module provides REST API endpoints for task management operations:
- Task history and search
- Running tasks
- Task statistics
- Scheduled jobs
- Task cancellation
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from example_service.features.tasks.schemas import (
    CancelTaskRequest,
    CancelTaskResponse,
    RunningTaskResponse,
    ScheduledJobListResponse,
    ScheduledJobResponse,
    TaskExecutionDetailResponse,
    TaskExecutionResponse,
    TaskSearchParams,
    TaskSearchResponse,
    TaskStatsResponse,
    TaskStatus,
    TriggerTaskRequest,
    TriggerTaskResponse,
)
from example_service.features.tasks.service import (
    BrokerNotConfiguredError,
    TaskManagementService,
    TaskServiceError,
    get_task_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tasks", tags=["tasks"])


# ──────────────────────────────────────────────────────────────
# Dependencies
# ──────────────────────────────────────────────────────────────


def get_service() -> TaskManagementService:
    """Dependency to get task management service."""
    return get_task_service()


TaskServiceDep = Annotated[TaskManagementService, Depends(get_service)]


# ──────────────────────────────────────────────────────────────
# Task History & Search Endpoints
# ──────────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=TaskSearchResponse,
    summary="Search task executions",
    description="Search and filter task execution history with various criteria.",
)
async def search_tasks(
    service: TaskServiceDep,
    task_name: Annotated[str | None, Query(description="Filter by exact task name")] = None,
    task_name_like: Annotated[str | None, Query(description="Filter by task name (contains)")] = None,
    status: Annotated[TaskStatus | None, Query(description="Filter by status")] = None,
    worker_id: Annotated[str | None, Query(description="Filter by worker ID")] = None,
    error_type: Annotated[str | None, Query(description="Filter by error type")] = None,
    created_after: Annotated[datetime | None, Query(description="Tasks created after this time")] = None,
    created_before: Annotated[datetime | None, Query(description="Tasks created before this time")] = None,
    min_duration_ms: Annotated[int | None, Query(ge=0, description="Minimum duration in ms")] = None,
    max_duration_ms: Annotated[int | None, Query(ge=0, description="Maximum duration in ms")] = None,
    order_by: Annotated[
        Literal["created_at", "duration_ms", "task_name", "status"],
        Query(description="Field to order by"),
    ] = "created_at",
    order_dir: Annotated[Literal["asc", "desc"], Query(description="Sort direction")] = "desc",
    limit: Annotated[int, Query(ge=1, le=200, description="Maximum results")] = 50,
    offset: Annotated[int, Query(ge=0, description="Skip results")] = 0,
) -> TaskSearchResponse:
    """Search task executions with filters.

    Supports filtering by:
    - Task name (exact or partial match)
    - Status (pending, running, success, failure, cancelled)
    - Worker ID
    - Error type
    - Date range
    - Duration range

    Results are ordered by the specified field and direction.
    """
    params = TaskSearchParams(
        task_name=task_name,
        task_name_like=task_name_like,
        status=status,
        worker_id=worker_id,
        error_type=error_type,
        created_after=created_after,
        created_before=created_before,
        min_duration_ms=min_duration_ms,
        max_duration_ms=max_duration_ms,
        order_by=order_by,
        order_dir=order_dir,
        limit=limit,
        offset=offset,
    )

    tasks, total = await service.search_tasks(params)

    return TaskSearchResponse(
        items=tasks,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/running",
    response_model=list[RunningTaskResponse],
    summary="Get running tasks",
    description="Get all currently running task executions.",
)
async def get_running_tasks(
    service: TaskServiceDep,
) -> list[RunningTaskResponse]:
    """Get currently running tasks.

    Returns a list of tasks that are currently being executed,
    including how long they've been running.
    """
    return await service.get_running_tasks()


@router.get(
    "/stats",
    response_model=TaskStatsResponse,
    summary="Get task statistics",
    description="Get aggregate statistics for task executions.",
)
async def get_task_stats(
    service: TaskServiceDep,
    hours: Annotated[int, Query(ge=1, le=720, description="Hours to include")] = 24,
) -> TaskStatsResponse:
    """Get task execution statistics.

    Returns aggregate statistics including:
    - Total task count
    - Counts by status (success, failure, running, cancelled)
    - Counts by task name
    - Average duration of successful tasks
    """
    return await service.get_stats(hours=hours)


@router.get(
    "/{task_id}",
    response_model=TaskExecutionDetailResponse,
    summary="Get task details",
    description="Get full details for a specific task execution.",
)
async def get_task_details(
    task_id: str,
    service: TaskServiceDep,
) -> TaskExecutionDetailResponse:
    """Get full details for a task execution.

    Returns complete information including:
    - Execution timing and status
    - Return value or error details
    - Task arguments and metadata
    - Progress information
    """
    result = await service.get_task_details(task_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task execution '{task_id}' not found",
        )
    return result


# ──────────────────────────────────────────────────────────────
# Task Cancellation Endpoints
# ──────────────────────────────────────────────────────────────


@router.post(
    "/cancel",
    response_model=CancelTaskResponse,
    summary="Cancel a task",
    description="Cancel a pending or running task execution.",
)
async def cancel_task(
    request: CancelTaskRequest,
    service: TaskServiceDep,
) -> CancelTaskResponse:
    """Cancel a task execution.

    Marks the task as cancelled. Note that this does not forcefully
    stop a running task - it only updates the status. Task workers
    should check for cancellation status periodically.

    Only tasks with status 'pending' or 'running' can be cancelled.
    """
    return await service.cancel_task(request.task_id, request.reason)


# ──────────────────────────────────────────────────────────────
# Task Triggering Endpoints
# ──────────────────────────────────────────────────────────────


@router.post(
    "/trigger",
    response_model=TriggerTaskResponse,
    summary="Trigger a task",
    description="Trigger a background task for immediate execution.",
)
async def trigger_task(
    request: TriggerTaskRequest,
    service: TaskServiceDep,
) -> TriggerTaskResponse:
    """Trigger a background task on-demand.

    The task will be queued for execution by a Taskiq worker.
    Make sure a worker is running: `taskiq worker example_service.tasks.broker:broker`

    Available tasks:
    - **backup_database**: Create a database backup
    - **check_due_reminders**: Check and send due reminder notifications
    - **warm_cache**: Pre-warm frequently accessed cache entries
    - **invalidate_cache**: Invalidate cache entries matching a pattern
    - **export_csv**: Export data to CSV format
    - **export_json**: Export data to JSON format
    - **cleanup_temp_files**: Remove temporary files older than threshold
    - **cleanup_old_backups**: Remove old backup files
    - **cleanup_old_exports**: Remove old export files
    - **cleanup_expired_data**: Remove expired data based on retention policy
    - **run_all_cleanup**: Run all cleanup tasks
    """
    try:
        return await service.trigger_task(request.task, request.params)
    except BrokerNotConfiguredError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e
    except TaskServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e


# ──────────────────────────────────────────────────────────────
# Scheduled Jobs Endpoints
# ──────────────────────────────────────────────────────────────


@router.get(
    "/scheduled",
    response_model=ScheduledJobListResponse,
    summary="List scheduled jobs",
    description="Get all scheduled APScheduler jobs.",
)
async def list_scheduled_jobs(
    service: TaskServiceDep,
) -> ScheduledJobListResponse:
    """List all scheduled jobs.

    Returns information about jobs scheduled via APScheduler,
    including their next run time and trigger configuration.
    """
    jobs = service.get_scheduled_jobs()
    return ScheduledJobListResponse(jobs=jobs, count=len(jobs))


@router.get(
    "/scheduled/{job_id}",
    response_model=ScheduledJobResponse,
    summary="Get scheduled job",
    description="Get details for a specific scheduled job.",
)
async def get_scheduled_job(
    job_id: str,
    service: TaskServiceDep,
) -> ScheduledJobResponse:
    """Get details for a scheduled job.

    Returns information about the job's trigger, next run time,
    and configuration.
    """
    result = service.get_scheduled_job(job_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scheduled job '{job_id}' not found",
        )
    return result


@router.post(
    "/scheduled/{job_id}/pause",
    response_model=dict,
    summary="Pause scheduled job",
    description="Pause a scheduled job.",
)
async def pause_scheduled_job(
    job_id: str,
    service: TaskServiceDep,
) -> dict:
    """Pause a scheduled job.

    The job will not run until resumed. Returns success status.
    """
    success = service.pause_job(job_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scheduled job '{job_id}' not found or could not be paused",
        )
    return {"job_id": job_id, "paused": True, "message": "Job paused successfully"}


@router.post(
    "/scheduled/{job_id}/resume",
    response_model=dict,
    summary="Resume scheduled job",
    description="Resume a paused scheduled job.",
)
async def resume_scheduled_job(
    job_id: str,
    service: TaskServiceDep,
) -> dict:
    """Resume a paused scheduled job.

    The job will resume its normal schedule. Returns success status.
    """
    success = service.resume_job(job_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scheduled job '{job_id}' not found or could not be resumed",
        )
    return {"job_id": job_id, "resumed": True, "message": "Job resumed successfully"}
