"""Trigger-based Faststream examples.

These examples demonstrate event-driven message processing where handlers
are triggered by incoming messages from queues. This is useful for:
- Processing user actions (user created, updated, deleted)
- Handling domain events
- Implementing event-driven architectures
- Decoupling services through async messaging
"""

from __future__ import annotations

import logging
from typing import Any

from faststream.rabbit import RabbitQueue
from pydantic import BaseModel, Field

from example_service.core.settings import get_rabbit_settings
from example_service.infra.messaging.broker import broker

logger = logging.getLogger(__name__)

# Get RabbitMQ settings
rabbit_settings = get_rabbit_settings()


# Event schemas
class UserCreatedEvent(BaseModel):
    """Event published when a user is created."""

    user_id: int = Field(description="User ID")
    email: str = Field(description="User email")
    username: str = Field(description="Username")
    full_name: str | None = Field(default=None, description="User's full name")


class UserNotificationEvent(BaseModel):
    """Event for sending user notifications."""

    user_id: int = Field(description="User ID")
    notification_type: str = Field(description="Type of notification (email, sms, push)")
    message: str = Field(description="Notification message")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


# Define queues
USER_EVENTS_QUEUE = rabbit_settings.get_prefixed_queue("user-events")
USER_NOTIFICATIONS_QUEUE = rabbit_settings.get_prefixed_queue("user-notifications")


# Publisher functions
async def publish_user_created_event(
    user_id: int,
    email: str,
    username: str,
    full_name: str | None = None,
) -> None:
    """Publish a user created event to the broker.

    This function demonstrates how to publish messages to RabbitMQ using Faststream.

    IMPORTANT: This function assumes the broker is already connected.
    Use this from FastAPI endpoints where the broker lifecycle is managed
    by the application lifespan.

    For Taskiq workers, use broker_context() instead:
            from example_service.infra.messaging.broker import broker_context

        @taskiq_broker.task()
        async def my_task():
            async with broker_context() as broker:
                if broker is not None:
                    event = UserCreatedEvent(user_id=1, email="...", username="...")
                    await broker.publish(event, queue=USER_EVENTS_QUEUE)

    Args:
        user_id: ID of the created user
        email: User email
        username: Username
        full_name: Optional full name

    Example (FastAPI endpoint):
            # In your FastAPI endpoint or service layer
        from example_service.infra.messaging.examples.trigger import publish_user_created_event

        @router.post("/users")
        async def create_user(user_data: UserCreate):
            # Create user in database
            user = await user_service.create(user_data)

            # Publish event
            await publish_user_created_event(
                user_id=user.id,
                email=user.email,
                username=user.username,
                full_name=user.full_name,
            )

            return user

    Raises:
        IncorrectState: If broker is not connected (e.g., called from Taskiq worker)
    """
    if not rabbit_settings.is_configured or broker is None:
        logger.warning("RabbitMQ not configured, skipping event publishing")
        return

    event = UserCreatedEvent(
        user_id=user_id,
        email=email,
        username=username,
        full_name=full_name,
    )

    try:
        await broker.publish(
            message=event,
            queue=USER_EVENTS_QUEUE,
        )
        logger.info(
            "Published user created event",
            extra={"user_id": user_id, "username": username},
        )
    except Exception as e:
        logger.exception(
            "Failed to publish user created event",
            extra={"user_id": user_id, "error": str(e)},
        )
        # Don't raise - publishing failure shouldn't break the main flow
        # Consider implementing a retry mechanism or dead letter queue


async def publish_user_notification(
    user_id: int,
    notification_type: str,
    message: str,
    **metadata: Any,
) -> None:
    """Publish a user notification event.

    IMPORTANT: This function assumes the broker is already connected.
    Use this from FastAPI endpoints where the broker lifecycle is managed
    by the application lifespan.

    For Taskiq workers, use broker_context() instead:
            from example_service.infra.messaging.broker import broker_context

        @taskiq_broker.task()
        async def send_notification_task():
            async with broker_context() as broker:
                if broker is not None:
                    event = UserNotificationEvent(
                        user_id=123,
                        notification_type="email",
                        message="Hello!",
                        metadata={},
                    )
                    await broker.publish(event, queue=USER_NOTIFICATIONS_QUEUE)

    Args:
        user_id: ID of the user to notify
        notification_type: Type of notification (email, sms, push)
        message: Notification message
        **metadata: Additional metadata

    Example (FastAPI endpoint):
            # Send a welcome email after user creation
        await publish_user_notification(
            user_id=user.id,
            notification_type="email",
            message="Welcome to our platform!",
            template="welcome",
            priority="high",
        )

    Raises:
        IncorrectState: If broker is not connected (e.g., called from Taskiq worker)
    """
    if not rabbit_settings.is_configured or broker is None:
        logger.warning("RabbitMQ not configured, skipping notification")
        return

    event = UserNotificationEvent(
        user_id=user_id,
        notification_type=notification_type,
        message=message,
        metadata=metadata,
    )

    try:
        await broker.publish(
            message=event,
            queue=USER_NOTIFICATIONS_QUEUE,
        )
        logger.info(
            "Published user notification",
            extra={
                "user_id": user_id,
                "notification_type": notification_type,
            },
        )
    except Exception as e:
        logger.exception(
            "Failed to publish notification",
            extra={"user_id": user_id, "error": str(e)},
        )


