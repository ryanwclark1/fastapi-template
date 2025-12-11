"""Domain events for the notifications feature.

These events are published when significant changes occur to notifications.
They enable:
- Event-driven communication between features
- Real-time notification delivery tracking
- Integration with external systems via webhooks
- Audit logging and analytics

Events are published by NotificationService and can be consumed by
other services for notifications, webhooks, metrics, etc.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import Field

from example_service.core.events import DomainEvent, event_registry

if TYPE_CHECKING:
    from datetime import datetime


@event_registry.register
class NotificationCreatedEvent(DomainEvent):
    """Published when a notification is created.

    This event is fired immediately after a notification record is
    persisted to the database, before it is dispatched to channels.

    Example:
        event = NotificationCreatedEvent(
            notification_id="...",
            user_id="user-123",
            notification_type="reminder_due",
            title="Review PR",
            priority="high",
        )
        await publisher.publish(event)
    """

    event_type: ClassVar[str] = "notification.created"
    event_version: ClassVar[int] = 1

    notification_id: str = Field(description="UUID of the created notification")
    user_id: str = Field(description="User who will receive the notification")
    tenant_id: str | None = Field(default=None, description="Optional tenant ID")
    notification_type: str = Field(description="Type/category of notification")
    title: str = Field(description="Notification title")
    body: str | None = Field(default=None, description="Notification body text")
    priority: str = Field(default="normal", description="Priority level")
    scheduled_for: datetime | None = Field(
        default=None,
        description="When notification should be sent (None = immediate)",
    )
    source_entity_type: str | None = Field(
        default=None,
        description="Type of entity that triggered this notification",
    )
    source_entity_id: str | None = Field(
        default=None,
        description="ID of entity that triggered this notification",
    )


@event_registry.register
class NotificationDispatchedEvent(DomainEvent):
    """Published when a notification has been dispatched to delivery channels.

    This event is fired after the notification service has attempted to
    send the notification through all enabled channels (email, webhook,
    websocket, in-app).

    Example:
        event = NotificationDispatchedEvent(
            notification_id="...",
            user_id="user-123",
            channels=["email", "websocket"],
            delivery_count=2,
        )
        await publisher.publish(event)
    """

    event_type: ClassVar[str] = "notification.dispatched"
    event_version: ClassVar[int] = 1

    notification_id: str = Field(description="UUID of the notification")
    user_id: str = Field(description="User who received the notification")
    tenant_id: str | None = Field(default=None, description="Optional tenant ID")
    notification_type: str = Field(description="Type/category of notification")
    channels: list[str] = Field(
        default_factory=list,
        description="Channels the notification was dispatched to",
    )
    delivery_count: int = Field(
        default=0,
        description="Number of delivery attempts created",
    )
    dispatched_at: datetime | None = Field(
        default=None,
        description="When the notification was dispatched",
    )


@event_registry.register
class NotificationDeliveredEvent(DomainEvent):
    """Published when a notification is successfully delivered via a channel.

    This event is fired for each successful delivery attempt through
    a specific channel (email sent, webhook delivered, etc.).

    Example:
        event = NotificationDeliveredEvent(
            notification_id="...",
            delivery_id="...",
            user_id="user-123",
            channel="email",
            delivered_at=datetime.now(UTC),
        )
        await publisher.publish(event)
    """

    event_type: ClassVar[str] = "notification.delivered"
    event_version: ClassVar[int] = 1

    notification_id: str = Field(description="UUID of the notification")
    delivery_id: str = Field(description="UUID of the delivery record")
    user_id: str = Field(description="User who received the notification")
    tenant_id: str | None = Field(default=None, description="Optional tenant ID")
    notification_type: str = Field(description="Type/category of notification")
    channel: str = Field(description="Delivery channel (email, webhook, etc.)")
    delivered_at: datetime | None = Field(
        default=None,
        description="When the delivery succeeded",
    )
    response_data: dict[str, Any] | None = Field(
        default=None,
        description="Channel-specific response data",
    )


@event_registry.register
class NotificationFailedEvent(DomainEvent):
    """Published when all delivery attempts for a notification have failed.

    This event is fired when a notification cannot be delivered through
    any of the enabled channels after all retry attempts have been exhausted.

    Example:
        event = NotificationFailedEvent(
            notification_id="...",
            user_id="user-123",
            notification_type="reminder_due",
            channels_attempted=["email", "webhook"],
            error_summary="SMTP connection timeout, Webhook 503 error",
        )
        await publisher.publish(event)
    """

    event_type: ClassVar[str] = "notification.failed"
    event_version: ClassVar[int] = 1

    notification_id: str = Field(description="UUID of the notification")
    user_id: str = Field(description="User who should have received the notification")
    tenant_id: str | None = Field(default=None, description="Optional tenant ID")
    notification_type: str = Field(description="Type/category of notification")
    channels_attempted: list[str] = Field(
        default_factory=list,
        description="Channels that were attempted",
    )
    error_summary: str | None = Field(
        default=None,
        description="Summary of errors encountered",
    )
    failed_at: datetime | None = Field(
        default=None,
        description="When the final failure was recorded",
    )


@event_registry.register
class NotificationReadEvent(DomainEvent):
    """Published when a user marks a notification as read.

    This event is useful for analytics, user engagement tracking,
    and updating notification badges in real-time.

    Example:
        event = NotificationReadEvent(
            notification_id="...",
            user_id="user-123",
            notification_type="reminder_due",
            read_at=datetime.now(UTC),
        )
        await publisher.publish(event)
    """

    event_type: ClassVar[str] = "notification.read"
    event_version: ClassVar[int] = 1

    notification_id: str = Field(description="UUID of the notification")
    user_id: str = Field(description="User who read the notification")
    tenant_id: str | None = Field(default=None, description="Optional tenant ID")
    notification_type: str = Field(description="Type/category of notification")
    read_at: datetime | None = Field(
        default=None,
        description="When the notification was marked as read",
    )


@event_registry.register
class NotificationChannelDeliveryFailedEvent(DomainEvent):
    """Published when a delivery attempt to a specific channel fails.

    This is more granular than NotificationFailedEvent - it tracks
    individual channel failures, which may be retried.

    Example:
        event = NotificationChannelDeliveryFailedEvent(
            notification_id="...",
            delivery_id="...",
            user_id="user-123",
            channel="email",
            error_message="SMTP timeout",
            retry_count=2,
        )
        await publisher.publish(event)
    """

    event_type: ClassVar[str] = "notification.channel_delivery_failed"
    event_version: ClassVar[int] = 1

    notification_id: str = Field(description="UUID of the notification")
    delivery_id: str = Field(description="UUID of the delivery record")
    user_id: str = Field(description="User who should receive the notification")
    tenant_id: str | None = Field(default=None, description="Optional tenant ID")
    notification_type: str = Field(description="Type/category of notification")
    channel: str = Field(description="Delivery channel that failed")
    error_message: str | None = Field(
        default=None,
        description="Error message from the channel",
    )
    retry_count: int = Field(
        default=0,
        description="Number of retry attempts so far",
    )
    will_retry: bool = Field(
        default=False,
        description="Whether the delivery will be retried",
    )


__all__ = [
    "NotificationChannelDeliveryFailedEvent",
    "NotificationCreatedEvent",
    "NotificationDeliveredEvent",
    "NotificationDispatchedEvent",
    "NotificationFailedEvent",
    "NotificationReadEvent",
]
