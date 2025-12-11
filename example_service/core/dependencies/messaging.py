"""Message bus publisher dependency.

This module provides FastAPI-compatible dependencies for publishing messages
to RabbitMQ via FastStream. It uses the Protocol pattern for loose coupling
and testability.

Features:
    - Protocol-based abstraction for easy testing and broker swapping
    - HTTP-aware error handling for endpoints that require messaging
    - Graceful degradation for optional messaging scenarios
    - Type-safe dependency injection via Annotated types

Usage:
    # Basic publisher - check is_configured before use
    from example_service.core.dependencies.messaging import BusPublisherDep

    @router.post("/users")
    async def create_user(
        data: UserCreate,
        bus: BusPublisherDep,
    ):
        user = await create_user_in_db(data)
        if bus.is_configured:
            await bus.publish(
                {"event": "user.created", "user_id": user.id},
                exchange="domain.events",
                routing_key="users.created",
            )
        return user

    # Required publisher - raises HTTP 503 if unavailable
    from example_service.core.dependencies.messaging import RequiredBusPublisher

    @router.post("/notifications")
    async def send_notification(
        data: NotificationData,
        bus: RequiredBusPublisher,
    ):
        # No need to check is_configured - guaranteed to be ready
        await bus.publish(
            data.model_dump(),
            exchange="notifications",
            routing_key="notifications.email",
        )
        return {"status": "sent"}
"""

from __future__ import annotations

from typing import Annotated, Any, Protocol, runtime_checkable

from fastapi import Depends, HTTPException, status
from faststream.rabbit import RabbitBroker


@runtime_checkable
class BusPublisher(Protocol):
    """Protocol for message bus publishers.

    This protocol defines the interface for publishing messages to a message bus.
    The default implementation uses RabbitMQ via FastStream, but this abstraction
    allows for easy testing and alternative implementations.

    The protocol uses structural subtyping (PEP 544), so any class implementing
    these methods will satisfy the protocol without explicit inheritance.
    """

    @property
    def is_configured(self) -> bool:
        """Check if the publisher is properly configured and ready to use.

        Returns:
            True if the publisher is configured and connected, False otherwise
        """
        ...

    async def publish(
        self,
        message: dict[str, Any] | bytes | str,
        *,
        exchange: str | None = None,
        routing_key: str | None = None,
        queue: str | None = None,
        headers: dict[str, str] | None = None,
        correlation_id: str | None = None,
        reply_to: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Publish a message to the bus.

        Args:
            message: The message payload (dict, bytes, or string)
            exchange: Target exchange name
            routing_key: Message routing key for exchange routing
            queue: Target queue name (alternative to exchange/routing_key)
            headers: Message headers for metadata
            correlation_id: Correlation ID for request-response patterns
            reply_to: Reply queue for request-response patterns
            **kwargs: Additional broker-specific options

        Note:
            If the publisher is not configured (is_configured=False), this
            method may silently no-op or raise an exception depending on
            the implementation.
        """
        ...


class RabbitBusPublisher:
    """RabbitMQ message bus publisher implementation.

    Wraps a FastStream RabbitBroker to provide the BusPublisher protocol interface.
    This implementation provides graceful degradation when the broker is not
    configured or connected.
    """

    def __init__(self, broker: RabbitBroker | None) -> None:
        """Initialize the publisher with a RabbitMQ broker.

        Args:
            broker: FastStream RabbitBroker instance, or None if not configured
        """
        self._broker = broker

    @property
    def is_configured(self) -> bool:
        """Check if the broker is configured and connected.

        Returns:
            True if broker exists and is running, False otherwise
        """
        if self._broker is None:
            return False
        return hasattr(self._broker, "running") and self._broker.running

    async def publish(
        self,
        message: dict[str, Any] | bytes | str,
        *,
        exchange: str | None = None,
        routing_key: str | None = None,
        queue: str | None = None,
        headers: dict[str, str] | None = None,
        correlation_id: str | None = None,
        reply_to: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Publish a message to RabbitMQ.

        Args:
            message: The message payload (dict, bytes, or string)
            exchange: Target exchange name
            routing_key: Message routing key for exchange routing
            queue: Target queue name (alternative to exchange/routing_key)
            headers: Message headers for metadata
            correlation_id: Correlation ID for request-response patterns
            reply_to: Reply queue for request-response patterns
            **kwargs: Additional broker-specific options (e.g., priority, expiration)

        Note:
            If the broker is not configured, this method silently no-ops.
            This enables graceful degradation in optional messaging scenarios.
        """
        if not self.is_configured:
            return

        await self._broker.publish(
            message,
            exchange=exchange,
            routing_key=routing_key,
            queue=queue,
            headers=headers,
            correlation_id=correlation_id,
            reply_to=reply_to,
            **kwargs,
        )


async def get_bus_publisher() -> BusPublisher:
    """Get the message bus publisher.

    This dependency provides access to the message bus for publishing events.
    If RabbitMQ is not configured, a RabbitBusPublisher with None broker is
    returned, which gracefully degrades (is_configured returns False and
    publish() becomes a no-op).

    Returns:
        BusPublisher instance (RabbitBusPublisher)

    Example:
        @router.post("/users")
        async def create_user(
            bus: Annotated[BusPublisher, Depends(get_bus_publisher)],
        ):
            user = await create_user_in_db()
            if bus.is_configured:
                await bus.publish(
                    {"event": "user.created", "user_id": user.id},
                    exchange="domain.events",
                    routing_key="users.created",
                )
            return user
    """
    from example_service.infra.messaging.broker import broker

    return RabbitBusPublisher(broker)


async def require_bus_publisher(
    bus: Annotated[BusPublisher, Depends(get_bus_publisher)],
) -> BusPublisher:
    """Dependency that requires message bus to be available.

    Use this dependency when the message bus is required for the endpoint
    to function. Automatically raises HTTP 503 if the bus is not configured.

    Args:
        bus: Injected bus publisher from get_bus_publisher

    Returns:
        BusPublisher: The configured publisher instance

    Raises:
        HTTPException: 503 Service Unavailable if bus is not configured

    Example:
        @router.post("/notifications")
        async def send_notification(
            bus: RequiredBusPublisher,  # Raises 503 if unavailable
            data: NotificationData,
        ):
            await bus.publish(
                data.model_dump(),
                exchange="notifications",
                routing_key="notifications.email",
            )
            return {"status": "sent"}
    """
    if not bus.is_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "messaging_unavailable",
                "message": "Message bus is not available",
            },
        )
    return bus


