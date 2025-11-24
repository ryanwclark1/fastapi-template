"""APScheduler integration for advanced task scheduling.

APScheduler provides more sophisticated scheduling capabilities compared to
basic Taskiq scheduling:

- Cron-like scheduling with better syntax
- Interval-based scheduling
- Date-based one-time scheduling
- Persistent job stores (database, Redis)
- Job coalescing and misfire handling
- Timezone support

This is the recommended approach for production scheduling.

Installation:
    pip install apscheduler>=3.10.0

Documentation:
    https://apscheduler.readthedocs.io/
"""

from __future__ import annotations

import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from example_service.core.tasks.broker import broker

logger = logging.getLogger(__name__)

# Initialize APScheduler
# This scheduler runs in the same process as your FastAPI application
scheduler = AsyncIOScheduler(
    timezone="UTC",  # Always use UTC for consistency
    job_defaults={
        "coalesce": True,  # Combine multiple pending executions into one
        "max_instances": 1,  # Only one instance of each job at a time
        "misfire_grace_time": 60,  # Allow 60s delay before considering job missed
    },
)


# Example scheduled tasks using APScheduler + Taskiq
if broker is not None:

    @broker.task()
    async def cleanup_expired_sessions() -> dict:
        """Clean up expired sessions from database.

        This task is scheduled via APScheduler to run every day at 2 AM UTC.
        """
        logger.info("Running cleanup_expired_sessions task")

        try:
            # TODO: Implement cleanup logic
            # from example_service.infra.database import get_async_session
            # async with get_async_session() as session:
            #     ...cleanup logic...

            deleted_count = 0  # Placeholder
            logger.info(f"Cleaned up {deleted_count} expired sessions")
            return {"status": "success", "deleted_count": deleted_count}

        except Exception as e:
            logger.exception("Failed to cleanup sessions")
            raise

    @broker.task()
    async def generate_hourly_metrics() -> dict:
        """Generate and store hourly metrics.

        This task runs every hour via APScheduler.
        """
        logger.info("Generating hourly metrics")

        try:
            # TODO: Implement metrics generation
            # - Query database for stats
            # - Calculate metrics
            # - Store in time-series database

            metrics = {
                "timestamp": datetime.utcnow().isoformat(),
                "active_users": 0,  # Placeholder
                "requests_per_hour": 0,  # Placeholder
            }

            logger.info("Hourly metrics generated successfully")
            return {"status": "success", "metrics": metrics}

        except Exception as e:
            logger.exception("Failed to generate metrics")
            raise

    @broker.task()
    async def sync_external_data() -> dict:
        """Sync data from external APIs.

        Runs every 15 minutes via APScheduler.
        """
        logger.info("Syncing external data")

        try:
            # TODO: Implement external sync
            synced_count = 0  # Placeholder
            logger.info(f"Synced {synced_count} records from external source")
            return {"status": "success", "synced_count": synced_count}

        except Exception as e:
            logger.exception("Failed to sync external data")
            raise

    @broker.task()
    async def send_daily_digest() -> dict:
        """Send daily digest emails to users.

        Runs every day at 8 AM UTC via APScheduler.
        """
        logger.info("Sending daily digest emails")

        try:
            # TODO: Implement digest sending
            # - Query users who opted in
            # - Generate digest content
            # - Send emails asynchronously

            sent_count = 0  # Placeholder
            logger.info(f"Sent daily digest to {sent_count} users")
            return {"status": "success", "sent_count": sent_count}

        except Exception as e:
            logger.exception("Failed to send daily digest")
            raise


