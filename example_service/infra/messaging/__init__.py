"""Message broker infrastructure for event-driven communication.

This module provides RabbitMQ message broker integration using FastStream:

- Broker: Message broker connection management with health checks
- Handlers: Event subscribers with automatic tracing and retry support
- Events: Event schema definitions
- Exchanges: Exchange and queue definitions with DLQ configuration
- Conventions: Naming conventions for exchanges, queues, and routing keys
- Middleware: Supplementary tracing utilities

Features:
    - Dead Letter Queue (DLQ) support for failed messages
    - Explicit exchange management with routing keys
    - Retry patterns using utils.retry decorator
    - Connection state tracking and health checks
    - Comprehensive examples and patterns

OpenTelemetry Tracing:
    When OTel is enabled, all handlers are automatically traced via
    FastStream's RabbitTelemetryMiddleware (configured in broker.py).
    Use add_message_span_attributes/add_message_span_event to add
    custom span data within handlers.

Retry and DLQ:
    Use the retry decorator from utils.retry for transient error handling.
    After max retries, messages automatically route to DLQ based on queue
    configuration. See examples/retry_patterns.py and examples/dlq_patterns.py.
"""

from __future__ import annotations

from example_service.infra.messaging.broker import (
    broker,
    check_broker_health,
    get_broker,
    get_router,
)
from example_service.infra.messaging.conventions import (
    DLQ_EXCHANGE_NAME,
    DOMAIN_EVENTS_EXCHANGE_NAME,
    get_queue_name,
    get_routing_key,
    get_routing_key_pattern,
)
from example_service.infra.messaging.exchanges import (
    DLQ_EXCHANGE,
    DLQ_QUEUE,
    DOMAIN_EVENTS_EXCHANGE,
    EXAMPLE_EVENTS_QUEUE,
    create_queue_with_dlq,
)
from example_service.infra.messaging.middleware import (
    add_message_span_attributes,
    add_message_span_event,
    traced_handler,
)

__all__ = [
    # Broker
    "broker",
    "get_broker",
    "get_router",
    "check_broker_health",
    # Exchanges and Queues
    "DOMAIN_EVENTS_EXCHANGE",
    "DLQ_EXCHANGE",
    "DLQ_QUEUE",
    "EXAMPLE_EVENTS_QUEUE",
    "create_queue_with_dlq",
    # Conventions
    "DOMAIN_EVENTS_EXCHANGE_NAME",
    "DLQ_EXCHANGE_NAME",
    "get_queue_name",
    "get_routing_key",
    "get_routing_key_pattern",
    # Tracing utilities
    "traced_handler",
    "add_message_span_attributes",
    "add_message_span_event",
]
