"""WebSocket channel dispatcher using ConnectionManager."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from example_service.features.notifications.channels.base import DeliveryResult
from example_service.infra.logging import get_logger
from example_service.infra.realtime.manager import get_connection_manager

if TYPE_CHECKING:
    from example_service.features.notifications.models import (
        Notification,
        NotificationDelivery,
        UserNotificationPreference,
    )


class WebSocketChannelDispatcher:
    """Dispatcher for real-time WebSocket notifications via ConnectionManager.

    Sends notifications to connected WebSocket clients in real-time.
    No retry logic needed - if client isn't connected, they'll see it in-app later.
    """

    def __init__(self) -> None:
        """Initialize with connection manager."""
        self._manager = get_connection_manager()
        self._logger = get_logger()

    async def send(
        self,
        notification: Notification,
        delivery: NotificationDelivery,
    ) -> DeliveryResult:
        """Send notification via WebSocket to connected clients.

        Args:
            notification: Notification with rendered content
            delivery: Delivery record (will update websocket_channel, websocket_connection_count)

        Returns:
            DeliveryResult with WebSocket-specific metadata
        """
        start_time = time.time()

        try:
            # Build WebSocket message payload
            payload = self._build_payload(notification)

            # Determine channel/room
            # User-specific channel: user/{user_id}
            channel = f"user/{notification.user_id}"

            # Send to all connections for this user
            connection_count = await self._manager.send_to_user(
                notification.user_id,
                payload,
            )

            # Calculate response time
            elapsed_ms = int((time.time() - start_time) * 1000)

            # Update delivery record
            delivery.websocket_channel = channel
            delivery.websocket_connection_count = connection_count

            if connection_count > 0:
                self._logger.info(
                    f"WebSocket sent for notification {notification.id} to {connection_count} connections",
                )
                return DeliveryResult(
                    success=True,
                    response_time_ms=elapsed_ms,
                    metadata={
                        "channel": channel,
                        "connection_count": connection_count,
                    },
                )

            # No connections - not necessarily an error, just means user isn't online
            self._logger.debug(
                lambda: f"WebSocket delivery for notification {notification.id}: no active connections",
            )

            return DeliveryResult(
                success=True,  # Still success - user will see it in-app
                response_time_ms=elapsed_ms,
                metadata={
                    "channel": channel,
                    "connection_count": 0,
                },
            )

        except Exception as exc:
            elapsed_ms = int((time.time() - start_time) * 1000)
            self._logger.exception(
                f"Exception sending WebSocket for notification {notification.id}: {exc}",
            )

            return DeliveryResult(
                success=False,
                error_message=str(exc),
                error_category="exception",
                response_time_ms=elapsed_ms,
            )

    async def is_enabled_for_user(
        self,
        preferences: UserNotificationPreference | None,
    ) -> bool:
        """Check if WebSocket is enabled for user.

        Args:
            preferences: User preferences (None = use defaults)

        Returns:
            True if websocket channel is enabled
        """
        if preferences is None:
            # Default: websocket enabled
            return True

        return "websocket" in preferences.enabled_channels

    def get_channel_name(self) -> str:
        """Get channel identifier.

        Returns:
            Channel name: 'websocket'
        """
        return "websocket"

    def _build_payload(self, notification: Notification) -> dict[str, Any]:
        """Build WebSocket message payload from notification.

        Args:
            notification: Notification instance

        Returns:
            WebSocket message payload
        """
        # Build standardized WebSocket notification payload
        # This format should match what the frontend expects
        payload = {
            "type": "notification",
            "event": f"notification.{notification.notification_type}",
            "data": {
                "id": str(notification.id),
                "notification_type": notification.notification_type,
                "title": notification.title,
                "body": notification.body,
                "body_html": notification.body_html,
                "priority": notification.priority,
                "created_at": notification.created_at.isoformat(),
                "read": notification.read,
            },
        }

        # Add optional fields
        if notification.actions:
            payload["data"]["actions"] = notification.actions

        if notification.progress is not None:
            payload["data"]["progress"] = notification.progress

        if notification.group_key:
            payload["data"]["group_key"] = notification.group_key

        if notification.auto_dismiss:
            payload["data"]["auto_dismiss"] = notification.auto_dismiss
            if notification.dismiss_after:
                payload["data"]["dismiss_after"] = notification.dismiss_after

        if notification.source_entity_type and notification.source_entity_id:
            payload["data"]["source"] = {
                "type": notification.source_entity_type,
                "id": notification.source_entity_id,
            }

        # Add context data if available
        if notification.context_data:
            payload["data"]["context"] = notification.context_data

        return payload
