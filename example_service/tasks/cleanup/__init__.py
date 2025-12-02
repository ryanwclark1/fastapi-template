"""Cleanup and maintenance tasks.

This module provides:
- Temporary file cleanup
- Old backup cleanup
- Expired data cleanup
"""

from __future__ import annotations

try:
    from .tasks import (
        cleanup_expired_data,
        cleanup_old_backups,
        cleanup_old_exports,
        cleanup_temp_files,
    )
except ImportError:
    cleanup_temp_files = None  # type: ignore[assignment]
    cleanup_old_backups = None  # type: ignore[assignment]
    cleanup_old_exports = None  # type: ignore[assignment]
    cleanup_expired_data = None  # type: ignore[assignment]
    __all__: list[str] = []
else:
    __all__ = [
        "cleanup_expired_data",
        "cleanup_old_backups",
        "cleanup_old_exports",
        "cleanup_temp_files",
    ]
