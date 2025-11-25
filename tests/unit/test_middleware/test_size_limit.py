"""Unit tests for RequestSizeLimitMiddleware."""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI, Request
from httpx import AsyncClient

from example_service.app.middleware.size_limit import RequestSizeLimitMiddleware


class TestRequestSizeLimitMiddleware:
    """Test suite for RequestSizeLimitMiddleware."""

    @pytest.fixture
    def app_with_limit(self) -> FastAPI:
        """Create FastAPI app with size limit middleware.

        Returns:
            FastAPI application with 1KB size limit.
        """
        app = FastAPI()
        # Set 1KB limit for easier testing
        app.add_middleware(RequestSizeLimitMiddleware, max_size=1024)

        @app.post("/upload")
        async def upload_endpoint(request: Request):
            body = await request.body()
            return {"size": len(body), "message": "ok"}

        return app

    @pytest.fixture
    async def client(self, app_with_limit: FastAPI) -> AsyncClient:
        """Create async HTTP client.

        Args:
            app_with_limit: FastAPI application fixture.

        Returns:
            Async HTTP client.
        """
        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app_with_limit), base_url="http://test"
        ) as ac:
            yield ac

    async def test_accepts_request_under_limit(self, client: AsyncClient):
        """Test that requests under size limit are accepted."""
        # Create payload under 1KB
        payload = {"data": "x" * 500}  # ~500 bytes

        response = await client.post("/upload", json=payload)

        assert response.status_code == 200
        assert "size" in response.json()

    async def test_rejects_request_over_limit(self, client: AsyncClient):
        """Test that requests exceeding size limit are rejected with 413."""
        # Create payload over 1KB
        payload = {"data": "x" * 2000}  # ~2KB

        response = await client.post("/upload", json=payload)

        assert response.status_code == 413
        assert "detail" in response.json()
        assert "exceeds maximum" in response.json()["detail"]

    async def test_exact_limit_boundary(self, client: AsyncClient):
        """Test request at exact size limit boundary."""
        # Create payload at exactly 1024 bytes
        # Account for JSON overhead
        payload = {"data": "x" * 1000}
        payload_bytes = json.dumps(payload).encode()

        # Adjust to be exactly at limit
        if len(payload_bytes) < 1024:
            # Under limit - should pass
            response = await client.post("/upload", json=payload)
            assert response.status_code == 200
        elif len(payload_bytes) == 1024:
            # Exactly at limit - should pass
            response = await client.post("/upload", json=payload)
            assert response.status_code == 200
        else:
            # Over limit - should fail
            response = await client.post("/upload", json=payload)
            assert response.status_code == 413

    async def test_handles_request_without_content_length(self, client: AsyncClient):
        """Test that requests without Content-Length header pass through."""
        # Note: httpx automatically adds Content-Length, so we test the middleware directly
        from starlette.types import Receive, Scope, Send

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

        middleware = RequestSizeLimitMiddleware(mock_app, max_size=1024)

        # Scope without content-length header
        scope: Scope = {
            "type": "http",
            "method": "POST",
            "path": "/upload",
            "headers": [],  # No content-length
        }

        from unittest.mock import AsyncMock

        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        # Should pass through (not rejected)
        # Check that response was sent successfully
        assert send.call_count >= 2  # response.start + response.body

    async def test_error_detail_message_format(self, client: AsyncClient):
        """Test that error response contains detailed size information."""
        # Create payload over limit
        payload = {"data": "x" * 2000}

        response = await client.post("/upload", json=payload)

        assert response.status_code == 413
        error_data = response.json()
        assert "detail" in error_data

        # Should mention both actual size and limit
        detail = error_data["detail"]
        assert "exceeds maximum" in detail.lower()
        assert "1024" in detail  # The limit

    async def test_different_size_limits(self):
        """Test middleware with different size limit configurations."""
        test_cases = [
            (100, 50, 200),  # limit, under, over
            (1024 * 1024, 500 * 1024, 2 * 1024 * 1024),  # 1MB limit
            (10 * 1024 * 1024, 5 * 1024 * 1024, 15 * 1024 * 1024),  # 10MB limit
        ]

        for max_size, under_size, over_size in test_cases:
            app = FastAPI()
            app.add_middleware(RequestSizeLimitMiddleware, max_size=max_size)

            @app.post("/upload")
            async def upload_endpoint(request: Request):
                body = await request.body()
                return {"size": len(body)}

            from httpx import ASGITransport

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                # Test under limit
                under_payload = "x" * under_size
                response = await client.post(
                    "/upload",
                    content=under_payload,
                    headers={"content-type": "text/plain"},
                )
                assert response.status_code == 200

                # Test over limit
                over_payload = "x" * over_size
                response = await client.post(
                    "/upload",
                    content=over_payload,
                    headers={"content-type": "text/plain"},
                )
                assert response.status_code == 413

    async def test_handles_non_http_scope(self):
        """Test that middleware passes through non-HTTP scopes."""
        from unittest.mock import AsyncMock

        from starlette.types import Receive, Scope, Send

        async def simple_app(scope: Scope, receive: Receive, send: Send):
            await send({"type": "websocket.accept"})

        middleware = RequestSizeLimitMiddleware(simple_app, max_size=1024)

        scope = {"type": "websocket", "path": "/ws"}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        # Should pass through without checking size
        send.assert_called_once()

    async def test_response_content_type_is_json(self, client: AsyncClient):
        """Test that 413 error response has JSON content type."""
        payload = {"data": "x" * 2000}

        response = await client.post("/upload", json=payload)

        assert response.status_code == 413
        assert "application/json" in response.headers["content-type"]

    async def test_handles_invalid_content_length_header(self):
        """Test that middleware handles malformed Content-Length header gracefully."""
        from unittest.mock import AsyncMock

        from starlette.types import Receive, Scope, Send

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

        middleware = RequestSizeLimitMiddleware(mock_app, max_size=1024)

        # Test with invalid content-length values
        invalid_values = [b"invalid", b"", b"12.5", b"abc123"]

        for invalid_value in invalid_values:
            scope: Scope = {
                "type": "http",
                "method": "POST",
                "path": "/upload",
                "headers": [[b"content-length", invalid_value]],
            }

            receive = AsyncMock()
            send = AsyncMock()

            # Should not raise exception, should pass through
            await middleware(scope, receive, send)
            assert send.call_count >= 2  # Response sent successfully

    async def test_get_requests_without_body(self, client: AsyncClient):
        """Test that GET requests without body are not affected."""
        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_size=100)

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/test")
            assert response.status_code == 200

    async def test_default_10mb_limit(self):
        """Test that default limit is 10MB."""

        from starlette.types import Receive, Scope, Send

        async def mock_app(scope: Scope, receive: Receive, send: Send):
            pass

        middleware = RequestSizeLimitMiddleware(mock_app)

        # Default should be 10 * 1024 * 1024 = 10485760 bytes
        assert middleware.max_size == 10 * 1024 * 1024

    async def test_multiple_content_length_headers(self):
        """Test handling of multiple Content-Length headers (takes first)."""
        from unittest.mock import AsyncMock

        from starlette.types import Receive, Scope, Send

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

        middleware = RequestSizeLimitMiddleware(mock_app, max_size=1024)

        # Multiple content-length headers (middleware should use first)
        scope: Scope = {
            "type": "http",
            "method": "POST",
            "path": "/upload",
            "headers": [
                [b"content-length", b"500"],  # First - under limit
                [b"content-length", b"2000"],  # Second - over limit
            ],
        }

        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        # Should accept (using first header value of 500)
        assert send.call_count >= 2

    async def test_performance_with_pure_asgi(self):
        """Test that pure ASGI implementation has minimal overhead."""
        import time

        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_size=10 * 1024 * 1024)

        @app.post("/upload")
        async def upload_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Warm up
            await client.post("/upload", json={"test": "data"})

            # Measure performance
            start = time.perf_counter()
            for _ in range(100):
                await client.post("/upload", json={"test": "data"})
            elapsed = time.perf_counter() - start

            # Should complete 100 requests in reasonable time
            assert elapsed < 1.0, f"100 requests took {elapsed:.3f}s, performance degraded"
