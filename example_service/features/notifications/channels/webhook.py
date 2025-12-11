"""Webhook channel dispatcher integrating with existing webhook system."""

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


class WebhookChannelDispatcher:
    """Dispatcher for webhook notifications.

    Integrates with existing webhook infrastructure for external system integration.
    NOTE: Integrate with WebhookDispatcher service when webhook support ships.
    """

    def __init__(self) -> None:
        """Initialize webhook dispatcher."""
        self._logger = get_logger()

    async def send(
        self,
        notification: Notification,
        delivery: NotificationDelivery,
    ) -> DeliveryResult:
        """Send notification via webhook.

        Args:
            notification: Notification with rendered content
            delivery: Delivery record (will update webhook_id, webhook_url)

        Returns:
            DeliveryResult with webhook-specific metadata
        """
        start_time = time.time()

        try:
            # NOTE: Webhook integration pending implementation.
            # 1. Find user's registered webhooks for this notification type
            # 2. Use WebhookDispatcher to send HTTP POST
            # 3. Track webhook_id and response
            #
            # For now, return not implemented

            self._logger.debug(
                lambda: f"Webhook dispatcher not yet implemented for notification {notification.id}",
            )

            elapsed_ms = int((time.time() - start_time) * 1000)

            return DeliveryResult(
                success=False,
                error_message="Webhook integration not yet implemented",
                error_category="not_implemented",
                response_time_ms=elapsed_ms,
            )

        except Exception as exc:
            elapsed_ms = int((time.time() - start_time) * 1000)
            self._logger.exception(
                f"Exception in webhook dispatcher for notification {notification.id}: {exc}",
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
        """Check if webhook is enabled for user.

        Args:
            preferences: User preferences (None = use defaults)

        Returns:
            True if webhook channel is enabled
        """
        if preferences is None:
            # Default: webhook disabled (opt-in only)
            return False

        return "webhook" in preferences.enabled_channels

    def get_channel_name(self) -> str:
        """Get channel identifier.

        Returns:
            Channel name: 'webhook'
        """
        return "webhook"
