"""File processing tasks.

This module provides background tasks for file processing:
- File validation and status updates
- Thumbnail generation for images
- Cleanup of expired files
"""

from __future__ import annotations

try:
    from .tasks import cleanup_expired_files, generate_thumbnails, process_uploaded_file
except ImportError:  # Optional dependencies missing (e.g., broker not configured)
    cleanup_expired_files = None  # type: ignore[assignment]
    generate_thumbnails = None  # type: ignore[assignment]
    process_uploaded_file = None  # type: ignore[assignment]
    __all__: list[str] = []
else:
    __all__ = [
        "cleanup_expired_files",
        "generate_thumbnails",
        "process_uploaded_file",
    ]
