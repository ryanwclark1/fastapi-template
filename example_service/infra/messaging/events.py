"""Domain event schemas for message publishing and consumption.

This module defines the data structures for events published to
and consumed from the message broker.

These events inherit from the core DomainEvent class to ensure consistency
across the codebase while providing simplified constructors for common
messaging patterns.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import Field

from example_service.core.events.base import DomainEvent


class BaseEvent(DomainEvent):
    """Base class for messaging domain events.

    Inherits from the core DomainEvent to provide:
    - Event versioning for schema evolution
    - Causation tracking (which event caused this event)
    - Correlation IDs for distributed tracing
    - Automatic timestamp and ID generation
    - Message headers generation for RabbitMQ publishing

    This class provides a simpler interface for common messaging patterns
    while maintaining full compatibility with the core event infrastructure.

    Note:
        For new events, prefer inheriting directly from DomainEvent
        unless you need the simplified interface provided here.
    """

    # Override to allow mutable events for messaging flexibility
    model_config = DomainEvent.model_config.copy()
    model_config["frozen"] = False


class ExampleCreatedEvent(BaseEvent):
    """Event published when an example entity is created.

    Example:
        event = ExampleCreatedEvent(
            data={"id": "123", "name": "Example"}
        )
        await broker.publish(event, queue="example-events")
    """

    event_type: ClassVar[str] = "example.created"
    event_version: ClassVar[int] = 1

    data: dict[str, Any] = Field(description="Entity data")


class ExampleUpdatedEvent(BaseEvent):
    """Event published when an example entity is updated.

    Example:
        event = ExampleUpdatedEvent(
            data={"id": "123", "changes": {"name": "New Name"}}
        )
        await broker.publish(event, queue="example-events")
    """

    event_type: ClassVar[str] = "example.updated"
    event_version: ClassVar[int] = 1

    data: dict[str, Any] = Field(description="Entity data with changes")


class ExampleDeletedEvent(BaseEvent):
    """Event published when an example entity is deleted.

    Example:
        event = ExampleDeletedEvent(
            data={"id": "123"}
        )
        await broker.publish(event, queue="example-events")
    """

    event_type: ClassVar[str] = "example.deleted"
    event_version: ClassVar[int] = 1

    data: dict[str, Any] = Field(description="Entity identifier")


# Rebuild all models to ensure they're fully defined before use in handlers
# This is required for FastStream's AsyncAPI schema generation
BaseEvent.model_rebuild()
ExampleCreatedEvent.model_rebuild()
ExampleUpdatedEvent.model_rebuild()
ExampleDeletedEvent.model_rebuild()
