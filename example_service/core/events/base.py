"""Domain event base class with versioning and causation tracking.

This module defines the base class for all domain events in the system.
Domain events represent something meaningful that happened in the domain,
and are used for event-driven communication between components.

Key features:
- Event versioning for schema evolution
- Causation tracking (which event caused this event)
- Correlation IDs for distributed tracing
- Automatic timestamp and ID generation
- Message headers generation for RabbitMQ publishing
- Optional routing key generation from format strings
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from example_service.core.settings import get_app_settings


def _generate_uuid7() -> str:
    """Generate a time-sortable UUID v7.

    UUID v7 embeds a Unix timestamp for time-based ordering,
    making it ideal for event IDs where chronological order matters.
    """
    try:
        from uuid_utils import uuid7

        return str(uuid7())
    except ImportError:
        # Fallback to uuid4 if uuid_utils not available
        from uuid import uuid4

        return str(uuid4())


class DomainEvent(BaseModel):
    """Base class for all domain events.

    Domain events represent meaningful occurrences in the business domain.
    They are immutable records of something that happened, used for:
    - Event-driven communication between services
    - Building event-sourced aggregates
    - Triggering side effects (notifications, projections, etc.)

    Subclasses must define:
    - event_type: ClassVar[str] - Unique event type identifier (e.g., "user.created")
    - event_version: ClassVar[int] - Schema version for evolution (default: 1)

    Example:
        class UserCreatedEvent(DomainEvent):
            event_type: ClassVar[str] = "user.created"
            event_version: ClassVar[int] = 1

            user_id: str
            email: str
            name: str | None = None

        # Create and publish
        event = UserCreatedEvent(
            user_id="123",
            email="user@example.com",
            correlation_id=request.state.correlation_id,
        )

    Attributes:
        event_id: Unique identifier for this event instance (UUID v7)
        timestamp: When the event occurred (UTC)
        correlation_id: ID linking related events across services
        causation_id: ID of the event that caused this event
        service: Name of the service that generated the event
        metadata: Additional context (user_id, request_id, etc.)
    """

    # Class-level attributes (must be overridden in subclasses)
    event_type: ClassVar[str] = "domain.event"
    event_version: ClassVar[int] = 1

    # Optional routing key format (e.g., "user.{action}" or "tenant.{tenant_uuid}.event")
    # If not defined, event_type is used as the routing key
    routing_key_fmt: ClassVar[str | None] = None

    # Instance attributes
    event_id: str = Field(
        default_factory=_generate_uuid7,
        description="Unique event identifier (UUID v7 for time-ordering)",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Event timestamp in UTC",
    )
    correlation_id: str | None = Field(
        default=None,
        description="Correlation ID for distributed tracing",
    )
    causation_id: str | None = Field(
        default=None,
        description="ID of the event that caused this event",
    )
    service: str = Field(
        default_factory=lambda: get_app_settings().service_name,
        description="Service that generated the event",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional event metadata",
    )

    model_config = ConfigDict(
        frozen=True,  # Events are immutable
        str_strip_whitespace=True,
        extra="forbid",  # Strict schema validation
    )

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Validate subclass has required class variables."""
        super().__init_subclass__(**kwargs)
        # Skip validation for intermediate base classes
        # These are abstract event hierarchies that shouldn't define event_type
        intermediate_bases = (
            "DomainEvent",
            "BaseEvent",  # Messaging base event
            "ServiceEvent",
            "TenantEvent",
            "UserEvent",
            "MultiUserEvent",
        )
        if cls.__name__ in intermediate_bases:
            return
        # Ensure event_type is defined for concrete event classes
        if not hasattr(cls, "event_type") or cls.event_type == "domain.event":
            msg = f"{cls.__name__} must define 'event_type' class variable"
            raise TypeError(msg)

    @classmethod
    def get_event_type(cls) -> str:
        """Get the event type identifier."""
        return cls.event_type

    @classmethod
    def get_event_version(cls) -> int:
        """Get the event schema version."""
        return cls.event_version

    @classmethod
    def get_qualified_type(cls) -> str:
        """Get fully qualified event type with version.

        Returns:
            String in format "event_type:v{version}" (e.g., "user.created:v1")
        """
        return f"{cls.event_type}:v{cls.event_version}"

    def with_causation(self, causing_event: DomainEvent) -> DomainEvent:
        """Create a copy of this event with causation tracking.

        Sets the causation_id to the causing event's ID and inherits
        the correlation_id if not already set.

        Args:
            causing_event: The event that caused this event

        Returns:
            New event instance with causation tracking

        Example:
            order_event = OrderCreatedEvent(...)
            payment_event = PaymentInitiatedEvent(...).with_causation(order_event)
        """
        updates: dict[str, Any] = {"causation_id": causing_event.event_id}
        if self.correlation_id is None and causing_event.correlation_id:
            updates["correlation_id"] = causing_event.correlation_id
        return self.model_copy(update=updates)

    def with_correlation(self, correlation_id: str) -> DomainEvent:
        """Create a copy of this event with a correlation ID.

        Args:
            correlation_id: The correlation ID for distributed tracing

        Returns:
            New event instance with correlation ID set
        """
        return self.model_copy(update={"correlation_id": correlation_id})

    def with_metadata(self, **kwargs: Any) -> DomainEvent:
        """Create a copy of this event with additional metadata.

        Args:
            **kwargs: Key-value pairs to add to metadata

        Returns:
            New event instance with updated metadata
        """
        new_metadata = {**self.metadata, **kwargs}
        return self.model_copy(update={"metadata": new_metadata})

    def to_outbox_payload(self) -> dict[str, Any]:
        """Serialize event for outbox storage.

        Returns:
            Dictionary with event data and type information
        """
        event_data = self.model_dump(mode="json")
        return {
            "event_type": self.event_type,
            "event_version": self.event_version,
            **event_data,
        }

    def headers(self) -> dict[str, Any]:
        """Generate message headers for RabbitMQ publishing.

        Returns a dictionary of headers containing event metadata.
        Subclasses can override to add additional headers (e.g., tenant_uuid).

        Headers are used for:
        - Message routing (x-match headers exchange)
        - Distributed tracing (correlation_id)
        - Event identification (event_type, event_version)

        Returns:
            Dictionary of header key-value pairs.

        Example:
            event = UserCreatedEvent(user_id="123")
            headers = event.headers()
            # {
            #     "x-event-type": "user.created",
            #     "x-event-version": "1",
            #     "x-event-id": "01234567-...",
            #     "x-correlation-id": "...",
            #     "x-service": "example-service"
            # }
        """
        headers: dict[str, Any] = {
            "x-event-type": self.event_type,
            "x-event-version": str(self.event_version),
            "x-event-id": self.event_id,
            "x-service": self.service,
            "x-timestamp": self.timestamp.isoformat(),
        }

        if self.correlation_id:
            headers["x-correlation-id"] = self.correlation_id

        if self.causation_id:
            headers["x-causation-id"] = self.causation_id

        return headers

    @property
    def routing_key(self) -> str:
        """Generate routing key for message publishing.

        If routing_key_fmt is defined, uses it as a format string with
        event fields as values. Otherwise, returns the event_type.

        The routing key determines which queues receive the message
        when using a topic exchange.

        Returns:
            Routing key string.

        Example:
            # Without routing_key_fmt
            class UserCreatedEvent(DomainEvent):
                event_type: ClassVar[str] = "user.created"
            event = UserCreatedEvent()
            assert event.routing_key == "user.created"

            # With routing_key_fmt
            class UserActionEvent(DomainEvent):
                event_type: ClassVar[str] = "user.action"
                routing_key_fmt: ClassVar[str] = "user.{action}.{user_id}"
                action: str
                user_id: str
            event = UserActionEvent(action="login", user_id="123")
            assert event.routing_key == "user.login.123"
        """
        if self.routing_key_fmt is None:
            return self.event_type

        # Format routing key using event fields
        try:
            return self.routing_key_fmt.format(**self.model_dump())
        except KeyError:
            # Fall back to event_type if format fails
            return self.event_type

    def __repr__(self) -> str:
        """Human-readable representation."""
        return (
            f"{self.__class__.__name__}("
            f"event_id={self.event_id!r}, "
            f"event_type={self.event_type!r}, "
            f"timestamp={self.timestamp.isoformat()}"
            f")"
        )


__all__ = ["DomainEvent"]
