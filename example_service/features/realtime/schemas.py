"""Pydantic schemas for realtime WebSocket messages.

Message Types:
- Client → Server: subscribe, unsubscribe, ping, message
- Server → Client: subscribed, unsubscribed, pong, message, error, broadcast
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ClientMessageType(str, Enum):
    """Message types sent from client to server."""

    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"
    PING = "ping"
    PONG = "pong"
    MESSAGE = "message"


class ServerMessageType(str, Enum):
    """Message types sent from server to client."""

    SUBSCRIBED = "subscribed"
    UNSUBSCRIBED = "unsubscribed"
    PING = "ping"
    PONG = "pong"
    MESSAGE = "message"
    BROADCAST = "broadcast"
    ERROR = "error"
    CONNECTED = "connected"


# ──────────────────────────────────────────────────────────────
# Client → Server Messages
# ──────────────────────────────────────────────────────────────


class ClientMessage(BaseModel):
    """Base model for messages from client to server."""

    type: ClientMessageType


class SubscribeMessage(ClientMessage):
    """Request to subscribe to channels."""

    type: Literal[ClientMessageType.SUBSCRIBE] = ClientMessageType.SUBSCRIBE
    channels: list[str] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Channels to subscribe to",
    )


class UnsubscribeMessage(ClientMessage):
    """Request to unsubscribe from channels."""

    type: Literal[ClientMessageType.UNSUBSCRIBE] = ClientMessageType.UNSUBSCRIBE
    channels: list[str] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Channels to unsubscribe from",
    )


class ClientPingMessage(ClientMessage):
    """Ping message from client."""

    type: Literal[ClientMessageType.PING] = ClientMessageType.PING


class ClientPongMessage(ClientMessage):
    """Pong response to server ping."""

    type: Literal[ClientMessageType.PONG] = ClientMessageType.PONG


class SendMessage(ClientMessage):
    """Message to send to a channel."""

    type: Literal[ClientMessageType.MESSAGE] = ClientMessageType.MESSAGE
    channel: str = Field(..., max_length=100, description="Target channel")
    data: dict[str, Any] = Field(default_factory=dict, description="Message payload")


# ──────────────────────────────────────────────────────────────
# Server → Client Messages
# ──────────────────────────────────────────────────────────────


class ServerMessage(BaseModel):
    """Base model for messages from server to client."""

    type: ServerMessageType


class ConnectedMessage(ServerMessage):
    """Sent immediately after connection is established."""

    type: Literal[ServerMessageType.CONNECTED] = ServerMessageType.CONNECTED
    connection_id: str = Field(..., description="Unique connection identifier")
    channels: list[str] = Field(default_factory=list, description="Subscribed channels")


class SubscribedMessage(ServerMessage):
    """Confirmation of channel subscription."""

    type: Literal[ServerMessageType.SUBSCRIBED] = ServerMessageType.SUBSCRIBED
    channel: str = Field(..., description="Channel subscribed to")


class UnsubscribedMessage(ServerMessage):
    """Confirmation of channel unsubscription."""

    type: Literal[ServerMessageType.UNSUBSCRIBED] = ServerMessageType.UNSUBSCRIBED
    channel: str = Field(..., description="Channel unsubscribed from")


class ServerPingMessage(ServerMessage):
    """Ping message from server (heartbeat)."""

    type: Literal[ServerMessageType.PING] = ServerMessageType.PING


class ServerPongMessage(ServerMessage):
    """Pong response to client ping."""

    type: Literal[ServerMessageType.PONG] = ServerMessageType.PONG


class MessageReceived(ServerMessage):
    """Message received from a channel."""

    type: Literal[ServerMessageType.MESSAGE] = ServerMessageType.MESSAGE
    channel: str = Field(..., description="Source channel")
    data: dict[str, Any] = Field(..., description="Message payload")
    sender_id: str | None = Field(None, description="Sender connection ID")
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class BroadcastMessage(ServerMessage):
    """System broadcast message (events, announcements)."""

    type: Literal[ServerMessageType.BROADCAST] = ServerMessageType.BROADCAST
    channel: str = Field(..., description="Source channel")
    event_type: str = Field(..., description="Type of event")
    data: dict[str, Any] = Field(..., description="Event payload")
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ErrorMessage(ServerMessage):
    """Error message from server."""

    type: Literal[ServerMessageType.ERROR] = ServerMessageType.ERROR
    code: str = Field(..., description="Error code")
    message: str = Field(..., description="Human-readable error message")
    details: dict[str, Any] | None = Field(None, description="Additional error details")


# ──────────────────────────────────────────────────────────────
# REST API Schemas
# ──────────────────────────────────────────────────────────────


class ConnectionStats(BaseModel):
    """Statistics about WebSocket connections."""

    total_connections: int = Field(..., ge=0)
    total_channels: int = Field(..., ge=0)
    channels: dict[str, int] = Field(
        default_factory=dict,
        description="Channel name to subscriber count",
    )


class BroadcastRequest(BaseModel):
    """Request to broadcast a message to a channel."""

    channel: str = Field(..., max_length=100, description="Target channel")
    event_type: str = Field(..., max_length=100, description="Event type identifier")
    data: dict[str, Any] = Field(default_factory=dict, description="Message payload")


class BroadcastResponse(BaseModel):
    """Response from broadcast request."""

    success: bool = Field(..., description="Whether broadcast was successful")
    channel: str = Field(..., description="Target channel")
    recipients: int = Field(..., ge=0, description="Number of local recipients")
