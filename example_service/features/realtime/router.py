"""WebSocket router for realtime communication.

Endpoints:
- GET /ws: WebSocket connection endpoint
- GET /ws/stats: Connection statistics (admin)
- POST /ws/broadcast: Broadcast message to channel (admin)
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse

from example_service.core.settings import get_websocket_settings
from example_service.features.realtime.schemas import (
    BroadcastMessage,
    BroadcastRequest,
    BroadcastResponse,
    ClientMessageType,
    ConnectedMessage,
    ConnectionStats,
    ErrorMessage,
    ServerMessageType,
    ServerPongMessage,
    SubscribedMessage,
    UnsubscribedMessage,
)
from example_service.infra.realtime import get_connection_manager

if TYPE_CHECKING:
    from example_service.infra.realtime.manager import ConnectionManager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ws", tags=["realtime"])

ws_settings = get_websocket_settings()


def _get_manager_safe() -> ConnectionManager | None:
    """Get connection manager, handling not-initialized case."""
    try:
        return get_connection_manager()
    except RuntimeError:
        return None


@router.websocket("")
async def websocket_endpoint(
    websocket: WebSocket,
    channels: Annotated[
        str, Query(description="Comma-separated list of channels to subscribe"),
    ] = "",
    user_id: Annotated[str | None, Query(description="User identifier")] = None,
) -> None:
    """WebSocket connection endpoint.

    Connect to receive real-time updates. Optionally specify channels
    to subscribe to on connection.

    Query Parameters:
        channels: Comma-separated list of channels (e.g., "notifications,updates")
        user_id: Optional user identifier for user-targeted messages

    Message Protocol:
        Client → Server:
        - {"type": "subscribe", "channels": ["channel1", "channel2"]}
        - {"type": "unsubscribe", "channels": ["channel1"]}
        - {"type": "ping"}
        - {"type": "pong"}
        - {"type": "message", "channel": "channel1", "data": {...}}

        Server → Client:
        - {"type": "connected", "connection_id": "...", "channels": [...]}
        - {"type": "subscribed", "channel": "..."}
        - {"type": "unsubscribed", "channel": "..."}
        - {"type": "ping"}
        - {"type": "pong"}
        - {"type": "message", "channel": "...", "data": {...}}
        - {"type": "broadcast", "channel": "...", "event_type": "...", "data": {...}}
        - {"type": "error", "code": "...", "message": "..."}
    """
    if not ws_settings.enabled:
        await websocket.close(code=status.WS_1013_TRY_AGAIN_LATER, reason="WebSocket disabled")
        return

    manager = _get_manager_safe()
    if manager is None:
        await websocket.close(code=status.WS_1013_TRY_AGAIN_LATER, reason="Server not ready")
        return

    # Parse initial channels
    initial_channels = [c.strip() for c in channels.split(",") if c.strip()]

    # Add default channels
    initial_channels.extend(ws_settings.default_channels)

    # Deduplicate while preserving order
    seen = set()
    unique_channels = []
    for ch in initial_channels:
        if ch not in seen:
            seen.add(ch)
            unique_channels.append(ch)

    try:
        # Connect and get connection ID
        connection_id = await manager.connect(
            websocket,
            channels=unique_channels,
            user_id=user_id,
            metadata={"initial_channels": initial_channels},
        )

        # Send connected message
        connected_msg = ConnectedMessage(
            connection_id=connection_id,
            channels=unique_channels,
        )
        await websocket.send_json(connected_msg.model_dump())

        logger.info(
            "WebSocket client connected",
            extra={
                "connection_id": connection_id,
                "channels": unique_channels,
                "user_id": user_id,
            },
        )

        # Message handling loop
        await _handle_messages(websocket, connection_id, manager)

    except ConnectionRefusedError as e:
        logger.warning("WebSocket connection refused", extra={"reason": str(e)})
        await websocket.close(code=status.WS_1013_TRY_AGAIN_LATER, reason=str(e))

    except WebSocketDisconnect:
        logger.debug("WebSocket client disconnected normally")

    except Exception as e:
        logger.exception("WebSocket error", extra={"error": str(e)})

    finally:
        if manager is not None:
            conn_id = locals().get("connection_id")
            if conn_id:
                await manager.disconnect(conn_id)


async def _handle_messages(
    websocket: WebSocket,
    connection_id: str,
    manager: Any,
) -> None:
    """Handle incoming WebSocket messages."""
    async for raw_message in websocket.iter_text():
        try:
            message = json.loads(raw_message)
            msg_type = message.get("type")

            if msg_type == ClientMessageType.PING:
                # Respond to client ping
                pong = ServerPongMessage()
                await websocket.send_json(pong.model_dump())

            elif msg_type == ClientMessageType.PONG:
                # Update last activity for heartbeat
                conn = manager.get_connection(connection_id)
                if conn:
                    import time

                    conn.last_ping = time.time()

            elif msg_type == ClientMessageType.SUBSCRIBE:
                # Subscribe to channels
                channels = message.get("channels", [])
                for channel in channels[: ws_settings.max_channels_per_connection]:
                    if await manager.subscribe(connection_id, channel):
                        subscribed = SubscribedMessage(channel=channel)
                        await websocket.send_json(subscribed.model_dump())

            elif msg_type == ClientMessageType.UNSUBSCRIBE:
                # Unsubscribe from channels
                channels = message.get("channels", [])
                for channel in channels:
                    if await manager.unsubscribe(connection_id, channel):
                        unsubscribed = UnsubscribedMessage(channel=channel)
                        await websocket.send_json(unsubscribed.model_dump())

            elif msg_type == ClientMessageType.MESSAGE:
                # Forward message to channel
                channel = message.get("channel")
                data = message.get("data", {})

                if channel:
                    await manager.broadcast(
                        channel,
                        {
                            "type": ServerMessageType.MESSAGE,
                            "channel": channel,
                            "data": data,
                            "sender_id": connection_id,
                        },
                        exclude={connection_id},  # Don't echo back to sender
                    )

            else:
                # Unknown message type
                error = ErrorMessage(
                    code="unknown_type",
                    message=f"Unknown message type: {msg_type}",
                )
                await websocket.send_json(error.model_dump())

        except json.JSONDecodeError:
            error = ErrorMessage(
                code="invalid_json",
                message="Invalid JSON message",
            )
            await websocket.send_json(error.model_dump())

        except Exception as e:
            logger.exception("Error handling WebSocket message")
            error = ErrorMessage(
                code="internal_error",
                message="Internal error processing message",
                details={"error": str(e)},
            )
            await websocket.send_json(error.model_dump())


@router.get(
    "/stats",
    response_model=ConnectionStats,
    summary="Get WebSocket connection statistics",
    description="Returns current connection and channel statistics.",
)
async def get_stats() -> ConnectionStats | JSONResponse:
    """Get current WebSocket connection statistics."""
    manager = _get_manager_safe()
    if manager is None:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "WebSocket manager not initialized"},
        )

    # Build channel stats
    channel_stats = {}
    for channel in list(manager._channel_connections.keys()):
        channel_stats[channel] = len(manager._channel_connections[channel])

    return ConnectionStats(
        total_connections=manager.connection_count,
        total_channels=manager.channel_count,
        channels=channel_stats,
    )


@router.post(
    "/broadcast",
    response_model=BroadcastResponse,
    summary="Broadcast message to channel",
    description="Send a message to all subscribers of a channel.",
)
async def broadcast_message(
    request: BroadcastRequest,
) -> BroadcastResponse | JSONResponse:
    """Broadcast a message to all subscribers of a channel.

    This endpoint is typically used by backend services to push
    updates to connected WebSocket clients.
    """
    manager = _get_manager_safe()
    if manager is None:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "WebSocket manager not initialized"},
        )

    # Build broadcast message
    message = BroadcastMessage(
        channel=request.channel,
        event_type=request.event_type,
        data=request.data,
    )

    # Broadcast to channel
    recipients = await manager.broadcast(
        request.channel,
        message.model_dump(),
    )

    logger.info(
        "Broadcast message sent",
        extra={
            "channel": request.channel,
            "event_type": request.event_type,
            "recipients": recipients,
        },
    )

    return BroadcastResponse(
        success=True,
        channel=request.channel,
        recipients=recipients,
    )
