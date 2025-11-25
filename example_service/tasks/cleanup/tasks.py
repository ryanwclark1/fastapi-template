"""Cleanup and maintenance task definitions.

This module provides:
- Temporary file cleanup
- Old backup file rotation
- Export file cleanup
- Database record cleanup (e.g., old completed reminders)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete

from example_service.core.settings import get_backup_settings
from example_service.infra.database.session import get_async_session
from example_service.tasks.broker import broker

logger = logging.getLogger(__name__)


if broker is not None:

    @broker.task()
    async def cleanup_temp_files(max_age_hours: int = 24) -> dict:
        """Remove temporary files older than max_age_hours.

        Scheduled: Daily at 3 AM UTC.

        Args:
            max_age_hours: Maximum age of files to keep (default 24 hours).

        Returns:
            Cleanup result with counts and sizes.

        Example:
            ```python
            from example_service.tasks.cleanup import cleanup_temp_files
            task = await cleanup_temp_files.kiq(max_age_hours=12)
            result = await task.wait_result()
            print(result)
            # {'deleted_count': 5, 'deleted_size_mb': 12.5}
            ```
        """
        temp_dirs = [
            Path("/tmp/exports"),
            Path("/tmp/uploads"),
        ]

        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        deleted_count = 0
        deleted_size = 0
        errors = []

        for temp_dir in temp_dirs:
            if not temp_dir.exists():
                continue

            for file_path in temp_dir.iterdir():
                if file_path.is_file():
                    try:
                        mtime = datetime.fromtimestamp(
                            file_path.stat().st_mtime,
                            tz=timezone.utc,
                        )

                        if mtime < cutoff:
                            file_size = file_path.stat().st_size
                            file_path.unlink()
                            deleted_count += 1
                            deleted_size += file_size
                            logger.debug(
                                "Deleted temp file",
                                extra={"path": str(file_path), "size": file_size},
                            )
                    except OSError as e:
                        errors.append({"path": str(file_path), "error": str(e)})
                        logger.warning(
                            "Failed to delete temp file",
                            extra={"path": str(file_path), "error": str(e)},
                        )

        result = {
            "status": "success" if not errors else "partial",
            "deleted_count": deleted_count,
            "deleted_size_bytes": deleted_size,
            "deleted_size_mb": round(deleted_size / (1024 * 1024), 2),
            "max_age_hours": max_age_hours,
        }

        if errors:
            result["errors"] = errors

        logger.info("Temp file cleanup completed", extra=result)

        return result

    @broker.task()
    async def cleanup_old_backups() -> dict:
        """Remove old backup files beyond retention period.

        Scheduled: Daily at 4 AM UTC.

        Cleans both local filesystem and S3 storage based on
        retention settings.

        Returns:
            Cleanup result with local and S3 deletion counts.
        """
        backup_settings = get_backup_settings()

        # Import local cleanup utility
        from example_service.tasks.backup.tasks import cleanup_old_local_backups

        # Clean local backups
        local_deleted = cleanup_old_local_backups(
            backup_dir=backup_settings.local_dir,
            retention_days=backup_settings.retention_days,
        )

        # Clean S3 backups
        s3_deleted = 0
        s3_error = None

        if backup_settings.is_s3_configured:
            try:
                from example_service.infra.storage.s3 import S3Client

                s3_client = S3Client(backup_settings)
                s3_deleted = await s3_client.delete_old_objects(
                    prefix=backup_settings.s3_prefix,
                    retention_days=backup_settings.s3_retention_days,
                )
            except Exception as e:
                s3_error = str(e)
                logger.warning(f"Failed to cleanup S3 backups: {e}")

        result = {
            "status": "success" if not s3_error else "partial",
            "local_deleted": local_deleted,
            "local_retention_days": backup_settings.retention_days,
            "s3_deleted": s3_deleted,
            "s3_retention_days": backup_settings.s3_retention_days,
        }

        if s3_error:
            result["s3_error"] = s3_error

        logger.info("Backup cleanup completed", extra=result)

        return result

    @broker.task()
    async def cleanup_old_exports(max_age_hours: int = 48) -> dict:
        """Remove old export files.

        Args:
            max_age_hours: Maximum age of export files to keep.

        Returns:
            Cleanup result with deletion counts.
        """
        export_dir = Path("/tmp/exports")

        if not export_dir.exists():
            return {
                "status": "success",
                "deleted_count": 0,
                "reason": "export_dir_not_found",
            }

        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        deleted_count = 0
        deleted_size = 0

        for export_file in export_dir.glob("*.*"):
            if export_file.is_file():
                try:
                    mtime = datetime.fromtimestamp(
                        export_file.stat().st_mtime,
                        tz=timezone.utc,
                    )

                    if mtime < cutoff:
                        file_size = export_file.stat().st_size
                        export_file.unlink()
                        deleted_count += 1
                        deleted_size += file_size
                except OSError as e:
                    logger.warning(
                        "Failed to delete export file",
                        extra={"path": str(export_file), "error": str(e)},
                    )

        result = {
            "status": "success",
            "deleted_count": deleted_count,
            "deleted_size_mb": round(deleted_size / (1024 * 1024), 2),
            "max_age_hours": max_age_hours,
        }

        logger.info("Export cleanup completed", extra=result)

        return result

    @broker.task()
    async def cleanup_expired_data(retention_days: int = 30) -> dict:
        """Clean up expired/old database records.

        Scheduled: Daily at 2 AM UTC.

        Currently cleans:
        - Old completed reminders (beyond retention period)

        Args:
            retention_days: Days to keep completed records.

        Returns:
            Cleanup result with deletion counts per table.
        """
        from example_service.features.reminders.models import Reminder

        results = {}
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

        async with get_async_session() as session:
            # Clean old completed reminders
            try:
                stmt = delete(Reminder).where(
                    Reminder.is_completed == True,  # noqa: E712
                    Reminder.updated_at < cutoff,
                )
                result = await session.execute(stmt)
                await session.commit()

                results["reminders"] = {
                    "deleted_count": result.rowcount,
                    "retention_days": retention_days,
                }

                logger.info(
                    "Cleaned old completed reminders",
                    extra={"deleted_count": result.rowcount},
                )
            except Exception as e:
                results["reminders"] = {"error": str(e)}
                logger.exception("Failed to cleanup old reminders")

        return {
            "status": "success",
            "retention_days": retention_days,
            "cutoff_date": cutoff.isoformat(),
            "tables": results,
        }

    @broker.task()
    async def run_all_cleanup() -> dict:
        """Run all cleanup tasks sequentially.

        Useful for manual maintenance or testing.

        Returns:
            Combined results from all cleanup tasks.
        """
        results = {}

        # Run temp file cleanup
        temp_result = await cleanup_temp_files()
        results["temp_files"] = temp_result

        # Run export cleanup
        export_result = await cleanup_old_exports()
        results["exports"] = export_result

        # Run backup cleanup
        backup_result = await cleanup_old_backups()
        results["backups"] = backup_result

        # Run database cleanup
        db_result = await cleanup_expired_data()
        results["database"] = db_result

        logger.info("All cleanup tasks completed", extra=results)

        return {
            "status": "success",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "results": results,
        }
