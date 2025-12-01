"""Realtime infrastructure for WebSocket connections.

This module provides the core infrastructure for real-time communication:
- ConnectionManager: Track and manage WebSocket connections
- Redis PubSub: Enable horizontal scaling across multiple instances
- Event broadcasting: Send messages to groups of connected clients

Architecture:
    When running multiple instances behind a load balancer, WebSocket
    connections are distributed across instances. Redis PubSub ensures
    that messages reach all connected clients regardless of which
    instance they're connected to.

    Client A (Instance 1) ──┐
    Client B (Instance 2) ──┼── Redis PubSub ──► All Clients
    Client C (Instance 1) ──┘

Usage:
    from example_service.infra.realtime import (
        ConnectionManager,
        get_connection_manager,
    )

    manager = get_connection_manager()
    await manager.broadcast("channel", {"event": "update", "data": {...}})
"""

from example_service.infra.realtime.event_bridge import (
    EventBridge,
    get_event_bridge,
    publish_to_websocket,
    start_event_bridge,
    stop_event_bridge,
)
from example_service.infra.realtime.manager import (
    ConnectionManager,
    get_connection_manager,
    start_connection_manager,
    stop_connection_manager,
)

__all__ = [
    # Connection manager
    "ConnectionManager",
    "get_connection_manager",
    "start_connection_manager",
    "stop_connection_manager",
    # Event bridge
    "EventBridge",
    "get_event_bridge",
    "publish_to_websocket",
    "start_event_bridge",
    "stop_event_bridge",
]
