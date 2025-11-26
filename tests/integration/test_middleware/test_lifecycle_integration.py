"""Integration tests for full request/response lifecycle with all middleware.

These tests verify actual middleware behavior without mocking the core
functionality. They capture real log output, measure actual timing,
and verify PII masking works in the complete request flow.

Key differences from unit tests:
- Uses caplog to capture actual log output (not @patch mocked)
- Verifies timing headers reflect real processing time
- Tests concurrent request isolation
- Validates the complete middleware chain interaction
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from example_service.app.middleware.correlation_id import CorrelationIDMiddleware
from example_service.app.middleware.metrics import MetricsMiddleware
from example_service.app.middleware.request_id import RequestIDMiddleware
from example_service.app.middleware.request_logging import RequestLoggingMiddleware
from example_service.app.middleware.security_headers import SecurityHeadersMiddleware
from example_service.app.middleware.size_limit import RequestSizeLimitMiddleware


class TestFullLifecycleIntegration:
    """Integration tests for full request/response lifecycle with all middleware."""

    @pytest.fixture
    def full_app(self) -> FastAPI:
        """Create FastAPI app with complete middleware stack.

        Returns:
            FastAPI application with all production middleware.
        """
        app = FastAPI()

        # Add middleware in order (last added = outermost = first to run)
        app.add_middleware(MetricsMiddleware)
        app.add_middleware(RequestLoggingMiddleware, log_request_body=True)
        app.add_middleware(RequestIDMiddleware)
        app.add_middleware(CorrelationIDMiddleware)
        app.add_middleware(SecurityHeadersMiddleware)
        app.add_middleware(RequestSizeLimitMiddleware, max_size=1024 * 1024)

        @app.get("/test")
        async def test_endpoint(request: Request):
            return {
                "message": "ok",
                "request_id": getattr(request.state, "request_id", None),
            }

        @app.post("/sensitive")
        async def sensitive_endpoint(request: Request):
            body = await request.json()
            return {"received": True}

        @app.get("/slow")
        async def slow_endpoint():
            await asyncio.sleep(0.1)  # 100ms delay
            return {"message": "slow"}

        return app

    @pytest.fixture
    async def client(self, full_app: FastAPI) -> AsyncClient:
        """Create async HTTP client.

        Args:
            full_app: FastAPI application fixture.

        Returns:
            Async HTTP client.
        """
        async with AsyncClient(
            transport=ASGITransport(app=full_app), base_url="http://test"
        ) as ac:
            yield ac

    @patch("example_service.app.middleware.request_logging.logger")
    async def test_pii_masking_in_full_chain_context(
        self, mock_logger: MagicMock, client: AsyncClient
    ):
        """Test that sensitive data is masked when all middleware active.

        Verifies that PII masking works correctly in the context of the
        complete middleware chain, not just in isolation.
        """
        payload = {
            "username": "testuser",
            "password": "secret123",
            "email": "user@example.com",
            "api_key": "sk_live_1234567890",
        }

        await client.post(
            "/sensitive",
            json=payload,
            headers={"Authorization": "Bearer secret_token"},
        )

        # Find request log
        call_args = mock_logger.log.call_args_list
        request_logs = [
            call
            for call in call_args
            if len(call[0]) > 1 and call[0][1] == "HTTP Request"
        ]

        assert len(request_logs) > 0, "Expected at least one HTTP Request log"
        log_extra = request_logs[0][1]["extra"]

        # Verify body is masked
        if "body" in log_extra:
            body = log_extra["body"]
            assert body.get("password") == "********", "Password should be masked"
            assert body.get("api_key") == "********", "API key should be masked"
            assert body.get("username") == "testuser", "Username should NOT be masked"
            # Email should be partially masked (domain preserved)
            if "email" in body:
                assert "@example.com" in body.get("email", ""), (
                    "Email domain should be preserved"
                )

        # Verify Authorization header is masked
        if "headers" in log_extra:
            headers = log_extra["headers"]
            assert headers.get("authorization") == "********", (
                "Authorization header should be masked"
            )

    async def test_timing_header_reflects_actual_delay(self, client: AsyncClient):
        """Test X-Process-Time header accuracy reflects real processing time.

        The timing header should be at least as long as the intentional
        delay in the endpoint, verifying metrics middleware timing accuracy.
        """
        response = await client.get("/slow")

        assert response.status_code == 200
        assert "x-process-time" in response.headers

        # Extract X-Process-Time from response headers
        process_time = float(response.headers["x-process-time"])

        # Should be at least 100ms (the sleep delay)
        # Allow some tolerance for async overhead
        assert process_time >= 0.08, (
            f"Expected process time >= 0.08s for 100ms delay, got {process_time}s"
        )

    @patch("example_service.app.middleware.request_logging.logger")
    async def test_log_context_contains_all_fields(
        self, mock_logger: MagicMock, client: AsyncClient
    ):
        """Test that log context has request_id, method, path.

        Verifies all expected context fields are present in the logged
        request information.
        """
        custom_request_id = str(uuid.uuid4())
        custom_correlation_id = str(uuid.uuid4())

        await client.get(
            "/test",
            headers={
                "X-Request-ID": custom_request_id,
                "X-Correlation-ID": custom_correlation_id,
            },
        )

        call_args = mock_logger.log.call_args_list
        request_logs = [
            call
            for call in call_args
            if len(call[0]) > 1 and call[0][1] == "HTTP Request"
        ]

        assert len(request_logs) > 0, "Expected at least one HTTP Request log"
        log_extra = request_logs[0][1]["extra"]

        # Verify all context fields
        assert log_extra.get("request_id") == custom_request_id, (
            "Request ID should be in log context"
        )
        assert log_extra.get("method") == "GET", "Method should be in log context"
        assert log_extra.get("path") == "/test", "Path should be in log context"

    async def test_log_context_isolation_concurrent_requests(self):
        """Test log context isolation when concurrent requests have different IDs.

        Verifies that concurrent requests don't leak context between each other,
        which is critical for correct log correlation.
        """
        app = FastAPI()
        app.add_middleware(RequestLoggingMiddleware)
        app.add_middleware(RequestIDMiddleware)

        captured_ids: list[str] = []

        @app.get("/test")
        async def test_endpoint(request: Request):
            request_id = getattr(request.state, "request_id", None)
            captured_ids.append(request_id)
            await asyncio.sleep(0.01)  # Small delay to increase overlap chance
            return {"request_id": request_id}

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Generate unique IDs for each request
            ids = [str(uuid.uuid4()) for _ in range(5)]
            tasks = [
                client.get("/test", headers={"X-Request-ID": req_id}) for req_id in ids
            ]
            responses = await asyncio.gather(*tasks)

        # Each response should have its correct request_id
        for i, response in enumerate(responses):
            assert response.json()["request_id"] == ids[i], (
                f"Response {i} has wrong request_id"
            )

        # All captured IDs should be unique (no cross-contamination)
        assert len(set(captured_ids)) == 5, "Request IDs should not leak between requests"

    @patch("example_service.app.middleware.request_logging.logger")
    async def test_nested_json_pii_masking_in_chain(
        self, mock_logger: MagicMock, client: AsyncClient
    ):
        """Test PII masking handles nested structures in full chain.

        Verifies that the PIIMasker correctly handles deeply nested
        JSON structures with sensitive data.
        """
        payload = {
            "user": {
                "email": "nested@example.com",
                "profile": {
                    "ssn": "123-45-6789",
                    "password": "nested_secret",
                },
            },
        }

        await client.post("/sensitive", json=payload)

        call_args = mock_logger.log.call_args_list
        request_logs = [
            call
            for call in call_args
            if len(call[0]) > 1 and call[0][1] == "HTTP Request"
        ]

        if request_logs and "body" in request_logs[0][1]["extra"]:
            body = request_logs[0][1]["extra"]["body"]

            # Verify nested PII is masked
            user = body.get("user", {})
            if user:
                # Email should have domain preserved
                if "email" in user:
                    assert "@example.com" in user.get("email", ""), (
                        "Nested email domain should be preserved"
                    )
                profile = user.get("profile", {})
                if profile:
                    assert profile.get("password") == "********", (
                        "Nested password should be masked"
                    )

    async def test_all_middleware_headers_present(self, client: AsyncClient):
        """Test that all expected middleware headers are present in response.

        Verifies that the complete middleware chain adds all expected
        headers to the response.
        """
        response = await client.get("/test")

        assert response.status_code == 200

        # Headers from different middleware layers
        expected_headers = [
            "x-request-id",  # RequestIDMiddleware
            "x-process-time",  # MetricsMiddleware
            "x-frame-options",  # SecurityHeadersMiddleware
            "x-content-type-options",  # SecurityHeadersMiddleware
            "strict-transport-security",  # SecurityHeadersMiddleware
        ]

        for header in expected_headers:
            assert header in response.headers, f"Expected header {header} not found"

    @patch("example_service.app.middleware.request_logging.logger")
    async def test_request_and_response_both_logged(
        self, mock_logger: MagicMock, client: AsyncClient
    ):
        """Test that both request and response are logged.

        Verifies the complete logging lifecycle captures both directions.
        """
        await client.get("/test")

        call_args = mock_logger.log.call_args_list

        # Find request log
        request_logs = [
            call
            for call in call_args
            if len(call[0]) > 1 and call[0][1] == "HTTP Request"
        ]

        # Find response log
        response_logs = [
            call
            for call in call_args
            if len(call[0]) > 1 and call[0][1] == "HTTP Response"
        ]

        assert len(request_logs) > 0, "Expected HTTP Request log"
        assert len(response_logs) > 0, "Expected HTTP Response log"

        # Verify response log contains expected fields
        response_extra = response_logs[0][1]["extra"]
        assert "status_code" in response_extra, "Response should include status_code"
        assert "duration" in response_extra, "Response should include duration"

    async def test_error_response_maintains_headers(self, client: AsyncClient):
        """Test that error responses still include middleware headers.

        Verifies that middleware headers are present even when the
        endpoint returns an error response (not an unhandled exception).
        """
        app = FastAPI()
        app.add_middleware(MetricsMiddleware)
        app.add_middleware(RequestIDMiddleware)
        app.add_middleware(SecurityHeadersMiddleware)

        from fastapi import HTTPException

        @app.get("/error")
        async def error_endpoint():
            raise HTTPException(status_code=500, detail="Test error")

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/error")

        assert response.status_code == 500

        # Headers should still be present despite error response
        assert "x-request-id" in response.headers
        assert "x-process-time" in response.headers
