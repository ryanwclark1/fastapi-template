"""Message broker infrastructure for event-driven communication.

This module provides RabbitMQ message broker integration using FastStream:

- Broker: Message broker connection management
- Handlers: Event subscribers with automatic tracing
- Events: Event schema definitions
- Middleware: Supplementary tracing utilities

OpenTelemetry Tracing:
    When OTel is enabled, all handlers are automatically traced via
    FastStream's RabbitTelemetryMiddleware (configured in broker.py).
    Use add_message_span_attributes/add_message_span_event to add
    custom span data within handlers.
"""

from __future__ import annotations

from example_service.infra.messaging.broker import broker, get_broker
from example_service.infra.messaging.middleware import (
    add_message_span_attributes,
    add_message_span_event,
    traced_handler,
)

__all__ = [
    "broker",
    "get_broker",
    # Tracing utilities
    "traced_handler",
    "add_message_span_attributes",
    "add_message_span_event",
]
