"""Taskiq + Faststream integration examples.

This module demonstrates how to integrate Taskiq with Faststream,
following the patterns from:
https://taskiq-python.github.io/framework_integrations/faststream.html

Key patterns:
1. Trigger Taskiq tasks from Faststream handlers
2. Process messages asynchronously
3. Fan-out patterns (one message triggers multiple tasks)
4. Event chaining (task completion triggers new events)
"""

from __future__ import annotations

import logging
from typing import Any

from faststream.rabbit import RabbitQueue
from pydantic import BaseModel, Field

from example_service.core.settings import get_rabbit_settings
from example_service.infra.messaging.broker import broker as faststream_broker
from example_service.infra.messaging.broker import router as faststream_router
from example_service.tasks.broker import broker as taskiq_broker

logger = logging.getLogger(__name__)

# Get settings
rabbit_settings = get_rabbit_settings()


# Event models
class DataProcessingEvent(BaseModel):
    """Event for triggering data processing."""

    event_id: str = Field(description="Event ID")
    data_source: str = Field(description="Data source identifier")
    batch_size: int = Field(default=100, description="Batch size for processing")
    priority: str = Field(default="normal", description="Processing priority")


class UserActionEvent(BaseModel):
    """Event for user actions that require background processing."""

    user_id: int = Field(description="User ID")
    action: str = Field(description="Action type")
    payload: dict[str, Any] = Field(default_factory=dict, description="Action payload")


# Define queues
DATA_PROCESSING_QUEUE = rabbit_settings.get_prefixed_queue("data-processing")
USER_ACTIONS_QUEUE = rabbit_settings.get_prefixed_queue("user-actions")


