"""Base protocol and types for channel dispatchers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from example_service.features.notifications.models import (
        Notification,
        NotificationDelivery,
        UserNotificationPreference,
    )


@dataclass
class DeliveryResult:
    """Result of a channel delivery attempt.

    Attributes:
        success: Whether delivery succeeded
        status_code: HTTP status code (for webhook/email) or None
        response_body: Response body/message
        response_time_ms: Time taken for delivery in milliseconds
        error_message: Error description if failed
        error_category: Error classification (network, auth, validation, etc.)
        metadata: Channel-specific metadata
    """

    success: bool
    status_code: int | None = None
    response_body: str | None = None
    response_time_ms: int | None = None
    error_message: str | None = None
    error_category: str | None = None
    metadata: dict[str, str | int | bool] | None = None


class ChannelDispatcher(Protocol):
    """Protocol for channel-specific notification dispatchers.

    Each channel (email, webhook, websocket, in-app) implements this protocol
    to provide consistent delivery interface.
    """

    async def send(
        self,
        notification: Notification,
        delivery: NotificationDelivery,
    ) -> DeliveryResult:
        """Send notification via this channel.

        Args:
            notification: Notification to send (contains rendered content)
            delivery: Delivery record to track attempt

        Returns:
            DeliveryResult with status and metadata
        """
        ...

    async def is_enabled_for_user(
        self,
        preferences: UserNotificationPreference | None,
    ) -> bool:
        """Check if channel is enabled for user based on preferences.

        Args:
            preferences: User's notification preferences (None = use defaults)

        Returns:
            True if channel should be used for this user
        """
        ...

    def get_channel_name(self) -> str:
        """Get the channel identifier.

        Returns:
            Channel name (email, webhook, websocket, in_app)
        """
        ...
