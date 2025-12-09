"""Message broker dependencies for FastAPI route handlers.

This module provides FastAPI-compatible dependencies for accessing the
RabbitMQ message broker using FastStream.

Usage:
    from example_service.core.dependencies.messaging import (
        MessageBroker,
        OptionalMessageBroker,
        get_message_broker,
    )

    @router.post("/events")
    async def publish_event(
        data: EventData,
        broker: MessageBroker,
    ):
        await broker.publish(message=data, exchange=DOMAIN_EVENTS_EXCHANGE)
        return {"status": "published"}

    @router.post("/events/optional")
    async def publish_event_optional(
        data: EventData,
        broker: OptionalMessageBroker,
    ):
        if broker is None:
            # Queue for later or handle gracefully
            return {"status": "queued_for_later"}
        await broker.publish(message=data, exchange=DOMAIN_EVENTS_EXCHANGE)
        return {"status": "published"}
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, HTTPException, status

if TYPE_CHECKING:
    from faststream.rabbit import RabbitBroker


def get_message_broker() -> RabbitBroker | None:
    """Get the RabbitMQ message broker instance.

    This is a thin wrapper that retrieves the global message broker
    singleton. The import is deferred to runtime to avoid circular
    dependencies.

    Returns:
        RabbitBroker | None: The broker instance, or None if not initialized.
    """
    from example_service.infra.messaging import get_broker

    return get_broker()


async def require_message_broker(
    broker: Annotated[RabbitBroker | None, Depends(get_message_broker)],
) -> RabbitBroker:
    """Dependency that requires message broker to be available.

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

    Use this dependency when the message broker is optional for the endpoint.
    Returns None if the broker is not available, allowing fallback behavior.

    Args:
        broker: Injected broker from get_message_broker

    Returns:
        RabbitBroker | None: The broker if available, None otherwise
    """
    return broker


# Type aliases for cleaner route signatures
MessageBroker = Annotated[RabbitBroker, Depends(require_message_broker)]
"""Message broker dependency that requires broker to be available.

This type alias enforces that the message broker must be connected
and ready. Raises HTTP 503 if unavailable.

Example:
    @router.post("/publish")
    async def publish(data: dict, broker: MessageBroker):
        await broker.publish(data, exchange=DOMAIN_EVENTS_EXCHANGE)
"""

OptionalMessageBroker = Annotated[RabbitBroker | None, Depends(optional_message_broker)]
"""Message broker dependency that is optional.

This type alias allows graceful degradation when the message broker
is unavailable. Returns None if not connected.

Example:
    @router.post("/publish")
    async def publish(data: dict, broker: OptionalMessageBroker):
        if broker is None:
            # Store in outbox for later delivery
            return {"status": "queued"}
        await broker.publish(data, exchange=DOMAIN_EVENTS_EXCHANGE)
"""


__all__ = [
    "MessageBroker",
    "OptionalMessageBroker",
    "get_message_broker",
    "optional_message_broker",
    "require_message_broker",
]
