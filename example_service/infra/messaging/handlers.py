"""Message handlers for consuming events from the broker.

This module contains subscribers that listen to specific queues
and process incoming messages. Handlers are registered with the
RabbitRouter for automatic AsyncAPI documentation.

All handlers use:
- Explicit exchanges with routing keys for flexible message routing
- Retry decorators from utils.retry for transient error handling
- DLQ configuration for permanent failures

AsyncAPI Documentation:
    All handlers defined here will appear in the AsyncAPI docs at /asyncapi
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from example_service.infra.messaging.broker import router
from example_service.infra.messaging.exchanges import (
    DLQ_EXCHANGE,
    DLQ_QUEUE,
    DOMAIN_EVENTS_EXCHANGE,
    EXAMPLE_EVENTS_QUEUE,
    create_queue_with_dlq,
)
from example_service.utils.retry import retry

if TYPE_CHECKING:
    from example_service.infra.messaging.events import (
        ExampleCreatedEvent,
        ExampleDeletedEvent,
        ExampleUpdatedEvent,
    )

logger = logging.getLogger(__name__)

# Echo service queues for demonstrating message bus round-trips
ECHO_SERVICE_QUEUE = create_queue_with_dlq("echo-service")
ECHO_RESPONSE_QUEUE = create_queue_with_dlq("echo-response")

# Only define handlers if router is available (for AsyncAPI documentation)
if router is not None:

    @router.subscriber(
        EXAMPLE_EVENTS_QUEUE,
        exchange=DOMAIN_EVENTS_EXCHANGE,
    )
    @retry(max_attempts=3, initial_delay=1.0, max_delay=10.0)
    async def handle_example_created(event: ExampleCreatedEvent) -> None:
        """Handle example.created events.

        This handler is called whenever an ExampleCreatedEvent is published
        to the example-events queue.

        Features:
        - Uses explicit exchange (DOMAIN_EVENTS_EXCHANGE) with routing key
        - Retry decorator handles transient errors (max 3 attempts)
        - Permanent failures route to DLQ via queue configuration
        - Automatic tracing via RabbitTelemetryMiddleware

        Args:
            event: The created event data.

        Note:
            If all retry attempts fail, the message will be routed to DLQ
            based on the queue's x-dead-letter-exchange configuration.
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

    @router.subscriber(
        EXAMPLE_EVENTS_QUEUE,
        exchange=DOMAIN_EVENTS_EXCHANGE,
    )
    @retry(max_attempts=3, initial_delay=1.0, max_delay=10.0)
    async def handle_example_updated(event: ExampleUpdatedEvent) -> None:
        """Handle example.updated events.

        Features:
        - Uses explicit exchange with routing key
        - Retry decorator for transient errors
        - DLQ routing for permanent failures

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

    @router.subscriber(
        EXAMPLE_EVENTS_QUEUE,
        exchange=DOMAIN_EVENTS_EXCHANGE,
    )
    @retry(max_attempts=3, initial_delay=1.0, max_delay=10.0)
    async def handle_example_deleted(event: ExampleDeletedEvent) -> None:
        """Handle example.deleted events.

        Features:
        - Uses explicit exchange with routing key
        - Retry decorator for transient errors
        - DLQ routing for permanent failures

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
        ECHO_SERVICE_QUEUE,
        exchange=DOMAIN_EVENTS_EXCHANGE,
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
        ECHO_RESPONSE_QUEUE,
        exchange=DOMAIN_EVENTS_EXCHANGE,
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

    # =========================================================================
    # DLQ Handler
    # =========================================================================
    # Handler for monitoring and processing Dead Letter Queue messages

    @router.subscriber(
        DLQ_QUEUE,
        exchange=DLQ_EXCHANGE,
    )
    async def handle_dlq_message(message: dict) -> None:
        """Handle messages from the Dead Letter Queue.

        This handler processes messages that have failed processing after
        all retry attempts. Use this for:
        - Monitoring DLQ message counts
        - Alerting on DLQ conditions
        - Logging failure reasons
        - Manual message inspection

        Args:
            message: DLQ message with failure metadata in headers.

        Note:
            DLQ messages include headers with failure information:
            - x-original-queue: Original queue name
            - x-original-routing-key: Original routing key
            - x-retry-count: Number of retry attempts
            - x-final-error: Final error message
            - x-traceback: Error traceback (if available)

        Example:
            This handler is automatically registered and will receive all
            messages that fail processing after max retries. Configure
            alerting based on DLQ message volume.
        """
        # Extract DLQ metadata from headers
        # Note: In FastStream, message headers are available via the message object
        # For dict messages, headers may be in the message itself or passed separately
        headers = message.get("headers", {})
        original_queue = headers.get("x-original-queue", "unknown")
        retry_count = headers.get("x-retry-count", 0)
        final_error = headers.get("x-final-error", "unknown")

        logger.error(
            "DLQ message received",
            extra={
                "original_queue": original_queue,
                "retry_count": retry_count,
                "final_error": final_error,
                "message_body": message,
            },
        )

        # TODO: Implement DLQ processing logic:
        # - Send alerts (email, Slack, PagerDuty)
        # - Log to external monitoring system
        # - Store in database for analysis
        # - Trigger manual review workflow
