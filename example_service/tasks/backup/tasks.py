"""Database backup task definitions.

This module provides:
- pg_dump execution for PostgreSQL backups
- Local backup storage with rotation
- S3 upload for offsite storage
- Old backup cleanup utilities
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from example_service.core.settings import get_backup_settings, get_db_settings
from example_service.tasks.broker import broker

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class BackupError(Exception):
    """Database backup operation error."""

    pass


async def run_pg_dump(
    database_url: str, output_path: Path, exclude_tables: list[str] | None = None
) -> None:
    """Execute pg_dump asynchronously.

    Args:
        database_url: PostgreSQL connection URL (without +psycopg driver specifier).
        output_path: Path to output file (.sql or .sql.gz for compressed).
        exclude_tables: Optional list of tables to exclude from backup.

    Raises:
        BackupError: If pg_dump fails.
    """
    backup_settings = get_backup_settings()

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Build pg_dump command
    pg_dump_path = backup_settings.pg_dump_path
    cmd_parts = [pg_dump_path, database_url, "--format=plain"]

    # Add blob inclusion if configured
    if backup_settings.include_blobs:
        cmd_parts.append("--blobs")

    # Add table exclusions
    if exclude_tables:
        for table in exclude_tables:
            cmd_parts.extend(["--exclude-table", table])
    elif backup_settings.exclude_tables:
        for table in backup_settings.exclude_tables:
            cmd_parts.extend(["--exclude-table", table])

    # Handle compression
    if backup_settings.compression and output_path.suffix == ".gz":
        # Use shell pipeline for compression
        cmd_str = f"{' '.join(cmd_parts)} | gzip > {output_path}"
        logger.info(
            "Running pg_dump with compression",
            extra={"output_path": str(output_path)},
        )

        proc = await asyncio.create_subprocess_shell(
            cmd_str,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    else:
        # Direct file output
        cmd_parts.extend(["--file", str(output_path)])
        logger.info(
            "Running pg_dump",
            extra={"output_path": str(output_path)},
        )

        proc = await asyncio.create_subprocess_exec(
            *cmd_parts,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        error_msg = stderr.decode() if stderr else "Unknown error"
        logger.error(
            "pg_dump failed",
            extra={"returncode": proc.returncode, "stderr": error_msg},
        )
        raise BackupError(f"pg_dump failed with code {proc.returncode}: {error_msg}")

    logger.info(
        "pg_dump completed successfully",
        extra={
            "output_path": str(output_path),
            "size_bytes": output_path.stat().st_size if output_path.exists() else 0,
        },
    )


def cleanup_old_local_backups(backup_dir: Path, retention_days: int) -> int:
    """Remove local backup files older than retention period.

    Args:
        backup_dir: Directory containing backup files.
        retention_days: Number of days to keep backups.

    Returns:
        Number of files deleted.
    """
    if not backup_dir.exists():
        return 0

    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    deleted_count = 0

    for backup_file in backup_dir.glob("backup_*.sql*"):
        if backup_file.is_file():
            # Get file modification time
            mtime = datetime.fromtimestamp(
                backup_file.stat().st_mtime,
                tz=UTC,
            )

            if mtime < cutoff:
                try:
                    backup_file.unlink()
                    deleted_count += 1
                    logger.debug(
                        "Deleted old backup file",
                        extra={"path": str(backup_file), "mtime": mtime.isoformat()},
                    )
                except OSError as e:
                    logger.warning(
                        "Failed to delete old backup file",
                        extra={"path": str(backup_file), "error": str(e)},
                    )

    if deleted_count > 0:
        logger.info(
            "Local backup cleanup completed",
            extra={
                "backup_dir": str(backup_dir),
                "retention_days": retention_days,
                "deleted_count": deleted_count,
            },
        )

    return deleted_count


if broker is not None:

    @broker.task(retry_on_error=True, max_retries=2)
    async def backup_database() -> dict:
        """Create database backup using pg_dump.

        Scheduled: Daily (configurable via BACKUP_SCHEDULE_HOUR).

        Flow:
        1. Check if backup is enabled and database is configured
        2. Run pg_dump to create compressed SQL backup
        3. Upload to S3 (if configured)
        4. Clean up old local backups based on retention policy

        Returns:
            Backup result dictionary with status, paths, and cleanup info.

        Example:
                    # Manually trigger backup
            from example_service.tasks.backup import backup_database
            task = await backup_database.kiq()
            result = await task.wait_result()
            print(result)
            # {'status': 'success', 'local_path': '/var/backups/...', 's3_uri': 's3://...', ...}
        """
        backup_settings = get_backup_settings()
        db_settings = get_db_settings()

        # Validate configuration
        if not backup_settings.is_configured:
            logger.warning("Backup is disabled or not configured, skipping")
            return {"status": "skipped", "reason": "backup_disabled"}

        if not db_settings.is_configured:
            logger.warning("Database is not configured, skipping backup")
            return {"status": "skipped", "reason": "database_not_configured"}

        # Generate timestamp and filename
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        filename = backup_settings.get_backup_filename(timestamp)
        local_path = backup_settings.get_local_path(filename)

        logger.info(
            "Starting database backup",
            extra={
                "timestamp": timestamp,
                "filename": filename,
                "local_path": str(local_path),
                "compression": backup_settings.compression,
            },
        )

        try:
            # Step 1: Run pg_dump
            await run_pg_dump(
                database_url=db_settings.get_psycopg_url(),
                output_path=local_path,
            )

            backup_size = local_path.stat().st_size

            # Step 2: Upload to S3 (if configured)
            s3_uri = None
            if backup_settings.is_s3_configured:
                try:
                    from example_service.infra.storage.s3 import S3Client

                    s3_client = S3Client(backup_settings)
                    s3_key = backup_settings.get_s3_key(filename)
                    s3_uri = await s3_client.upload_file(
                        local_path=local_path,
                        s3_key=s3_key,
                        metadata={
                            "backup_timestamp": timestamp,
                            "database": "postgresql",
                        },
                    )
                    logger.info(
                        "Backup uploaded to S3",
                        extra={"s3_uri": s3_uri},
                    )
                except Exception as e:
                    logger.exception(
                        "Failed to upload backup to S3",
                        extra={"error": str(e)},
                    )
                    # Continue - local backup succeeded

            # Step 3: Clean up old local backups
            deleted_count = cleanup_old_local_backups(
                backup_dir=backup_settings.local_dir,
                retention_days=backup_settings.retention_days,
            )

            result = {
                "status": "success",
                "timestamp": timestamp,
                "local_path": str(local_path),
                "s3_uri": s3_uri,
                "size_bytes": backup_size,
                "size_mb": round(backup_size / (1024 * 1024), 2),
                "old_backups_deleted": deleted_count,
            }

            logger.info(
                "Database backup completed successfully",
                extra=result,
            )

            return result

        except BackupError as e:
            logger.exception("Database backup failed", extra={"error": str(e)})
            raise
        except Exception as e:
            logger.exception("Unexpected error during backup", extra={"error": str(e)})
            raise BackupError(f"Backup failed: {e}") from e

    @broker.task()
    async def list_backups() -> dict:
        """List available backups (local and S3).

        Returns:
            Dictionary with local and S3 backup listings.
        """
        backup_settings = get_backup_settings()

        result = {
            "local_backups": [],
            "s3_backups": [],
        }

        # List local backups
        if backup_settings.local_dir.exists():
            for backup_file in sorted(
                backup_settings.local_dir.glob("backup_*.sql*"),
                reverse=True,
            ):
                stat = backup_file.stat()
                result["local_backups"].append(
                    {
                        "filename": backup_file.name,
                        "path": str(backup_file),
                        "size_bytes": stat.st_size,
                        "size_mb": round(stat.st_size / (1024 * 1024), 2),
                        "modified": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
                    }
                )

        # List S3 backups
        if backup_settings.is_s3_configured:
            try:
                from example_service.infra.storage.s3 import S3Client

                s3_client = S3Client(backup_settings)
                s3_objects = await s3_client.list_objects(prefix=backup_settings.s3_prefix)

                for obj in s3_objects:
                    result["s3_backups"].append(
                        {
                            "key": obj["Key"],
                            "size_bytes": obj["Size"],
                            "size_mb": round(obj["Size"] / (1024 * 1024), 2),
                            "modified": obj["LastModified"].isoformat(),
                        }
                    )
            except Exception as e:
                logger.warning(f"Failed to list S3 backups: {e}")
                result["s3_error"] = str(e)

        return result

    @broker.task()
    async def restore_backup(
        backup_path: str | None = None,
        s3_key: str | None = None,
    ) -> dict:
        """Restore database from backup (placeholder for future implementation).

        Note: This is a placeholder. Actual restore should be done carefully
        with proper planning and possibly manual intervention.

        Args:
            backup_path: Local path to backup file.
            s3_key: S3 key for backup file (downloads first).

        Returns:
            Restore status.
        """
        # This is intentionally a placeholder
        # Database restoration is a critical operation that should be
        # handled with care and possibly manual oversight
        logger.warning(
            "restore_backup called - this is a placeholder task",
            extra={"backup_path": backup_path, "s3_key": s3_key},
        )

        return {
            "status": "not_implemented",
            "message": "Database restoration requires manual intervention. "
            "Use pg_restore or psql directly with the backup file.",
            "backup_path": backup_path,
            "s3_key": s3_key,
        }
