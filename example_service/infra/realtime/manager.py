"""WebSocket connection manager with Redis PubSub for horizontal scaling.

This module provides a connection manager that:
- Tracks active WebSocket connections per channel
- Uses Redis PubSub for cross-instance message broadcasting
- Handles connection lifecycle (connect, disconnect, reconnect)
- Supports heartbeat/ping-pong for connection health
- Provides metrics for observability

The manager supports two modes:
1. Local-only: Messages only reach clients on the same instance
2. Redis PubSub: Messages broadcast to all instances (horizontally scalable)
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
import contextlib
from dataclasses import dataclass, field
import json
import logging
import time
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from example_service.core.settings import get_redis_settings, get_websocket_settings

if TYPE_CHECKING:
    from fastapi import WebSocket
    from redis.asyncio import Redis
    from redis.asyncio.client import PubSub

logger = logging.getLogger(__name__)


@dataclass
class ConnectionInfo:
    """Metadata about a WebSocket connection."""

    connection_id: str
    websocket: WebSocket
    channels: set[str] = field(default_factory=set)
    user_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    connected_at: float = field(default_factory=time.time)
    last_ping: float = field(default_factory=time.time)


class ConnectionManager:
    """Manages WebSocket connections with optional Redis PubSub.

    The manager tracks connections locally and optionally uses Redis PubSub
    to enable broadcasting across multiple server instances.

    Example:
        manager = ConnectionManager()
        await manager.start()

        # In WebSocket endpoint
        connection_id = await manager.connect(websocket, ["notifications"])
        try:
            async for message in websocket.iter_text():
                # Handle incoming messages
                pass
        finally:
            await manager.disconnect(connection_id)

        # Broadcast to all subscribers (all instances if Redis enabled)
        await manager.broadcast("notifications", {"event": "new_item", "id": 123})
    """

    def __init__(
        self,
        redis_client: Redis | None = None,
        channel_prefix: str = "ws:",
    ) -> None:
        """Initialize the connection manager.

        Args:
            redis_client: Optional Redis client for PubSub. If None, runs in
                          local-only mode (single instance).
            channel_prefix: Prefix for Redis PubSub channels.
        """
        self._redis = redis_client
        self._channel_prefix = channel_prefix
        self._settings = get_websocket_settings()

        # Local connection tracking
        # connection_id -> ConnectionInfo
        self._connections: dict[str, ConnectionInfo] = {}
        # channel -> set of connection_ids
        self._channel_connections: dict[str, set[str]] = defaultdict(set)

        # Redis PubSub
        self._pubsub: PubSub | None = None
        self._listener_task: asyncio.Task | None = None
        self._running = False

        # Heartbeat task
        self._heartbeat_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the connection manager.

        If Redis is configured, starts the PubSub listener for cross-instance
        message broadcasting. Also starts the heartbeat task for connection
        health monitoring.
        """
        if self._running:
            return

        self._running = True

        # Start Redis PubSub listener if Redis is available
        if self._redis is not None:
            await self._start_pubsub_listener()
            logger.info(
                "Connection manager started with Redis PubSub",
                extra={"channel_prefix": self._channel_prefix},
            )
        else:
            logger.info("Connection manager started in local-only mode")

        # Start heartbeat task
        if self._settings.heartbeat_interval > 0:
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            logger.debug(
                "Heartbeat task started",
                extra={"interval": self._settings.heartbeat_interval},
            )

    async def stop(self) -> None:
        """Stop the connection manager and close all connections."""
        self._running = False

        # Cancel heartbeat task
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._heartbeat_task
            self._heartbeat_task = None

        # Stop PubSub listener
        if self._listener_task:
            self._listener_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listener_task
            self._listener_task = None

        if self._pubsub:
            close_method = getattr(self._pubsub, "aclose", None)
            if close_method is not None:
                await close_method()
            else:
                await self._pubsub.close()
            self._pubsub = None

        # Close all connections
        for conn_info in list(self._connections.values()):
            with contextlib.suppress(Exception):
                await conn_info.websocket.close(code=1001, reason="Server shutdown")

        self._connections.clear()
        self._channel_connections.clear()

        logger.info(
            "Connection manager stopped",
            extra={"connections_closed": len(self._connections)},
        )

    async def connect(
        self,
        websocket: WebSocket,
        channels: list[str] | None = None,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Accept a new WebSocket connection.

        Args:
            websocket: FastAPI WebSocket instance
            channels: Channels to subscribe to on connect
            user_id: Optional user identifier for the connection
            metadata: Additional metadata to store with the connection

        Returns:
            Unique connection ID

        Raises:
            ConnectionRefusedError: If max connections reached
        """
        # Check connection limits
        if len(self._connections) >= self._settings.max_connections:
            logger.warning(
                "Connection refused: max connections reached",
                extra={"max": self._settings.max_connections},
            )
            raise ConnectionRefusedError("Maximum connections reached")

        # Accept the WebSocket connection
        await websocket.accept()

        # Generate connection ID and create info
        connection_id = str(uuid4())
        conn_info = ConnectionInfo(
            connection_id=connection_id,
            websocket=websocket,
            user_id=user_id,
            metadata=metadata or {},
        )

        # Store connection
        self._connections[connection_id] = conn_info

        # Subscribe to channels
        if channels:
            for channel in channels:
                await self.subscribe(connection_id, channel)

        # Update metrics
        self._update_connection_metrics()

        logger.info(
            "WebSocket connected",
            extra={
                "connection_id": connection_id,
                "channels": channels or [],
                "user_id": user_id,
                "total_connections": len(self._connections),
            },
        )

        return connection_id

    async def disconnect(self, connection_id: str) -> None:
        """Remove a WebSocket connection.

        Args:
            connection_id: ID of the connection to remove
        """
        conn_info = self._connections.pop(connection_id, None)
        if conn_info is None:
            return

        # Remove from all channels
        for channel in conn_info.channels:
            self._channel_connections[channel].discard(connection_id)
            if not self._channel_connections[channel]:
                del self._channel_connections[channel]
                # Unsubscribe from Redis PubSub if no more local subscribers
                if self._pubsub:
                    await self._pubsub.unsubscribe(f"{self._channel_prefix}{channel}")

        # Close WebSocket
        with contextlib.suppress(Exception):
            await conn_info.websocket.close()

        # Update metrics
        self._update_connection_metrics()

        logger.info(
            "WebSocket disconnected",
            extra={
                "connection_id": connection_id,
                "user_id": conn_info.user_id,
                "duration_seconds": time.time() - conn_info.connected_at,
                "total_connections": len(self._connections),
            },
        )

    async def subscribe(self, connection_id: str, channel: str) -> bool:
        """Subscribe a connection to a channel.

        Args:
            connection_id: ID of the connection
            channel: Channel to subscribe to

        Returns:
            True if subscribed, False if connection not found
        """
        conn_info = self._connections.get(connection_id)
        if conn_info is None:
            return False

        # Add to local tracking
        conn_info.channels.add(channel)
        is_first_subscriber = (
            channel not in self._channel_connections or not self._channel_connections[channel]
        )
        self._channel_connections[channel].add(connection_id)

        # Subscribe to Redis PubSub if this is the first local subscriber
        if is_first_subscriber and self._pubsub:
            await self._pubsub.subscribe(f"{self._channel_prefix}{channel}")
            logger.debug(
                "Subscribed to Redis PubSub channel",
                extra={"channel": channel},
            )

        return True

    async def unsubscribe(self, connection_id: str, channel: str) -> bool:
        """Unsubscribe a connection from a channel.

        Args:
            connection_id: ID of the connection
            channel: Channel to unsubscribe from

        Returns:
            True if unsubscribed, False if connection not found
        """
        conn_info = self._connections.get(connection_id)
        if conn_info is None:
            return False

        conn_info.channels.discard(channel)
        self._channel_connections[channel].discard(connection_id)

        # Unsubscribe from Redis PubSub if no more local subscribers
        if not self._channel_connections[channel]:
            del self._channel_connections[channel]
            if self._pubsub:
                await self._pubsub.unsubscribe(f"{self._channel_prefix}{channel}")

        return True

    async def broadcast(
        self,
        channel: str,
        message: dict[str, Any],
        exclude: set[str] | None = None,
    ) -> int:
        """Broadcast a message to all subscribers of a channel.

        If Redis is configured, the message is published to Redis PubSub,
        reaching all server instances. Otherwise, only local connections
        receive the message.

        Args:
            channel: Channel to broadcast to
            message: Message to send (will be JSON serialized)
            exclude: Connection IDs to exclude from broadcast

        Returns:
            Number of connections the message was sent to (local only)
        """
        exclude = exclude or set()

        # Publish to Redis for cross-instance broadcasting
        if self._redis is not None:
            await self._redis.publish(
                f"{self._channel_prefix}{channel}",
                json.dumps(message),
            )
            # Local delivery will happen via PubSub listener
            return 0

        # Local-only broadcast
        return await self._send_to_channel(channel, message, exclude)

    async def send_to_connection(
        self,
        connection_id: str,
        message: dict[str, Any],
    ) -> bool:
        """Send a message to a specific connection.

        Args:
            connection_id: ID of the connection
            message: Message to send

        Returns:
            True if sent, False if connection not found
        """
        conn_info = self._connections.get(connection_id)
        if conn_info is None:
            return False

        try:
            await conn_info.websocket.send_json(message)
            return True
        except Exception as e:
            logger.warning(
                "Failed to send message to connection",
                extra={"connection_id": connection_id, "error": str(e)},
            )
            # Connection is likely dead, remove it
            await self.disconnect(connection_id)
            return False

    async def send_to_user(
        self,
        user_id: str,
        message: dict[str, Any],
    ) -> int:
        """Send a message to all connections for a user.

        Args:
            user_id: User identifier
            message: Message to send

        Returns:
            Number of connections the message was sent to
        """
        count = 0
        for conn_info in list(self._connections.values()):
            if conn_info.user_id == user_id and await self.send_to_connection(
                conn_info.connection_id, message
            ):
                count += 1
        return count

    def get_connection(self, connection_id: str) -> ConnectionInfo | None:
        """Get connection info by ID."""
        return self._connections.get(connection_id)

    def get_channel_connections(self, channel: str) -> list[ConnectionInfo]:
        """Get all connections subscribed to a channel."""
        connection_ids = self._channel_connections.get(channel, set())
        return [self._connections[cid] for cid in connection_ids if cid in self._connections]

    @property
    def connection_count(self) -> int:
        """Total number of active connections."""
        return len(self._connections)

    @property
    def channel_count(self) -> int:
        """Number of active channels."""
        return len(self._channel_connections)

    # Private methods

    async def _send_to_channel(
        self,
        channel: str,
        message: dict[str, Any],
        exclude: set[str],
    ) -> int:
        """Send message to all local connections in a channel."""
        connection_ids = self._channel_connections.get(channel, set())
        count = 0

        for connection_id in list(connection_ids):
            if connection_id in exclude:
                continue
            if await self.send_to_connection(connection_id, message):
                count += 1

        return count

    async def _start_pubsub_listener(self) -> None:
        """Start the Redis PubSub listener task."""
        if self._redis is None:
            return

        self._pubsub = self._redis.pubsub()
        self._listener_task = asyncio.create_task(self._pubsub_listener())

    async def _pubsub_listener(self) -> None:
        """Listen for Redis PubSub messages and broadcast locally."""
        if self._pubsub is None:
            return

        try:
            async for message in self._pubsub.listen():
                if not self._running:
                    break

                if message["type"] != "message":
                    continue

                try:
                    channel = message["channel"]
                    if isinstance(channel, bytes):
                        channel = channel.decode()

                    # Remove prefix to get logical channel name
                    channel = channel.removeprefix(self._channel_prefix)

                    data = message["data"]
                    if isinstance(data, bytes):
                        data = json.loads(data.decode())
                    elif isinstance(data, str):
                        data = json.loads(data)

                    # Broadcast to local connections
                    await self._send_to_channel(channel, data, set())

                except Exception as e:
                    logger.error(
                        "Error processing PubSub message",
                        extra={"error": str(e)},
                    )

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("PubSub listener error", extra={"error": str(e)})

    async def _heartbeat_loop(self) -> None:
        """Send periodic pings to all connections."""
        try:
            while self._running:
                await asyncio.sleep(self._settings.heartbeat_interval)

                now = time.time()
                timeout = self._settings.connection_timeout

                for conn_id in list(self._connections.keys()):
                    conn_info = self._connections.get(conn_id)
                    if conn_info is None:
                        continue

                    # Check for stale connections
                    if timeout > 0 and (now - conn_info.last_ping) > timeout:
                        logger.warning(
                            "Connection timed out",
                            extra={"connection_id": conn_id},
                        )
                        await self.disconnect(conn_id)
                        continue

                    # Send ping
                    try:
                        await conn_info.websocket.send_json({"type": "ping"})
                    except Exception:
                        await self.disconnect(conn_id)

        except asyncio.CancelledError:
            pass

    def _update_connection_metrics(self) -> None:
        """Update Prometheus metrics for connections."""
        try:
            from example_service.infra.metrics.prometheus import (
                websocket_connections_total,
            )

            websocket_connections_total.set(len(self._connections))
        except ImportError:
            pass


# Global manager instance
_manager: ConnectionManager | None = None


def get_connection_manager() -> ConnectionManager:
    """Get the global connection manager instance.

    Returns:
        ConnectionManager instance

    Raises:
        RuntimeError: If manager not initialized
    """
    if _manager is None:
        raise RuntimeError(
            "Connection manager not initialized. Call start_connection_manager() first."
        )
    return _manager


async def start_connection_manager() -> ConnectionManager:
    """Initialize and start the global connection manager.

    Uses Redis for PubSub if configured, otherwise runs in local-only mode.

    Returns:
        ConnectionManager instance
    """
    global _manager

    redis_settings = get_redis_settings()
    redis_client = None

    if redis_settings.is_configured:
        try:
            from redis.asyncio import ConnectionPool, Redis

            pool: ConnectionPool = ConnectionPool.from_url(
                redis_settings.url,
                **redis_settings.connection_pool_kwargs(),
            )
            redis_client = Redis(connection_pool=pool)
            # Test connection
            await redis_client.ping()
            logger.info("WebSocket manager using Redis PubSub for horizontal scaling")
        except Exception as e:
            logger.warning(
                "Failed to connect to Redis for WebSocket PubSub, using local-only mode",
                extra={"error": str(e)},
            )
            redis_client = None

    _manager = ConnectionManager(redis_client=redis_client)
    await _manager.start()

    return _manager


async def stop_connection_manager() -> None:
    """Stop and cleanup the global connection manager."""
    global _manager

    if _manager is not None:
        await _manager.stop()
        _manager = None
        logger.info("Connection manager stopped")
