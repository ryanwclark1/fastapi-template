"""Export file cleanup utilities.

Provides scheduled cleanup of old export files based on retention settings.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
from pathlib import Path

from example_service.core.settings import get_datatransfer_settings

logger = logging.getLogger(__name__)


def cleanup_old_exports() -> dict[str, int]:
    """Clean up export files older than the retention period.

    Removes export files from the export directory that are older
    than the configured retention period.

    Returns:
        Dictionary with cleanup statistics:
        - deleted_count: Number of files deleted
        - skipped_count: Number of files skipped (not old enough)
        - error_count: Number of errors encountered
        - total_bytes_freed: Total bytes freed
    """
    settings = get_datatransfer_settings()
    export_dir = settings.export_path
    retention_hours = settings.export_retention_hours

    stats = {
        "deleted_count": 0,
        "skipped_count": 0,
        "error_count": 0,
        "total_bytes_freed": 0,
    }

    if not export_dir.exists():
        logger.debug("Export directory does not exist: %s", export_dir)
        return stats

    cutoff_time = datetime.now(UTC) - timedelta(hours=retention_hours)
    cutoff_timestamp = cutoff_time.timestamp()

    logger.info(
        "Starting export cleanup",
        extra={
            "export_dir": str(export_dir),
            "retention_hours": retention_hours,
            "cutoff_time": cutoff_time.isoformat(),
        },
    )

    # Iterate through files in export directory
    for file_path in export_dir.iterdir():
        if not file_path.is_file():
            continue

        try:
            file_stat = file_path.stat()
            file_mtime = file_stat.st_mtime

            if file_mtime < cutoff_timestamp:
                # File is older than retention period
                file_size = file_stat.st_size
                file_path.unlink()

                stats["deleted_count"] += 1
                stats["total_bytes_freed"] += file_size

                logger.debug(
                    "Deleted old export file",
                    extra={
                        "file": str(file_path),
                        "size_bytes": file_size,
                        "age_hours": (datetime.now(UTC).timestamp() - file_mtime) / 3600,
                    },
                )
            else:
                stats["skipped_count"] += 1

        except OSError as e:
            stats["error_count"] += 1
            logger.warning(
                "Failed to process export file",
                extra={"file": str(file_path), "error": str(e)},
            )

    logger.info(
        "Export cleanup completed",
        extra={
            "deleted_count": stats["deleted_count"],
            "skipped_count": stats["skipped_count"],
            "error_count": stats["error_count"],
            "total_bytes_freed": stats["total_bytes_freed"],
            "total_mb_freed": stats["total_bytes_freed"] / (1024 * 1024),
        },
    )

    return stats


async def cleanup_old_exports_async() -> dict[str, int]:
    """Async wrapper for cleanup_old_exports.

    Can be used as a background task or scheduled job.

    Returns:
        Cleanup statistics dictionary.
    """
    import asyncio

    # Run in thread pool to avoid blocking
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, cleanup_old_exports)


def get_export_stats() -> dict[str, int | float]:
    """Get statistics about current export files.

    Returns:
        Dictionary with:
        - file_count: Number of export files
        - total_size_bytes: Total size of all files
        - total_size_mb: Total size in MB
        - oldest_file_hours: Age of oldest file in hours
        - newest_file_hours: Age of newest file in hours
    """
    settings = get_datatransfer_settings()
    export_dir = settings.export_path

    stats: dict[str, int | float] = {
        "file_count": 0,
        "total_size_bytes": 0,
        "total_size_mb": 0.0,
        "oldest_file_hours": 0.0,
        "newest_file_hours": 0.0,
    }

    if not export_dir.exists():
        return stats

    now = datetime.now(UTC).timestamp()
    oldest_mtime = now
    newest_mtime = 0.0

    for file_path in export_dir.iterdir():
        if not file_path.is_file():
            continue

        try:
            file_stat = file_path.stat()
            stats["file_count"] += 1
            stats["total_size_bytes"] += file_stat.st_size

            if file_stat.st_mtime < oldest_mtime:
                oldest_mtime = file_stat.st_mtime
            if file_stat.st_mtime > newest_mtime:
                newest_mtime = file_stat.st_mtime

        except OSError:
            pass

    stats["total_size_mb"] = stats["total_size_bytes"] / (1024 * 1024)

    if stats["file_count"] > 0:
        stats["oldest_file_hours"] = (now - oldest_mtime) / 3600
        stats["newest_file_hours"] = (now - newest_mtime) / 3600

    return stats