def setup_scheduled_jobs() -> None:
    """Set up all scheduled jobs with APScheduler.

    Call this function during application startup to register all
    scheduled tasks with APScheduler.

    This should be called AFTER the Taskiq broker is initialized.
    """
    if broker is None:
        logger.warning("Taskiq broker not configured, skipping job scheduling")
        return

    logger.info("Setting up scheduled jobs with APScheduler")

    # Schedule cleanup every day at 2 AM UTC
    scheduler.add_job(
        func=lambda: cleanup_expired_sessions.kiq(),
        trigger=CronTrigger(hour=2, minute=0),
        id="cleanup_sessions",
        name="Cleanup expired sessions",
        replace_existing=True,
    )

    # Generate metrics every hour
    scheduler.add_job(
        func=lambda: generate_hourly_metrics.kiq(),
        trigger=IntervalTrigger(hours=1),
        id="hourly_metrics",
        name="Generate hourly metrics",
        replace_existing=True,
    )

    # Sync external data every 15 minutes
    scheduler.add_job(
        func=lambda: sync_external_data.kiq(),
        trigger=IntervalTrigger(minutes=15),
        id="sync_external",
        name="Sync external data",
        replace_existing=True,
    )

    # Send daily digest at 8 AM UTC
    scheduler.add_job(
        func=lambda: send_daily_digest.kiq(),
        trigger=CronTrigger(hour=8, minute=0),
        id="daily_digest",
        name="Send daily digest",
        replace_existing=True,
    )

    logger.info(f"Scheduled {len(scheduler.get_jobs())} jobs")


async def start_scheduler() -> None:
    """Start the APScheduler.

    Call this during application startup, after setting up scheduled jobs.

    Example:
        ```python
        # In lifespan.py
        from example_service.core.tasks.examples.apscheduler_integration import (
            setup_scheduled_jobs,
            start_scheduler,
            stop_scheduler,
        )

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            # ... other startup code ...

            # Set up and start APScheduler
            setup_scheduled_jobs()
            await start_scheduler()

            yield

            # Shutdown APScheduler
            await stop_scheduler()
        ```
    """
    if not scheduler.running:
        logger.info("Starting APScheduler")
        scheduler.start()
        logger.info(f"APScheduler started with {len(scheduler.get_jobs())} jobs")
    else:
        logger.warning("APScheduler is already running")


async def stop_scheduler() -> None:
    """Stop the APScheduler gracefully.

    Call this during application shutdown.
    """
    if scheduler.running:
        logger.info("Stopping APScheduler")
        scheduler.shutdown(wait=True)
        logger.info("APScheduler stopped")
    else:
        logger.debug("APScheduler is not running")


# Advanced scheduling examples
def schedule_one_time_task(task_name: str, run_time: datetime) -> None:
    """Schedule a one-time task to run at a specific time.

    Example:
        ```python
        from datetime import datetime, timedelta

        # Schedule a task to run in 1 hour
        future_time = datetime.utcnow() + timedelta(hours=1)
        schedule_one_time_task("send_reminder", future_time)
        ```

    Args:
        task_name: Name/ID of the task
        run_time: When to run the task (datetime object)
    """
    scheduler.add_job(
        func=lambda: logger.info(f"Running one-time task: {task_name}"),
        trigger="date",
        run_date=run_time,
        id=f"onetime_{task_name}",
        name=f"One-time: {task_name}",
        replace_existing=True,
    )
    logger.info(f"Scheduled one-time task '{task_name}' for {run_time}")


def pause_job(job_id: str) -> None:
    """Pause a scheduled job.

    Example:
        ```python
        pause_job("cleanup_sessions")
        ```

    Args:
        job_id: ID of the job to pause
    """
    scheduler.pause_job(job_id)
    logger.info(f"Paused job: {job_id}")


def resume_job(job_id: str) -> None:
    """Resume a paused job.

    Example:
        ```python
        resume_job("cleanup_sessions")
        ```

    Args:
        job_id: ID of the job to resume
    """
    scheduler.resume_job(job_id)
    logger.info(f"Resumed job: {job_id}")


def get_job_status() -> list[dict]:
    """Get status of all scheduled jobs.

    Returns:
        List of job information dictionaries

    Example:
        ```python
        jobs = get_job_status()
        for job in jobs:
            print(f"{job['name']}: next run at {job['next_run_time']}")
        ```
    """
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append(
            {
                "id": job.id,
                "name": job.name,
                "next_run_time": job.next_run_time.isoformat()
                if job.next_run_time
                else None,
                "trigger": str(job.trigger),
            }
        )
    return jobs