# Subscriber handlers (decorators register them with the broker)
if rabbit_settings.is_configured and broker is not None:

    @broker.subscriber(
        RabbitQueue(
            USER_EVENTS_QUEUE,
            durable=True,  # Survive broker restarts
            auto_delete=False,  # Don't delete when no consumers
        )
    )
    async def user_created_handler(event: UserCreatedEvent) -> None:
        """Handle user created events.

        This handler is automatically triggered when a UserCreatedEvent is published
        to the user-events queue. It demonstrates how to process events asynchronously.

        The handler can:
        - Store data in database
        - Update cache
        - Call external services
        - Publish other events (event chaining)

        Args:
            event: The user created event

        Example:
            This handler is automatically registered with the broker and will be
            called whenever a message arrives in the USER_EVENTS_QUEUE.

            If the handler completes successfully, the message is acknowledged.
            If an exception is raised, the message is nack'd and may be requeued.
        """
        logger.info(
            "Processing user created event",
            extra={
                "user_id": event.user_id,
                "email": event.email,
                "username": event.username,
            },
        )

        try:
            # Example: Send welcome notification
            await publish_user_notification(
                user_id=event.user_id,
                notification_type="email",
                message=f"Welcome {event.full_name or event.username}!",
                template="welcome_email",
                recipient=event.email,
            )

            # Example: Update analytics
            logger.info(
                "User created event processed successfully",
                extra={"user_id": event.user_id},
            )

            # Example: Additional processing
            # - Update search index
            # - Sync to external CRM
            # - Trigger onboarding workflow

        except Exception as e:
            logger.exception(
                "Failed to process user created event",
                extra={"user_id": event.user_id, "error": str(e)},
            )
            # Re-raise to trigger message requeue
            raise

    @broker.subscriber(
        RabbitQueue(
            USER_NOTIFICATIONS_QUEUE,
            durable=True,
            auto_delete=False,
        )
    )
    async def user_notification_handler(event: UserNotificationEvent) -> None:
        """Handle user notification events.

        This handler processes notification requests and sends them through
        the appropriate channel (email, SMS, push notification, etc.).

        Args:
            event: The notification event

        Example:
            This handler demonstrates how to:
            1. Route to different notification providers based on type
            2. Handle errors gracefully
            3. Log notification delivery status
        """
        logger.info(
            "Processing user notification",
            extra={
                "user_id": event.user_id,
                "notification_type": event.notification_type,
            },
        )

        try:
            # Route to appropriate notification service
            if event.notification_type == "email":
                logger.info(
                    "Sending email notification",
                    extra={
                        "user_id": event.user_id,
                        "template": event.metadata.get("template"),
                    },
                )
                # TODO: Integrate with email service (SendGrid, SES, etc.)
                # await email_service.send(...)

            elif event.notification_type == "sms":
                logger.info(
                    "Sending SMS notification",
                    extra={"user_id": event.user_id},
                )
                # TODO: Integrate with SMS service (Twilio, etc.)
                # await sms_service.send(...)

            elif event.notification_type == "push":
                logger.info(
                    "Sending push notification",
                    extra={"user_id": event.user_id},
                )
                # TODO: Integrate with push service (FCM, APNS, etc.)
                # await push_service.send(...)

            else:
                logger.warning(
                    "Unknown notification type",
                    extra={
                        "user_id": event.user_id,
                        "notification_type": event.notification_type,
                    },
                )

            logger.info(
                "Notification processed successfully",
                extra={
                    "user_id": event.user_id,
                    "notification_type": event.notification_type,
                },
            )

        except Exception as e:
            logger.exception(
                "Failed to process notification",
                extra={
                    "user_id": event.user_id,
                    "notification_type": event.notification_type,
                    "error": str(e),
                },
            )
            # Re-raise to trigger message requeue
            raise
