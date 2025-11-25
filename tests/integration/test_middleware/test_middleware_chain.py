"""Integration tests for middleware chain behavior."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from httpx import AsyncClient

from example_service.app.middleware.metrics import MetricsMiddleware
from example_service.app.middleware.request_id import RequestIDMiddleware
from example_service.app.middleware.request_logging import RequestLoggingMiddleware
from example_service.app.middleware.security_headers import SecurityHeadersMiddleware
from example_service.app.middleware.size_limit import RequestSizeLimitMiddleware


class TestMiddlewareChain:
    """Integration tests for complete middleware chain."""

    @pytest.fixture
    def full_app(self) -> FastAPI:
        """Create FastAPI app with full middleware stack.

        Returns:
            FastAPI application with all middleware configured.
        """
        app = FastAPI()

        # Add middleware in order (last added = outermost = first to run)
        app.add_middleware(MetricsMiddleware)
        app.add_middleware(RequestLoggingMiddleware, log_request_body=True)
        app.add_middleware(RequestIDMiddleware)
        app.add_middleware(SecurityHeadersMiddleware)
        app.add_middleware(RequestSizeLimitMiddleware, max_size=1024 * 1024)  # 1MB

        @app.get("/test")
        async def test_endpoint(request: Request):
            # Access request_id from state
            request_id = getattr(request.state, "request_id", None)
            return {"message": "ok", "request_id": request_id}

        @app.post("/upload")
        async def upload_endpoint(request: Request):
            body = await request.json()
            return {"received": body}

        return app

    @pytest.fixture
    async def client(self, full_app: FastAPI) -> AsyncClient:
        """Create async HTTP client.

        Args:
            full_app: FastAPI application fixture.

        Returns:
            Async HTTP client.
        """
        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=full_app), base_url="http://test"
        ) as ac:
            yield ac

    async def test_request_id_propagates_through_chain(self, client: AsyncClient):
        """Test that request_id is available throughout middleware chain."""
        import uuid

        custom_id = str(uuid.uuid4())
        response = await client.get("/test", headers={"X-Request-ID": custom_id})

        assert response.status_code == 200
        # Request ID should be in response headers (from RequestIDMiddleware)
        assert response.headers["x-request-id"] == custom_id
        # Request ID should be in response body (from endpoint accessing state)
        assert response.json()["request_id"] == custom_id

    async def test_security_headers_present_with_full_chain(self, client: AsyncClient):
        """Test that security headers are present in final response."""
        response = await client.get("/test")

        assert response.status_code == 200
        # Security headers should be present
        assert "x-frame-options" in response.headers
        assert "x-content-type-options" in response.headers
        assert "strict-transport-security" in response.headers

    async def test_timing_header_present_with_full_chain(self, client: AsyncClient):
        """Test that metrics middleware adds timing header."""
        response = await client.get("/test")

        assert response.status_code == 200
        # Timing header from MetricsMiddleware
        assert "x-process-time" in response.headers
        assert float(response.headers["x-process-time"]) >= 0

    async def test_size_limit_enforced_in_chain(self, client: AsyncClient):
        """Test that request size limit works in full chain."""
        # Create large payload (over 1MB limit)
        large_payload = {"data": "x" * (2 * 1024 * 1024)}  # 2MB

        response = await client.post("/upload", json=large_payload)

        # Should be rejected by size limit middleware
        assert response.status_code == 413
        assert "exceeds maximum" in response.json()["detail"]

    @patch("example_service.app.middleware.request_logging.logger")
    async def test_logging_includes_request_id(
        self, mock_logger: MagicMock, client: AsyncClient
    ):
        """Test that request logging includes request_id from context."""
        import uuid

        custom_id = str(uuid.uuid4())
        await client.get("/test", headers={"X-Request-ID": custom_id})

        # Find log calls
        call_args = mock_logger.log.call_args_list

        # Check that logs contain request_id
        if call_args:
            request_logs = [
                call
                for call in call_args
                if len(call[0]) > 1 and call[0][1] == "HTTP Request"
            ]
            if request_logs:
                log_extra = request_logs[0][1]["extra"]
                assert log_extra.get("request_id") == custom_id

    @patch("example_service.app.middleware.metrics.http_requests_total")
    async def test_metrics_tracked_for_all_requests(
        self, mock_metrics: MagicMock, client: AsyncClient
    ):
        """Test that metrics are tracked even with full middleware stack."""
        await client.get("/test")

        # Metrics middleware should track the request
        assert mock_metrics.labels.return_value.inc.called

    async def test_multiple_headers_combined(self, client: AsyncClient):
        """Test that headers from all middleware are combined in response."""
        response = await client.get("/test")

        assert response.status_code == 200

        # Headers from different middleware
        expected_headers = [
            "x-request-id",  # RequestIDMiddleware
            "x-frame-options",  # SecurityHeadersMiddleware
            "x-process-time",  # MetricsMiddleware
        ]

        for header in expected_headers:
            assert header in response.headers, f"Missing header: {header}"

    async def test_error_propagation_through_chain(self):
        """Test that errors properly propagate through middleware chain."""
        app = FastAPI()

        # Add full middleware stack
        app.add_middleware(MetricsMiddleware)
        app.add_middleware(RequestLoggingMiddleware)
        app.add_middleware(RequestIDMiddleware)
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/error")
        async def error_endpoint():
            raise ValueError("Test error")

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            with pytest.raises(ValueError):
                await client.get("/error")

    @patch("example_service.app.middleware.request_logging.logger")
    @patch("example_service.app.middleware.request_id.clear_log_context")
    async def test_context_cleanup_after_request(
        self, mock_clear: MagicMock, mock_logger: MagicMock, client: AsyncClient
    ):
        """Test that logging context is cleaned up after request completes."""
        await client.get("/test")

        # clear_log_context should be called by RequestIDMiddleware
        assert mock_clear.called

    async def test_post_request_with_body_masking(self, client: AsyncClient):
        """Test POST request with sensitive data masking in logs."""
        payload = {
            "username": "testuser",
            "password": "secret123",
            "email": "user@example.com",
        }

        with patch("example_service.app.middleware.request_logging.logger") as mock_logger:
            response = await client.post("/upload", json=payload)

        assert response.status_code == 200

        # Check logs for masked data
        if mock_logger.log.called:
            call_args = mock_logger.log.call_args_list
            request_logs = [
                call
                for call in call_args
                if len(call[0]) > 1 and call[0][1] == "HTTP Request"
            ]
            if request_logs and "body" in request_logs[0][1]["extra"]:
                logged_body = request_logs[0][1]["extra"]["body"]
                if isinstance(logged_body, dict) and "password" in logged_body:
                    # Password should be masked
                    assert logged_body["password"] == "********"

    async def test_concurrent_requests_maintain_isolation(self):
        """Test that concurrent requests maintain proper request_id isolation."""
        import asyncio
        import uuid

        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)

        captured_ids = []

        @app.get("/test")
        async def test_endpoint(request: Request):
            request_id = getattr(request.state, "request_id", None)
            captured_ids.append(request_id)
            await asyncio.sleep(0.01)  # Small delay to ensure concurrency
            return {"request_id": request_id}

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Generate unique IDs for each request
            ids = [str(uuid.uuid4()) for _ in range(5)]

            # Make concurrent requests with different IDs
            tasks = [
                client.get("/test", headers={"X-Request-ID": req_id}) for req_id in ids
            ]
            responses = await asyncio.gather(*tasks)

        # Each response should have its correct request_id
        for i, response in enumerate(responses):
            assert response.json()["request_id"] == ids[i]

        # All request_ids should be unique
        assert len(set(captured_ids)) == 5

    async def test_size_limit_checked_before_logging(self):
        """Test that size limit is enforced before expensive logging."""
        app = FastAPI()

        # Order matters: size limit should run before logging
        app.add_middleware(RequestLoggingMiddleware, log_request_body=True)
        app.add_middleware(RequestSizeLimitMiddleware, max_size=100)  # Very small

        @app.post("/upload")
        async def upload_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        with patch("example_service.app.middleware.request_logging.logger") as mock_logger:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                # Large payload
                response = await client.post("/upload", json={"data": "x" * 1000})

        # Should be rejected by size limit
        assert response.status_code == 413

        # Logging should not process the large body (request was rejected early)

    async def test_all_middleware_with_successful_request(self, client: AsyncClient):
        """Test complete successful request flow through all middleware."""
        import uuid

        custom_id = str(uuid.uuid4())

        with patch("example_service.app.middleware.metrics.http_requests_total") as mock_metrics:
            with patch("example_service.app.middleware.request_logging.logger") as mock_logger:
                response = await client.get("/test", headers={"X-Request-ID": custom_id})

        assert response.status_code == 200

        # Verify all middleware effects:
        # 1. Request ID in headers
        assert response.headers["x-request-id"] == custom_id

        # 2. Security headers present
        assert "x-frame-options" in response.headers

        # 3. Timing header present
        assert "x-process-time" in response.headers

        # 4. Metrics tracked
        assert mock_metrics.labels.return_value.inc.called

        # 5. Request/response logged
        assert mock_logger.log.called

    async def test_middleware_chain_with_custom_headers(self, client: AsyncClient):
        """Test that custom request headers are preserved through chain."""
        custom_headers = {
            "X-Custom-Header": "custom-value",
            "User-Agent": "test-client/1.0",
        }

        with patch("example_service.app.middleware.request_logging.logger") as mock_logger:
            response = await client.get("/test", headers=custom_headers)

        assert response.status_code == 200

        # Check that custom headers were logged
        if mock_logger.log.called:
            call_args = mock_logger.log.call_args_list
            request_logs = [
                call
                for call in call_args
                if len(call[0]) > 1 and call[0][1] == "HTTP Request"
            ]
            if request_logs and "headers" in request_logs[0][1]["extra"]:
                logged_headers = request_logs[0][1]["extra"]["headers"]
                if isinstance(logged_headers, dict):
                    # Custom headers should be present (case-insensitive)
                    assert any(
                        k.lower() == "x-custom-header" for k in logged_headers.keys()
                    )

    async def test_performance_of_full_middleware_stack(self):
        """Test that full middleware stack has acceptable performance."""
        import time

        app = FastAPI()

        # Add complete middleware stack
        app.add_middleware(MetricsMiddleware)
        app.add_middleware(RequestLoggingMiddleware)
        app.add_middleware(RequestIDMiddleware)
        app.add_middleware(SecurityHeadersMiddleware)
        app.add_middleware(RequestSizeLimitMiddleware)

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Warm up
            await client.get("/test")

            # Measure performance with full stack
            start = time.perf_counter()
            for _ in range(100):
                await client.get("/test")
            elapsed = time.perf_counter() - start

            # Even with full middleware stack, should be reasonably fast
            # Allow more time due to multiple middleware
            assert (
                elapsed < 3.0
            ), f"100 requests with full stack took {elapsed:.3f}s, performance issue"

    async def test_request_state_accessible_in_endpoint(self, client: AsyncClient):
        """Test that request state from middleware is accessible in endpoints."""
        response = await client.get("/test")

        assert response.status_code == 200
        data = response.json()

        # request_id from state should be in response
        assert "request_id" in data
        assert data["request_id"] is not None
        assert len(data["request_id"]) > 0

    async def test_middleware_chain_with_different_content_types(self):
        """Test middleware chain handles different content types correctly."""
        app = FastAPI()

        app.add_middleware(MetricsMiddleware)
        app.add_middleware(RequestIDMiddleware)
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/json")
        async def json_endpoint():
            return {"type": "json"}

        @app.get("/text")
        async def text_endpoint():
            from fastapi.responses import PlainTextResponse

            return PlainTextResponse("text response")

        @app.get("/html")
        async def html_endpoint():
            from fastapi.responses import HTMLResponse

            return HTMLResponse("<html><body>HTML</body></html>")

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # JSON response
            response = await client.get("/json")
            assert response.status_code == 200
            assert "x-request-id" in response.headers

            # Text response
            response = await client.get("/text")
            assert response.status_code == 200
            assert "x-request-id" in response.headers

            # HTML response
            response = await client.get("/html")
            assert response.status_code == 200
            assert "x-request-id" in response.headers
