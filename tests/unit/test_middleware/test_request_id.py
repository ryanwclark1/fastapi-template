"""Unit tests for RequestIDMiddleware."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from httpx import AsyncClient

from example_service.app.middleware.request_id import RequestIDMiddleware


class TestRequestIDMiddleware:
    """Test suite for RequestIDMiddleware."""

    @pytest.fixture
    def app(self) -> FastAPI:
        """Create a minimal FastAPI app with RequestIDMiddleware.

        Returns:
            FastAPI application with middleware.
        """
        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        return app

    @pytest.fixture
    async def client(self, app: FastAPI) -> AsyncClient:
        """Create an async HTTP client.

        Args:
            app: FastAPI application fixture.

        Returns:
            Async HTTP client.
        """
        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac

    async def test_generates_request_id_when_not_provided(self, client: AsyncClient):
        """Test that middleware generates UUID when X-Request-ID header not provided."""
        response = await client.get("/test")

        assert response.status_code == 200
        assert "x-request-id" in response.headers

        # Validate it's a proper UUID
        request_id = response.headers["x-request-id"]
        try:
            uuid.UUID(request_id)
        except ValueError:
            pytest.fail(f"Invalid UUID format: {request_id}")

    async def test_preserves_existing_request_id(self, client: AsyncClient):
        """Test that middleware preserves X-Request-ID from incoming request."""
        custom_id = str(uuid.uuid4())

        response = await client.get("/test", headers={"X-Request-ID": custom_id})

        assert response.status_code == 200
        assert response.headers["x-request-id"] == custom_id

    async def test_request_id_in_response_header(self, client: AsyncClient):
        """Test that X-Request-ID is included in response headers."""
        response = await client.get("/test")

        assert "x-request-id" in response.headers
        assert len(response.headers["x-request-id"]) > 0

    @patch("example_service.app.middleware.base.set_log_context")
    async def test_sets_logging_context(self, mock_set_context: MagicMock, client: AsyncClient):
        """Test that middleware sets logging context with request_id."""
        custom_id = str(uuid.uuid4())

        await client.get("/test", headers={"X-Request-ID": custom_id})

        # Verify set_log_context was called with the request_id
        mock_set_context.assert_called()
        call_args = mock_set_context.call_args
        assert call_args is not None
        assert call_args[1].get("request_id") == custom_id

    @patch("example_service.app.middleware.base.clear_log_context")
    async def test_clears_logging_context_after_request(
        self, mock_clear_context: MagicMock, client: AsyncClient
    ):
        """Test that middleware clears logging context after request completes."""
        await client.get("/test")

        # Verify clear_log_context was called
        mock_clear_context.assert_called_once()

    @patch("example_service.app.middleware.base.clear_log_context")
    async def test_clears_context_on_error(
        self, mock_clear_context: MagicMock
    ):
        """Test that middleware clears context even when handler raises exception."""
        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)

        @app.get("/error")
        async def error_endpoint():
            raise ValueError("Test error")

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            with pytest.raises(ValueError):
                await client.get("/error")

        # Verify clear_log_context was called despite the error
        mock_clear_context.assert_called_once()

    async def test_request_id_available_in_scope_state(self):
        """Test that request_id is stored in scope state for downstream access."""
        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)

        captured_request_id = None

        @app.get("/test")
        async def test_endpoint(request: Request):
            nonlocal captured_request_id
            captured_request_id = getattr(request.state, "request_id", None)
            return {"message": "ok"}

        from httpx import ASGITransport

        custom_id = str(uuid.uuid4())
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/test", headers={"X-Request-ID": custom_id})

        assert response.status_code == 200
        assert captured_request_id == custom_id

    async def test_handles_non_http_scope(self):
        """Test that middleware passes through non-HTTP scopes (websocket, lifespan)."""
        from starlette.types import Receive, Scope, Send

        # Create a simple ASGI app
        async def simple_app(scope: Scope, receive: Receive, send: Send):
            await send({"type": "websocket.accept"})

        # Wrap with middleware
        middleware = RequestIDMiddleware(simple_app)

        # Test with websocket scope
        scope = {"type": "websocket", "path": "/ws"}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        # Should pass through to app without modification
        send.assert_called_once()

    async def test_handles_missing_headers(self):
        """Test that middleware handles requests with no headers gracefully."""
        from starlette.types import Receive, Scope, Send

        # Mock ASGI app
        async def mock_app(scope: Scope, receive: Receive, send: Send):
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [[b"content-type", b"application/json"]],
            })
            await send({
                "type": "http.response.body",
                "body": b'{"status":"ok"}',
            })

        middleware = RequestIDMiddleware(mock_app)

        # Scope with no headers
        scope: Scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "headers": [],  # No headers
            "state": {},
        }

        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        # Should generate a request_id
        assert "request_id" in scope["state"]
        assert isinstance(scope["state"]["request_id"], str)

    async def test_case_insensitive_header_handling(self, client: AsyncClient):
        """Test that middleware handles X-Request-ID header case-insensitively."""
        custom_id = str(uuid.uuid4())

        # Test with lowercase header
        response = await client.get("/test", headers={"x-request-id": custom_id})
        assert response.headers["x-request-id"] == custom_id

    async def test_multiple_requests_have_different_ids(self, client: AsyncClient):
        """Test that each request without X-Request-ID gets unique ID."""
        response1 = await client.get("/test")
        response2 = await client.get("/test")

        id1 = response1.headers["x-request-id"]
        id2 = response2.headers["x-request-id"]

        assert id1 != id2

        # Both should be valid UUIDs
        uuid.UUID(id1)
        uuid.UUID(id2)

    async def test_performance_with_pure_asgi(self):
        """Test that pure ASGI implementation has minimal overhead."""
        import time

        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Warm up
            await client.get("/test")

            # Measure performance
            start = time.perf_counter()
            for _ in range(100):
                await client.get("/test")
            elapsed = time.perf_counter() - start

            # Should complete 100 requests in reasonable time (< 1 second)
            assert elapsed < 1.0, f"100 requests took {elapsed:.3f}s, performance degraded"
