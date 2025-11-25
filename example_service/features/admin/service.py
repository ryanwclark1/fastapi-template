"""Service layer for admin task management operations.

Provides business logic for:
- Scheduled job management (list, pause, resume)
- On-demand task triggering
- Task execution history and statistics
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from example_service.core.services.base import BaseService
from example_service.tasks import get_job_status, get_tracker, pause_job, resume_job
from example_service.tasks.broker import broker

if TYPE_CHECKING:
    pass


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


class AdminServiceError(Exception):
    """Base exception for admin service errors."""

    pass


class BrokerNotConfiguredError(AdminServiceError):
    """Raised when the task broker is not configured."""

    pass


class TrackerNotAvailableError(AdminServiceError):
    """Raised when task tracking is not available."""

    pass


class TaskNotFoundError(AdminServiceError):
    """Raised when a task execution is not found."""

    def __init__(self, task_id: str):
        self.task_id = task_id
        super().__init__(f"Task execution not found: {task_id}")


class JobNotFoundError(AdminServiceError):
    """Raised when a scheduled job is not found."""

    def __init__(self, job_id: str, action: str):
        self.job_id = job_id
        self.action = action
        super().__init__(f"Job not found or cannot be {action}: {job_id}")


class AdminService(BaseService):
    """Orchestrates admin task management operations.

    This service handles:
    - Scheduled job management (APScheduler)
    - On-demand task triggering (Taskiq)
    - Task execution tracking (Redis-based tracker)
    """

    def __init__(self) -> None:
        """Initialize admin service."""
        super().__init__()

    # =========================================================================
    # Scheduled Job Management
    # =========================================================================

    def list_scheduled_jobs(self) -> list[dict[str, Any]]:
        """List all scheduled jobs with their status.

        Returns:
            List of job status dictionaries with id, name, next_run_time, trigger.
        """
        return get_job_status()

    def pause_job(self, job_id: str) -> dict[str, str]:
        """Pause a scheduled job.

        Args:
            job_id: ID of the job to pause.

        Returns:
            Status dictionary with job_id and status.

        Raises:
            JobNotFoundError: If the job doesn't exist or can't be paused.
        """
        try:
            pause_job(job_id)
            self.logger.info("Paused scheduled job", extra={"job_id": job_id})
            return {"status": "paused", "job_id": job_id}
        except Exception as e:
            raise JobNotFoundError(job_id, "paused") from e

    def resume_job(self, job_id: str) -> dict[str, str]:
        """Resume a paused scheduled job.

        Args:
            job_id: ID of the job to resume.

        Returns:
            Status dictionary with job_id and status.

        Raises:
            JobNotFoundError: If the job doesn't exist or can't be resumed.
        """
        try:
            resume_job(job_id)
            self.logger.info("Resumed scheduled job", extra={"job_id": job_id})
            return {"status": "resumed", "job_id": job_id}
        except Exception as e:
            raise JobNotFoundError(job_id, "resumed") from e

    # =========================================================================
    # Task Triggering
    # =========================================================================

    async def trigger_task(
        self, task_name: TaskName, params: dict[str, Any] | None = None
    ) -> dict[str, str]:
        """Trigger a background task for immediate execution.

        Args:
            task_name: The task to trigger.
            params: Optional parameters for the task.

        Returns:
            Dictionary with task_id, task_name, status, and message.

        Raises:
            BrokerNotConfiguredError: If the task broker is not available.
            AdminServiceError: If the task fails to trigger.
        """
        if broker is None:
            raise BrokerNotConfiguredError("Task broker not configured")

        params = params or {}

        try:
            task_handle = await self._dispatch_task(task_name, params)

            self.logger.info(
                "Task triggered",
                extra={
                    "task_name": task_name.value,
                    "task_id": task_handle.task_id,
                    "params": params,
                },
            )

            return {
                "task_id": task_handle.task_id,
                "task_name": task_name.value,
                "status": "queued",
                "message": f"Task '{task_name.value}' queued for execution",
            }

        except BrokerNotConfiguredError:
            raise
        except Exception as e:
            self.logger.error(
                "Failed to trigger task",
                extra={"task_name": task_name.value, "error": str(e)},
            )
            raise AdminServiceError(f"Failed to trigger task: {e}") from e

    async def _dispatch_task(self, task_name: TaskName, params: dict[str, Any]) -> Any:
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
                from example_service.tasks.backup.tasks import backup_database

                return await backup_database.kiq()

            # Notification tasks
            case TaskName.check_due_reminders:
                from example_service.tasks.notifications.tasks import check_due_reminders

                return await check_due_reminders.kiq()

            # Cache tasks
            case TaskName.warm_cache:
                from example_service.tasks.cache.tasks import warm_cache

                return await warm_cache.kiq()

            case TaskName.invalidate_cache:
                from example_service.tasks.cache.tasks import invalidate_cache_pattern

                pattern = params.get("pattern", "*")
                return await invalidate_cache_pattern.kiq(pattern=pattern)

            # Export tasks
            case TaskName.export_csv:
                from example_service.tasks.export.tasks import export_data_csv

                model_name = params.get("model", "reminders")
                filters = params.get("filters")
                return await export_data_csv.kiq(model_name=model_name, filters=filters)

            case TaskName.export_json:
                from example_service.tasks.export.tasks import export_data_json

                model_name = params.get("model", "reminders")
                filters = params.get("filters")
                return await export_data_json.kiq(model_name=model_name, filters=filters)

            # Cleanup tasks
            case TaskName.cleanup_temp_files:
                from example_service.tasks.cleanup.tasks import cleanup_temp_files

                max_age = params.get("max_age_hours", 24)
                return await cleanup_temp_files.kiq(max_age_hours=max_age)

            case TaskName.cleanup_old_backups:
                from example_service.tasks.cleanup.tasks import cleanup_old_backups

                return await cleanup_old_backups.kiq()

            case TaskName.cleanup_old_exports:
                from example_service.tasks.cleanup.tasks import cleanup_old_exports

                max_age = params.get("max_age_hours", 48)
                return await cleanup_old_exports.kiq(max_age_hours=max_age)

            case TaskName.cleanup_expired_data:
                from example_service.tasks.cleanup.tasks import cleanup_expired_data

                retention = params.get("retention_days", 30)
                return await cleanup_expired_data.kiq(retention_days=retention)

            case TaskName.run_all_cleanup:
                from example_service.tasks.cleanup.tasks import run_all_cleanup

                return await run_all_cleanup.kiq()

    # =========================================================================
    # Task History & Statistics
    # =========================================================================

    def _get_tracker(self):
        """Get the task tracker, raising if unavailable.

        Returns:
            The task tracker instance.

        Raises:
            TrackerNotAvailableError: If tracking is not available.
        """
        tracker = get_tracker()
        if tracker is None or not tracker.is_connected:
            raise TrackerNotAvailableError("Task tracking not available")
        return tracker

    async def get_task_history(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        task_name: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get task execution history.

        Args:
            limit: Maximum number of results.
            offset: Number of results to skip.
            task_name: Optional filter by task name.
            status: Optional filter by status (success/failure).

        Returns:
            List of task execution records.

        Raises:
            TrackerNotAvailableError: If tracking is not available.
        """
        tracker = self._get_tracker()

        history = await tracker.get_task_history(
            limit=limit,
            offset=offset,
            task_name=task_name,
            status=status,
        )

        return self._format_task_records(history)

    async def get_running_tasks(self) -> list[dict[str, Any]]:
        """Get currently running tasks.

        Returns:
            List of running task records.

        Raises:
            TrackerNotAvailableError: If tracking is not available.
        """
        tracker = self._get_tracker()
        running = await tracker.get_running_tasks()

        return [
            {
                "task_id": task["task_id"],
                "task_name": task["task_name"],
                "started_at": datetime.fromisoformat(task["started_at"]),
                "running_for_ms": task["running_for_ms"],
                "worker_id": task.get("worker_id"),
            }
            for task in running
        ]

    async def get_task_stats(self) -> dict[str, Any]:
        """Get aggregate task execution statistics.

        Returns:
            Statistics dictionary with counts and averages.

        Raises:
            TrackerNotAvailableError: If tracking is not available.
        """
        tracker = self._get_tracker()
        return await tracker.get_stats()

    async def get_task_details(self, task_id: str) -> dict[str, Any]:
        """Get details for a specific task execution.

        Args:
            task_id: ID of the task execution.

        Returns:
            Task execution details.

        Raises:
            TrackerNotAvailableError: If tracking is not available.
            TaskNotFoundError: If the task execution is not found.
        """
        tracker = self._get_tracker()
        task = await tracker.get_task_details(task_id)

        if task is None:
            raise TaskNotFoundError(task_id)

        return self._format_task_record(task)

    def _format_task_records(self, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Format a list of task records for response."""
        return [self._format_task_record(task) for task in tasks]

    def _format_task_record(self, task: dict[str, Any]) -> dict[str, Any]:
        """Format a single task record for response."""
        return {
            "task_id": task["task_id"],
            "task_name": task["task_name"],
            "status": task["status"],
            "started_at": datetime.fromisoformat(task["started_at"]),
            "finished_at": (
                datetime.fromisoformat(task["finished_at"])
                if task.get("finished_at")
                else None
            ),
            "duration_ms": task.get("duration_ms"),
            "return_value": task.get("return_value"),
            "error_message": task.get("error_message"),
            "error_type": task.get("error_type"),
        }


def get_admin_service() -> AdminService:
    """Factory function for AdminService.

    Returns:
        AdminService instance.
    """
    return AdminService()


__all__ = [
    "AdminService",
    "AdminServiceError",
    "BrokerNotConfiguredError",
    "JobNotFoundError",
    "TaskName",
    "TaskNotFoundError",
    "TrackerNotAvailableError",
    "get_admin_service",
]
