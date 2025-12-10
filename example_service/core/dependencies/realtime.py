"""WebSocket/Realtime dependencies for FastAPI route handlers.

This module provides FastAPI-compatible dependencies for accessing the
WebSocket connection manager and event bridge for real-time communication.

Usage:
    from example_service.core.dependencies.realtime import (
        ConnectionManagerDep,
        EventBridgeDep,
        get_connection_manager,
    )

    @router.websocket("/ws/{channel}")
    async def websocket_endpoint(
        websocket: WebSocket,
        channel: str,
        manager: ConnectionManagerDep,
    ):
        await manager.connect(websocket, channel)
        try:
            while True:
                data = await websocket.receive_text()
                await manager.broadcast(channel, {"message": data})
        except WebSocketDisconnect:
            manager.disconnect(websocket, channel)

    @router.post("/broadcast/{channel}")
    async def broadcast_message(
        channel: str,
        data: dict,
        bridge: EventBridgeDep,
    ):
        await bridge.publish(channel, data)
        return {"status": "broadcast_sent"}
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status


def get_ws_connection_manager() -> ConnectionManager | None:
    """Get the WebSocket connection manager instance.

    This is a thin wrapper that retrieves the global connection manager
    singleton. The import is deferred to runtime to avoid circular
    dependencies.

    Note: The infra.realtime.get_connection_manager() raises RuntimeError
    if the manager hasn't been started. This dependency catches that
    exception and returns None to allow graceful degradation.

    Returns:
        ConnectionManager | None: The manager instance, or None if not initialized.
    """
    from example_service.infra.realtime import get_connection_manager

    try:
        return get_connection_manager()
    except RuntimeError:
        return None


def get_ws_event_bridge() -> EventBridge | None:
    """Get the WebSocket event bridge instance.

    The event bridge enables publishing events to WebSocket channels
    from anywhere in the application.

    Returns:
        EventBridge | None: The bridge instance, or None if not initialized.
    """
    from example_service.infra.realtime import get_event_bridge

    return get_event_bridge()


async def require_connection_manager(
    manager: Annotated[ConnectionManager | None, Depends(get_ws_connection_manager)],
) -> ConnectionManager:
    """Dependency that requires connection manager to be available.

    Use this dependency when WebSocket functionality is required for the
    endpoint to function. Automatically raises HTTP 503 if unavailable.

    Args:
        manager: Injected manager from get_ws_connection_manager

    Returns:
        ConnectionManager: The connection manager instance

    Raises:
        HTTPException: 503 Service Unavailable if manager is not available
    """
    if manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "websocket_unavailable",
                "message": "WebSocket connection manager is not available",
            },
        )
    return manager


async def optional_connection_manager(
    manager: Annotated[ConnectionManager | None, Depends(get_ws_connection_manager)],
) -> ConnectionManager | None:
    """Dependency that optionally provides connection manager.

    Use this when WebSocket functionality is optional. Returns None if
    the connection manager is not available.

    Args:
        manager: Injected manager from get_ws_connection_manager

    Returns:
        ConnectionManager | None: The manager if available, None otherwise
    """
    return manager


async def require_event_bridge(
    bridge: Annotated[EventBridge | None, Depends(get_ws_event_bridge)],
) -> EventBridge:
    """Dependency that requires event bridge to be available.

    Use this dependency when you need to publish events to WebSocket
    channels. Automatically raises HTTP 503 if unavailable.

    Args:
        bridge: Injected bridge from get_ws_event_bridge

    Returns:
        EventBridge: The event bridge instance

    Raises:
        HTTPException: 503 Service Unavailable if bridge is not available
    """
    if bridge is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "event_bridge_unavailable",
                "message": "WebSocket event bridge is not available",
            },
        )
    return bridge


async def optional_event_bridge(
    bridge: Annotated[EventBridge | None, Depends(get_ws_event_bridge)],
) -> EventBridge | None:
    """Dependency that optionally provides event bridge.

    Use this when event publishing is optional. Returns None if
    the event bridge is not available.

    Args:
        bridge: Injected bridge from get_ws_event_bridge

    Returns:
        EventBridge | None: The bridge if available, None otherwise
    """
    return bridge


# Type aliases for cleaner route signatures
# Import at runtime after function definitions to avoid circular dependencies
from example_service.infra.realtime import ConnectionManager, EventBridge  # noqa: E402

ConnectionManagerDep = Annotated[ConnectionManager, Depends(require_connection_manager)]
"""Connection manager dependency that requires it to be available.

Example:
    @router.websocket("/ws/{channel}")
    async def ws_endpoint(websocket: WebSocket, manager: ConnectionManagerDep):
        await manager.connect(websocket, channel)
"""

OptionalConnectionManager = Annotated[
    ConnectionManager | None, Depends(optional_connection_manager)
]
"""Connection manager dependency that is optional.

Example:
    @router.get("/status")
    async def status(manager: OptionalConnectionManager):
        if manager is None:
            return {"websocket": "disabled"}
        return {"websocket": "enabled", "connections": manager.connection_count}
"""

EventBridgeDep = Annotated[EventBridge, Depends(require_event_bridge)]
"""Event bridge dependency that requires it to be available.

Example:
    @router.post("/notify/{channel}")
    async def notify(channel: str, data: dict, bridge: EventBridgeDep):
        await bridge.publish(channel, data)
"""

OptionalEventBridge = Annotated[EventBridge | None, Depends(optional_event_bridge)]
"""Event bridge dependency that is optional.

Example:
    @router.post("/update")
    async def update(data: dict, bridge: OptionalEventBridge):
        # Update data...
        if bridge:
            await bridge.publish("updates", data)
"""


__all__ = [
    "ConnectionManagerDep",
    "EventBridgeDep",
    "OptionalConnectionManager",
    "OptionalEventBridge",
    "get_ws_connection_manager",
    "get_ws_event_bridge",
    "optional_connection_manager",
    "optional_event_bridge",
    "require_connection_manager",
    "require_event_bridge",
]
