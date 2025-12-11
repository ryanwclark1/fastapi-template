"""Task execution infrastructure using Taskiq.

This package provides the infrastructure layer for background task execution:
- broker.py: Taskiq broker configuration (taskiq-aio-pika for RabbitMQ)
- middleware.py: Task middleware (metrics, tracing, tracking)
- scheduler.py: APScheduler integration for periodic task execution
- tracking/: Task execution tracking (Redis/PostgreSQL backends)
- jobs/: Job orchestration system with priorities, dependencies, audit trail

For task definitions (the actual work), see the `workers/` package.

Run the worker to execute tasks:
    taskiq worker example_service.infra.tasks.broker:broker
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from taskiq_aio_pika import AioPikaBroker as AioPikaBrokerType
else:
    AioPikaBrokerType = Any

# Unconditional local imports
from example_service.infra.tasks.tracking import (
    TaskExecutionTracker,
    get_tracker,
    start_tracker,
    stop_tracker,
)

# Conditional imports - broker/scheduler may not be available during test runs
try:
    from example_service.infra.tasks.broker import broker, get_broker
except ImportError:
    broker = None

    async def get_broker() -> AsyncIterator[AioPikaBrokerType | None]:
        """Yield None when the broker backend is unavailable."""
        yield None


try:
    from example_service.infra.tasks.scheduler import (
        get_job_status,
        pause_job,
        resume_job,
        scheduler,
        setup_scheduled_jobs,
        start_scheduler,
        stop_scheduler,
    )
except ImportError:
    scheduler = None

    def get_job_status() -> list[dict[Any, Any]]:
        """Return an empty job list when scheduler is unavailable."""
        return []

    def pause_job(job_id: str) -> None:
        """No-op pause function when scheduler is unavailable."""

    def resume_job(job_id: str) -> None:
        """No-op resume function when scheduler is unavailable."""

    def setup_scheduled_jobs() -> None:
        """No-op scheduled job setup when scheduler is unavailable."""

    async def start_scheduler() -> None:
        """No-op scheduler startup when scheduler is unavailable."""

    async def stop_scheduler() -> None:
        """No-op scheduler shutdown when scheduler is unavailable."""


__all__ = [
    # Tracking
    "TaskExecutionTracker",
    # Broker
    "broker",
    "get_broker",
    "get_job_status",
    "get_tracker",
    "pause_job",
    "resume_job",
    # Scheduler
    "scheduler",
    "setup_scheduled_jobs",
    "start_scheduler",
    "start_tracker",
    "stop_scheduler",
    "stop_tracker",
]