# Taskiq tasks that will be triggered by Faststream
if taskiq_broker is not None:

    @taskiq_broker.task()
    async def process_batch_task(
        data_source: str,
        batch_id: int,
        batch_size: int,
    ) -> dict[str, Any]:
        """Process a batch of data.

        This task is triggered by Faststream handlers to process
        data asynchronously in the background.

        Args:
            data_source: Source of the data
            batch_id: Batch identifier
            batch_size: Number of records in batch

        Returns:
            Processing result
        """
        logger.info(
            f"Processing batch {batch_id} from {data_source}",
            extra={"batch_id": batch_id, "batch_size": batch_size},
        )

        try:
            # TODO: Implement batch processing logic
            # - Fetch data from source
            # - Transform data
            # - Store in database
            # - Update processing status

            processed_count = batch_size  # Placeholder

            result = {
                "status": "success",
                "batch_id": batch_id,
                "processed_count": processed_count,
            }

            logger.info(f"Batch {batch_id} processed successfully")
            return result

        except Exception as e:
            logger.exception(f"Failed to process batch {batch_id}: {e}")
            raise

    @taskiq_broker.task(retry_on_error=True, max_retries=3)
    async def handle_user_action_task(
        user_id: int,
        action: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Handle user action with retry logic.

        Args:
            user_id: User ID
            action: Action type
            payload: Action payload

        Returns:
            Action result
        """
        payload_keys = sorted(payload.keys())
        logger.info(
            f"Handling action '{action}' for user {user_id}",
            extra={
                "user_id": user_id,
                "action": action,
                "payload_keys": payload_keys,
            },
        )

        try:
            # TODO: Implement action handling logic
            # Different actions might require different processing
            if action == "profile_update":
                # Update profile, sync to external services
                pass
            elif action == "subscription_change":
                # Update subscription, send notifications
                pass
            elif action == "data_export":
                # Generate export file, notify user
                pass

            result = {
                "status": "success",
                "user_id": user_id,
                "action": action,
            }

            logger.info(f"Action '{action}' handled successfully for user {user_id}")
            return result

        except Exception as e:
            logger.exception(f"Failed to handle action: {e}")
            raise

    @taskiq_broker.task()
    async def send_completion_notification_task(
        user_id: int,
        task_type: str,
        result: dict[str, Any],
    ) -> None:
        """Send notification about task completion.

        This demonstrates event chaining where task completion
        triggers another task.

        Args:
            user_id: User to notify
            task_type: Type of completed task
            result: Task result
        """
        logger.info(
            f"Sending completion notification to user {user_id}",
            extra={"task_type": task_type, "result_status": result.get("status")},
        )

        try:
            # TODO: Send notification (email, push, etc.)
            logger.info(f"Notification sent for {task_type} completion")

        except Exception:
            logger.exception("Failed to send notification")
            # Don't raise - notification failure shouldn't fail the whole flow


# Faststream handlers that trigger Taskiq tasks
# Use faststream_router for AsyncAPI documentation
if faststream_router is not None and rabbit_settings.is_configured:

    @faststream_router.subscriber(
        RabbitQueue(DATA_PROCESSING_QUEUE, durable=True, auto_delete=False)
    )
    async def handle_data_processing_event(event: DataProcessingEvent) -> None:
        """Handle data processing events by fanning out to Taskiq tasks.

        This demonstrates the fan-out pattern where a single message
        triggers multiple background tasks for parallel processing.

        Args:
            event: Data processing event
        """
        logger.info(
            f"Received data processing event: {event.event_id}",
            extra={
                "event_id": event.event_id,
                "data_source": event.data_source,
            },
        )

        try:
            # Fan out to multiple tasks for parallel processing
            # Each task processes a batch of data
            num_batches = 5  # Example: split into 5 batches

            task_ids = []
            for batch_id in range(num_batches):
                task = await process_batch_task.kiq(
                    data_source=event.data_source,
                    batch_id=batch_id,
                    batch_size=event.batch_size,
                )
                task_ids.append(task.task_id)

            logger.info(
                f"Kicked {num_batches} batch processing tasks",
                extra={"event_id": event.event_id, "task_ids": task_ids},
            )

        except Exception as e:
            logger.exception(f"Failed to handle data processing event: {e}")
            raise

    @faststream_broker.subscriber(RabbitQueue(USER_ACTIONS_QUEUE, durable=True, auto_delete=False))
    async def handle_user_action_event(event: UserActionEvent) -> None:
        """Handle user action events by triggering Taskiq tasks.

        This demonstrates:
        1. Event validation
        2. Task kicking with retry logic
        3. Event chaining (trigger notification after completion)

        Args:
            event: User action event
        """
        logger.info(
            f"Received user action: {event.action} for user {event.user_id}",
            extra={
                "user_id": event.user_id,
                "action": event.action,
            },
        )

        try:
            # Kick the action handling task
            task = await handle_user_action_task.kiq(
                user_id=event.user_id,
                action=event.action,
                payload=event.payload,
            )

            logger.info(
                f"Action task kicked: {task.task_id}",
                extra={"user_id": event.user_id, "task_id": task.task_id},
            )

            # Wait for task to complete (optional - depends on use case)
            # result = await task.wait_result(timeout=30)

            # Event chaining: Send notification about completion
            # This could also be done by the task itself
            # await send_completion_notification_task.kiq(
            #     user_id=event.user_id,
            #     task_type=event.action,
            #     result=result,
            # )

        except Exception as e:
            logger.exception(f"Failed to handle user action event: {e}")
            raise


# Example: Publishing events that trigger these handlers
async def publish_data_processing_event(
    data_source: str,
    batch_size: int = 100,
    priority: str = "normal",
) -> None:
    """Publish a data processing event.

    This event will be consumed by handle_data_processing_event,
    which will fan out to multiple Taskiq tasks.

    IMPORTANT: This function assumes the broker is already connected.
    Use this from FastAPI endpoints where the broker lifecycle is managed
    by the application lifespan.

    For Taskiq workers, use broker_context() instead:
            from example_service.infra.messaging.broker import broker_context

        @taskiq_broker.task()
        async def my_task():
            async with broker_context() as broker:
                if broker is not None:
                    await broker.publish(event, queue=DATA_PROCESSING_QUEUE)

    Example (FastAPI endpoint):
            # In your FastAPI endpoint
        @router.post("/process")
        async def trigger_processing():
            await publish_data_processing_event(
                data_source="external_api",
                batch_size=100,
                priority="high",
            )

    Args:
        data_source: Source of data to process
        batch_size: Batch size for processing
        priority: Processing priority

    Raises:
        IncorrectState: If broker is not connected (e.g., called from Taskiq worker)
    """
    if faststream_broker is None:
        logger.warning("Faststream broker not configured")
        return

    import uuid

    event = DataProcessingEvent(
        event_id=str(uuid.uuid4()),
        data_source=data_source,
        batch_size=batch_size,
        priority=priority,
    )

    await faststream_broker.publish(
        message=event,
        queue=DATA_PROCESSING_QUEUE,
    )

    logger.info(f"Published data processing event: {event.event_id}")


async def publish_user_action_event(
    user_id: int,
    action: str,
    **payload: Any,
) -> None:
    """Publish a user action event.

    This event will be consumed by handle_user_action_event,
    which will trigger a Taskiq task with retry logic.

    IMPORTANT: This function assumes the broker is already connected.
    Use this from FastAPI endpoints where the broker lifecycle is managed
    by the application lifespan.

    For Taskiq workers, use broker_context() instead:
            from example_service.infra.messaging.broker import broker_context

        @taskiq_broker.task()
        async def my_task():
            async with broker_context() as broker:
                if broker is not None:
                    event = UserActionEvent(user_id=123, action="test", payload={})
                    await broker.publish(event, queue=USER_ACTIONS_QUEUE)

    Example (FastAPI endpoint):
            # In your FastAPI endpoint
        @router.post("/users/{user_id}/actions")
        async def create_action(user_id: int):
            await publish_user_action_event(
                user_id=user_id,
                action="data_export",
                format="csv",
                include_history=True,
            )

    Args:
        user_id: User ID
        action: Action type
        **payload: Action payload

    Raises:
        IncorrectState: If broker is not connected (e.g., called from Taskiq worker)
    """
    if faststream_broker is None:
        logger.warning("Faststream broker not configured")
        return

    event = UserActionEvent(
        user_id=user_id,
        action=action,
        payload=payload,
    )

    await faststream_broker.publish(
        message=event,
        queue=USER_ACTIONS_QUEUE,
    )

    logger.info(f"Published user action event for user {user_id}: {action}")
