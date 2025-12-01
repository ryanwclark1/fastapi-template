"""RabbitMQ to WebSocket event bridge.

This module bridges domain events from RabbitMQ to WebSocket clients,
enabling real-time updates when backend events occur.

Architecture:
    Domain Event → RabbitMQ → Event Bridge → WebSocket Manager → Clients

The bridge:
1. Subscribes to a dedicated RabbitMQ queue for WebSocket events
2. Transforms domain events into WebSocket broadcast messages
3. Sends broadcasts through the connection manager

Configuration:
    WS_EVENT_BRIDGE_ENABLED: Enable/disable the bridge
    WS_EVENT_BRIDGE_QUEUE: Queue name for events
    WS_EVENT_BRIDGE_ROUTING_KEY: Routing key pattern
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from example_service.core.settings import get_rabbit_settings, get_websocket_settings

if TYPE_CHECKING:
    from faststream.rabbit import RabbitBroker

logger = logging.getLogger(__name__)


class EventBridge:
    """Bridges RabbitMQ events to WebSocket broadcasts.

    The bridge subscribes to a RabbitMQ queue and forwards matching
    events to WebSocket clients through the connection manager.

    Example:
        bridge = EventBridge()
        await bridge.start()

        # Events published to ws.broadcast.* routing key will be
        # automatically forwarded to WebSocket clients

        await bridge.stop()
    """

    def __init__(self) -> None:
        """Initialize the event bridge."""
        self._settings = get_websocket_settings()
        self._rabbit_settings = get_rabbit_settings()
        self._running = False
        self._consumer_task: asyncio.Task | None = None

    async def start(self) -> bool:
        """Start the event bridge.

        Returns:
            True if started successfully, False if disabled or unavailable.
        """
        if not self._settings.event_bridge_enabled:
            logger.info("Event bridge disabled via configuration")
            return False

        if not self._rabbit_settings.is_configured:
            logger.warning("Event bridge requires RabbitMQ, skipping")
            return False

        try:
            from example_service.infra.messaging.broker import broker

            if broker is None:
                logger.warning("RabbitMQ broker not available, skipping event bridge")
                return False

            # Set up consumer
            self._running = True
            await self._setup_consumer(broker)

            logger.info(
                "Event bridge started",
                extra={
                    "queue": self._settings.event_bridge_queue,
                    "routing_key": self._settings.event_bridge_routing_key,
                },
            )
            return True

        except Exception as e:
            logger.exception("Failed to start event bridge", extra={"error": str(e)})
            return False

    async def stop(self) -> None:
        """Stop the event bridge."""
        self._running = False

        if self._consumer_task:
            self._consumer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._consumer_task
            self._consumer_task = None

        logger.info("Event bridge stopped")

    async def _setup_consumer(self, broker: RabbitBroker) -> None:
        """Set up the RabbitMQ consumer for WebSocket events."""
        from faststream.rabbit import ExchangeType, RabbitExchange, RabbitQueue

        # Create exchange and queue
        exchange = RabbitExchange(
            name="websocket-events",
            type=ExchangeType.TOPIC,
            durable=True,
        )

        queue = RabbitQueue(
            name=self._settings.event_bridge_queue,
            durable=True,
            routing_key=self._settings.event_bridge_routing_key,
        )

        # Register the handler
        @broker.subscriber(queue, exchange)
        async def handle_websocket_event(body: dict[str, Any], msg: Any) -> None:  # noqa: ARG001
            """Handle incoming events and broadcast to WebSocket clients.

            Args:
                body: Event payload dictionary
                msg: RabbitMQ message object (required by FastStream protocol)
            """
            await self._handle_event(body)

        logger.debug(
            "Event bridge consumer registered",
            extra={"queue": queue.name, "exchange": exchange.name},
        )

    async def _handle_event(self, event: dict[str, Any]) -> None:
        """Process an event and broadcast to WebSocket clients.

        Args:
            event: Event payload with structure:
                {
                    "event_type": "reminder.created",
                    "channel": "reminders",  # optional, derived from event_type
                    "data": {...},
                    "correlation_id": "...",  # optional
                }
        """
        try:
            from example_service.infra.realtime import get_connection_manager

            manager = get_connection_manager()
        except RuntimeError:
            logger.debug("Connection manager not available, skipping event")
            return

        event_type = event.get("event_type", "unknown")
        channel = event.get("channel") or self._derive_channel(event_type)
        data = event.get("data", {})

        # Build WebSocket broadcast message
        broadcast_msg = {
            "type": "broadcast",
            "channel": channel,
            "event_type": event_type,
            "data": data,
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Add correlation ID if present
        if "correlation_id" in event:
            broadcast_msg["correlation_id"] = event["correlation_id"]

        # Broadcast to channel
        recipients = await manager.broadcast(channel, broadcast_msg)

        logger.debug(
            "Event broadcasted to WebSocket clients",
            extra={
                "event_type": event_type,
                "channel": channel,
                "recipients": recipients,
            },
        )

        # Update metrics
        try:
            from example_service.infra.metrics.prometheus import (
                websocket_broadcast_recipients,
            )

            websocket_broadcast_recipients.observe(recipients)
        except ImportError:
            pass

    def _derive_channel(self, event_type: str) -> str:
        """Derive WebSocket channel from event type.

        Converts event types like "reminder.created" to channel "reminders".

        Args:
            event_type: Domain event type (e.g., "reminder.created")

        Returns:
            Channel name (e.g., "reminders")
        """
        # Take the first part and pluralize simple cases
        parts = event_type.split(".")
        if parts:
            base = parts[0]
            # Simple pluralization
            if not base.endswith("s"):
                return f"{base}s"
            return base
        return "events"


# Global bridge instance
_bridge: EventBridge | None = None


async def start_event_bridge() -> bool:
    """Start the global event bridge.

    Returns:
        True if started, False if disabled or failed.
    """
    global _bridge
    _bridge = EventBridge()
    return await _bridge.start()


async def stop_event_bridge() -> None:
    """Stop the global event bridge."""
    global _bridge
    if _bridge:
        await _bridge.stop()
        _bridge = None


def get_event_bridge() -> EventBridge | None:
    """Get the global event bridge instance."""
    return _bridge


# Utility function for publishing events to the bridge
async def publish_to_websocket(
    event_type: str,
    data: dict[str, Any],
    channel: str | None = None,
    correlation_id: str | None = None,
) -> bool:
    """Publish an event for WebSocket broadcast.

    This is a convenience function for publishing events that should
    be forwarded to WebSocket clients.

    Args:
        event_type: Type of the event (e.g., "reminder.created")
        data: Event payload
        channel: Target WebSocket channel (derived from event_type if not provided)
        correlation_id: Optional correlation ID for tracing

    Returns:
        True if published, False if RabbitMQ unavailable.
    """
    rabbit_settings = get_rabbit_settings()
    if not rabbit_settings.is_configured:
        return False

    try:
        from example_service.infra.messaging.broker import broker

        if broker is None:
            return False

        event = {
            "event_type": event_type,
            "data": data,
            "timestamp": datetime.utcnow().isoformat(),
        }

        if channel:
            event["channel"] = channel
        if correlation_id:
            event["correlation_id"] = correlation_id

        # Publish with routing key based on event type
        routing_key = f"ws.broadcast.{event_type}"

        await broker.publish(
            message=json.dumps(event),
            exchange="websocket-events",
            routing_key=routing_key,
        )

        logger.debug(
            "Event published to WebSocket bridge",
            extra={"event_type": event_type, "routing_key": routing_key},
        )
        return True

    except Exception as e:
        logger.warning(
            "Failed to publish to WebSocket bridge",
            extra={"event_type": event_type, "error": str(e)},
        )
        return False
