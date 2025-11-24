"""Message handlers for consuming events from the broker.

This module contains subscribers that listen to specific queues
and process incoming messages.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from faststream.rabbit import RabbitQueue

from example_service.core.settings import get_rabbit_settings
from example_service.infra.messaging.broker import broker
from example_service.infra.messaging.events import (
    ExampleCreatedEvent,
    ExampleDeletedEvent,
    ExampleUpdatedEvent,
)

if TYPE_CHECKING:
    from faststream import Context

logger = logging.getLogger(__name__)

# Get RabbitMQ settings from modular configuration
rabbit_settings = get_rabbit_settings()

# Define queues with prefixes for multi-environment support
EXAMPLE_EVENTS_QUEUE = rabbit_settings.get_prefixed_queue("example-events")


@broker.subscriber(
    RabbitQueue(
        EXAMPLE_EVENTS_QUEUE,
        durable=True,  # Survive broker restarts
        auto_delete=False,  # Don't delete when no consumers
    )
)
async def handle_example_created(
    event: ExampleCreatedEvent,
    message: Context = Context("message"),
) -> None:
    """Handle example.created events.

    This handler is called whenever an ExampleCreatedEvent is published
    to the example-events queue.

    Args:
        event: The created event data.
        message: FastStream message context for ack/nack operations.

    Example:
        The event will be automatically acknowledged if this function
        completes successfully. If an exception is raised, it will be
        nack'd and potentially requeued based on the broker configuration.
    """
    logger.info(
        "Processing example.created event",
        extra={
            "event_id": event.event_id,
            "event_type": event.event_type,
            "data": event.data,
        },
    )

    try:
        # TODO: Implement your business logic here
        # For example:
        # - Store in database
        # - Update cache
        # - Call external service
        # - Trigger another event

        logger.info(
            "Successfully processed example.created event",
            extra={"event_id": event.event_id},
        )
    except Exception as e:
        logger.exception(
            "Failed to process example.created event",
            extra={"event_id": event.event_id, "error": str(e)},
        )
        # Re-raise to trigger message requeue
        raise


@broker.subscriber(RabbitQueue(EXAMPLE_EVENTS_QUEUE, durable=True))
async def handle_example_updated(event: ExampleUpdatedEvent) -> None:
    """Handle example.updated events.

    Args:
        event: The updated event data.
    """
    logger.info(
        "Processing example.updated event",
        extra={
            "event_id": event.event_id,
            "event_type": event.event_type,
            "data": event.data,
        },
    )

    try:
        # TODO: Implement your business logic here
        logger.info(
            "Successfully processed example.updated event",
            extra={"event_id": event.event_id},
        )
    except Exception as e:
        logger.exception(
            "Failed to process example.updated event",
            extra={"event_id": event.event_id, "error": str(e)},
        )
        raise


@broker.subscriber(RabbitQueue(EXAMPLE_EVENTS_QUEUE, durable=True))
async def handle_example_deleted(event: ExampleDeletedEvent) -> None:
    """Handle example.deleted events.

    Args:
        event: The deleted event data.
    """
    logger.info(
        "Processing example.deleted event",
        extra={
            "event_id": event.event_id,
            "event_type": event.event_type,
            "data": event.data,
        },
    )

    try:
        # TODO: Implement your business logic here
        logger.info(
            "Successfully processed example.deleted event",
            extra={"event_id": event.event_id},
        )
    except Exception as e:
        logger.exception(
            "Failed to process example.deleted event",
            extra={"event_id": event.event_id, "error": str(e)},
        )
        raise
