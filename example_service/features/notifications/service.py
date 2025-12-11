"""Core notification service for creating and dispatching notifications."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from example_service.core.events import EventPublisher
from example_service.core.services.base import BaseService
from example_service.features.notifications.channels.dispatcher import (
    get_notification_dispatcher,
)
from example_service.features.notifications.metrics import (
    notification_created_total,
    notification_dispatched_total,
    notification_read_total,
)
from example_service.features.notifications.models import Notification
from example_service.features.notifications.repository import (
    NotificationDeliveryRepository,
    NotificationRepository,
    UserNotificationPreferenceRepository,
    get_notification_delivery_repository,
    get_notification_repository,
    get_user_notification_preference_repository,
)
from example_service.features.notifications.templates.service import (
    get_notification_template_service,
)
from example_service.infra.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from example_service.features.notifications.models import NotificationDelivery


class NotificationService(BaseService):
    """Service for creating and managing notifications.

    Provides:
    - Notification creation with template rendering
    - Multi-channel dispatch via NotificationDispatcher
    - Scheduled notification support
    - Notification status tracking
    - Event publishing for notification lifecycle
    """

    def __init__(
        self,
        repository: NotificationRepository | None = None,
        delivery_repository: NotificationDeliveryRepository | None = None,
        preference_repository: UserNotificationPreferenceRepository | None = None,
    ) -> None:
        """Initialize with repositories and services.

        Args:
            repository: Optional notification repository
            delivery_repository: Optional delivery repository
            preference_repository: Optional preference repository
        """
        super().__init__()
        self._repository: NotificationRepository = repository or get_notification_repository()
        self._delivery_repository = delivery_repository or get_notification_delivery_repository()
        self._preference_repository = preference_repository or get_user_notification_preference_repository()
        self._template_service = get_notification_template_service()
        self._dispatcher = get_notification_dispatcher()
        self._logger = get_logger()

    async def create_notification(
        self,
        session: AsyncSession,
        user_id: str,
        notification_type: str,
        title: str,
        body: str | None = None,
        body_html: str | None = None,
        *,
        tenant_id: str | None = None,
        template_name: str | None = None,
        context: dict[str, Any] | None = None,
        priority: str = "normal",
        scheduled_for: datetime | None = None,
        source_entity_type: str | None = None,
        source_entity_id: str | None = None,
        actions: list[dict[str, Any]] | None = None,
        progress: int | None = None,
        group_key: str | None = None,
        auto_dismiss: bool = False,
        dismiss_after: int | None = None,
        expires_at: datetime | None = None,
    ) -> Notification:
        """Create a new notification.

        If template_name is provided, renders the template with context.
        Otherwise, uses provided title/body directly.

        Args:
            session: Database session
            user_id: User identifier
            notification_type: Type/category of notification
            title: Notification title (or template will render this)
            body: Plain text body (optional)
            body_html: HTML body (optional)
            tenant_id: Optional tenant ID
            template_name: Optional template name for rendering
            context: Template context variables
            priority: Priority level (low, normal, high, urgent)
            scheduled_for: When to send (None = immediate)
            source_entity_type: Type of entity that triggered this
            source_entity_id: ID of entity that triggered this
            actions: Action buttons for UI
            progress: Progress percentage (0-100)
            group_key: Key for grouping related notifications
            auto_dismiss: Whether to auto-dismiss
            dismiss_after: Auto-dismiss timeout in milliseconds
            expires_at: When notification expires

        Returns:
            Created notification

        Raises:
            ValueError: If template not found or rendering fails
        """
        # If template provided, render it
        if template_name:
            rendered = await self._template_service.render_template_by_name(
                session,
                template_name,
                "email",  # Use email template for title/body
                context or {},
                tenant_id,
            )

            # Use rendered content
            title = rendered.get("subject", title)
            body = rendered.get("body", body)
            body_html = rendered.get("body_html", body_html)

        # Create notification record
        notification = Notification(
            user_id=user_id,
            tenant_id=tenant_id,
            notification_type=notification_type,
            template_name=template_name,
            title=title,
            body=body,
            body_html=body_html,
            context_data=context,
            priority=priority,
            scheduled_for=scheduled_for,
            source_entity_type=source_entity_type,
            source_entity_id=source_entity_id,
            actions=actions,
            progress=progress,
            group_key=group_key,
            auto_dismiss=auto_dismiss,
            dismiss_after=dismiss_after,
            expires_at=expires_at,
            status="pending",
            read=False,
        )

        session.add(notification)
        await session.flush()

        # Track metrics
        notification_created_total.labels(
            notification_type=notification_type,
            priority=priority,
        ).inc()

        self._logger.info(
            f"Created notification {notification.id} for user {user_id} (type={notification_type}, scheduled={scheduled_for})",
        )

        # Publish NotificationCreatedEvent
        await self._publish_notification_created_event(session, notification)

        # If immediate delivery, queue dispatch task (non-blocking)
        if scheduled_for is None:
            # Queue background task for dispatch
            try:
                from example_service.workers.notifications.tasks import (
                    dispatch_notification_task,
                )

                # Queue the task (fire and forget)
                await dispatch_notification_task.kiq(notification_id=str(notification.id))

                self._logger.debug(
                    lambda: f"Queued dispatch task for notification {notification.id}",
                )
            except Exception as exc:
                # If queueing fails, fall back to synchronous dispatch
                self._logger.warning(
                    f"Failed to queue dispatch task, falling back to sync dispatch: {exc}",
                )
                await self.dispatch_notification(session, notification)

        return notification

    async def dispatch_notification(
        self,
        session: AsyncSession,
        notification: Notification,
    ) -> Sequence[NotificationDelivery]:
        """Dispatch notification to all enabled channels.

        Args:
            session: Database session
            notification: Notification to dispatch

        Returns:
            Sequence of delivery records created
        """
        # Get user preferences
        preferences = await self._preference_repository.get_for_user_and_type(
            session,
            notification.user_id,
            notification.notification_type,
            notification.tenant_id,
        )

        # Dispatch via channels
        deliveries = await self._dispatcher.dispatch(notification, preferences)

        # Add deliveries to session
        for delivery in deliveries:
            session.add(delivery)

        # Update notification status
        notification.status = "dispatched"
        notification.dispatched_at = datetime.now(UTC)

        await session.flush()

        # Track metrics
        notification_dispatched_total.labels(
            notification_type=notification.notification_type,
        ).inc()

        self._logger.info(
            f"Dispatched notification {notification.id} to {len(deliveries)} channels",
        )

        # Publish NotificationDispatchedEvent
        await self._publish_notification_dispatched_event(session, notification, deliveries)

        # Publish delivery events (success/failure)
        await self._publish_delivery_events(session, notification, deliveries)

        return deliveries

    async def mark_as_read(
        self,
        session: AsyncSession,
        notification_id: UUID,
        user_id: str,
    ) -> Notification | None:
        """Mark notification as read (for in-app notifications).

        Args:
            session: Database session
            notification_id: Notification UUID
            user_id: User ID (for authorization check)

        Returns:
            Updated notification or None if not found/unauthorized
        """
        notification = await self._repository.get(session, notification_id)

        if not notification:
            return None

        # Verify ownership
        if notification.user_id != user_id:
            self._logger.warning(
                f"User {user_id} attempted to mark notification {notification_id} as read (belongs to {notification.user_id})",
            )
            return None

        # Mark as read
        notification.read = True
        notification.read_at = datetime.now(UTC)

        await session.flush()

        # Track metrics
        notification_read_total.labels(
            notification_type=notification.notification_type,
        ).inc()

        self._logger.debug(
            lambda: f"Marked notification {notification_id} as read for user {user_id}",
        )

        # Publish NotificationReadEvent
        await self._publish_notification_read_event(session, notification)

        return notification

    async def list_user_notifications(
        self,
        session: AsyncSession,
        user_id: str,
        *,
        tenant_id: str | None = None,
        notification_type: str | None = None,
        unread_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[Notification], int, int]:
        """List notifications for a user.

        Args:
            session: Database session
            user_id: User identifier
            tenant_id: Optional tenant filter
            notification_type: Optional type filter
            unread_only: Only return unread notifications
            limit: Max results
            offset: Pagination offset

        Returns:
            Tuple of (notifications, total_count, unread_count)
        """
        notifications, total = await self._repository.list_for_user(
            session,
            user_id,
            tenant_id=tenant_id,
            notification_type=notification_type,
            unread_only=unread_only,
            limit=limit,
            offset=offset,
        )

        # Get unread count
        unread_count = await self._repository.get_unread_count(session, user_id, tenant_id)

        return notifications, total, unread_count

    async def _publish_notification_created_event(
        self,
        session: AsyncSession,
        notification: Notification,
    ) -> None:
        """Publish NotificationCreatedEvent to the event bus.

        Args:
            session: Database session
            notification: Created notification
        """
        try:
            from example_service.features.notifications.events import (
                NotificationCreatedEvent,
            )

            publisher = EventPublisher(session)
            event = NotificationCreatedEvent(
                notification_id=str(notification.id),
                user_id=notification.user_id,
                tenant_id=notification.tenant_id,
                notification_type=notification.notification_type,
                title=notification.title,
                body=notification.body,
                priority=notification.priority,
                scheduled_for=notification.scheduled_for,
                source_entity_type=notification.source_entity_type,
                source_entity_id=notification.source_entity_id,
            )
            await publisher.publish(event)

            self._logger.debug(
                lambda: f"Published NotificationCreatedEvent for notification {notification.id}",
            )
        except Exception as e:
            # Don't fail the main operation if event publishing fails
            self._logger.warning(
                f"Failed to publish NotificationCreatedEvent: {e}",
                extra={"notification_id": str(notification.id)},
            )

    async def _publish_notification_dispatched_event(
        self,
        session: AsyncSession,
        notification: Notification,
        deliveries: Sequence[NotificationDelivery],
    ) -> None:
        """Publish NotificationDispatchedEvent to the event bus.

        Args:
            session: Database session
            notification: Dispatched notification
            deliveries: List of delivery records
        """
        try:
            from example_service.features.notifications.events import (
                NotificationDispatchedEvent,
            )

            publisher = EventPublisher(session)
            event = NotificationDispatchedEvent(
                notification_id=str(notification.id),
                user_id=notification.user_id,
                tenant_id=notification.tenant_id,
                notification_type=notification.notification_type,
                channels=[d.channel for d in deliveries],
                delivery_count=len(deliveries),
                dispatched_at=notification.dispatched_at,
            )
            await publisher.publish(event)

            self._logger.debug(
                lambda: f"Published NotificationDispatchedEvent for notification {notification.id}",
            )
        except Exception as e:
            self._logger.warning(
                f"Failed to publish NotificationDispatchedEvent: {e}",
                extra={"notification_id": str(notification.id)},
            )

    async def _publish_delivery_events(
        self,
        session: AsyncSession,
        notification: Notification,
        deliveries: Sequence[NotificationDelivery],
    ) -> None:
        """Publish delivery events (success/failure) for each channel.

        Args:
            session: Database session
            notification: Notification
            deliveries: List of delivery records
        """
        try:
            from example_service.features.notifications.events import (
                NotificationChannelDeliveryFailedEvent,
                NotificationDeliveredEvent,
            )

            publisher = EventPublisher(session)

            for delivery in deliveries:
                if delivery.status == "delivered":
                    # Publish success event
                    event = NotificationDeliveredEvent(
                        notification_id=str(notification.id),
                        delivery_id=str(delivery.id),
                        user_id=notification.user_id,
                        tenant_id=notification.tenant_id,
                        notification_type=notification.notification_type,
                        channel=delivery.channel,
                        delivered_at=delivery.delivered_at,
                        response_data=delivery.response_data,
                    )
                    await publisher.publish(event)

                elif delivery.status == "failed":
                    # Publish failure event
                    event = NotificationChannelDeliveryFailedEvent(
                        notification_id=str(notification.id),
                        delivery_id=str(delivery.id),
                        user_id=notification.user_id,
                        tenant_id=notification.tenant_id,
                        notification_type=notification.notification_type,
                        channel=delivery.channel,
                        error_message=delivery.error_message,
                        retry_count=delivery.retry_count,
                        will_retry=delivery.status == "pending",
                    )
                    await publisher.publish(event)

            self._logger.debug(
                lambda: f"Published delivery events for notification {notification.id}",
            )
        except Exception as e:
            self._logger.warning(
                f"Failed to publish delivery events: {e}",
                extra={"notification_id": str(notification.id)},
            )

    async def _publish_notification_read_event(
        self,
        session: AsyncSession,
        notification: Notification,
    ) -> None:
        """Publish NotificationReadEvent to the event bus.

        Args:
            session: Database session
            notification: Notification that was marked as read
        """
        try:
            from example_service.features.notifications.events import (
                NotificationReadEvent,
            )

            publisher = EventPublisher(session)
            event = NotificationReadEvent(
                notification_id=str(notification.id),
                user_id=notification.user_id,
                tenant_id=notification.tenant_id,
                notification_type=notification.notification_type,
                read_at=notification.read_at,
            )
            await publisher.publish(event)

            self._logger.debug(
                lambda: f"Published NotificationReadEvent for notification {notification.id}",
            )
        except Exception as e:
            self._logger.warning(
                f"Failed to publish NotificationReadEvent: {e}",
                extra={"notification_id": str(notification.id)},
            )


# Singleton instance
_service: NotificationService | None = None


def get_notification_service() -> NotificationService:
    """Get or create the singleton NotificationService instance.

    Returns:
        NotificationService instance
    """
    global _service
    if _service is None:
        _service = NotificationService()
    return _service
