"""Admin feature for system operations.

This module provides:
- Email administration endpoints (email/)

Note: Task management has been migrated to the dedicated tasks feature.
See: example_service.features.tasks
"""

from __future__ import annotations

from .email import router as email_admin_router

__all__ = [
    "email_admin_router",
]
