"""Domain event schemas for message publishing and consumption.

This module defines the data structures for events published to
and consumed from the message broker.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class BaseEvent(BaseModel):
    """Base class for all domain events.

    All events should inherit from this class to ensure they have
    common fields like event_id, timestamp, and event_type.
    """

    event_id: str = Field(default_factory=lambda: str(uuid4()), description="Unique event ID")
    event_type: str = Field(min_length=1, max_length=100, description="Type of the event")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Event timestamp"
    )
    service: str = Field(
        default="example-service",
        min_length=1,
        max_length=100,
        description="Service that generated the event",
    )
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional event metadata")

    model_config = ConfigDict(
        str_strip_whitespace=True,
    )


class ExampleCreatedEvent(BaseEvent):
    """Event published when an example entity is created.

    Example:
            event = ExampleCreatedEvent(
            data={"id": "123", "name": "Example"}
        )
        await broker.publish(event, queue="example-events")
    """

    event_type: Literal["example.created"] = Field(
        default="example.created", description="Event type"
    )
    data: dict[str, Any] = Field(description="Entity data")


class ExampleUpdatedEvent(BaseEvent):
    """Event published when an example entity is updated.

    Example:
            event = ExampleUpdatedEvent(
            data={"id": "123", "changes": {"name": "New Name"}}
        )
        await broker.publish(event, queue="example-events")
    """

    event_type: Literal["example.updated"] = Field(
        default="example.updated", description="Event type"
    )
    data: dict[str, Any] = Field(description="Entity data with changes")


class ExampleDeletedEvent(BaseEvent):
    """Event published when an example entity is deleted.

    Example:
            event = ExampleDeletedEvent(
            data={"id": "123"}
        )
        await broker.publish(event, queue="example-events")
    """

    event_type: Literal["example.deleted"] = Field(
        default="example.deleted", description="Event type"
    )
    data: dict[str, Any] = Field(description="Entity identifier")


# Rebuild all models to ensure they're fully defined before use in handlers
# This is required for FastStream's AsyncAPI schema generation
BaseEvent.model_rebuild()
ExampleCreatedEvent.model_rebuild()
ExampleUpdatedEvent.model_rebuild()
ExampleDeletedEvent.model_rebuild()
