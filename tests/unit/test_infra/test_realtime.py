"""Unit tests for WebSocket realtime infrastructure."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ──────────────────────────────────────────────────────────────
# Test ConnectionInfo
# ──────────────────────────────────────────────────────────────


class TestConnectionInfo:
    """Tests for ConnectionInfo dataclass."""

    def test_connection_info_creation(self):
        """ConnectionInfo should store connection metadata."""
        from example_service.infra.realtime.manager import ConnectionInfo

        mock_ws = MagicMock()
        info = ConnectionInfo(
            connection_id="conn-123",
            websocket=mock_ws,
            user_id="user-456",
            metadata={"client": "test"},
        )

        assert info.connection_id == "conn-123"
        assert info.websocket == mock_ws
        assert info.user_id == "user-456"
        assert info.metadata == {"client": "test"}

    def test_connection_info_defaults(self):
        """ConnectionInfo should have sensible defaults."""
        from example_service.infra.realtime.manager import ConnectionInfo

        mock_ws = MagicMock()
        info = ConnectionInfo(
            connection_id="conn-789",
            websocket=mock_ws,
        )

        assert info.channels == set()
        assert info.user_id is None
        assert info.metadata == {}
        assert info.connected_at > 0
        assert info.last_ping > 0


# ──────────────────────────────────────────────────────────────
# Test ConnectionManager
# ──────────────────────────────────────────────────────────────


class TestConnectionManager:
    """Tests for ConnectionManager."""

    @pytest.fixture
    def manager(self):
        """Create ConnectionManager for testing."""
        from example_service.infra.realtime.manager import ConnectionManager

        with patch(
            "example_service.infra.realtime.manager.get_websocket_settings"
        ) as mock_settings:
            mock_settings.return_value = MagicMock(
                max_connections=100,
                heartbeat_interval=0,  # Disable heartbeat for tests
                connection_timeout=0,
            )
            return ConnectionManager()

    @pytest.mark.asyncio
    async def test_connect_accepts_websocket(self, manager):
        """Manager should accept and track WebSocket connections."""
        mock_ws = AsyncMock()

        connection_id = await manager.connect(
            mock_ws,
            channels=["test-channel"],
            user_id="user-123",
        )

        assert connection_id is not None
        assert manager.connection_count == 1
        mock_ws.accept.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_adds_to_channels(self, manager):
        """Manager should subscribe connection to specified channels."""
        mock_ws = AsyncMock()

        connection_id = await manager.connect(
            mock_ws,
            channels=["channel-a", "channel-b"],
        )

        conn = manager.get_connection(connection_id)
        assert "channel-a" in conn.channels
        assert "channel-b" in conn.channels

    @pytest.mark.asyncio
    async def test_disconnect_removes_connection(self, manager):
        """Manager should remove connection on disconnect."""
        mock_ws = AsyncMock()

        connection_id = await manager.connect(mock_ws)
        assert manager.connection_count == 1

        await manager.disconnect(connection_id)
        assert manager.connection_count == 0

    @pytest.mark.asyncio
    async def test_disconnect_removes_from_channels(self, manager):
        """Disconnect should unsubscribe from all channels."""
        mock_ws = AsyncMock()

        connection_id = await manager.connect(
            mock_ws,
            channels=["my-channel"],
        )

        # Channel should have subscriber
        connections = manager.get_channel_connections("my-channel")
        assert len(connections) == 1

        await manager.disconnect(connection_id)

        # Channel should be empty
        connections = manager.get_channel_connections("my-channel")
        assert len(connections) == 0

    @pytest.mark.asyncio
    async def test_subscribe_adds_to_channel(self, manager):
        """Subscribe should add connection to channel."""
        mock_ws = AsyncMock()

        connection_id = await manager.connect(mock_ws)
        result = await manager.subscribe(connection_id, "new-channel")

        assert result is True
        conn = manager.get_connection(connection_id)
        assert "new-channel" in conn.channels

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_from_channel(self, manager):
        """Unsubscribe should remove connection from channel."""
        mock_ws = AsyncMock()

        connection_id = await manager.connect(
            mock_ws,
            channels=["remove-me"],
        )

        result = await manager.unsubscribe(connection_id, "remove-me")

        assert result is True
        conn = manager.get_connection(connection_id)
        assert "remove-me" not in conn.channels

    @pytest.mark.asyncio
    async def test_send_to_connection(self, manager):
        """Manager should send messages to specific connections."""
        mock_ws = AsyncMock()

        connection_id = await manager.connect(mock_ws)
        result = await manager.send_to_connection(
            connection_id,
            {"type": "test", "data": "hello"},
        )

        assert result is True
        mock_ws.send_json.assert_called_once_with(
            {"type": "test", "data": "hello"}
        )

    @pytest.mark.asyncio
    async def test_send_to_nonexistent_connection(self, manager):
        """Sending to nonexistent connection should return False."""
        result = await manager.send_to_connection(
            "does-not-exist",
            {"type": "test"},
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_broadcast_local_only(self, manager):
        """Broadcast without Redis should send to local connections."""
        mock_ws1 = AsyncMock()
        mock_ws2 = AsyncMock()
        mock_ws3 = AsyncMock()

        # Connect 3 clients, 2 to channel-x
        await manager.connect(mock_ws1, channels=["channel-x"])
        await manager.connect(mock_ws2, channels=["channel-x"])
        await manager.connect(mock_ws3, channels=["other"])

        recipients = await manager.broadcast(
            "channel-x",
            {"type": "update", "data": "broadcast"},
        )

        # Should send to 2 connections
        assert recipients == 2
        mock_ws1.send_json.assert_called()
        mock_ws2.send_json.assert_called()
        mock_ws3.send_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_broadcast_with_exclude(self, manager):
        """Broadcast should skip excluded connections."""
        mock_ws1 = AsyncMock()
        mock_ws2 = AsyncMock()

        conn_id1 = await manager.connect(mock_ws1, channels=["test"])
        await manager.connect(mock_ws2, channels=["test"])

        recipients = await manager.broadcast(
            "test",
            {"type": "message"},
            exclude={conn_id1},
        )

        assert recipients == 1
        mock_ws1.send_json.assert_not_called()
        mock_ws2.send_json.assert_called()

    @pytest.mark.asyncio
    async def test_send_to_user(self, manager):
        """Manager should send to all connections for a user."""
        mock_ws1 = AsyncMock()
        mock_ws2 = AsyncMock()
        mock_ws3 = AsyncMock()

        await manager.connect(mock_ws1, user_id="user-A")
        await manager.connect(mock_ws2, user_id="user-A")
        await manager.connect(mock_ws3, user_id="user-B")

        recipients = await manager.send_to_user(
            "user-A",
            {"type": "notification"},
        )

        assert recipients == 2
        mock_ws1.send_json.assert_called()
        mock_ws2.send_json.assert_called()
        mock_ws3.send_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_connection_count(self, manager):
        """Manager should track connection count."""
        mock_ws = AsyncMock()

        assert manager.connection_count == 0

        conn_id1 = await manager.connect(mock_ws)
        assert manager.connection_count == 1

        conn_id2 = await manager.connect(AsyncMock())
        assert manager.connection_count == 2

        await manager.disconnect(conn_id1)
        assert manager.connection_count == 1

        await manager.disconnect(conn_id2)
        assert manager.connection_count == 0

    @pytest.mark.asyncio
    async def test_channel_count(self, manager):
        """Manager should track active channel count."""
        mock_ws = AsyncMock()

        assert manager.channel_count == 0

        await manager.connect(mock_ws, channels=["ch1", "ch2"])
        assert manager.channel_count == 2

        await manager.connect(AsyncMock(), channels=["ch2", "ch3"])
        assert manager.channel_count == 3  # ch1, ch2, ch3

    @pytest.mark.asyncio
    async def test_max_connections_enforcement(self, manager):
        """Manager should enforce max connections limit."""
        # Create manager with low limit
        from example_service.infra.realtime.manager import ConnectionManager

        with patch(
            "example_service.infra.realtime.manager.get_websocket_settings"
        ) as mock_settings:
            mock_settings.return_value = MagicMock(
                max_connections=2,
                heartbeat_interval=0,
                connection_timeout=0,
            )
            limited_manager = ConnectionManager()

        mock_ws = AsyncMock()
        await limited_manager.connect(mock_ws)
        await limited_manager.connect(AsyncMock())

        # Third connection should be refused
        with pytest.raises(ConnectionRefusedError):
            await limited_manager.connect(AsyncMock())

    @pytest.mark.asyncio
    async def test_get_channel_connections(self, manager):
        """Manager should return all connections in a channel."""
        mock_ws1 = AsyncMock()
        mock_ws2 = AsyncMock()

        conn_id1 = await manager.connect(mock_ws1, channels=["shared"])
        conn_id2 = await manager.connect(mock_ws2, channels=["shared"])

        connections = manager.get_channel_connections("shared")

        assert len(connections) == 2
        conn_ids = {c.connection_id for c in connections}
        assert conn_id1 in conn_ids
        assert conn_id2 in conn_ids


# ──────────────────────────────────────────────────────────────
# Test WebSocket Schemas
# ──────────────────────────────────────────────────────────────


class TestWebSocketSchemas:
    """Tests for WebSocket message schemas."""

    def test_connected_message(self):
        """ConnectedMessage should serialize correctly."""
        from example_service.features.realtime.schemas import ConnectedMessage

        msg = ConnectedMessage(
            connection_id="conn-123",
            channels=["global", "notifications"],
        )

        data = msg.model_dump()
        assert data["type"] == "connected"
        assert data["connection_id"] == "conn-123"
        assert data["channels"] == ["global", "notifications"]

    def test_broadcast_message(self):
        """BroadcastMessage should serialize correctly."""
        from example_service.features.realtime.schemas import BroadcastMessage

        msg = BroadcastMessage(
            channel="updates",
            event_type="item.created",
            data={"id": 123, "name": "Test"},
        )

        data = msg.model_dump()
        assert data["type"] == "broadcast"
        assert data["channel"] == "updates"
        assert data["event_type"] == "item.created"
        assert data["data"]["id"] == 123

    def test_error_message(self):
        """ErrorMessage should serialize correctly."""
        from example_service.features.realtime.schemas import ErrorMessage

        msg = ErrorMessage(
            code="invalid_channel",
            message="Channel does not exist",
            details={"channel": "unknown"},
        )

        data = msg.model_dump()
        assert data["type"] == "error"
        assert data["code"] == "invalid_channel"
        assert data["message"] == "Channel does not exist"
        assert data["details"]["channel"] == "unknown"

    def test_subscribe_message(self):
        """SubscribeMessage should serialize correctly."""
        from example_service.features.realtime.schemas import SubscribeMessage

        msg = SubscribeMessage(channels=["ch1", "ch2", "ch3"])

        data = msg.model_dump()
        assert data["type"] == "subscribe"
        assert len(data["channels"]) == 3
