"""Exchange and routing key patterns for FastStream.

This module demonstrates various exchange patterns and routing key usage
with FastStream, including:
- Topic exchange with routing key patterns
- Direct exchange examples
- Fanout exchange examples
- Multiple queues bound to same exchange
- Exchange-to-exchange binding patterns

Reference FastStream documentation:
    https://faststream.ag2.ai/latest/getting-started/
"""

from __future__ import annotations

import logging
from typing import Any

from faststream.rabbit import ExchangeType, RabbitExchange, RabbitQueue

from example_service.infra.messaging.broker import router
from example_service.infra.messaging.conventions import (
    get_queue_name,
    get_routing_key,
    get_routing_key_pattern,
    get_tenant_routing_key_pattern,
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Topic Exchange Patterns
# ──────────────────────────────────────────────────────────────────────────────

# Topic exchanges support routing key patterns:
# - * (star) matches exactly one word
# - # (hash) matches zero or more words
# Examples:
#   "example.*" matches "example.created", "example.updated", but not "example.created.tenant-123"
#   "example.#" matches "example.created", "example.created.tenant-123", etc.
#   "example.*.tenant-123" matches "example.created.tenant-123", "example.updated.tenant-123"

if router is not None:
    # Example 1: Single routing key pattern
    @router.subscriber(
        RabbitQueue(
            get_queue_name("example-all-events"),
            durable=True,
            routing_key=get_routing_key_pattern("example"),  # "example.*"
        ),
        exchange=RabbitExchange(
            name="example-service",
            type=ExchangeType.TOPIC,
            durable=True,
        ),
    )
    async def handle_all_example_events(message: dict[str, Any]) -> None:  # noqa: ARG001
        """Handle all example events using routing key pattern.

        This handler receives all events matching "example.*":
        - example.created
        - example.updated
        - example.deleted
        - etc.

        Args:
            message: Event message dictionary.
        """
        event_type = message.get("event_type", "unknown")
        logger.info(
            "Received example event",
            extra={"event_type": event_type, "routing_pattern": "example.*"},
        )

    # Example 2: Tenant-specific routing
    @router.subscriber(
        RabbitQueue(
            get_queue_name("example-tenant-events"),
            durable=True,
            routing_key=get_tenant_routing_key_pattern(
                "example", "tenant-123"
            ),  # "example.*.tenant-123"
        ),
        exchange=RabbitExchange(
            name="example-service",
            type=ExchangeType.TOPIC,
            durable=True,
        ),
    )
    async def handle_tenant_example_events(message: dict[str, Any]) -> None:  # noqa: ARG001
        """Handle example events for a specific tenant.

        This handler receives events matching "example.*.tenant-123":
        - example.created.tenant-123
        - example.updated.tenant-123
        - etc.

        Args:
            message: Event message dictionary.
        """
        event_type = message.get("event_type", "unknown")
        logger.info(
            "Received tenant-specific example event",
            extra={
                "event_type": event_type,
                "tenant_id": "tenant-123",
                "routing_pattern": "example.*.tenant-123",
            },
        )

    # Example 3: Specific event type
    @router.subscriber(
        RabbitQueue(
            get_queue_name("example-created-only"),
            durable=True,
            routing_key=get_routing_key("example.created"),  # Exact match
        ),
        exchange=RabbitExchange(
            name="example-service",
            type=ExchangeType.TOPIC,
            durable=True,
        ),
    )
    async def handle_only_created_events(message: dict[str, Any]) -> None:  # noqa: ARG001
        """Handle only example.created events.

        This handler receives only events with routing key "example.created".

        Args:
            message: Event message dictionary.
        """
        logger.info("Received example.created event only")

    # ──────────────────────────────────────────────────────────────────────────────
    # Direct Exchange Patterns
    # ──────────────────────────────────────────────────────────────────────────────

    # Direct exchanges route messages based on exact routing key matches.
    # No pattern matching - routing key must match exactly.

    DIRECT_EXCHANGE = RabbitExchange(
        name=get_queue_name("direct-events"),
        type=ExchangeType.DIRECT,
        durable=True,
    )

    @router.subscriber(
        RabbitQueue(
            get_queue_name("direct-queue-1"),
            durable=True,
            routing_key="task.high-priority",  # Exact match required
        ),
        exchange=DIRECT_EXCHANGE,
    )
    async def handle_high_priority_tasks(message: dict[str, Any]) -> None:  # noqa: ARG001
        """Handle high-priority tasks via direct exchange.

        Direct exchange requires exact routing key match.
        Routing key "task.high-priority" must match exactly.

        Args:
            message: Task message dictionary.
        """
        logger.info("Processing high-priority task", extra={"routing_key": "task.high-priority"})

    # ──────────────────────────────────────────────────────────────────────────────
    # Fanout Exchange Patterns
    # ──────────────────────────────────────────────────────────────────────────────

    # Fanout exchanges broadcast messages to all bound queues.
    # Routing keys are ignored - all queues receive all messages.

    FANOUT_EXCHANGE = RabbitExchange(
        name=get_queue_name("broadcast-events"),
        type=ExchangeType.FANOUT,
        durable=True,
    )

    @router.subscriber(
        RabbitQueue(
            get_queue_name("broadcast-queue-1"),
            durable=True,
            # routing_key ignored for fanout
        ),
        exchange=FANOUT_EXCHANGE,
    )
    async def handle_broadcast_queue1(message: dict[str, Any]) -> None:  # noqa: ARG001
        """Handle broadcast messages in queue 1.

        Fanout exchange broadcasts to all bound queues.
        This queue receives all messages published to FANOUT_EXCHANGE.

        Args:
            message: Broadcast message dictionary.
        """
        logger.info("Broadcast queue 1 received message")

    @router.subscriber(
        RabbitQueue(
            get_queue_name("broadcast-queue-2"),
            durable=True,
            # routing_key ignored for fanout
        ),
        exchange=FANOUT_EXCHANGE,
    )
    async def handle_broadcast_queue2(message: dict[str, Any]) -> None:  # noqa: ARG001
        """Handle broadcast messages in queue 2.

        Both queue1 and queue2 receive the same messages
        when published to FANOUT_EXCHANGE.

        Args:
            message: Broadcast message dictionary.
        """
        logger.info("Broadcast queue 2 received message")

    # ──────────────────────────────────────────────────────────────────────────────
    # Multiple Queues, Same Exchange
    # ──────────────────────────────────────────────────────────────────────────────

    # Multiple queues can be bound to the same exchange with different routing keys.
    # This allows different consumers to receive different subsets of messages.

    SHARED_EXCHANGE = RabbitExchange(
        name=get_queue_name("shared-events"),
        type=ExchangeType.TOPIC,
        durable=True,
    )

    # Queue 1: Receives user events
    @router.subscriber(
        RabbitQueue(
            get_queue_name("user-events-consumer"),
            durable=True,
            routing_key="user.*",
        ),
        exchange=SHARED_EXCHANGE,
    )
    async def handle_user_events(message: dict[str, Any]) -> None:  # noqa: ARG001
        """Handle user events from shared exchange.

        Args:
            message: User event message dictionary.
        """
        logger.info("User events consumer received message")

    # Queue 2: Receives order events
    @router.subscriber(
        RabbitQueue(
            get_queue_name("order-events-consumer"),
            durable=True,
            routing_key="order.*",
        ),
        exchange=SHARED_EXCHANGE,
    )
    async def handle_order_events(message: dict[str, Any]) -> None:  # noqa: ARG001
        """Handle order events from shared exchange.

        Args:
            message: Order event message dictionary.
        """
        logger.info("Order events consumer received message")

    # ──────────────────────────────────────────────────────────────────────────────
    # Publishing Examples
    # ──────────────────────────────────────────────────────────────────────────────

    async def publish_to_topic_exchange(
        event_type: str,
        message: dict[str, Any],
        tenant_id: str | None = None,
    ) -> None:
        """Publish message to topic exchange with routing key.

        Args:
            event_type: Event type (e.g., "example.created").
            message: Message payload.
            tenant_id: Optional tenant ID for tenant-specific routing.

        Example:
            >>> await publish_to_topic_exchange(
            ...     "example.created",
            ...     {"id": "123"},
            ...     tenant_id="tenant-123"
            ... )
            >>> # Published with routing key: "example.created.tenant-123"
        """
        if router is None or router.broker is None:
            logger.warning("Broker not available")
            return

        routing_key = get_routing_key(event_type, tenant_id)

        await router.broker.publish(
            message=message,
            exchange=RabbitExchange(
                name="example-service",
                type=ExchangeType.TOPIC,
                durable=True,
            ),
            routing_key=routing_key,
        )

        logger.info(
            "Published to topic exchange",
            extra={"routing_key": routing_key, "event_type": event_type},
        )

    async def publish_to_fanout_exchange(message: dict[str, Any]) -> None:
        """Publish message to fanout exchange (broadcasts to all queues).

        Args:
            message: Message payload.

        Example:
            >>> await publish_to_fanout_exchange({"announcement": "System maintenance"})
            >>> # All queues bound to FANOUT_EXCHANGE receive this message
        """
        if router is None or router.broker is None:
            logger.warning("Broker not available")
            return

        await router.broker.publish(
            message=message,
            exchange=FANOUT_EXCHANGE,
            # routing_key ignored for fanout
        )

        logger.info("Published to fanout exchange (broadcast)")
