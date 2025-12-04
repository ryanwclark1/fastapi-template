"""Domain event system with versioning and outbox pattern.

This module provides a robust event system for publishing domain events
with guaranteed delivery through the outbox pattern.

Includes a multi-tenant event hierarchy:
- ServiceEvent: Internal service events
- TenantEvent: Tenant-wide broadcasts
- UserEvent: Single user targeted events
- MultiUserEvent: Multiple user targeted events

Usage:
    from example_service.core.events import (
        DomainEvent,
        TenantEvent,
        UserEvent,
        EventPublisher,
        event_registry,
    )

    # Define a tenant-wide event
    class OrderCreatedEvent(TenantEvent):
        event_type: ClassVar[str] = "order.created"
        order_id: str

    # Define a user-specific event
    class UserNotificationEvent(UserEvent):
        event_type: ClassVar[str] = "user.notification"
        message: str

    # Register and publish events
    event_registry.register(OrderCreatedEvent)
    publisher = EventPublisher(session)
    await publisher.publish(
        OrderCreatedEvent(tenant_uuid="tenant-123", order_id="order-456")
    )
"""

from example_service.core.events.base import DomainEvent
from example_service.core.events.hierarchy import (
    MultiUserEvent,
    ServiceEvent,
    TenantEvent,
    UserEvent,
)
from example_service.core.events.publisher import EventPublisher
from example_service.core.events.registry import EventRegistry, event_registry

__all__ = [
    # Base event
    "DomainEvent",
    # Publishing
    "EventPublisher",
    "EventRegistry",
    # Event hierarchy
    "MultiUserEvent",
    "ServiceEvent",
    "TenantEvent",
    "UserEvent",
    "event_registry",
]
