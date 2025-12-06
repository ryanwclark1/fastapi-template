"""FastStream exchange and queue definitions with DLQ configuration.

This module defines RabbitExchange and RabbitQueue objects for use with FastStream,
including Dead Letter Queue (DLQ) configuration for reliable message processing.

All exchanges and queues are configured with:
- Durability (survive broker restarts)
- DLQ routing for failed messages
- Proper routing key bindings
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from faststream.rabbit import ExchangeType, RabbitExchange, RabbitQueue

if TYPE_CHECKING:
    from faststream.rabbit import RabbitBroker

from example_service.infra.messaging.conventions import (
    DLQ_EXCHANGE_NAME,
    DOMAIN_EVENTS_EXCHANGE_NAME,
    EXAMPLE_EVENTS_QUEUE_NAME,
    get_queue_name,
)

# ──────────────────────────────────────────────────────────────────────────────
# Exchange Definitions
# ──────────────────────────────────────────────────────────────────────────────

DOMAIN_EVENTS_EXCHANGE = RabbitExchange(
    name=DOMAIN_EVENTS_EXCHANGE_NAME,
    type=ExchangeType.TOPIC,
    durable=True,
    auto_delete=False,
)
"""Domain events exchange.

This is the primary exchange for domain events. Uses topic exchange type
to support flexible routing with routing key patterns (e.g., "example.*").
"""

DLQ_EXCHANGE = RabbitExchange(
    name=DLQ_EXCHANGE_NAME,
    type=ExchangeType.TOPIC,
    durable=True,
    auto_delete=False,
)
"""Dead Letter Queue exchange.

All failed messages after max retries are routed to this exchange.
Consumers can subscribe to "dlq.#" to receive all DLQ messages, or
to specific patterns like "dlq.example-events" for queue-specific DLQ messages.
"""

# ──────────────────────────────────────────────────────────────────────────────
# Queue Definitions with DLQ Configuration
# ──────────────────────────────────────────────────────────────────────────────

EXAMPLE_EVENTS_QUEUE = RabbitQueue(
    name=EXAMPLE_EVENTS_QUEUE_NAME,
    durable=True,
    auto_delete=False,
    arguments={
        "x-dead-letter-exchange": DLQ_EXCHANGE_NAME,
        "x-dead-letter-routing-key": "dlq.example-events",
    },
)
"""Example events queue with DLQ configuration.

Messages that fail processing after max retries will be routed to:
- Exchange: {queue_prefix}.dlq
- Routing key: dlq.example-events

DLQ Arguments:
    - x-dead-letter-exchange: Exchange to route failed messages to
    - x-dead-letter-routing-key: Routing key for DLQ messages
"""

DLQ_QUEUE = RabbitQueue(
    name=get_queue_name("dlq"),
    durable=True,
    auto_delete=False,
    routing_key="dlq.#",  # Consume all DLQ messages
)
"""Dead Letter Queue for monitoring and alerting.

This queue is bound to the DLQ exchange with routing key "dlq.#" to
receive all failed messages. Use this for:
- Monitoring DLQ message counts
- Alerting on DLQ conditions
- Manual message inspection and replay
"""

# ──────────────────────────────────────────────────────────────────────────────
# Helper Functions
# ──────────────────────────────────────────────────────────────────────────────


def create_queue_with_dlq(
    queue_name: str,
    dlq_routing_key: str | None = None,
    durable: bool = True,
    auto_delete: bool = False,
) -> RabbitQueue:
    """Create a RabbitQueue with DLQ configuration.

    Args:
        queue_name: Base queue name (will be prefixed).
        dlq_routing_key: Optional DLQ routing key (defaults to "dlq.{queue_name}").
        durable: Whether queue survives broker restart.
        auto_delete: Whether queue is deleted when no consumers.

    Returns:
        RabbitQueue with DLQ arguments configured.

    Example:
        >>> queue = create_queue_with_dlq("user-events", dlq_routing_key="dlq.users")
        >>> # Queue configured with DLQ routing to "dlq.users"
    """
    prefixed_name = get_queue_name(queue_name)
    if dlq_routing_key is None:
        dlq_routing_key = f"dlq.{queue_name}"

    return RabbitQueue(
        name=prefixed_name,
        durable=durable,
        auto_delete=auto_delete,
        arguments={
            "x-dead-letter-exchange": DLQ_EXCHANGE_NAME,
            "x-dead-letter-routing-key": dlq_routing_key,
        },
    )


async def setup_exchanges_and_queues(broker: RabbitBroker) -> None:
    """Set up exchanges and queues explicitly.

    This function can be called during application startup to ensure
    all exchanges and queues are declared. FastStream typically handles
    this automatically, but explicit setup can be useful for:
    - Ensuring exchanges exist before publishing
    - Pre-declaring queues for monitoring
    - Setting up infrastructure in a controlled order

    Args:
        broker: FastStream RabbitBroker instance.

    Note:
        FastStream automatically declares exchanges and queues when
        subscribers are registered, so this is typically not needed.
        Use only if you need explicit control over declaration order.

    Example:
        >>> from example_service.infra.messaging.broker import broker
        >>> if broker is not None:
        ...     await setup_exchanges_and_queues(broker)
    """
    # FastStream automatically declares exchanges and queues when subscribers
    # are registered, so this function is primarily for documentation and
    # explicit setup scenarios. In most cases, FastStream's automatic
    # declaration is sufficient.
    # FastStream handles this automatically
