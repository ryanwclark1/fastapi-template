"""Event type registry for deserialization and discovery.

The registry maintains a mapping from event type strings to event classes,
enabling:
- Safe deserialization of events from the outbox/message broker
- Event type discovery for documentation
- Version management for schema evolution

Usage:
    from example_service.core.events import event_registry, DomainEvent

    # Define and register an event
    class UserCreatedEvent(DomainEvent):
        event_type: ClassVar[str] = "user.created"
        user_id: str

    event_registry.register(UserCreatedEvent)

    # Or use the decorator
    @event_registry.register
    class OrderPlacedEvent(DomainEvent):
        event_type: ClassVar[str] = "order.placed"
        order_id: str

    # Deserialize from stored payload
    event = event_registry.deserialize(payload)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, TypeVar, overload

if TYPE_CHECKING:
    from example_service.core.events.base import DomainEvent

logger = logging.getLogger(__name__)

T = TypeVar("T", bound="DomainEvent")


class EventRegistry:
    """Registry for domain event types.

    Maintains a mapping of event type strings to event classes for
    deserialization and discovery. Supports versioning to handle
    schema evolution gracefully.

    Thread-safe for read operations (registration is expected during startup).
    """

    def __init__(self) -> None:
        """Initialize empty registry."""
        # Map: event_type -> version -> event_class
        self._events: dict[str, dict[int, type[DomainEvent]]] = {}
        # Map: event_type -> latest version number
        self._latest_versions: dict[str, int] = {}

    @overload
    def register(self, event_class: type[T]) -> type[T]: ...

    @overload
    def register(self, event_class: None = None) -> Any: ...

    def register(self, event_class: type[T] | None = None) -> type[T] | Any:
        """Register an event class in the registry.

        Can be used as a decorator or direct method call.

        Args:
            event_class: The event class to register

        Returns:
            The event class (unchanged) when used as decorator,
            or a decorator function when called without arguments

        Example:
            # Direct registration
            event_registry.register(UserCreatedEvent)

            # As decorator
            @event_registry.register
            class OrderPlacedEvent(DomainEvent):
                event_type: ClassVar[str] = "order.placed"
                ...

        Raises:
            ValueError: If event_type is not defined or already registered
                with the same version
        """

        def _register(cls: type[T]) -> type[T]:
            event_type = cls.get_event_type()
            event_version = cls.get_event_version()

            if event_type not in self._events:
                self._events[event_type] = {}

            if event_version in self._events[event_type]:
                existing = self._events[event_type][event_version]
                if existing is not cls:
                    raise ValueError(
                        f"Event type '{event_type}' version {event_version} "
                        f"already registered with {existing.__name__}"
                    )
                # Already registered (idempotent)
                return cls

            self._events[event_type][event_version] = cls

            # Update latest version tracking
            current_latest = self._latest_versions.get(event_type, 0)
            if event_version > current_latest:
                self._latest_versions[event_type] = event_version

            logger.debug(
                "Registered event type",
                extra={
                    "event_type": event_type,
                    "version": event_version,
                    "class": cls.__name__,
                },
            )
            return cls

        if event_class is None:
            # Called as @register() with parentheses
            return _register

        # Called as @register without parentheses or register(EventClass)
        return _register(event_class)

    def get(
        self,
        event_type: str,
        version: int | None = None,
    ) -> type[DomainEvent] | None:
        """Get an event class by type and optional version.

        Args:
            event_type: The event type string (e.g., "user.created")
            version: Specific version to retrieve (latest if None)

        Returns:
            The event class, or None if not found
        """
        if event_type not in self._events:
            return None

        versions = self._events[event_type]

        if version is not None:
            return versions.get(version)

        # Return latest version
        latest_version = self._latest_versions.get(event_type)
        if latest_version is None:
            return None
        return versions.get(latest_version)

    def get_or_raise(
        self,
        event_type: str,
        version: int | None = None,
    ) -> type[DomainEvent]:
        """Get an event class or raise if not found.

        Args:
            event_type: The event type string
            version: Specific version to retrieve (latest if None)

        Returns:
            The event class

        Raises:
            KeyError: If event type/version not found
        """
        event_class = self.get(event_type, version)
        if event_class is None:
            version_str = f" version {version}" if version else ""
            raise KeyError(f"Unknown event type: '{event_type}'{version_str}")
        return event_class

    def deserialize(
        self,
        payload: dict[str, Any],
        *,
        strict_version: bool = False,
    ) -> DomainEvent:
        """Deserialize an event from outbox/message payload.

        Args:
            payload: Dictionary containing event_type, event_version, and data
            strict_version: If True, require exact version match;
                if False (default), try latest version for forward compatibility

        Returns:
            Deserialized event instance

        Raises:
            KeyError: If event type not found
            ValueError: If payload is malformed
            ValidationError: If data doesn't match schema

        Example:
            payload = {
                "event_type": "user.created",
                "event_version": 1,
                "data": {"event_id": "...", "user_id": "123", ...}
            }
            event = event_registry.deserialize(payload)
        """
        if "event_type" not in payload:
            msg = "Payload missing 'event_type'"
            raise ValueError(msg)

        event_type = payload["event_type"]
        event_version = payload.get("event_version", 1)
        data = payload.get("data")
        if data is None:
            data = {
                key: value
                for key, value in payload.items()
                if key not in {"event_type", "event_version"}
            }

        # Try exact version first
        event_class = self.get(event_type, event_version)

        if event_class is None and not strict_version:
            # Try latest version for forward compatibility
            event_class = self.get(event_type)
            if event_class is not None:
                logger.warning(
                    "Using latest version for deserialization",
                    extra={
                        "event_type": event_type,
                        "requested_version": event_version,
                        "using_version": event_class.get_event_version(),
                    },
                )

        if event_class is None:
            message = f"Unknown event type: '{event_type}' version {event_version}"
            if strict_version:
                raise ValueError(message)
            raise KeyError(message)

        return event_class.model_validate(data)

    def list_types(self) -> list[str]:
        """List all registered event types.

        Returns:
            List of event type strings
        """
        return list(self._events.keys())

    def list_versions(self, event_type: str) -> list[int]:
        """List all registered versions for an event type.

        Args:
            event_type: The event type string

        Returns:
            List of version numbers, sorted ascending
        """
        if event_type not in self._events:
            return []
        return sorted(self._events[event_type].keys())

    def get_latest_version(self, event_type: str) -> int | None:
        """Get the latest version number for an event type.

        Args:
            event_type: The event type string

        Returns:
            Latest version number, or None if not found
        """
        return self._latest_versions.get(event_type)

    def __contains__(self, event_type: str) -> bool:
        """Check if event type is registered."""
        return event_type in self._events

    def __len__(self) -> int:
        """Get total number of registered event types."""
        return len(self._events)

    def clear(self) -> None:
        """Clear all registrations (mainly for testing)."""
        self._events.clear()
        self._latest_versions.clear()


# Global registry instance
event_registry = EventRegistry()


__all__ = ["EventRegistry", "event_registry"]
