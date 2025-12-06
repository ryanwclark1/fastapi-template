"""Task management service layer.

This module provides business logic for task management operations,
abstracting the tracker and scheduler interactions.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from example_service.features.tasks.schemas import (
    CancelTaskResponse,
    RunningTaskResponse,
    ScheduledJobResponse,
    TaskExecutionDetailResponse,
    TaskExecutionResponse,
    TaskName,
    TaskSearchParams,
    TaskStatsResponse,
    TriggerTaskResponse,
)
from example_service.infra.tasks.tracking import get_tracker

# Optional references for patching/testing; actual imports may fail if infra not set up
try:
    from example_service.infra.tasks.broker import broker
except Exception:  # pragma: no cover - best effort
    broker = None

try:
    from example_service.infra.tasks.scheduler import scheduler
except Exception:  # pragma: no cover - best effort
    scheduler = None


# ──────────────────────────────────────────────────────────────
# Exceptions
# ──────────────────────────────────────────────────────────────


class TaskServiceError(Exception):
    """Base exception for task service errors."""



class BrokerNotConfiguredError(TaskServiceError):
    """Raised when the task broker is not configured."""



class TrackerNotAvailableError(TaskServiceError):
    """Raised when task tracking is not available."""



if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import (
        AsyncIOScheduler,  # type: ignore[import-untyped]
    )

    from example_service.infra.tasks.tracking.base import BaseTaskTracker

logger = logging.getLogger(__name__)


class TaskManagementService:
    """Service for task management operations.

    This service provides a high-level interface for:
    - Querying task execution history
    - Getting task statistics
    - Managing scheduled jobs
    - Cancelling tasks

    Example:
            service = TaskManagementService(tracker=get_tracker(), scheduler=scheduler)

        # Get task history
        tasks = await service.search_tasks(TaskSearchParams(limit=50))

        # Get statistics
        stats = await service.get_stats(hours=24)

        # Cancel a task
        result = await service.cancel_task("task-123")
    """

    def __init__(
        self,
        tracker: BaseTaskTracker | None = None,
        scheduler: AsyncIOScheduler | None = None,
    ) -> None:
        """Initialize task management service.

        Args:
            tracker: Task tracker instance (defaults to global tracker).
            scheduler: APScheduler instance for scheduled jobs.
        """
        self._tracker = tracker
        self._scheduler = scheduler

    @property
    def tracker(self) -> BaseTaskTracker | None:
        """Get the task tracker."""
        if self._tracker is None:
            return get_tracker()
        return self._tracker

    # ──────────────────────────────────────────────────────────────
    # Task History & Search
    # ──────────────────────────────────────────────────────────────

    async def search_tasks(
        self,
        params: TaskSearchParams,
    ) -> tuple[list[TaskExecutionResponse], int]:
        """Search task executions with filters.

        Args:
            params: Search parameters.

        Returns:
            Tuple of (task list, total count).
        """
        tracker = self.tracker
        if not tracker or not tracker.is_connected:
            logger.warning("Task tracker not available")
            return [], 0

        try:
            # Convert datetime to ISO string for tracker
            created_after = params.created_after.isoformat() if params.created_after else None
            created_before = params.created_before.isoformat() if params.created_before else None

            # Get primary status filter
            status = params.status.value if params.status else None

            tracker_params: dict[str, Any] = {
                "task_name": params.task_name,
                "status": status,
                "worker_id": params.worker_id,
                "error_type": params.error_type,
                "created_after": created_after,
                "created_before": created_before,
                "min_duration_ms": params.min_duration_ms,
                "max_duration_ms": params.max_duration_ms,
            }

            tasks = await tracker.get_task_history(
                limit=params.limit,
                offset=params.offset,
                **tracker_params,
            )

            # Convert to response models
            responses = [
                TaskExecutionResponse(
                    task_id=t["task_id"],
                    task_name=t["task_name"],
                    status=t["status"],
                    worker_id=t.get("worker_id"),
                    started_at=t.get("started_at"),
                    finished_at=t.get("finished_at"),
                    duration_ms=t.get("duration_ms"),
                )
                for t in tasks
            ]

            try:
                total = await tracker.count_task_history(**tracker_params)
            except Exception as e:
                logger.warning(
                    "Failed to count task history; falling back to page size",
                    extra={"error": str(e)},
                )
                total = len(tasks) + params.offset

            return responses, total
        except Exception as e:
            logger.exception("Failed to search tasks", extra={"error": str(e)})
            return [], 0

    async def get_task_details(self, task_id: str) -> TaskExecutionDetailResponse | None:
        """Get full details for a specific task.

        Args:
            task_id: Task identifier.

        Returns:
            Task details or None if not found.
        """
        tracker = self.tracker
        if not tracker or not tracker.is_connected:
            return None

        try:
            details = await tracker.get_task_details(task_id)
            if not details:
                return None

            return TaskExecutionDetailResponse(
                task_id=details["task_id"],
                task_name=details["task_name"],
                status=details["status"],
                worker_id=details.get("worker_id"),
                started_at=details.get("started_at"),
                finished_at=details.get("finished_at"),
                duration_ms=details.get("duration_ms"),
                return_value=details.get("return_value"),
                error_type=details.get("error_type"),
                error_message=details.get("error_message"),
                error_traceback=details.get("error_traceback"),
                task_args=details.get("task_args"),
                task_kwargs=details.get("task_kwargs"),
                labels=details.get("labels"),
                retry_count=details.get("retry_count", 0),
                queue_name=details.get("queue_name"),
                progress=details.get("progress"),
            )
        except Exception as e:
            logger.exception(
                "Failed to get task details",
                extra={"task_id": task_id, "error": str(e)},
            )
            return None

    async def get_running_tasks(self) -> list[RunningTaskResponse]:
        """Get currently running tasks.

        Returns:
            List of running tasks.
        """
        tracker = self.tracker
        if not tracker or not tracker.is_connected:
            return []

        try:
            tasks = await tracker.get_running_tasks()
            return [
                RunningTaskResponse(
                    task_id=t["task_id"],
                    task_name=t["task_name"],
                    started_at=t["started_at"],
                    running_for_ms=t["running_for_ms"],
                    worker_id=t.get("worker_id"),
                )
                for t in tasks
            ]
        except Exception as e:
            logger.exception("Failed to get running tasks", extra={"error": str(e)})
            return []

    # ──────────────────────────────────────────────────────────────
    # Statistics
    # ──────────────────────────────────────────────────────────────

    async def get_stats(self, hours: int = 24) -> TaskStatsResponse:
        """Get task execution statistics.

        Args:
            hours: Number of hours to include.

        Returns:
            Task statistics.
        """
        tracker = self.tracker
        if not tracker or not tracker.is_connected:
            return TaskStatsResponse(
                total_count=0,
                success_count=0,
                failure_count=0,
                running_count=0,
                cancelled_count=0,
                avg_duration_ms=None,
                by_task_name={},
                by_status={},
            )

        try:
            stats = await tracker.get_stats(hours=hours)
            return TaskStatsResponse(
                total_count=stats.get("total_count", 0),
                success_count=stats.get("success_count", 0),
                failure_count=stats.get("failure_count", 0),
                running_count=stats.get("running_count", 0),
                cancelled_count=stats.get("cancelled_count", 0),
                avg_duration_ms=stats.get("avg_duration_ms"),
                by_task_name=stats.get("by_task_name", {}),
                by_status={
                    "success": stats.get("success_count", 0),
                    "failure": stats.get("failure_count", 0),
                    "running": stats.get("running_count", 0),
                    "cancelled": stats.get("cancelled_count", 0),
                },
            )
        except Exception as e:
            logger.exception("Failed to get task stats", extra={"error": str(e)})
            return TaskStatsResponse(
                total_count=0,
                success_count=0,
                failure_count=0,
                running_count=0,
                cancelled_count=0,
                avg_duration_ms=None,
                by_task_name={},
                by_status={},
            )

    # ──────────────────────────────────────────────────────────────
    # Task Cancellation
    # ──────────────────────────────────────────────────────────────

    async def cancel_task(
        self,
        task_id: str,
        reason: str | None = None,
    ) -> CancelTaskResponse:
        """Cancel a task.

        Currently supports cancelling queued/running tasks by marking
        their status as cancelled. Does not actually stop running tasks.

        Args:
            task_id: Task identifier.
            reason: Optional cancellation reason.

        Returns:
            Cancellation result.
        """
        tracker = self.tracker
        if not tracker or not tracker.is_connected:
            return CancelTaskResponse(
                task_id=task_id,
                cancelled=False,
                message="Task tracker not available",
                previous_status=None,
            )

        try:
            # Get current status first
            details = await tracker.get_task_details(task_id)
            if not details:
                return CancelTaskResponse(
                    task_id=task_id,
                    cancelled=False,
                    message="Task not found",
                    previous_status=None,
                )

            previous_status = details.get("status")

            # Attempt cancellation
            cancelled = await tracker.cancel_task(task_id)

            if cancelled:
                message = "Task cancelled successfully"
                if reason:
                    message += f" (reason: {reason})"
                logger.info(
                    "Task cancelled",
                    extra={"task_id": task_id, "reason": reason},
                )
            else:
                message = f"Cannot cancel task with status '{previous_status}'"

            return CancelTaskResponse(
                task_id=task_id,
                cancelled=cancelled,
                message=message,
                previous_status=previous_status,
            )
        except Exception as e:
            logger.exception(
                "Failed to cancel task",
                extra={"task_id": task_id, "error": str(e)},
            )
            return CancelTaskResponse(
                task_id=task_id,
                cancelled=False,
                message=f"Error: {e!s}",
                previous_status=None,
            )

    # ──────────────────────────────────────────────────────────────
    # Task Triggering
    # ──────────────────────────────────────────────────────────────

    async def trigger_task(
        self,
        task_name: TaskName,
        params: dict[str, Any] | None = None,
    ) -> TriggerTaskResponse:
        """Trigger a background task for immediate execution.

        The task will be queued for execution by a Taskiq worker.
        Requires a worker to be running: `taskiq worker example_service.infra.tasks.broker:broker`

        Args:
            task_name: The predefined task to trigger.
            params: Optional task-specific parameters.

        Returns:
            TriggerTaskResponse with task_id and status.

        Raises:
            BrokerNotConfiguredError: If the task broker is not available.
            TaskServiceError: If the task fails to trigger.
        """
        if broker is None:
            raise BrokerNotConfiguredError(
                "Task broker not configured. Ensure RabbitMQ and Redis are available."
            )

        params = params or {}

        try:
            task_handle = await self._dispatch_task(task_name, params)

            logger.info(
                "Task triggered",
                extra={
                    "task_name": task_name.value,
                    "task_id": task_handle.task_id,
                    "params": params,
                },
            )

            return TriggerTaskResponse(
                task_id=task_handle.task_id,
                task_name=task_name.value,
                status="queued",
                message=f"Task '{task_name.value}' queued for execution",
            )

        except BrokerNotConfiguredError:
            raise
        except Exception as e:
            logger.exception(
                "Failed to trigger task",
                extra={"task_name": task_name.value, "error": str(e)},
            )
            raise TaskServiceError(f"Failed to trigger task: {e}") from e

    async def _dispatch_task(
        self,
        task_name: TaskName,
        params: dict[str, Any],
    ) -> Any:
        """Dispatch a task to the appropriate handler.

        Args:
            task_name: The task to dispatch.
            params: Parameters for the task.

        Returns:
            Task handle from the broker.
        """
        match task_name:
            # Backup tasks
            case TaskName.backup_database:
                from example_service.workers.backup.tasks import backup_database

                return await backup_database.kiq()

            # Notification tasks
            case TaskName.check_due_reminders:
                from example_service.workers.notifications.tasks import (
                    check_due_reminders,
                )

                return await check_due_reminders.kiq()

            # Cache tasks
            case TaskName.warm_cache:
                from example_service.workers.cache.tasks import warm_cache

                return await warm_cache.kiq()

            case TaskName.invalidate_cache:
                from example_service.workers.cache.tasks import invalidate_cache_pattern

                pattern = params.get("pattern", "*")
                return await invalidate_cache_pattern.kiq(pattern=pattern)

            # Export tasks
            case TaskName.export_csv:
                from example_service.workers.export.tasks import export_data_csv

                model_name = params.get("model", "reminders")
                filters = params.get("filters")
                return await export_data_csv.kiq(model_name=model_name, filters=filters)

            case TaskName.export_json:
                from example_service.workers.export.tasks import export_data_json

                model_name = params.get("model", "reminders")
                filters = params.get("filters")
                return await export_data_json.kiq(model_name=model_name, filters=filters)

            # Cleanup tasks
            case TaskName.cleanup_temp_files:
                from example_service.workers.cleanup.tasks import cleanup_temp_files

                max_age = params.get("max_age_hours", 24)
                return await cleanup_temp_files.kiq(max_age_hours=max_age)

            case TaskName.cleanup_old_backups:
                from example_service.workers.cleanup.tasks import cleanup_old_backups

                return await cleanup_old_backups.kiq()

            case TaskName.cleanup_old_exports:
                from example_service.workers.cleanup.tasks import cleanup_old_exports

                max_age = params.get("max_age_hours", 48)
                return await cleanup_old_exports.kiq(max_age_hours=max_age)

            case TaskName.cleanup_expired_data:
                from example_service.workers.cleanup.tasks import cleanup_expired_data

                retention = params.get("retention_days", 30)
                return await cleanup_expired_data.kiq(retention_days=retention)

            case TaskName.run_all_cleanup:
                from example_service.workers.cleanup.tasks import run_all_cleanup

                return await run_all_cleanup.kiq()

    # ──────────────────────────────────────────────────────────────
    # Scheduled Jobs
    # ──────────────────────────────────────────────────────────────

    def get_scheduled_jobs(self) -> list[ScheduledJobResponse]:
        """Get all scheduled APScheduler jobs.

        Returns:
            List of scheduled jobs.
        """
        if not self._scheduler:
            logger.warning("No scheduler available")
            return []

        try:
            jobs = self._scheduler.get_jobs()
            return [self._job_to_response(job) for job in jobs]
        except Exception as e:
            logger.exception("Failed to get scheduled jobs", extra={"error": str(e)})
            return []

    def get_scheduled_job(self, job_id: str) -> ScheduledJobResponse | None:
        """Get a specific scheduled job.

        Args:
            job_id: Job identifier.

        Returns:
            Job details or None if not found.
        """
        if not self._scheduler:
            return None

        try:
            job = self._scheduler.get_job(job_id)
            if not job:
                return None
            return self._job_to_response(job)
        except Exception as e:
            logger.exception(
                "Failed to get scheduled job",
                extra={"job_id": job_id, "error": str(e)},
            )
            return None

    def pause_job(self, job_id: str) -> bool:
        """Pause a scheduled job.

        Args:
            job_id: Job identifier.

        Returns:
            True if paused, False otherwise.
        """
        if not self._scheduler:
            return False

        try:
            self._scheduler.pause_job(job_id)
            logger.info("Job paused", extra={"job_id": job_id})
            return True
        except Exception as e:
            logger.exception(
                "Failed to pause job",
                extra={"job_id": job_id, "error": str(e)},
            )
            return False

    def resume_job(self, job_id: str) -> bool:
        """Resume a paused job.

        Args:
            job_id: Job identifier.

        Returns:
            True if resumed, False otherwise.
        """
        if not self._scheduler:
            return False

        try:
            self._scheduler.resume_job(job_id)
            logger.info("Job resumed", extra={"job_id": job_id})
            return True
        except Exception as e:
            logger.exception(
                "Failed to resume job",
                extra={"job_id": job_id, "error": str(e)},
            )
            return False

    def _job_to_response(self, job: Any) -> ScheduledJobResponse:
        """Convert APScheduler job to response model."""
        trigger = job.trigger
        trigger_type = type(trigger).__name__.lower().replace("trigger", "")

        # Get trigger description
        trigger_desc = str(trigger)

        # Check if paused (next_run_time is None when paused)
        is_paused = job.next_run_time is None

        return ScheduledJobResponse(
            job_id=job.id,
            job_name=job.name or job.func_ref,
            next_run_time=job.next_run_time,
            trigger_type=trigger_type,
            trigger_description=trigger_desc,
            is_paused=is_paused,
            misfire_grace_time=job.misfire_grace_time,
            max_instances=job.max_instances,
        )


# ──────────────────────────────────────────────────────────────
# Dependency Injection
# ──────────────────────────────────────────────────────────────


def get_task_service(
    scheduler: AsyncIOScheduler | None = None,
) -> TaskManagementService:
    """Create a task management service instance.

    Args:
        scheduler: Optional APScheduler instance.

    Returns:
        TaskManagementService instance.
    """
    # Try to get scheduler from the tasks module if not provided
    if scheduler is None:
        scheduler = globals().get("scheduler")
        if scheduler is None:
            try:
                from example_service.infra.tasks.scheduler import (
                    scheduler as app_scheduler,
                )

                scheduler = app_scheduler
                globals()["scheduler"] = app_scheduler
            except ImportError:
                scheduler = None

    return TaskManagementService(scheduler=scheduler)
