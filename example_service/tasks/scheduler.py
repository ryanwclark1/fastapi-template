"""APScheduler integration for scheduled task execution.

This module manages scheduled tasks using APScheduler with Taskiq:
- APScheduler triggers tasks on a schedule (cron, interval, date)
- Taskiq executes the tasks asynchronously via workers

Run the Taskiq worker to execute scheduled tasks:
    taskiq worker example_service.tasks.broker:broker

Architecture:
    APScheduler (in-process) → Taskiq kiq() → RabbitMQ → Taskiq Worker
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from example_service.tasks.broker import broker

logger = logging.getLogger(__name__)

# Initialize APScheduler (runs in same process as FastAPI)
scheduler = AsyncIOScheduler(
    timezone="UTC",
    job_defaults={
        "coalesce": True,  # Combine multiple pending executions into one
        "max_instances": 1,  # Only one instance of each job at a time
        "misfire_grace_time": 60,  # Allow 60s delay before considering job missed
    },
)


# =============================================================================
# Scheduled Task Definitions
# =============================================================================
# These tasks are triggered by APScheduler on a schedule.
# They're executed asynchronously via Taskiq workers.

if broker is not None:

    @broker.task()
    async def cleanup_expired_sessions() -> dict:
        """Clean up expired sessions from database.

        Scheduled: Daily at 2 AM UTC.
        """
        logger.info("Running cleanup_expired_sessions task")

        try:
            # TODO: Implement cleanup logic
            deleted_count = 0  # Placeholder
            logger.info(f"Cleaned up {deleted_count} expired sessions")
            return {"status": "success", "deleted_count": deleted_count}
        except Exception:
            logger.exception("Failed to cleanup sessions")
            raise

    @broker.task()
    async def generate_hourly_metrics() -> dict:
        """Generate and store hourly metrics.

        Scheduled: Every hour.
        """
        logger.info("Generating hourly metrics")

        try:
            # TODO: Implement metrics generation
            metrics = {
                "timestamp": datetime.now(UTC).isoformat(),
                "active_users": 0,  # Placeholder
                "requests_per_hour": 0,  # Placeholder
            }
            logger.info("Hourly metrics generated successfully")
            return {"status": "success", "metrics": metrics}
        except Exception:
            logger.exception("Failed to generate metrics")
            raise

    @broker.task()
    async def sync_external_data() -> dict:
        """Sync data from external APIs.

        Scheduled: Every 15 minutes.
        """
        logger.info("Syncing external data")

        try:
            # TODO: Implement external sync
            synced_count = 0  # Placeholder
            logger.info(f"Synced {synced_count} records from external source")
            return {"status": "success", "synced_count": synced_count}
        except Exception:
            logger.exception("Failed to sync external data")
            raise

    @broker.task()
    async def send_daily_digest() -> dict:
        """Send daily digest emails to users.

        Scheduled: Daily at 8 AM UTC.
        """
        logger.info("Sending daily digest emails")

        try:
            # TODO: Implement digest sending
            sent_count = 0  # Placeholder
            logger.info(f"Sent daily digest to {sent_count} users")
            return {"status": "success", "sent_count": sent_count}
        except Exception:
            logger.exception("Failed to send daily digest")
            raise

    @broker.task()
    async def publish_heartbeat() -> dict:
        """Publish heartbeat event to message bus.

        Scheduled: Every 60 seconds.

        Demonstrates:
        - Scheduled task execution
        - Message bus publishing
        - System health monitoring

        Note: This task runs in a Taskiq worker, so it uses broker_context()
        to manage the FastStream broker lifecycle.
        """
        from example_service.core.settings import get_rabbit_settings
        from example_service.infra.messaging.broker import broker_context

        rabbit_settings = get_rabbit_settings()

        heartbeat = {
            "event_type": "heartbeat",
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "example-service",
        }

        async with broker_context() as faststream_broker:
            if faststream_broker is not None:
                echo_queue = rabbit_settings.get_prefixed_queue("echo-service")
                await faststream_broker.publish(
                    message=heartbeat,
                    queue=echo_queue,
                )
                logger.info("Heartbeat published to message bus", extra=heartbeat)
            else:
                logger.warning("Message broker not available, heartbeat not published")

        return {"status": "heartbeat_sent", **heartbeat}


# =============================================================================
# Scheduler Job Wrappers
# =============================================================================
# APScheduler requires callable functions that properly await Taskiq tasks.


async def _schedule_cleanup() -> None:
    """Wrapper to properly await the Taskiq kiq() call."""
    await cleanup_expired_sessions.kiq()


async def _schedule_metrics() -> None:
    """Wrapper to properly await the Taskiq kiq() call."""
    await generate_hourly_metrics.kiq()


async def _schedule_sync() -> None:
    """Wrapper to properly await the Taskiq kiq() call."""
    await sync_external_data.kiq()


async def _schedule_digest() -> None:
    """Wrapper to properly await the Taskiq kiq() call."""
    await send_daily_digest.kiq()


async def _schedule_heartbeat() -> None:
    """Wrapper to properly await the Taskiq kiq() call."""
    await publish_heartbeat.kiq()


# -----------------------------------------------------------------------------
# New Background Worker Wrappers
# -----------------------------------------------------------------------------


async def _schedule_database_backup() -> None:
    """Wrapper for database backup task."""
    from example_service.tasks.backup.tasks import backup_database

    await backup_database.kiq()


async def _schedule_check_reminders() -> None:
    """Wrapper for reminder notification check."""
    from example_service.tasks.notifications.tasks import check_due_reminders

    await check_due_reminders.kiq()


async def _schedule_cache_warming() -> None:
    """Wrapper for cache warming task."""
    from example_service.tasks.cache.tasks import warm_cache

    await warm_cache.kiq()


async def _schedule_temp_cleanup() -> None:
    """Wrapper for temp file cleanup task."""
    from example_service.tasks.cleanup.tasks import cleanup_temp_files

    await cleanup_temp_files.kiq()


async def _schedule_backup_cleanup() -> None:
    """Wrapper for old backup cleanup task."""
    from example_service.tasks.cleanup.tasks import cleanup_old_backups

    await cleanup_old_backups.kiq()


async def _schedule_export_cleanup() -> None:
    """Wrapper for old export cleanup task."""
    from example_service.tasks.cleanup.tasks import cleanup_old_exports

    await cleanup_old_exports.kiq()


async def _schedule_data_cleanup() -> None:
    """Wrapper for expired data cleanup task."""
    from example_service.tasks.cleanup.tasks import cleanup_expired_data

    await cleanup_expired_data.kiq()


# =============================================================================
# Scheduler Management
# =============================================================================


def setup_scheduled_jobs() -> None:
    """Register all scheduled jobs with APScheduler.

    Call during application startup AFTER Taskiq broker is initialized.
    """
    if broker is None:
        logger.warning("Taskiq broker not configured, skipping job scheduling")
        return

    logger.info("Setting up scheduled jobs with APScheduler")

    # Cleanup expired sessions daily at 2 AM UTC
    scheduler.add_job(
        func=_schedule_cleanup,
        trigger=CronTrigger(hour=2, minute=0),
        id="cleanup_sessions",
        name="Cleanup expired sessions",
        replace_existing=True,
    )

    # Generate metrics every hour
    scheduler.add_job(
        func=_schedule_metrics,
        trigger=IntervalTrigger(hours=1),
        id="hourly_metrics",
        name="Generate hourly metrics",
        replace_existing=True,
    )

    # Sync external data every 15 minutes
    scheduler.add_job(
        func=_schedule_sync,
        trigger=IntervalTrigger(minutes=15),
        id="sync_external",
        name="Sync external data",
        replace_existing=True,
    )

    # Send daily digest at 8 AM UTC
    scheduler.add_job(
        func=_schedule_digest,
        trigger=CronTrigger(hour=8, minute=0),
        id="daily_digest",
        name="Send daily digest",
        replace_existing=True,
    )

    # Publish heartbeat every 60 seconds
    scheduler.add_job(
        func=_schedule_heartbeat,
        trigger=IntervalTrigger(seconds=60),
        id="heartbeat",
        name="Publish heartbeat every 60 seconds",
        replace_existing=True,
    )

    # -------------------------------------------------------------------------
    # New Background Worker Jobs
    # -------------------------------------------------------------------------

    # Database backup - daily at configured hour (default 2 AM)
    from example_service.core.settings import get_backup_settings

    backup_settings = get_backup_settings()
    if backup_settings.is_configured:
        scheduler.add_job(
            func=_schedule_database_backup,
            trigger=CronTrigger(
                hour=backup_settings.schedule_hour,
                minute=backup_settings.schedule_minute,
            ),
            id="database_backup",
            name="Daily database backup",
            replace_existing=True,
        )

    # Check due reminders - every 1 minute
    scheduler.add_job(
        func=_schedule_check_reminders,
        trigger=IntervalTrigger(minutes=1),
        id="check_reminders",
        name="Check due reminders",
        replace_existing=True,
    )

    # Cache warming - every 30 minutes
    scheduler.add_job(
        func=_schedule_cache_warming,
        trigger=IntervalTrigger(minutes=30),
        id="cache_warming",
        name="Warm cache with frequently accessed data",
        replace_existing=True,
    )

    # Temp file cleanup - daily at 3 AM UTC
    scheduler.add_job(
        func=_schedule_temp_cleanup,
        trigger=CronTrigger(hour=3, minute=0),
        id="temp_cleanup",
        name="Clean up temporary files",
        replace_existing=True,
    )

    # Old backup cleanup - daily at 4 AM UTC
    scheduler.add_job(
        func=_schedule_backup_cleanup,
        trigger=CronTrigger(hour=4, minute=0),
        id="backup_cleanup",
        name="Clean up old backup files",
        replace_existing=True,
    )

    # Export file cleanup - daily at 3:30 AM UTC
    scheduler.add_job(
        func=_schedule_export_cleanup,
        trigger=CronTrigger(hour=3, minute=30),
        id="export_cleanup",
        name="Clean up old export files",
        replace_existing=True,
    )

    # Expired data cleanup - daily at 2 AM UTC (alongside session cleanup)
    scheduler.add_job(
        func=_schedule_data_cleanup,
        trigger=CronTrigger(hour=2, minute=30),
        id="data_cleanup",
        name="Clean up expired database records",
        replace_existing=True,
    )

    logger.info(f"Scheduled {len(scheduler.get_jobs())} jobs")


async def start_scheduler() -> None:
    """Start the APScheduler.

    Call during application startup after setup_scheduled_jobs().
    """
    if not scheduler.running:
        logger.info("Starting APScheduler")
        scheduler.start()
        logger.info(f"APScheduler started with {len(scheduler.get_jobs())} jobs")
    else:
        logger.warning("APScheduler is already running")


async def stop_scheduler() -> None:
    """Stop the APScheduler gracefully.

    Call during application shutdown.
    """
    if scheduler.running:
        logger.info("Stopping APScheduler")
        scheduler.shutdown(wait=True)
        logger.info("APScheduler stopped")
    else:
        logger.debug("APScheduler is not running")


# =============================================================================
# Job Management Utilities
# =============================================================================


def get_job_status() -> list[dict]:
    """Get status of all scheduled jobs.

    Returns:
        List of job information dictionaries.
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


def pause_job(job_id: str) -> None:
    """Pause a scheduled job."""
    scheduler.pause_job(job_id)
    logger.info(f"Paused job: {job_id}")


def resume_job(job_id: str) -> None:
    """Resume a paused job."""
    scheduler.resume_job(job_id)
    logger.info(f"Resumed job: {job_id}")
