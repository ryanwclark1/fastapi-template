"""Admin feature for task management and system operations."""
from __future__ import annotations

from .router import router
from .schemas import (
    RunningTaskResponse,
    TaskExecutionResponse,
    TaskStatsResponse,
)
from .service import (
    AdminService,
    AdminServiceError,
    BrokerNotConfiguredError,
    JobNotFoundError,
    TaskName,
    TaskNotFoundError,
    TrackerNotAvailableError,
    get_admin_service,
)

__all__ = [
    # Router
    "router",
    # Service
    "AdminService",
    "AdminServiceError",
    "BrokerNotConfiguredError",
    "JobNotFoundError",
    "TaskName",
    "TaskNotFoundError",
    "TrackerNotAvailableError",
    "get_admin_service",
    # Schemas
    "RunningTaskResponse",
    "TaskExecutionResponse",
    "TaskStatsResponse",
]
