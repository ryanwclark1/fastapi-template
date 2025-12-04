"""Admin feature for system operations.

This module provides:
- Email administration endpoints (email_admin.py)

Note: Task management has been migrated to the dedicated tasks feature.
See: example_service.features.tasks
"""

from __future__ import annotations

from .email_admin import router as email_admin_router

__all__ = [
    "email_admin_router",
]
