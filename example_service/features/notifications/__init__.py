"""Unified notifications feature with multi-channel delivery support.

This feature provides a comprehensive notification system that:
- Supports multiple delivery channels (email, webhook, WebSocket, in-app)
- User-configurable preferences per notification type
- Template-based content with Jinja2 rendering
- Delivery tracking with retry logic
- Event-driven triggers from domain events
- Full multi-tenant isolation

Architecture:
    - Models: Notification, NotificationDelivery, NotificationTemplate, UserNotificationPreference
    - Channels: Pluggable dispatchers for email, webhook, websocket, in-app
    - Templates: Jinja2 rendering with context validation
    - Events: Domain event integration for automatic notifications
    - Event Handlers: Automatic notification creation from domain events

Example:
    ```python
    # Create a notification
    notification = await notification_service.create_notification(
        user_id="user-123",
        notification_type="reminder_due",
        context={"title": "Review PR", "remind_at": datetime.now()},
        template_name="reminder_due",
        priority="high",
    )

    # Configure user preferences
    await preference_service.update_preference(
        user_id="user-123",
        notification_type="reminder_due",
        enabled_channels=["email", "websocket"],
    )

    # Event handlers are automatically registered at startup
    # Publishing a ReminderDueEvent will automatically create a notification
    ```
"""

from example_service.features.notifications import event_handlers
from example_service.features.notifications.models import (
    Notification,
    NotificationDelivery,
    NotificationTemplate,
    UserNotificationPreference,
)

# Repositories
from example_service.features.notifications.repository import (
    NotificationDeliveryRepository,
    NotificationRepository,
    NotificationTemplateRepository,
    UserNotificationPreferenceRepository,
    get_notification_delivery_repository,
    get_notification_repository,
    get_notification_template_repository,
    get_user_notification_preference_repository,
)

# Router
from example_service.features.notifications.router import (
    admin_router,
    router,
)

# Services
from example_service.features.notifications.service import (
    NotificationService,
    get_notification_service,
)

__all__ = [
    "Notification",
    "NotificationDelivery",
    "NotificationDeliveryRepository",
    "NotificationRepository",
    "NotificationService",
    "NotificationTemplate",
    "NotificationTemplateRepository",
    "UserNotificationPreference",
    "UserNotificationPreferenceRepository",
    "admin_router",
    "event_handlers",
    "get_notification_delivery_repository",
    "get_notification_repository",
    "get_notification_service",
    "get_notification_template_repository",
    "get_user_notification_preference_repository",
    "router",
]
