"""Task execution dependencies for FastAPI route handlers.

This module provides FastAPI-compatible dependencies for accessing the
background task infrastructure including the Taskiq broker, task tracker,
and scheduler.

Usage:
    from example_service.core.dependencies.tasks import (
        TaskBrokerDep,
        TaskTrackerDep,
        get_task_broker,
    )

    @router.post("/process")
    async def start_processing(
        data: ProcessData,
        broker: TaskBrokerDep,
    ):
        # Enqueue a background task
        task = await process_data.kiq(data.model_dump())
        return {"task_id": task.task_id}

    @router.get("/tasks/history")
    async def get_task_history(
        tracker: TaskTrackerDep,
        limit: int = 100,
    ):
        history = await tracker.get_task_history(limit=limit)
        return {"tasks": history}
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, HTTPException, status


async def get_task_broker() -> AioPikaBroker | None:
    """Get the Taskiq message broker instance.

    This is a thin wrapper that retrieves the task broker singleton.
    The import is deferred to runtime to avoid circular dependencies.

    Returns:
        AioPikaBroker | None: The broker instance, or None if not initialized.
    """
    from example_service.infra.tasks import get_broker

    # get_broker is an async generator, we need to iterate it
    async for broker in get_broker():
        return broker
    return None


def get_task_tracker() -> BaseTaskTracker | None:
    """Get the task execution tracker instance.

    The tracker provides task history, statistics, and status tracking.

    Returns:
        BaseTaskTracker | None: The tracker instance, or None if not initialized.
    """
    from example_service.infra.tasks import get_tracker

    return get_tracker()


def get_scheduler_status() -> list[dict[str, Any]]:
    """Get the current status of scheduled jobs.

    Returns:
        list[dict]: List of scheduled job statuses.
    """
    from example_service.infra.tasks import get_job_status

    return get_job_status()


async def require_task_broker(
    broker: Annotated[AioPikaBroker | None, Depends(get_task_broker)],
) -> AioPikaBroker:
    """Dependency that requires task broker to be available.

    Use this when background task enqueueing is required for the endpoint.
    Raises HTTP 503 if the broker is not available.

    Args:
        broker: Injected broker from get_task_broker

    Returns:
        AioPikaBroker: The task broker instance

    Raises:
        HTTPException: 503 Service Unavailable if broker is not available
    """
    if broker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "task_broker_unavailable",
                "message": "Task broker is not available for enqueueing tasks",
            },
        )
    return broker


async def optional_task_broker(
    broker: Annotated[AioPikaBroker | None, Depends(get_task_broker)],
) -> AioPikaBroker | None:
    """Dependency that optionally provides task broker.

    Use this when background task enqueueing is optional. Allows
    synchronous fallback when broker is unavailable.

    Args:
        broker: Injected broker from get_task_broker

    Returns:
        AioPikaBroker | None: The broker if available, None otherwise
    """
    return broker


async def require_task_tracker(
    tracker: Annotated[BaseTaskTracker | None, Depends(get_task_tracker)],
) -> BaseTaskTracker:
    """Dependency that requires task tracker to be available.

    Use this when task tracking/history is required.
    Raises HTTP 503 if the tracker is not available.

    Args:
        tracker: Injected tracker from get_task_tracker

    Returns:
        BaseTaskTracker: The task tracker instance

    Raises:
        HTTPException: 503 Service Unavailable if tracker is not available
    """
    if tracker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "task_tracker_unavailable",
                "message": "Task tracker is not available",
            },
        )
    return tracker


async def optional_task_tracker(
    tracker: Annotated[BaseTaskTracker | None, Depends(get_task_tracker)],
) -> BaseTaskTracker | None:
    """Dependency that optionally provides task tracker.

    Use this when task tracking is optional.

    Args:
        tracker: Injected tracker from get_task_tracker

    Returns:
        BaseTaskTracker | None: The tracker if available, None otherwise
    """
    return tracker


# Type aliases for cleaner route signatures
# Import at runtime after function definitions to avoid circular dependencies
from taskiq_aio_pika import AioPikaBroker  # noqa: E402

from example_service.infra.tasks.tracking import BaseTaskTracker  # noqa: E402

TaskBrokerDep = Annotated[AioPikaBroker, Depends(require_task_broker)]
"""Task broker dependency that requires broker to be available.

Example:
    @router.post("/enqueue")
    async def enqueue(data: dict, broker: TaskBrokerDep):
        task = await my_task.kiq(data)
        return {"task_id": task.task_id}
"""

OptionalTaskBroker = Annotated[AioPikaBroker | None, Depends(optional_task_broker)]
"""Task broker dependency that is optional.

Example:
    @router.post("/process")
    async def process(data: dict, broker: OptionalTaskBroker):
        if broker:
            await my_task.kiq(data)  # Async processing
        else:
            await my_task(data)  # Sync fallback
"""

TaskTrackerDep = Annotated[BaseTaskTracker, Depends(require_task_tracker)]
"""Task tracker dependency that requires tracker to be available.

Example:
    @router.get("/tasks")
    async def list_tasks(tracker: TaskTrackerDep):
        return await tracker.get_task_history(limit=100)
"""

OptionalTaskTracker = Annotated[BaseTaskTracker | None, Depends(optional_task_tracker)]
"""Task tracker dependency that is optional.

Example:
    @router.get("/status")
    async def status(tracker: OptionalTaskTracker):
        if tracker:
            return {"tasks": await tracker.get_stats()}
        return {"tasks": "tracking_disabled"}
"""

SchedulerStatusDep = Annotated[list[dict[str, Any]], Depends(get_scheduler_status)]
"""Scheduler status dependency for retrieving scheduled job info.

Example:
    @router.get("/scheduled-jobs")
    async def scheduled_jobs(status: SchedulerStatusDep):
        return {"jobs": status}
"""


__all__ = [
    "OptionalTaskBroker",
    "OptionalTaskTracker",
    "SchedulerStatusDep",
    "TaskBrokerDep",
    "TaskTrackerDep",
    "get_scheduler_status",
    "get_task_broker",
    "get_task_tracker",
    "optional_task_broker",
    "optional_task_tracker",
    "require_task_broker",
    "require_task_tracker",
]
