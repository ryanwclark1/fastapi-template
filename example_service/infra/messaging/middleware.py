"""OpenTelemetry tracing utilities for FastStream message handlers.

This module provides supplementary tracing utilities for FastStream handlers.
The primary tracing is handled by FastStream's built-in RabbitTelemetryMiddleware
(configured in broker.py), but these utilities provide:

1. @traced_handler() decorator - For selective per-handler tracing when you need
   more control than the broker-level middleware provides
2. add_message_span_attributes() - Add custom attributes within handler spans
3. add_message_span_event() - Add custom events within handler spans

Primary Tracing (Recommended):
    FastStream's RabbitTelemetryMiddleware is added to the broker in broker.py
    when OTel is enabled. This automatically traces all handlers with proper
    W3C trace context propagation.

Supplementary Usage:
    Use these utilities when you need to add custom span data or selectively
    trace specific handlers:

    from example_service.infra.messaging.middleware import (
        add_message_span_attributes,
        add_message_span_event,
    )

    @router.subscriber(queue)
    async def handle_order_created(event: OrderCreatedEvent) -> None:
        # Add custom attributes to the span created by TelemetryMiddleware
        add_message_span_attributes({
            "order.id": event.data["order_id"],
            "order.amount": event.data["amount"],
        })

        # Add event markers for key processing milestones
        add_message_span_event("order.validated")

        # ... handler logic ...

        add_message_span_event("order.processed")
"""

from __future__ import annotations

import logging
from functools import wraps
from typing import TYPE_CHECKING, Any, Callable, TypeVar

from opentelemetry import trace

from example_service.infra.tracing.opentelemetry import get_tracer

if TYPE_CHECKING:
    from example_service.infra.messaging.events import BaseEvent

logger = logging.getLogger(__name__)

# Module-level tracer for messaging operations
# Mirrors the pattern from tasks/middleware.py: get_tracer("taskiq.worker")
_tracer = get_tracer("faststream.messaging")

F = TypeVar("F", bound=Callable[..., Any])


def traced_handler(handler_name: str | None = None) -> Callable[[F], F]:
    """Decorator to add OpenTelemetry tracing to FastStream message handlers.

    This decorator mirrors the TracingMiddleware pattern from Taskiq,
    creating spans for each message processed by the handler.

    For each message, it:
    - Creates a span named "message.{handler_name}"
    - Sets span attributes for message.id, message.type, handler.name
    - Records exceptions if the handler fails
    - Properly ends the span on completion (via finally block)

    Args:
        handler_name: Optional custom name for the handler span.
                     If not provided, uses the function name.

    Returns:
        Decorated async function with tracing.

    Example:
        @router.subscriber(queue)
        @traced_handler()
        async def handle_example_created(event: ExampleCreatedEvent) -> None:
            # Handler logic - automatically traced
            ...

        @router.subscriber(queue)
        @traced_handler("custom-handler-name")
        async def my_handler(event: ExampleCreatedEvent) -> None:
            ...
    """

    def decorator(func: F) -> F:
        name = handler_name or func.__name__

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Extract event from args/kwargs for span attributes
            event = _extract_event(args, kwargs)

            # Build span attributes (mirrors task.id, task.name pattern from Taskiq)
            attributes: dict[str, Any] = {
                "handler.name": name,
            }

            if event is not None:
                attributes["message.id"] = str(
                    getattr(event, "event_id", "unknown")
                )
                attributes["message.type"] = str(
                    getattr(event, "event_type", "unknown")
                )
                # Include service name if available
                if hasattr(event, "service"):
                    attributes["message.service"] = str(event.service)

            # Create and start span (mirrors TracingMiddleware.pre_execute)
            span = _tracer.start_span(
                name=f"message.{name}",
                attributes=attributes,
            )

            try:
                result = await func(*args, **kwargs)
                span.set_attribute("message.status", "success")
                return result
            except Exception as e:
                # Record exception (mirrors TracingMiddleware.post_execute)
                span.record_exception(e)
                span.set_status(trace.Status(trace.StatusCode.ERROR))
                span.set_attribute("message.status", "failure")
                logger.error(
                    f"Handler {name} failed",
                    extra={
                        "handler_name": name,
                        "error": str(e),
                        "message_id": attributes.get("message.id"),
                    },
                    exc_info=True,
                )
                raise
            finally:
                # Always end span (mirrors Taskiq pattern - ensures no leaked spans)
                span.end()

        return wrapper  # type: ignore[return-value]

    return decorator


def _extract_event(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    """Extract the event object from handler arguments.

    Handles both positional and keyword argument patterns that FastStream
    handlers may use.

    Args:
        args: Positional arguments to handler.
        kwargs: Keyword arguments to handler.

    Returns:
        The event object if found, None otherwise.
    """
    # Check first positional arg (most common pattern)
    if args:
        first_arg = args[0]
        if hasattr(first_arg, "event_id"):
            return first_arg

    # Check common keyword argument names
    for key in ("event", "message", "msg"):
        if key in kwargs and hasattr(kwargs[key], "event_id"):
            return kwargs[key]

    # Check any kwarg that looks like an event
    for value in kwargs.values():
        if hasattr(value, "event_id"):
            return value

    return None


def add_message_span_attributes(attributes: dict[str, Any]) -> None:
    """Add attributes to the current message processing span.

    This is useful for adding business-specific attributes within a
    traced handler. Mirrors add_span_attributes() from
    infra/tracing/opentelemetry.py.

    Args:
        attributes: Dictionary of attributes to add to current span.

    Example:
        @traced_handler()
        async def handle_user_created(event: UserCreatedEvent) -> None:
            add_message_span_attributes({
                "user.id": event.data["user_id"],
                "user.email_domain": event.data["email"].split("@")[1],
            })
            # Process user...
    """
    span = trace.get_current_span()
    if span.is_recording():
        for key, value in attributes.items():
            span.set_attribute(key, value)


def add_message_span_event(name: str, attributes: dict[str, Any] | None = None) -> None:
    """Add an event to the current message processing span.

    Events are timestamped markers within a span that record when something
    happened. Useful for tracking progress within long-running handlers.
    Mirrors add_span_event() from infra/tracing/opentelemetry.py.

    Args:
        name: Event name.
        attributes: Optional event attributes.

    Example:
        @traced_handler()
        async def handle_order_created(event: OrderCreatedEvent) -> None:
            # After validation
            add_message_span_event("order.validated", {"order_id": event.data["id"]})

            # After processing
            add_message_span_event("order.processed")
    """
    span = trace.get_current_span()
    if span.is_recording():
        span.add_event(name, attributes or {})
