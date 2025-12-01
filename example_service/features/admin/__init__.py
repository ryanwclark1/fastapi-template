"""Admin feature for system operations.

Note: Task management has been migrated to the dedicated tasks feature.
See: example_service.features.tasks

For task management functionality, import from:
    from example_service.features.tasks import (
        TaskManagementService,
        TaskName,
        get_task_service,
    )
"""

from __future__ import annotations

from .router import router

__all__ = [
    "router",
]
