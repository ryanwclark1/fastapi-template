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

from datetime import UTC, datetime
import logging

from faststream.exceptions import SubscriberNotFound

from example_service.infra.messaging.broker import router
from example_service.infra.messaging.events import (
    ExampleCreatedEvent,
    ExampleDeletedEvent,
    ExampleUpdatedEvent,
)
from example_service.infra.messaging.exchanges import (
    DLQ_EXCHANGE,
    DLQ_QUEUE,
    DOMAIN_EVENTS_EXCHANGE,
    EXAMPLE_EVENTS_QUEUE,
    create_queue_with_dlq,
)
from example_service.utils.retry import retry

# Ensure all event models are fully rebuilt after import
# This is critical for FastStream's AsyncAPI schema generation
# which needs to introspect handler signatures
ExampleCreatedEvent.model_rebuild()
ExampleUpdatedEvent.model_rebuild()
ExampleDeletedEvent.model_rebuild()

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
            # Extract and validate entity data
            entity_id = event.data.get("id")
            entity_name = event.data.get("name")

            if not entity_id:
                msg = "Missing required field 'id' in event data"
                raise ValueError(msg)

            # Example: Persist to cache or trigger downstream processing
            # In a real application, you might:
            # - Update a read model/projection
            # - Invalidate relevant caches
            # - Trigger notifications
            # - Sync with external systems
            logger.info(
                "Entity created - updating projections",
                extra={
                    "event_id": event.event_id,
                    "entity_id": entity_id,
                    "entity_name": entity_name,
                },
            )

            # Emit metrics for observability
            # from example_service.infra.metrics.prometheus import REGISTRY
            # entity_created_counter.labels(entity_type="example").inc()

            logger.info(
                "Successfully processed example.created event",
                extra={"event_id": event.event_id, "entity_id": entity_id},
            )
        except ValueError as e:
            # Validation errors are permanent failures - don't retry
            logger.error(
                "Validation failed for example.created event",
                extra={"event_id": event.event_id, "error": str(e)},
            )
            raise
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
            # Extract update information
            entity_id = event.data.get("id")
            changes = event.data.get("changes", {})

            if not entity_id:
                msg = "Missing required field 'id' in event data"
                raise ValueError(msg)

            # Example: Apply changes to read model
            # In a real application, you might:
            # - Update cached projections
            # - Propagate changes to search index
            # - Notify subscribers of changes
            changed_fields = list(changes.keys()) if isinstance(changes, dict) else []
            logger.info(
                "Entity updated - applying changes to projections",
                extra={
                    "event_id": event.event_id,
                    "entity_id": entity_id,
                    "changed_fields": changed_fields,
                },
            )

            logger.info(
                "Successfully processed example.updated event",
                extra={"event_id": event.event_id, "entity_id": entity_id},
            )
        except ValueError as e:
            logger.error(
                "Validation failed for example.updated event",
                extra={"event_id": event.event_id, "error": str(e)},
            )
            raise
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
            # Extract entity identifier
            entity_id = event.data.get("id")

            if not entity_id:
                msg = "Missing required field 'id' in event data"
                raise ValueError(msg)

            # Example: Clean up related resources
            # In a real application, you might:
            # - Remove from search index
            # - Invalidate caches
            # - Clean up related storage (files, etc.)
            # - Archive audit trail
            logger.info(
                "Entity deleted - cleaning up projections and related resources",
                extra={
                    "event_id": event.event_id,
                    "entity_id": entity_id,
                },
            )

            logger.info(
                "Successfully processed example.deleted event",
                extra={"event_id": event.event_id, "entity_id": entity_id},
            )
        except ValueError as e:
            logger.error(
                "Validation failed for example.deleted event",
                extra={"event_id": event.event_id, "error": str(e)},
            )
            raise
        except Exception as e:
            logger.exception(
                "Failed to process example.deleted event",
                extra={"event_id": event.event_id, "error": str(e)},
            )
            raise

    # Resolve forward annotations to concrete types for FastStream schema generation
    # Pydantic v2 needs real types (not forward-ref strings) when building models
    # from handler signatures for AsyncAPI docs.
    from typing import get_type_hints

    def _resolve_annotations(func: object) -> None:
        target = getattr(func, "_original_call", func)
        if not hasattr(target, "__annotations__"):
            return
        try:
            hints = get_type_hints(target, globalns=globals(), localns=locals())
            target.__annotations__.update(hints)
        except Exception:
            # Best-effort; schema generation will skip unresolved funcs
            return

    for _fn in (
        "handle_example_created",
        "handle_example_updated",
        "handle_example_deleted",
        "handle_echo_request",
        "handle_echo_response",
    ):
        _func = locals().get(_fn)
        if _func:
            _resolve_annotations(_func)

    # =========================================================================
    # Echo Service Handlers
    # =========================================================================
    # Demonstrates message bus communication with a simple echo pattern.
    # Messages sent to echo-service queue are logged and republished.

    @router.subscriber(
        ECHO_SERVICE_QUEUE,
        exchange=DOMAIN_EVENTS_EXCHANGE,
    )
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

        if router is not None and router.broker is not None:
            try:
                await router.broker.publish(
                    echo_response,
                    queue=ECHO_RESPONSE_QUEUE,
                    exchange=DOMAIN_EVENTS_EXCHANGE,
                )
            except SubscriberNotFound:
                logger.warning(
                    "No subscribers registered for echo responses, processing inline",
                    extra={"response_queue": ECHO_RESPONSE_QUEUE},
                )
                await handle_echo_response(echo_response)
        else:
            await handle_echo_response(echo_response)

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

    from example_service.infra.messaging.dlq.alerting import get_dlq_alerter

    @router.subscriber(
        DLQ_QUEUE,
        exchange=DLQ_EXCHANGE,
    )
    async def handle_dlq_message(message: dict) -> None:
        """Handle messages from the Dead Letter Queue.

        This handler processes messages that have failed processing after
        all retry attempts. It provides:
        - Structured logging of failure details
        - Alerting via configured channels (email, webhook, log)
        - Prometheus metrics for monitoring
        - Message inspection for debugging

        Args:
            message: DLQ message with failure metadata in headers.

        Note:
            DLQ messages include headers with failure information:
            - x-original-queue: Original queue name
            - x-original-routing-key: Original routing key
            - x-retry-count: Number of retry attempts
            - x-final-error: Final error message
            - x-final-error-type: Exception class name
            - x-traceback: Error traceback (if available)

        Example:
            This handler is automatically registered and will receive all
            messages that fail processing after max retries. Configure
            alerting via environment variables or settings:
            - DLQ_ALERTS_ENABLED=true
            - DLQ_ALERT_EMAIL=ops@example.com
            - DLQ_WEBHOOK_URL=https://hooks.slack.com/...
        """
        # Extract DLQ metadata from headers
        headers = message.get("headers", {})
        original_queue = headers.get("x-original-queue", "unknown")
        original_routing_key = headers.get("x-original-routing-key", "")
        retry_count = headers.get("x-retry-count", 0)
        final_error = headers.get("x-final-error", "unknown")
        final_error_type = headers.get("x-final-error-type", "Exception")
        traceback_str = headers.get("x-traceback", "")

        # Structured logging for observability
        logger.error(
            "DLQ message received - message failed after max retries",
            extra={
                "original_queue": original_queue,
                "original_routing_key": original_routing_key,
                "retry_count": retry_count,
                "final_error": final_error,
                "final_error_type": final_error_type,
                "message_body": message,
                "has_traceback": bool(traceback_str),
            },
        )

        # Send alert via configured channels
        alerter = get_dlq_alerter()
        await alerter.alert_dlq_message(
            original_queue=original_queue,
            error_type=final_error_type,
            error_message=final_error,
            retry_count=retry_count if isinstance(retry_count, int) else 0,
            message_body=message,
            metadata={
                "original_routing_key": original_routing_key,
                "has_traceback": bool(traceback_str),
            },
        )

        # Record metrics for monitoring dashboards
        try:
            from example_service.infra.messaging.dlq.metrics import record_dlq_routing

            record_dlq_routing(
                queue=original_queue,
                reason=final_error_type,
            )
        except Exception as e:
            logger.debug(
                "Failed to record DLQ routing metrics: %s", str(e)
            )  # Metrics are best-effort
