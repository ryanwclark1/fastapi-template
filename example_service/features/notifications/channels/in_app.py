"""In-app channel dispatcher for database-only notifications."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from example_service.features.notifications.channels.base import DeliveryResult
from example_service.infra.logging import get_logger

if TYPE_CHECKING:
    from example_service.features.notifications.models import (
        Notification,
        NotificationDelivery,
        UserNotificationPreference,
    )


class InAppChannelDispatcher:
    """Dispatcher for in-app notifications (database-only).

    In-app notifications are stored in the database and displayed in the
    application UI. No external delivery needed - the notification record
    itself is the delivery mechanism.
    """

    def __init__(self) -> None:
        """Initialize in-app dispatcher."""
        self._logger = get_logger()

    async def send(
        self,
        notification: Notification,
        delivery: NotificationDelivery,
    ) -> DeliveryResult:
        """Mark notification as available in-app.

        For in-app channel, "delivery" just means ensuring the notification
        is marked as unread in the database. No external action needed.

        Args:
            notification: Notification instance
            delivery: Delivery record

        Returns:
            DeliveryResult (always successful for in-app)
        """
        start_time = time.time()

        try:
            # Ensure notification is marked as unread
            # (This should already be the default, but be explicit)
            if not notification.read:
                # Already unread - delivery successful
                pass
            else:
                # Mark as unread
                notification.read = False
                notification.read_at = None

            elapsed_ms = int((time.time() - start_time) * 1000)

            self._logger.debug(
                lambda: f"In-app notification {notification.id} marked as unread for user {notification.user_id}",
            )

            return DeliveryResult(
                success=True,
                response_time_ms=elapsed_ms,
                metadata={"read": notification.read},
            )

        except Exception as exc:
            elapsed_ms = int((time.time() - start_time) * 1000)
            self._logger.exception(
                f"Exception in in-app dispatcher for notification {notification.id}: {exc}",
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
        """Check if in-app is enabled for user.

        Args:
            preferences: User preferences (None = use defaults)

        Returns:
            True if in_app channel is enabled
        """
        if preferences is None:
            # Default: in-app enabled
            return True

        return "in_app" in preferences.enabled_channels

    def get_channel_name(self) -> str:
        """Get channel identifier.

        Returns:
            Channel name: 'in_app'
        """
        return "in_app"
