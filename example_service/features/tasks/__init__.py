"""Tasks feature module.

This module provides a comprehensive API for task management, including:
- Viewing task execution history
- Searching and filtering tasks
- Getting task statistics
- Viewing and managing scheduled jobs
- Triggering tasks on-demand
- Cancelling queued tasks
- Dead Letter Queue (DLQ) management
- Bulk operations (cancel/retry multiple tasks)
- Task progress tracking

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

    # Get DLQ entries
    dlq = await service.get_dlq_entries()

    # Get task progress
    progress = await service.get_task_progress("task-123")
"""

from example_service.features.tasks.router import router
from example_service.features.tasks.schemas import (
    BulkCancelRequest,
    BulkCancelResponse,
    BulkOperationResult,
    BulkRetryRequest,
    BulkRetryResponse,
    CancelTaskRequest,
    CancelTaskResponse,
    DLQDiscardRequest,
    DLQDiscardResponse,
    DLQEntryResponse,
    DLQListResponse,
    DLQRetryRequest,
    DLQRetryResponse,
    DLQStatus,
    RunningTaskResponse,
    ScheduledJobListResponse,
    ScheduledJobResponse,
    TaskExecutionDetailResponse,
    TaskExecutionResponse,
    TaskName,
    TaskProgressResponse,
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
    # Exceptions
    "BrokerNotConfiguredError",
    # Schemas - Bulk Operations
    "BulkCancelRequest",
    "BulkCancelResponse",
    "BulkOperationResult",
    "BulkRetryRequest",
    "BulkRetryResponse",
    # Schemas - Task Operations
    "CancelTaskRequest",
    "CancelTaskResponse",
    "DLQDiscardRequest",
    "DLQDiscardResponse",
    # Schemas - DLQ
    "DLQEntryResponse",
    "DLQListResponse",
    "DLQRetryRequest",
    "DLQRetryResponse",
    # Schemas - Enums
    "DLQStatus",
    "RunningTaskResponse",
    # Schemas - Scheduled Jobs
    "ScheduledJobListResponse",
    "ScheduledJobResponse",
    "TaskExecutionDetailResponse",
    # Schemas - Task Execution
    "TaskExecutionResponse",
    # Service
    "TaskManagementService",
    "TaskName",
    # Schemas - Progress
    "TaskProgressResponse",
    "TaskSearchParams",
    "TaskSearchResponse",
    "TaskServiceError",
    "TaskStatsResponse",
    "TaskStatus",
    "TrackerNotAvailableError",
    "TriggerTaskRequest",
    "TriggerTaskResponse",
    "get_task_service",
    # Router
    "router",
]
