"""Scheduled task examples using Taskiq scheduler.

These examples demonstrate how to create scheduled/cron tasks that run
automatically at specified intervals or times.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from example_service.infra.tasks.broker import broker, scheduler

logger = logging.getLogger(__name__)


if broker is not None and scheduler is not None:

    @broker.task()
    async def cleanup_old_sessions() -> dict:
        """Clean up expired sessions from the database.

        This task is typically scheduled to run periodically to remove
        old session data and free up storage.

        Returns:
            Cleanup statistics
        """
        logger.info("Running cleanup_old_sessions task")

        try:
            # TODO: Implement session cleanup logic
            # from example_service.infra.database import get_async_session
            # from sqlalchemy import delete, select
            # from example_service.core.models import Session

            # async with get_async_session() as session:
            #     cutoff_date = datetime.utcnow() - timedelta(days=30)
            #     result = await session.execute(
            #         delete(Session).where(Session.expires_at < cutoff_date)
            #     )
            #     await session.commit()
            #     deleted_count = result.rowcount

            deleted_count = 0  # Placeholder
            logger.info(f"Cleaned up {deleted_count} old sessions")
            return {"deleted_count": deleted_count, "status": "success"}

        except Exception as e:
            logger.exception(f"Failed to cleanup sessions: {e}")
            raise

    @broker.task()
    async def generate_daily_report() -> dict:
        """Generate daily summary report.

        This task aggregates data and generates a report that can be
        emailed to stakeholders or stored for later retrieval.

        Returns:
            Report generation status
        """
        logger.info("Generating daily report")

        try:
            # TODO: Implement report generation logic
            # - Query database for metrics
            # - Generate charts/graphs
            # - Create PDF/HTML report
            # - Email to stakeholders

            report_data = {
                "date": datetime.utcnow().date().isoformat(),
                "total_users": 0,  # Placeholder
                "active_users": 0,  # Placeholder
                "new_registrations": 0,  # Placeholder
            }

            logger.info("Daily report generated successfully")
            return {"status": "success", "report": report_data}

        except Exception as e:
            logger.exception(f"Failed to generate report: {e}")
            raise

    @broker.task()
    async def sync_external_data() -> dict:
        """Sync data from external sources.

        This task fetches data from external APIs or services and
        updates the local database.

        Returns:
            Sync status
        """
        logger.info("Syncing external data")

        try:
            # TODO: Implement external data sync
            # - Fetch from external API
            # - Transform data
            # - Update database
            # - Handle conflicts

            synced_records = 0  # Placeholder
            logger.info(f"Synced {synced_records} records from external source")
            return {"status": "success", "synced_records": synced_records}

        except Exception as e:
            logger.exception(f"Failed to sync external data: {e}")
            raise

    @broker.task()
    async def backup_database() -> dict:
        """Perform database backup.

        This task creates a backup of the database and uploads it
        to a remote storage service.

        Returns:
            Backup status
        """
        logger.info("Starting database backup")

        try:
            # TODO: Implement backup logic
            # - Create database dump
            # - Compress backup
            # - Upload to S3/GCS
            # - Cleanup old backups

            backup_size_mb = 0  # Placeholder
            logger.info(f"Database backup completed ({backup_size_mb}MB)")
            return {
                "status": "success",
                "backup_size_mb": backup_size_mb,
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.exception(f"Database backup failed: {e}")
            raise

    # Schedule tasks using cron expressions
    # https://en.wikipedia.org/wiki/Cron

    # Run cleanup every day at 2 AM
    scheduler.task(cleanup_old_sessions, cron="0 2 * * *")

    # Generate report every day at 8 AM
    scheduler.task(generate_daily_report, cron="0 8 * * *")

    # Sync external data every hour
    scheduler.task(sync_external_data, cron="0 * * * *")

    # Backup database every day at 3 AM
    scheduler.task(backup_database, cron="0 3 * * *")


    # Alternative: Using timedelta for simpler recurring tasks
    # scheduler.task(
    #     cleanup_old_sessions,
    #     time=timedelta(hours=24),  # Run every 24 hours
    # )
