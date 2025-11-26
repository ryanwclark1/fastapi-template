"""Message handlers for consuming events from the broker.

This module contains subscribers that listen to specific queues
and process incoming messages. Handlers are registered with the
RabbitRouter for automatic AsyncAPI documentation.

AsyncAPI Documentation:
    All handlers defined here will appear in the AsyncAPI docs at /asyncapi
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from faststream.rabbit import RabbitQueue

from example_service.core.settings import get_rabbit_settings
from example_service.infra.messaging.broker import router
from example_service.infra.messaging.events import (
    ExampleCreatedEvent,
    ExampleDeletedEvent,
    ExampleUpdatedEvent,
)

logger = logging.getLogger(__name__)

# Get RabbitMQ settings from modular configuration
rabbit_settings = get_rabbit_settings()

# Define queues with prefixes for multi-environment support
EXAMPLE_EVENTS_QUEUE = rabbit_settings.get_prefixed_queue("example-events")

# Echo service queues for demonstrating message bus round-trips
ECHO_SERVICE_QUEUE = rabbit_settings.get_prefixed_queue("echo-service")
ECHO_RESPONSE_QUEUE = rabbit_settings.get_prefixed_queue("echo-response")

# Only define handlers if router is available (for AsyncAPI documentation)
if router is not None:

    @router.subscriber(
        RabbitQueue(
            EXAMPLE_EVENTS_QUEUE,
            durable=True,
            auto_delete=False,
        )
    )
    async def handle_example_created(event: ExampleCreatedEvent) -> None:
        """Handle example.created events.

        This handler is called whenever an ExampleCreatedEvent is published
        to the example-events queue.

        Args:
            event: The created event data.
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
            logger.info(
                "Successfully processed example.created event",
                extra={"event_id": event.event_id},
            )
        except Exception as e:
            logger.exception(
                "Failed to process example.created event",
                extra={"event_id": event.event_id, "error": str(e)},
            )
            raise

    @router.subscriber(RabbitQueue(EXAMPLE_EVENTS_QUEUE, durable=True))
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

    @router.subscriber(RabbitQueue(EXAMPLE_EVENTS_QUEUE, durable=True))
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

    # =========================================================================
    # Echo Service Handlers
    # =========================================================================
    # Demonstrates message bus communication with a simple echo pattern.
    # Messages sent to echo-service queue are logged and republished.

    @router.subscriber(
        RabbitQueue(ECHO_SERVICE_QUEUE, durable=True, auto_delete=False)
    )
    @router.publisher(ECHO_RESPONSE_QUEUE)
    async def handle_echo_request(message: dict) -> dict:
        """Echo service - receives message, logs it, returns with timestamp.

        Demonstrates:
        - Message consumption from queue
        - Message publishing via @router.publisher decorator
        - Request/response pattern over message bus

        Args:
            message: Any dict message sent to the echo-service queue.

        Returns:
            Echo response with original message and timestamp.
        """
        logger.info(
            "Echo service received message",
            extra={"payload": message},
        )

        # Create and return echo response (auto-published via @router.publisher)
        echo_response = {
            "original": message,
            "echo_timestamp": datetime.now(UTC).isoformat(),
            "service": "echo-service",
        }

        logger.info(
            "Echo response being published",
            extra={"response_queue": ECHO_RESPONSE_QUEUE},
        )

        return echo_response

    @router.subscriber(
        RabbitQueue(ECHO_RESPONSE_QUEUE, durable=True, auto_delete=False)
    )
    async def handle_echo_response(message: dict) -> None:
        """Log echo responses - completes the round-trip demonstration.

        This handler receives the echoed messages and logs them,
        completing the observable cycle for the heartbeat demo.

        Args:
            message: Echo response containing original message and timestamp.
        """
        original_event = message.get("original", {})
        event_type = original_event.get("event_type", "unknown")

        logger.info(
            "Echo response received",
            extra={
                "original_event_type": event_type,
                "echo_timestamp": message.get("echo_timestamp"),
                "service": message.get("service"),
            },
        )
