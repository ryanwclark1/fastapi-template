"""Multi-channel notification delivery infrastructure.

Provides channel-specific dispatchers for:
- Email: via EnhancedEmailService
- WebSocket: via ConnectionManager (real-time)
- Webhook: via WebhookDispatcher
- In-App: database-only notifications

Each dispatcher implements the ChannelDispatcher protocol and handles:
- Channel-specific delivery logic
- Retry and error handling
- Delivery tracking and metrics
"""

from __future__ import annotations

from example_service.features.notifications.channels.base import (
    ChannelDispatcher,
    DeliveryResult,
)
from example_service.features.notifications.channels.dispatcher import (
    NotificationDispatcher,
    get_notification_dispatcher,
)

__all__ = [
    "ChannelDispatcher",
    "DeliveryResult",
    "NotificationDispatcher",
    "get_notification_dispatcher",
]
