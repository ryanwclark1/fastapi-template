"""Database backup tasks.

This module provides scheduled database backup functionality:
- pg_dump for PostgreSQL backups
- Local filesystem storage with rotation
- S3 upload for offsite storage
- Automatic cleanup of old backups
"""

from __future__ import annotations

try:
    from .tasks import backup_database, cleanup_old_local_backups, run_pg_dump
except ImportError:  # Optional dependencies missing (e.g., broker not configured)
    backup_database = None  # type: ignore[assignment]
    cleanup_old_local_backups = None  # type: ignore[assignment]
    run_pg_dump = None  # type: ignore[assignment]
    __all__: list[str] = []
else:
    __all__ = [
        "backup_database",
        "cleanup_old_local_backups",
        "run_pg_dump",
    ]
