"""Domain event system with versioning and outbox pattern.

This module provides a robust event system for publishing domain events
with guaranteed delivery through the outbox pattern.

Usage:
    from example_service.core.events import DomainEvent, EventPublisher, event_registry

    # Define a domain event
    class UserCreatedEvent(DomainEvent):
        event_type: ClassVar[str] = "user.created"
        event_version: ClassVar[int] = 1

        user_id: str
        email: str

    # Register the event
    event_registry.register(UserCreatedEvent)

    # Publish an event (transactionally safe)
    publisher = EventPublisher(session)
    await publisher.publish(UserCreatedEvent(user_id="123", email="user@example.com"))
"""

from example_service.core.events.base import DomainEvent
from example_service.core.events.publisher import EventPublisher
from example_service.core.events.registry import EventRegistry, event_registry

__all__ = [
    "DomainEvent",
    "EventPublisher",
    "EventRegistry",
    "event_registry",
]
