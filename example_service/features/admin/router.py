"""Admin API endpoints.

This module provides administrative endpoints for system management.

Note: Task management endpoints have been migrated to the dedicated
tasks feature module at /api/v1/tasks/*. See:
- GET /api/v1/tasks - Search task history
- GET /api/v1/tasks/running - Running tasks
- GET /api/v1/tasks/stats - Task statistics
- GET /api/v1/tasks/{task_id} - Task details
- POST /api/v1/tasks/trigger - Trigger a task
- POST /api/v1/tasks/cancel - Cancel a task
- GET /api/v1/tasks/scheduled - Scheduled jobs
- POST /api/v1/tasks/scheduled/{job_id}/pause - Pause job
- POST /api/v1/tasks/scheduled/{job_id}/resume - Resume job
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/admin", tags=["Admin"])


# ──────────────────────────────────────────────────────────────
# System Information
# ──────────────────────────────────────────────────────────────


@router.get(
    "/info",
    summary="Get system information",
    description="Get basic system and application information.",
)
async def get_system_info() -> dict:
    """Get system information.

    Returns basic information about the running application
    and system status.
    """
    from example_service.core.settings import get_app_settings

    settings = get_app_settings()

    return {
        "service_name": settings.service_name,
        "version": settings.version,
        "environment": settings.environment,
        "api_prefix": settings.api_prefix,
    }
