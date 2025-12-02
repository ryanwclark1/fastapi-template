"""Webhooks feature package."""

from .client import WebhookClient, WebhookDeliveryResult
from .dispatcher import dispatch_event, process_pending_deliveries
from .events import (
    ALL_EVENT_TYPES,
    FileEvents,
    ReminderEvents,
    build_file_event_payload,
    build_reminder_event_payload,
    generate_event_id,
    get_event_category,
    validate_event_type,
)
from .repository import (
    WebhookDeliveryRepository,
    WebhookRepository,
    get_webhook_delivery_repository,
    get_webhook_repository,
)
from .router import router
from .service import WebhookService

__all__ = [
    "ALL_EVENT_TYPES",
    # Event types and utilities
    "FileEvents",
    "ReminderEvents",
    "WebhookClient",
    "WebhookDeliveryRepository",
    "WebhookDeliveryResult",
    "WebhookRepository",
    "WebhookService",
    "build_file_event_payload",
    "build_reminder_event_payload",
    "dispatch_event",
    "generate_event_id",
    "get_event_category",
    "get_webhook_delivery_repository",
    "get_webhook_repository",
    "process_pending_deliveries",
    "router",
    "validate_event_type",
]
