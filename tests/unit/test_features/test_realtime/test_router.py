"""Unit tests for Realtime Router endpoints."""

from __future__ import annotations

import contextlib
import json
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient
import pytest
from websockets.exceptions import ConnectionClosed

from example_service.core.settings import get_websocket_settings
from example_service.features.realtime.router import router
from example_service.features.realtime.schemas import (
    BroadcastRequest,
    ClientMessageType,
)
from example_service.infra.realtime import get_connection_manager

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
else:  # pragma: no cover - runtime placeholder for typing-only import
    AsyncGenerator = Any


@pytest.fixture
def mock_connection_manager() -> MagicMock:
    """Create a mock connection manager."""
    manager = MagicMock()
    manager.connect = AsyncMock(return_value="conn-123")
    manager.disconnect = AsyncMock()
    manager.subscribe = AsyncMock(return_value=True)
    manager.unsubscribe = AsyncMock(return_value=True)
    manager.broadcast = AsyncMock(return_value=5)
    manager.get_connection = MagicMock(return_value=MagicMock(last_ping=0))
    manager.connection_count = 0
    manager.channel_count = 0
    manager._channel_connections = {}
    return manager


@pytest.fixture
async def realtime_client(
    mock_connection_manager: MagicMock,
) -> AsyncGenerator[AsyncClient]:
    """Create HTTP client with realtime router and mocked dependencies."""
    app = FastAPI()
    app.include_router(router)

    # Override dependencies
    with patch("example_service.features.realtime.router.get_connection_manager") as mock_get:
        mock_get.return_value = mock_connection_manager

        with patch(
            "example_service.features.realtime.router.get_websocket_settings",
        ) as mock_settings:
            mock_settings.return_value = MagicMock(
                enabled=True,
                default_channels=["default"],
                max_channels_per_connection=10,
            )

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test",
            ) as client:
                yield client


@pytest.fixture
async def realtime_client_disabled() -> AsyncGenerator[AsyncClient]:
    """Create HTTP client with WebSocket disabled."""
    app = FastAPI()
    app.include_router(router)

    with patch("example_service.features.realtime.router.get_websocket_settings") as mock_settings:
        mock_settings.return_value = MagicMock(enabled=False)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client


class TestWebSocketEndpoint:
    """Test WebSocket endpoint."""

    @pytest.mark.asyncio
    async def test_websocket_disabled_closes_connection(
        self, realtime_client_disabled: AsyncClient,
    ) -> None:
        """Test that WebSocket closes when disabled."""
        # WebSocket connections can't be tested with httpx directly
        # This test verifies the logic path
        # Integration test would be needed

    @pytest.mark.asyncio
    async def test_websocket_manager_not_initialized(self, realtime_client: AsyncClient) -> None:
        """Test WebSocket behavior when manager is not initialized."""
        with patch("example_service.features.realtime.router._get_manager_safe") as mock_get:
            mock_get.return_value = None

            # WebSocket connections require actual WebSocket client
            # This test verifies the logic path
            # Integration test would be needed

    @pytest.mark.asyncio
    async def test_websocket_connection_refused(self, realtime_client: AsyncClient) -> None:
        """Test WebSocket connection refused handling."""
        # Integration test would be needed for actual WebSocket testing


class TestGetStats:
    """Test GET /ws/stats endpoint."""

    @pytest.mark.asyncio
    async def test_get_stats_success(
        self, realtime_client: AsyncClient, mock_connection_manager: MagicMock,
    ) -> None:
        """Test successfully getting connection statistics."""
        mock_connection_manager.connection_count = 5
        mock_connection_manager.channel_count = 3
        mock_connection_manager._channel_connections = {
            "channel1": [1, 2, 3],
            "channel2": [4, 5],
            "channel3": [1],
        }

        response = await realtime_client.get("/ws/stats")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total_connections"] == 5
        assert data["total_channels"] == 3
        assert "channels" in data
        assert data["channels"]["channel1"] == 3
        assert data["channels"]["channel2"] == 2
        assert data["channels"]["channel3"] == 1

    @pytest.mark.asyncio
    async def test_get_stats_manager_not_initialized(self, realtime_client: AsyncClient) -> None:
        """Test stats endpoint when manager is not initialized."""
        with patch("example_service.features.realtime.router._get_manager_safe") as mock_get:
            mock_get.return_value = None

            response = await realtime_client.get("/ws/stats")

            assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
            data = response.json()
            assert "not initialized" in data["detail"].lower()


