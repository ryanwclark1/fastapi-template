"""Taskiq + FastAPI integration examples.

This module demonstrates how to integrate Taskiq background tasks
with FastAPI endpoints, following the patterns from:
https://taskiq-python.github.io/framework_integrations/taskiq-with-fastapi.html

Key patterns:
1. Kick tasks from API endpoints
2. Check task status
3. Retrieve task results
4. Cancel running tasks
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from example_service.infra.tasks.broker import broker

logger = logging.getLogger(__name__)

# Create router for task examples
router = APIRouter(prefix="/tasks", tags=["tasks"])


# Request/Response models
class TaskKickRequest(BaseModel):
    """Request to kick a background task."""

    data: dict[str, Any] = Field(description="Task input data")


class TaskKickResponse(BaseModel):
    """Response after kicking a task."""

    task_id: str = Field(description="Unique task ID")
    status: str = Field(description="Task status")
    message: str = Field(description="Success message")


class TaskStatusResponse(BaseModel):
    """Response for task status check."""

    task_id: str = Field(description="Task ID")
    status: str = Field(description="Task status (pending, running, complete, failed)")
    result: Any | None = Field(default=None, description="Task result if complete")
    error: str | None = Field(default=None, description="Error message if failed")


# Example background tasks (should be imported from tasks.py)
if broker is not None:

    @broker.task()
    async def process_data_task(data: dict[str, Any]) -> dict[str, Any]:
        """Process data in the background.

        Args:
            data: Input data to process

        Returns:
            Processed result
        """
        logger.info(f"Processing data: {data}")

        try:
            # Simulate processing
            result = {
                "status": "processed",
                "input_data": data,
                "output": f"Processed: {data.get('value', 'unknown')}",
            }

            logger.info("Data processed successfully")
            return result

        except Exception as e:
            logger.exception(f"Failed to process data: {e}")
            raise

    @broker.task(retry_on_error=True, max_retries=3)
    async def send_notification_task(
        user_id: int,
        message: str,
        notification_type: str = "email",
    ) -> dict[str, Any]:
        """Send notification in the background.

        Args:
            user_id: User ID to notify
            message: Notification message
            notification_type: Type of notification

        Returns:
            Notification status
        """
        logger.info(f"Sending {notification_type} notification to user {user_id}")

        try:
            # TODO: Implement actual notification sending
            # This would integrate with email service, SMS, push notifications, etc.

            result = {
                "status": "sent",
                "user_id": user_id,
                "notification_type": notification_type,
                "message": message,
            }

            logger.info(f"Notification sent to user {user_id}")
            return result

        except Exception as e:
            logger.exception(f"Failed to send notification: {e}")
            raise

    # API Endpoints demonstrating Taskiq + FastAPI integration

    @router.post(
        "/process",
        response_model=TaskKickResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def process_data_endpoint(request: TaskKickRequest) -> TaskKickResponse:
        """Kick a background task to process data.

        This endpoint demonstrates how to:
        1. Accept data from the client
        2. Kick a background task
        3. Return task ID immediately
        4. Client can poll for results using the task ID

        Example:
            ```bash
            curl -X POST http://localhost:8000/api/tasks/process \\
                -H "Content-Type: application/json" \\
                -d '{"data": {"value": "test", "count": 42}}'
            ```

        Args:
            request: Task input data

        Returns:
            Task ID and status
        """
        logger.info(f"Kicking process_data_task with data: {request.data}")

        try:
            # Kick the task (non-blocking)
            task = await process_data_task.kiq(**request.data)

            return TaskKickResponse(
                task_id=task.task_id,
                status="accepted",
                message="Task has been queued for processing",
            )

        except Exception as e:
            logger.exception("Failed to kick task")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to queue task: {str(e)}",
            )

    @router.post(
        "/notify/{user_id}",
        response_model=TaskKickResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def send_notification_endpoint(
        user_id: int,
        message: str,
        notification_type: str = "email",
    ) -> TaskKickResponse:
        """Send notification to user asynchronously.

        This demonstrates kicking a task with retry logic.
        If the task fails, it will automatically retry up to 3 times.

        Example:
            ```bash
            curl -X POST "http://localhost:8000/api/tasks/notify/123?message=Hello&notification_type=email"
            ```

        Args:
            user_id: User ID to notify
            message: Notification message
            notification_type: Type of notification (email, sms, push)

        Returns:
            Task ID and status
        """
        logger.info(f"Kicking notification task for user {user_id}")

        try:
            task = await send_notification_task.kiq(
                user_id=user_id,
                message=message,
                notification_type=notification_type,
            )

            return TaskKickResponse(
                task_id=task.task_id,
                status="accepted",
                message=f"Notification task queued for user {user_id}",
            )

        except Exception as e:
            logger.exception("Failed to kick notification task")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to queue notification: {str(e)}",
            )

    @router.get(
        "/status/{task_id}",
        response_model=TaskStatusResponse,
    )
    async def get_task_status(task_id: str) -> TaskStatusResponse:
        """Get the status of a background task.

        This endpoint allows clients to poll for task completion
        and retrieve results once the task is done.

        Example:
            ```bash
            # First kick a task
            TASK_ID=$(curl -X POST http://localhost:8000/api/tasks/process \\
                -H "Content-Type: application/json" \\
                -d '{"data": {"value": "test"}}' | jq -r '.task_id')

            # Then check status
            curl http://localhost:8000/api/tasks/status/$TASK_ID
            ```

        Args:
            task_id: Task ID to check

        Returns:
            Task status and result if complete
        """
        logger.info(f"Checking status for task {task_id}")

        try:
            # Get task result from broker
            # Note: This requires the task to be completed
            # For pending tasks, you may need to track them separately
            # or use a different mechanism

            # TODO: Implement proper task status tracking
            # For now, we'll return a placeholder response

            return TaskStatusResponse(
                task_id=task_id,
                status="pending",
                result=None,
                error=None,
            )

        except Exception as e:
            logger.exception(f"Failed to get task status: {e}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task not found: {task_id}",
            )

    @router.delete(
        "/cancel/{task_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def cancel_task(task_id: str) -> None:
        """Cancel a running background task.

        Note: Task cancellation support depends on the broker implementation.
        Not all tasks can be cancelled once started.

        Example:
            ```bash
            curl -X DELETE http://localhost:8000/api/tasks/cancel/$TASK_ID
            ```

        Args:
            task_id: Task ID to cancel
        """
        logger.info(f"Attempting to cancel task {task_id}")

        try:
            # TODO: Implement task cancellation
            # This may require tracking task instances and
            # using asyncio.Task.cancel() or similar mechanism

            logger.info(f"Task {task_id} cancelled")

        except Exception as e:
            logger.exception(f"Failed to cancel task: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to cancel task: {str(e)}",
            )


# To use this router in your FastAPI app:
# from example_service.infra.tasks.examples.fastapi_integration import router as tasks_router
# app.include_router(tasks_router, prefix="/api")
