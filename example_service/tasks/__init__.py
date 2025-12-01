"""Background task infrastructure using Taskiq.

This package provides:
- broker.py: Taskiq broker configuration (taskiq-aio-pika for tasks)
- scheduler.py: APScheduler integration for periodic task execution
- tasks.py: Main background task definitions (examples)

Task modules:
- backup/: Database backup tasks (pg_dump + S3 upload)
- notifications/: Reminder notification tasks
- cache/: Cache warming and invalidation
- export/: Data export (CSV/JSON)
- cleanup/: Cleanup tasks (temp files, old backups, expired data)

Run the worker to execute tasks:
    taskiq worker example_service.tasks.broker:broker
"""

from __future__ import annotations

# Re-export task modules for convenient access
# Import broker/scheduler lazily to avoid hard dependency during test runs
try:
    from example_service.tasks.broker import broker, get_broker
except Exception:  # pragma: no cover - broker optional in some environments
    broker = None  # type: ignore[assignment]

    def get_broker():  # type: ignore[override]
        return None


try:
    from example_service.tasks.scheduler import (
        get_job_status,
        pause_job,
        resume_job,
        scheduler,
        setup_scheduled_jobs,
        start_scheduler,
        stop_scheduler,
    )
except Exception:  # pragma: no cover - scheduler optional without broker
    scheduler = None  # type: ignore[assignment]

    def get_job_status():
        return []

    def pause_job(job_id: str) -> None:  # noqa: ARG001
        return None

    def resume_job(job_id: str) -> None:  # noqa: ARG001
        return None

    def setup_scheduled_jobs() -> None:
        return None

    async def start_scheduler() -> None:
        return None

    async def stop_scheduler() -> None:
        return None


from example_service.tasks.tracking import (
    TaskExecutionTracker,
    get_tracker,
    start_tracker,
    stop_tracker,
)

__all__ = [
    # Broker
    "broker",
    "get_broker",
    # Scheduler
    "scheduler",
    "setup_scheduled_jobs",
    "start_scheduler",
    "stop_scheduler",
    "get_job_status",
    "pause_job",
    "resume_job",
    # Tracking
    "TaskExecutionTracker",
    "get_tracker",
    "start_tracker",
    "stop_tracker",
]
