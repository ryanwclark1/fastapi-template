"""Tasks feature module.

This module provides a comprehensive API for task management, including:
- Viewing task execution history
- Searching and filtering tasks
- Getting task statistics
- Viewing and managing scheduled jobs
- Triggering tasks on-demand
- Cancelling queued tasks

Example usage:
    from example_service.features.tasks import (
        TaskManagementService,
        TaskName,
        get_task_service,
    )

    # Get the service
    service = get_task_service()

    # Trigger a task
    result = await service.trigger_task(TaskName.backup_database)

    # Search task history
    tasks, total = await service.search_tasks(TaskSearchParams(limit=50))
"""

from example_service.features.tasks.router import router
from example_service.features.tasks.schemas import (
    CancelTaskRequest,
    CancelTaskResponse,
    RunningTaskResponse,
    ScheduledJobListResponse,
    ScheduledJobResponse,
    TaskExecutionDetailResponse,
    TaskExecutionResponse,
    TaskName,
    TaskSearchParams,
    TaskSearchResponse,
    TaskStatsResponse,
    TaskStatus,
    TriggerTaskRequest,
    TriggerTaskResponse,
)
from example_service.features.tasks.service import (
    BrokerNotConfiguredError,
    TaskManagementService,
    TaskServiceError,
    TrackerNotAvailableError,
    get_task_service,
)

__all__ = [
    # Router
    "router",
    # Service
    "TaskManagementService",
    "get_task_service",
    # Exceptions
    "TaskServiceError",
    "BrokerNotConfiguredError",
    "TrackerNotAvailableError",
    # Schemas - Enums
    "TaskStatus",
    "TaskName",
    # Schemas - Requests
    "TaskSearchParams",
    "TriggerTaskRequest",
    "CancelTaskRequest",
    # Schemas - Responses
    "TaskExecutionResponse",
    "TaskExecutionDetailResponse",
    "RunningTaskResponse",
    "TaskSearchResponse",
    "TaskStatsResponse",
    "ScheduledJobResponse",
    "ScheduledJobListResponse",
    "TriggerTaskResponse",
    "CancelTaskResponse",
]
