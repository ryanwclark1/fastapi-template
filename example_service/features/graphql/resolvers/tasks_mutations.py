"""Mutation resolvers for the Tasks feature.

Provides:
- triggerTask: Manually trigger a background task
- cancelTask: Cancel a running task
- bulkCancelTasks: Cancel multiple tasks at once
- retryDLQTask: Retry a task from the Dead Letter Queue
- bulkRetryDLQTasks: Retry multiple DLQ tasks at once
- discardDLQTask: Discard a task from the DLQ
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import strawberry

from example_service.features.graphql.types.reminders import DeletePayload
from example_service.features.graphql.types.tasks import (
    BulkCancelInput,
    BulkCancelResult,
    BulkOperationItemResult,
    BulkRetryInput,
    BulkRetryResult,
    CancelTaskInput,
    CancelTaskResult,
    RetryDLQResult,
    TaskNameEnum,
    TaskOperationError,
    TaskStatusEnum,
    TriggerTaskInput,
    TriggerTaskPayload,
    TriggerTaskSuccess,
)

if TYPE_CHECKING:
    from strawberry.types import Info

    from example_service.features.graphql.context import GraphQLContext

logger = logging.getLogger(__name__)

# Map of task names to their Taskiq task functions
# This would be populated with actual task imports in production
TASK_REGISTRY: dict[TaskNameEnum, str] = {
    TaskNameEnum.BACKUP_DATABASE: "example_service.workers.backup.backup_database",
    TaskNameEnum.CHECK_DUE_REMINDERS: "example_service.workers.notifications.check_due_reminders",
    TaskNameEnum.WARM_CACHE: "example_service.workers.cache.warm_cache",
    TaskNameEnum.INVALIDATE_CACHE: "example_service.workers.cache.invalidate_cache",
    TaskNameEnum.EXPORT_CSV: "example_service.workers.export.export_csv",
    TaskNameEnum.EXPORT_JSON: "example_service.workers.export.export_json",
    TaskNameEnum.CLEANUP_TEMP_FILES: "example_service.workers.cleanup.cleanup_temp_files",
    TaskNameEnum.CLEANUP_OLD_BACKUPS: "example_service.workers.cleanup.cleanup_old_backups",
    TaskNameEnum.CLEANUP_OLD_EXPORTS: "example_service.workers.cleanup.cleanup_old_exports",
    TaskNameEnum.CLEANUP_EXPIRED_DATA: "example_service.workers.cleanup.cleanup_expired_data",
    TaskNameEnum.RUN_ALL_CLEANUP: "example_service.workers.cleanup.run_all_cleanup",
}


@strawberry.mutation(description="Trigger a background task manually")
async def trigger_task_mutation(
    info: Info[GraphQLContext, None],
    input: TriggerTaskInput,
) -> TriggerTaskPayload:
    """Trigger a predefined background task.

    Args:
        info: Strawberry info with context
        input: Task trigger parameters

    Returns:
        TriggerTaskSuccess with task ID, or TaskOperationError
    """
    task_path = TASK_REGISTRY.get(input.task)
    if not task_path:
        return TaskOperationError(
            code="INVALID_TASK",
            message=f"Unknown task: {input.task.value}",
        )

    try:
        # In production, this would import and trigger the actual Taskiq task.
        # Mock implementation
        import uuid
        task_id = str(uuid.uuid4())

        logger.info("Triggered task %s with ID %s", input.task.value, task_id)

        return TriggerTaskSuccess(
            task_id=task_id,
            task_name=input.task.value,
            status="queued",
            message=f"Task {input.task.value} has been queued",
        )

    except Exception as e:
        logger.exception("Error triggering task %s: %s", input.task.value, e)
        return TaskOperationError(
            code="TRIGGER_FAILED",
            message=f"Failed to trigger task: {e!s}",
        )


@strawberry.mutation(description="Cancel a running task")
async def cancel_task_mutation(
    info: Info[GraphQLContext, None],
    input: CancelTaskInput,
) -> CancelTaskResult:
    """Cancel a running or pending task.

    Args:
        info: Strawberry info with context
        input: Cancellation parameters

    Returns:
        CancelTaskResult with status
    """
    try:
        # In production, this would:
        # 1. Check if task exists and is cancellable
        # 2. Send cancellation signal to worker
        # 3. Update task status in result backend

        logger.info("Cancelling task %s: %s", input.task_id, input.reason)

        # Mock implementation
        return CancelTaskResult(
            task_id=input.task_id,
            cancelled=True,
            message="Task cancellation requested",
            previous_status=TaskStatusEnum.RUNNING,
        )

    except Exception as e:
        logger.exception("Error cancelling task %s: %s", input.task_id, e)
        return CancelTaskResult(
            task_id=input.task_id,
            cancelled=False,
            message=f"Failed to cancel task: {e!s}",
            previous_status=None,
        )


@strawberry.mutation(description="Cancel multiple tasks at once")
async def bulk_cancel_tasks_mutation(
    info: Info[GraphQLContext, None],
    input: BulkCancelInput,
) -> BulkCancelResult:
    """Cancel multiple tasks at once.

    Args:
        info: Strawberry info with context
        input: Bulk cancellation parameters

    Returns:
        BulkCancelResult with individual results
    """
    if len(input.task_ids) > 100:
        return BulkCancelResult(
            total_requested=len(input.task_ids),
            successful=0,
            failed=len(input.task_ids),
            results=[
                BulkOperationItemResult(
                    task_id="",
                    success=False,
                    message="Maximum 100 tasks can be cancelled at once",
                    previous_status=None,
                ),
            ],
        )

    results = []
    successful = 0
    failed = 0

    for task_id in input.task_ids:
        try:
            # In production, implement actual cancellation
            results.append(
                BulkOperationItemResult(
                    task_id=task_id,
                    success=True,
                    message="Task cancellation requested",
                    previous_status=TaskStatusEnum.RUNNING,
                ),
            )
            successful += 1
        except Exception as e:
            results.append(
                BulkOperationItemResult(
                    task_id=task_id,
                    success=False,
                    message=str(e),
                    previous_status=None,
                ),
            )
            failed += 1

    logger.info("Bulk cancelled %d/%d tasks", successful, len(input.task_ids))

    return BulkCancelResult(
        total_requested=len(input.task_ids),
        successful=successful,
        failed=failed,
        results=results,
    )


@strawberry.mutation(description="Retry a task from the Dead Letter Queue")
async def retry_dlq_task_mutation(
    info: Info[GraphQLContext, None],
    task_id: str,
) -> RetryDLQResult:
    """Retry a failed task from the DLQ.

    Args:
        info: Strawberry info with context
        task_id: Original task ID

    Returns:
        RetryDLQResult with new task ID
    """
    try:
        # In production, this would:
        # 1. Fetch the failed task from DLQ
        # 2. Re-queue with same arguments
        # 3. Mark DLQ entry as retried

        import uuid
        new_task_id = str(uuid.uuid4())

        logger.info("Retrying DLQ task %s as %s", task_id, new_task_id)

        return RetryDLQResult(
            original_task_id=task_id,
            new_task_id=new_task_id,
            task_name="unknown",  # Would be fetched from DLQ
            status="queued",
            message="Task has been re-queued",
        )

    except Exception as e:
        logger.exception("Error retrying DLQ task %s: %s", task_id, e)
        return RetryDLQResult(
            original_task_id=task_id,
            new_task_id="",
            task_name="unknown",
            status="failed",
            message=f"Failed to retry task: {e!s}",
        )


@strawberry.mutation(description="Retry multiple tasks from the DLQ")
async def bulk_retry_dlq_tasks_mutation(
    info: Info[GraphQLContext, None],
    input: BulkRetryInput,
) -> BulkRetryResult:
    """Retry multiple failed tasks from the DLQ.

    Args:
        info: Strawberry info with context
        input: Bulk retry parameters

    Returns:
        BulkRetryResult with individual results
    """
    if len(input.task_ids) > 100:
        return BulkRetryResult(
            total_requested=len(input.task_ids),
            successful=0,
            failed=len(input.task_ids),
            results=[
                BulkOperationItemResult(
                    task_id="",
                    success=False,
                    message="Maximum 100 tasks can be retried at once",
                    previous_status=None,
                ),
            ],
        )

    results = []
    successful = 0
    failed = 0

    for task_id in input.task_ids:
        try:
            # In production, implement actual retry
            results.append(
                BulkOperationItemResult(
                    task_id=task_id,
                    success=True,
                    message="Task has been re-queued",
                    previous_status=None,
                ),
            )
            successful += 1
        except Exception as e:
            results.append(
                BulkOperationItemResult(
                    task_id=task_id,
                    success=False,
                    message=str(e),
                    previous_status=None,
                ),
            )
            failed += 1

    logger.info("Bulk retried %d/%d DLQ tasks", successful, len(input.task_ids))

    return BulkRetryResult(
        total_requested=len(input.task_ids),
        successful=successful,
        failed=failed,
        results=results,
    )


@strawberry.mutation(description="Discard a task from the Dead Letter Queue")
async def discard_dlq_task_mutation(
    info: Info[GraphQLContext, None],
    task_id: str,
    reason: str | None = None,
) -> DeletePayload:
    """Permanently discard a task from the DLQ.

    Args:
        info: Strawberry info with context
        task_id: Task ID to discard
        reason: Optional reason for discarding

    Returns:
        DeletePayload indicating success or failure
    """
    try:
        # In production, this would mark the DLQ entry as discarded
        logger.info("Discarding DLQ task %s: %s", task_id, reason)

        return DeletePayload(
            success=True,
            message="Task has been discarded from the DLQ",
        )

    except Exception as e:
        logger.exception("Error discarding DLQ task %s: %s", task_id, e)
        return DeletePayload(
            success=False,
            message=f"Failed to discard task: {e!s}",
        )


__all__ = [
    "bulk_cancel_tasks_mutation",
    "bulk_retry_dlq_tasks_mutation",
    "cancel_task_mutation",
    "discard_dlq_task_mutation",
    "retry_dlq_task_mutation",
    "trigger_task_mutation",
]
