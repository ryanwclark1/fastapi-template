"""Main notification dispatcher coordinating all channels."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from example_service.features.notifications.channels.email import EmailChannelDispatcher
from example_service.features.notifications.channels.in_app import (
    InAppChannelDispatcher,
)
from example_service.features.notifications.channels.webhook import (
    WebhookChannelDispatcher,
)
from example_service.features.notifications.channels.websocket import (
    WebSocketChannelDispatcher,
)
from example_service.features.notifications.metrics import (
    notification_delivered_total,
    notification_delivery_duration_seconds,
    notification_errors_total,
    notification_quiet_hours_delayed_total,
)
from example_service.features.notifications.models import NotificationDelivery
from example_service.infra.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence

    from example_service.features.notifications.channels.base import ChannelDispatcher
    from example_service.features.notifications.models import (
        Notification,
        UserNotificationPreference,
    )


class NotificationDispatcher:
    """Main dispatcher coordinating multi-channel notification delivery.

    Routes notifications to appropriate channels based on:
    - User preferences (enabled channels)
    - Quiet hours (UTC timezone)
    - Channel availability

    Creates NotificationDelivery records for tracking and retry.
    """

    def __init__(self) -> None:
        """Initialize with all channel dispatchers."""
        self._logger = get_logger()

        # Initialize channel dispatchers
        self._channels: dict[str, ChannelDispatcher] = {
            "email": EmailChannelDispatcher(),
            "websocket": WebSocketChannelDispatcher(),
            "webhook": WebhookChannelDispatcher(),
            "in_app": InAppChannelDispatcher(),
        }

    async def dispatch(
        self,
        notification: Notification,
        preferences: UserNotificationPreference | None = None,
    ) -> Sequence[NotificationDelivery]:
        """Dispatch notification to all enabled channels.

        Args:
            notification: Notification to dispatch
            preferences: User preferences (None = use defaults)

        Returns:
            Sequence of NotificationDelivery records created
        """
        deliveries: list[NotificationDelivery] = []

        # Check quiet hours
        if self._is_in_quiet_hours(preferences):
            self._logger.info(
                f"Notification {notification.id} delayed due to quiet hours",
            )
            # Track quiet hours delay
            notification_quiet_hours_delayed_total.labels(
                notification_type=notification.notification_type,
            ).inc()
            # Reschedule for after quiet hours
            # For now, just log and skip. In production, this would update scheduled_for
            return deliveries

        # Determine enabled channels
        enabled_channels = self._get_enabled_channels(preferences)

        self._logger.debug(
            lambda: f"Dispatching notification {notification.id} to channels: {enabled_channels}",
        )

        # Dispatch to each enabled channel
        for channel_name in enabled_channels:
            dispatcher = self._channels.get(channel_name)

            if not dispatcher:
                self._logger.warning(
                    f"No dispatcher found for channel {channel_name}",
                )
                continue

            # Check if channel is enabled for this user
            if not await dispatcher.is_enabled_for_user(preferences):
                self._logger.debug(
                    lambda channel=channel_name: (
                        f"Channel {channel} disabled by user preference"
                    ),
                )
                continue

            # Create delivery record
            delivery = NotificationDelivery(
                notification_id=notification.id,
                channel=channel_name,
                status="pending",
                attempt_count=0,
                max_attempts=5 if channel_name in ("email", "webhook") else 1,
            )

            # Attempt delivery
            try:
                result = await dispatcher.send(notification, delivery)

                # Update delivery record based on result
                delivery.attempt_count += 1
                delivery.response_status_code = result.status_code
                delivery.response_body = result.response_body
                delivery.response_time_ms = result.response_time_ms

                # Track delivery duration
                if result.response_time_ms:
                    notification_delivery_duration_seconds.labels(
                        channel=channel_name,
                    ).observe(result.response_time_ms / 1000.0)

                if result.success:
                    delivery.status = "delivered"
                    delivery.delivered_at = datetime.now(UTC)

                    # Track successful delivery
                    notification_delivered_total.labels(
                        channel=channel_name,
                        status="delivered",
                    ).inc()

                    self._logger.info(
                        f"Notification {notification.id} delivered via {channel_name}",
                    )
                else:
                    # Delivery failed - set for retry if applicable
                    delivery.status = "failed" if channel_name in ("websocket", "in_app") else "pending"
                    delivery.error_message = result.error_message
                    delivery.error_category = result.error_category

                    # Track failed delivery
                    notification_delivered_total.labels(
                        channel=channel_name,
                        status="failed",
                    ).inc()

                    # Track error by category
                    if result.error_category:
                        notification_errors_total.labels(
                            channel=channel_name,
                            error_category=result.error_category,
                        ).inc()

                    if delivery.status == "pending":
                        # Schedule retry with exponential backoff
                        backoff_seconds = min(2 ** delivery.attempt_count * 60, 3600)  # Max 1 hour
                        delivery.next_retry_at = datetime.now(UTC) + timedelta(seconds=backoff_seconds)

                    self._logger.warning(
                        f"Notification {notification.id} failed via {channel_name}: {result.error_message}",
                    )

            except Exception as exc:
                # Unexpected error during dispatch
                delivery.attempt_count += 1
                delivery.status = "failed"
                delivery.error_message = str(exc)
                delivery.error_category = "exception"
                delivery.failed_at = datetime.now(UTC)

                # Track exception
                notification_delivered_total.labels(
                    channel=channel_name,
                    status="failed",
                ).inc()

                notification_errors_total.labels(
                    channel=channel_name,
                    error_category="exception",
                ).inc()

                self._logger.exception(
                    f"Exception dispatching notification {notification.id} via {channel_name}: {exc}",
                )

            deliveries.append(delivery)

        return deliveries

    def _get_enabled_channels(
        self,
        preferences: UserNotificationPreference | None,
    ) -> list[str]:
        """Get list of enabled channels for user.

        Args:
            preferences: User preferences (None = use defaults)

        Returns:
            List of channel names
        """
        if preferences is None:
            # Default channels: email, websocket, in_app
            return ["email", "websocket", "in_app"]

        if not preferences.is_active:
            # Preferences disabled - use defaults
            return ["email", "websocket", "in_app"]

        return list(preferences.enabled_channels)

    def _is_in_quiet_hours(
        self,
        preferences: UserNotificationPreference | None,
    ) -> bool:
        """Check if current time is within user's quiet hours.

        Args:
            preferences: User preferences (None = no quiet hours)

        Returns:
            True if currently in quiet hours
        """
        if not preferences:
            return False

        if preferences.quiet_hours_start is None or preferences.quiet_hours_end is None:
            return False

        # Get current hour in UTC
        current_hour = datetime.now(UTC).hour

        start = preferences.quiet_hours_start
        end = preferences.quiet_hours_end

        # Handle quiet hours that span midnight
        if start < end:
            # e.g., 22:00 - 08:00 (quiet hours span midnight)
            return current_hour >= start or current_hour < end

        # Normal case: e.g., 08:00 - 22:00
        return start <= current_hour < end


# Singleton instance
_dispatcher: NotificationDispatcher | None = None


def get_notification_dispatcher() -> NotificationDispatcher:
    """Get or create the singleton NotificationDispatcher instance.

    Returns:
        NotificationDispatcher instance
    """
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = NotificationDispatcher()
    return _dispatcher