# Type aliases for dependency injection
BusPublisherDep = Annotated[BusPublisher, Depends(get_bus_publisher)]
"""Message bus publisher dependency (may or may not be configured).

Returns a BusPublisher that gracefully degrades when unavailable.
Always check `is_configured` before publishing to handle unconfigured state.

Example:
    @router.post("/users")
    async def create_user(
        data: UserCreate,
        bus: BusPublisherDep,
    ):
        user = await create_user_in_db(data)
        if bus.is_configured:
            await bus.publish(
                {"event": "user.created", "user_id": user.id},
                exchange="domain.events",
            )
        return user
"""

RequiredBusPublisher = Annotated[BusPublisher, Depends(require_bus_publisher)]
"""Message bus dependency that MUST be configured.

Raises HTTP 503 if the bus is unavailable. Use when messaging is critical
to the endpoint's functionality.

Example:
    @router.post("/notifications")
    async def send_notification(
        data: NotificationData,
        bus: RequiredBusPublisher,  # Guaranteed to be configured
    ):
        # No need to check is_configured
        await bus.publish(
            data.model_dump(),
            exchange="notifications",
            routing_key="notifications.email",
        )
        return {"status": "sent"}
"""


# Backward compatibility aliases
# These maintain the old API while using the new Protocol-based implementation


def get_message_broker() -> RabbitBroker | None:
    """Get the RabbitMQ message broker instance.

    DEPRECATED: Use get_bus_publisher() instead for Protocol-based abstraction.

    This is a thin wrapper that retrieves the global message broker singleton.
    Kept for backward compatibility with existing code.

    Returns:
        RabbitBroker | None: The broker instance, or None if not initialized.
    """
    from example_service.infra.messaging.broker import broker as rabbit_broker

    return rabbit_broker


async def require_message_broker(
    broker: Annotated[RabbitBroker | None, Depends(get_message_broker)],
) -> RabbitBroker:
    """Dependency that requires message broker to be available.

    DEPRECATED: Use BusPublisherDep instead for Protocol-based abstraction.

    Use this dependency when the message broker is required for the endpoint
    to function. Automatically raises HTTP 503 if the broker is not available.

    Args:
        broker: Injected broker from get_message_broker

    Returns:
        RabbitBroker: The connected broker instance

    Raises:
        HTTPException: 503 Service Unavailable if broker is not available
    """
    if broker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "broker_unavailable",
                "message": "Message broker is not available",
            },
        )
    return broker


async def optional_message_broker(
    broker: Annotated[RabbitBroker | None, Depends(get_message_broker)],
) -> RabbitBroker | None:
    """Dependency that optionally provides message broker.

    DEPRECATED: Use BusPublisherDep instead for Protocol-based abstraction.

    Use this dependency when the message broker is optional for the endpoint.
    Returns None if the broker is not available, allowing fallback behavior.

    Args:
        broker: Injected broker from get_message_broker

    Returns:
        RabbitBroker | None: The broker if available, None otherwise
    """
    return broker


MessageBroker = Annotated[RabbitBroker, Depends(require_message_broker)]
"""DEPRECATED: Use RequiredBusPublisher instead.

Message broker dependency that requires broker to be available.
Raises HTTP 503 if unavailable.
"""

OptionalMessageBroker = Annotated[RabbitBroker | None, Depends(optional_message_broker)]
"""DEPRECATED: Use BusPublisherDep instead.

Message broker dependency that is optional.
Returns None if not connected.
"""


__all__ = [
    # New Protocol-based API (recommended)
    "BusPublisher",
    "BusPublisherDep",
    # Legacy API (backward compatibility)
    "MessageBroker",
    "OptionalMessageBroker",
    "RabbitBusPublisher",
    "RequiredBusPublisher",
    "get_bus_publisher",
    "get_message_broker",
    "optional_message_broker",
    "require_bus_publisher",
    "require_message_broker",
]