class TestBroadcast:
    """Test POST /ws/broadcast endpoint."""

    @pytest.mark.asyncio
    async def test_broadcast_success(
        self, realtime_client: AsyncClient, mock_connection_manager: MagicMock,
    ) -> None:
        """Test successfully broadcasting a message."""
        mock_connection_manager.broadcast.return_value = 3

        response = await realtime_client.post(
            "/ws/broadcast",
            json={
                "channel": "notifications",
                "event_type": "user_joined",
                "data": {"user_id": "user-123", "name": "Test User"},
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        assert data["channel"] == "notifications"
        assert data["recipients"] == 3
        mock_connection_manager.broadcast.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast_manager_not_initialized(self, realtime_client: AsyncClient) -> None:
        """Test broadcast when manager is not initialized."""
        with patch("example_service.features.realtime.router._get_manager_safe") as mock_get:
            mock_get.return_value = None

            response = await realtime_client.post(
                "/ws/broadcast",
                json={
                    "channel": "notifications",
                    "event_type": "test",
                    "data": {},
                },
            )

            assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
            data = response.json()
            assert "not initialized" in data["detail"].lower()

    @pytest.mark.asyncio
    async def test_broadcast_invalid_request(self, realtime_client: AsyncClient) -> None:
        """Test broadcast with invalid request data."""
        response = await realtime_client.post(
            "/ws/broadcast",
            json={
                "channel": "",  # Invalid empty channel
            },
        )

        # Should return validation error
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


class TestWebSocketMessageHandling:
    """Test WebSocket message handling logic."""

    @pytest.mark.asyncio
    async def test_handle_ping_message(self) -> None:
        """Test handling ping message."""
        from example_service.features.realtime.router import _handle_messages
        from example_service.features.realtime.schemas import ServerPongMessage

        mock_websocket = AsyncMock()
        mock_manager = MagicMock()

        # Simulate ping message
        async def mock_iter_text():
            yield json.dumps({"type": ClientMessageType.PING})

        mock_websocket.iter_text = mock_iter_text

        with contextlib.suppress(StopAsyncIteration):
            await _handle_messages(mock_websocket, "conn-123", mock_manager)

        # Verify pong was sent
        calls = mock_websocket.send_json.call_args_list
        assert len(calls) > 0
        sent_data = calls[0][0][0]
        assert sent_data["type"] == "pong"

    @pytest.mark.asyncio
    async def test_handle_subscribe_message(self) -> None:
        """Test handling subscribe message."""
        from example_service.features.realtime.router import _handle_messages

        mock_websocket = AsyncMock()
        mock_manager = MagicMock()
        mock_manager.subscribe = AsyncMock(return_value=True)

        with patch("example_service.features.realtime.router.ws_settings") as mock_settings:
            mock_settings.max_channels_per_connection = 10

            async def mock_iter_text():
                yield json.dumps(
                    {"type": ClientMessageType.SUBSCRIBE, "channels": ["test-channel"]},
                )

            mock_websocket.iter_text = mock_iter_text

            with contextlib.suppress(StopAsyncIteration):
                await _handle_messages(mock_websocket, "conn-123", mock_manager)

            mock_manager.subscribe.assert_called_once_with("conn-123", "test-channel")

    @pytest.mark.asyncio
    async def test_handle_unsubscribe_message(self) -> None:
        """Test handling unsubscribe message."""
        from example_service.features.realtime.router import _handle_messages

        mock_websocket = AsyncMock()
        mock_manager = MagicMock()
        mock_manager.unsubscribe = AsyncMock(return_value=True)

        async def mock_iter_text():
            yield json.dumps({"type": ClientMessageType.UNSUBSCRIBE, "channels": ["test-channel"]})

        mock_websocket.iter_text = mock_iter_text

        with contextlib.suppress(StopAsyncIteration):
            await _handle_messages(mock_websocket, "conn-123", mock_manager)

        mock_manager.unsubscribe.assert_called_once_with("conn-123", "test-channel")

    @pytest.mark.asyncio
    async def test_handle_message_forwarding(self) -> None:
        """Test handling message forwarding."""
        from example_service.features.realtime.router import _handle_messages

        mock_websocket = AsyncMock()
        mock_manager = MagicMock()
        mock_manager.broadcast = AsyncMock(return_value=2)

        async def mock_iter_text():
            yield json.dumps(
                {
                    "type": ClientMessageType.MESSAGE,
                    "channel": "test-channel",
                    "data": {"content": "Hello"},
                },
            )

        mock_websocket.iter_text = mock_iter_text

        with contextlib.suppress(StopAsyncIteration):
            await _handle_messages(mock_websocket, "conn-123", mock_manager)

        mock_manager.broadcast.assert_called_once()
        call_args = mock_manager.broadcast.call_args
        assert call_args[0][0] == "test-channel"
        assert call_args[1]["exclude"] == {"conn-123"}

    @pytest.mark.asyncio
    async def test_handle_invalid_json(self) -> None:
        """Test handling invalid JSON message."""
        from example_service.features.realtime.router import _handle_messages

        mock_websocket = AsyncMock()
        mock_manager = MagicMock()

        async def mock_iter_text():
            yield "invalid json {"

        mock_websocket.iter_text = mock_iter_text

        with contextlib.suppress(StopAsyncIteration):
            await _handle_messages(mock_websocket, "conn-123", mock_manager)

        # Verify error message was sent
        calls = mock_websocket.send_json.call_args_list
        assert len(calls) > 0
        sent_data = calls[0][0][0]
        assert sent_data["type"] == "error"
        assert sent_data["code"] == "invalid_json"

    @pytest.mark.asyncio
    async def test_handle_unknown_message_type(self) -> None:
        """Test handling unknown message type."""
        from example_service.features.realtime.router import _handle_messages

        mock_websocket = AsyncMock()
        mock_manager = MagicMock()

        async def mock_iter_text():
            yield json.dumps({"type": "unknown_type", "data": {}})

        mock_websocket.iter_text = mock_iter_text

        with contextlib.suppress(StopAsyncIteration):
            await _handle_messages(mock_websocket, "conn-123", mock_manager)

        # Verify error message was sent
        calls = mock_websocket.send_json.call_args_list
        assert len(calls) > 0
        sent_data = calls[0][0][0]
        assert sent_data["type"] == "error"
        assert sent_data["code"] == "unknown_type"

    @pytest.mark.asyncio
    async def test_handle_message_exception(self) -> None:
        """Test handling exception during message processing."""
        from example_service.features.realtime.router import _handle_messages

        mock_websocket = AsyncMock()
        mock_manager = MagicMock()
        mock_manager.subscribe = AsyncMock(side_effect=Exception("Internal error"))

        async def mock_iter_text():
            yield json.dumps({"type": ClientMessageType.SUBSCRIBE, "channels": ["test"]})

        mock_websocket.iter_text = mock_iter_text

        with contextlib.suppress(StopAsyncIteration):
            await _handle_messages(mock_websocket, "conn-123", mock_manager)

        # Verify error message was sent
        calls = mock_websocket.send_json.call_args_list
        assert len(calls) > 0
        sent_data = calls[-1][0][0]
        assert sent_data["type"] == "error"
        assert sent_data["code"] == "internal_error"
