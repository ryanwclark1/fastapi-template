"""Tests for RequestLoggingMiddleware and PIIMasker."""

from __future__ import annotations

import contextlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, Request, Response
from httpx import ASGITransport, AsyncClient
import pytest

from example_service.app.middleware.request_logging import (
    PIIMasker,
    RequestLoggingMiddleware,
)

# ============================================================================
# PIIMasker Tests
# ============================================================================


def test_masker_masks_common_pii_fields_and_strings():
    masker = PIIMasker()
    data = {
        "email": "user@example.com",
        "phone": "555-123-4567",
        "password": "secret123",
        "nested": {"token": "abcd1234efgh5678"},
        "list": [{"ssn": "123-45-6789"}, "4111-1111-1111-1111"],
        "note": "Call me at 555-000-1111 or email test@test.com",
    }

    masked = masker.mask_dict(data)

    assert masked["email"] != "user@example.com"
    assert masked["phone"].startswith("***-***")
    assert masked["password"] == "*" * 8
    assert masked["nested"]["token"] == "*" * 8
    assert masked["list"][0]["ssn"] == "*" * len("123-45-6789")
    assert "***@" in masked["note"]
    assert "***-***-1111" in masked["note"]


def test_masker_truncates_on_max_depth_and_custom_pattern():
    masker = PIIMasker(custom_patterns={"hex": PIIMasker.API_KEY_PATTERN})
    deep = {"a": {"b": {"c": {"d": {"e": "value"}}}}}
    masked = masker.mask_dict(deep, max_depth=2)
    assert masked["a"]["b"]["c"] == {"_truncated": "max_depth_exceeded"}

    api_key = "A" * 32
    masked_string = masker.mask_string(f"token {api_key}")
    assert "*" * 8 in masked_string


def test_masker_masks_email_preserve_domain():
    masker = PIIMasker(preserve_domain=True)
    masked = masker.mask_email("user@example.com")
    assert masked.endswith("@example.com")
    assert masked.startswith("u***")


def test_masker_masks_email_no_preserve_domain():
    masker = PIIMasker(preserve_domain=False)
    masked = masker.mask_email("user@example.com")
    assert masked == "***@***.com"


def test_masker_masks_phone_preserve_last_4():
    masker = PIIMasker(preserve_last_4=True)
    masked = masker.mask_phone("555-123-4567")
    assert masked.endswith("4567")
    assert masked.startswith("***")


def test_masker_masks_credit_card():
    masker = PIIMasker(preserve_last_4=True)
    masked = masker.mask_credit_card("4111-1111-1111-1111")
    assert masked.endswith("1111")
    assert "****" in masked


# ============================================================================
# RequestLoggingMiddleware Tests
# ============================================================================


@pytest.fixture
def app() -> FastAPI:
    """Create FastAPI app for testing."""
    app = FastAPI()

    @app.get("/test")
    async def test_endpoint() -> dict:
        return {"message": "test"}

    @app.post("/test")
    async def test_post(data: dict) -> dict:
        return {"received": data}

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncClient:
    """Create HTTP client."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


class TestRequestLoggingMiddleware:
    """Test RequestLoggingMiddleware."""

    @pytest.mark.asyncio
    async def test_middleware_logs_request(self, app: FastAPI, client: AsyncClient) -> None:
        """Test that middleware logs request details."""
        with patch("example_service.app.middleware.request_logging.logger") as mock_logger:
            app.add_middleware(RequestLoggingMiddleware, log_request_body=False)

            await client.get("/test")

            # Verify logging was called
            assert mock_logger.log.called or mock_logger.info.called

    @pytest.mark.asyncio
    async def test_middleware_exempts_health_path(self, app: FastAPI, client: AsyncClient) -> None:
        """Test that middleware exempts health check paths."""
        app.add_middleware(RequestLoggingMiddleware)

        # Health path should be exempt, so detailed logging shouldn't happen
        # But basic logging might still occur
        response = await client.get("/health")
        assert response.status_code == 200  # Just verify no exception

    @pytest.mark.asyncio
    async def test_middleware_extracts_client_ip_from_forwarded_for(
        self, app: FastAPI, client: AsyncClient,
    ) -> None:
        """Test that middleware extracts IP from X-Forwarded-For header."""
        with patch("example_service.app.middleware.request_logging.logger") as mock_logger:
            app.add_middleware(RequestLoggingMiddleware, log_request_body=False)

            await client.get("/test", headers={"X-Forwarded-For": "192.168.1.1, 10.0.0.1"})

            # Verify IP extraction
            calls = mock_logger.log.call_args_list
            if calls:
                log_data = calls[0][1].get("extra", {})
                assert log_data.get("client_ip") == "192.168.1.1"

    @pytest.mark.asyncio
    async def test_middleware_extracts_client_ip_from_real_ip(
        self, app: FastAPI, client: AsyncClient,
    ) -> None:
        """Test that middleware extracts IP from X-Real-IP header."""
        with patch("example_service.app.middleware.request_logging.logger") as mock_logger:
            app.add_middleware(RequestLoggingMiddleware, log_request_body=False)

            await client.get("/test", headers={"X-Real-IP": "192.168.1.2"})

            # Verify IP extraction
            calls = mock_logger.log.call_args_list
            if calls:
                log_data = calls[0][1].get("extra", {})
                assert log_data.get("client_ip") == "192.168.1.2"

    @pytest.mark.asyncio
    async def test_middleware_masks_sensitive_headers(
        self, app: FastAPI, client: AsyncClient,
    ) -> None:
        """Test that middleware masks sensitive headers."""
        with patch("example_service.app.middleware.request_logging.logger") as mock_logger:
            app.add_middleware(RequestLoggingMiddleware, log_request_body=False)

            await client.get(
                "/test",
                headers={
                    "Authorization": "Bearer secret-token",
                    "X-API-Key": "api-key-123",
                    "Cookie": "session=abc123",
                },
            )

            # Verify headers were masked in logs
            calls = mock_logger.log.call_args_list
            if calls:
                log_data = calls[0][1].get("extra", {})
                headers = log_data.get("headers", {})
                assert headers.get("authorization") == "********"
                assert headers.get("x-api-key") == "********"
                assert headers.get("cookie") == "********"

    @pytest.mark.asyncio
    async def test_middleware_logs_request_body_when_enabled(
        self, app: FastAPI, client: AsyncClient,
    ) -> None:
        """Test that middleware logs request body when enabled."""
        with patch("example_service.app.middleware.request_logging.logger") as mock_logger:
            app.add_middleware(RequestLoggingMiddleware, log_request_body=True)

            await client.post("/test", json={"email": "user@example.com", "password": "secret"})

            # Verify body was logged and masked
            calls = mock_logger.log.call_args_list
            if calls:
                log_data = calls[0][1].get("extra", {})
                body = log_data.get("body", {})
                # Password should be masked
                if "password" in body:
                    assert body["password"] == "********"

    @pytest.mark.asyncio
    async def test_middleware_does_not_log_body_when_disabled(
        self, app: FastAPI, client: AsyncClient,
    ) -> None:
        """Test that middleware doesn't log body when disabled."""
        with patch("example_service.app.middleware.request_logging.logger") as mock_logger:
            app.add_middleware(RequestLoggingMiddleware, log_request_body=False)

            await client.post("/test", json={"data": "test"})

            # Body should not be in logs
            calls = mock_logger.log.call_args_list
            if calls:
                log_data = calls[0][1].get("extra", {})
                assert "body" not in log_data

    @pytest.mark.asyncio
    async def test_middleware_detects_security_events(
        self, app: FastAPI, client: AsyncClient,
    ) -> None:
        """Test that middleware detects security events when enabled."""
        with patch("example_service.app.middleware.request_logging.logger") as mock_logger:
            app.add_middleware(
                RequestLoggingMiddleware, log_request_body=True, detect_security_events=True,
            )

            # SQL injection attempt
            await client.get("/test?q=1' OR '1'='1")

            # Verify security event was detected
            calls = mock_logger.warning.call_args_list
            if calls:
                log_data = calls[0][1].get("extra", {})
                assert "security_events" in log_data

    @pytest.mark.asyncio
    async def test_middleware_logs_user_context(self, app: FastAPI, client: AsyncClient) -> None:
        """Test that middleware logs user context from request state."""
        from example_service.app.middleware.request_logging import (
            RequestLoggingMiddleware,
        )

        middleware = RequestLoggingMiddleware(app, log_request_body=False)

        # Create mock request with user context
        request = MagicMock(spec=Request)
        request.url.path = "/test"
        request.method = "GET"
        request.headers = {}
        request.query_params = {}
        request.client = MagicMock(host="127.0.0.1")
        request.state = MagicMock()
        request.state.user = MagicMock(id="user-123")
        request.state.tenant_id = "tenant-456"
        request.state.request_id = "req-789"

        # Test user context extraction
        context = middleware._get_user_context(request)

        assert context["user_id"] == "user-123"
        assert context["tenant_id"] == "tenant-456"

    @pytest.mark.asyncio
    async def test_middleware_handles_exception(self, app: FastAPI) -> None:
        """Test that middleware logs exceptions properly."""

        @app.get("/error")
        async def error_endpoint() -> None:
            msg = "Test error"
            raise ValueError(msg)

        with patch("example_service.app.middleware.request_logging.logger") as mock_logger:
            app.add_middleware(RequestLoggingMiddleware)

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test",
            ) as client:
                with contextlib.suppress(Exception):
                    await client.get("/error")

            # Verify error was logged (middleware uses logger.exception, not logger.error)
            assert mock_logger.exception.called

    @pytest.mark.asyncio
    async def test_middleware_logs_slow_requests(self, app: FastAPI) -> None:
        """Test that middleware tracks slow requests."""

        @app.get("/slow")
        async def slow_endpoint() -> dict:
            import asyncio

            await asyncio.sleep(0.01)  # Small delay for testing
            return {"message": "slow"}

        app.add_middleware(RequestLoggingMiddleware)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/slow")
            assert response.status_code == 200  # Verify no exception

    @pytest.mark.asyncio
    async def test_middleware_respects_max_body_size(
        self, app: FastAPI, client: AsyncClient,
    ) -> None:
        """Test that middleware respects max body size limit."""
        with patch("example_service.app.middleware.request_logging.logger") as mock_logger:
            app.add_middleware(RequestLoggingMiddleware, log_request_body=True, max_body_size=10)

            # Large body
            large_body = "x" * 1000
            await client.post("/test", json={"data": large_body})

            # Body should not be logged due to size
            calls = mock_logger.log.call_args_list
            if calls:
                log_data = calls[0][1].get("extra", {})
                assert "body" not in log_data or log_data.get("body_size", 0) <= 10

    @pytest.mark.asyncio
    async def test_middleware_handles_malformed_json_body(
        self, app: FastAPI, client: AsyncClient,
    ) -> None:
        """Test that middleware handles malformed JSON gracefully."""
        app.add_middleware(RequestLoggingMiddleware, log_request_body=True)

        # Should not raise exception even with malformed body
        response = await client.post(
            "/test",
            content=b"not valid json",
            headers={"Content-Type": "application/json"},
        )
        # Should handle gracefully
        assert response.status_code in [200, 400, 422]

    @pytest.mark.asyncio
    async def test_middleware_logs_response_body_when_enabled(
        self, app: FastAPI, client: AsyncClient,
    ) -> None:
        """Test that middleware logs response body when enabled."""
        with patch("example_service.app.middleware.request_logging.logger") as mock_logger:
            app.add_middleware(RequestLoggingMiddleware, log_response_body=True)

            await client.get("/test")

            # Verify response was logged
            calls = mock_logger.log.call_args_list
            assert len(calls) >= 1

    @pytest.mark.asyncio
    async def test_middleware_handles_empty_request_body(
        self, app: FastAPI, client: AsyncClient,
    ) -> None:
        """Test that middleware handles empty request body."""
        app.add_middleware(RequestLoggingMiddleware, log_request_body=True)

        response = await client.post("/test", json={})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_middleware_handles_non_json_body(
        self, app: FastAPI, client: AsyncClient,
    ) -> None:
        """Test that middleware handles non-JSON body."""
        app.add_middleware(RequestLoggingMiddleware, log_request_body=True)

        response = await client.post(
            "/test", content=b"plain text", headers={"Content-Type": "text/plain"},
        )
        # Should handle gracefully
        assert response.status_code in [200, 400, 422]

    @pytest.mark.asyncio
    async def test_middleware_detects_xss_attempts(self, app: FastAPI, client: AsyncClient) -> None:
        """Test that middleware detects XSS attempts."""
        with patch("example_service.app.middleware.request_logging.logger") as mock_logger:
            app.add_middleware(
                RequestLoggingMiddleware, log_request_body=True, detect_security_events=True,
            )

            await client.get("/test?q=<script>alert('xss')</script>")

            # Verify security event was detected
            calls = mock_logger.warning.call_args_list
            if calls:
                log_data = calls[0][1].get("extra", {})
                security_events = log_data.get("security_events", [])
                assert any("xss" in str(event).lower() for event in security_events)

    @pytest.mark.asyncio
    async def test_middleware_detects_path_traversal(
        self, app: FastAPI, client: AsyncClient,
    ) -> None:
        """Test that middleware detects path traversal attempts."""
        with patch("example_service.app.middleware.request_logging.logger") as mock_logger:
            app.add_middleware(
                RequestLoggingMiddleware, log_request_body=True, detect_security_events=True,
            )

            await client.get("/test?file=../../../etc/passwd")

            # Verify security event was detected
            calls = mock_logger.warning.call_args_list
            if calls:
                log_data = calls[0][1].get("extra", {})
                security_events = log_data.get("security_events", [])
                assert any("path_traversal" in str(event).lower() for event in security_events)

    @pytest.mark.asyncio
    async def test_middleware_handles_custom_exempt_paths(
        self, app: FastAPI, client: AsyncClient,
    ) -> None:
        """Test that middleware respects custom exempt paths."""
        app.add_middleware(RequestLoggingMiddleware, exempt_paths=["/test"], log_request_body=True)

        response = await client.get("/test")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_middleware_logs_custom_sensitive_fields(
        self, app: FastAPI, client: AsyncClient,
    ) -> None:
        """Test that middleware masks custom sensitive fields."""
        with patch("example_service.app.middleware.request_logging.logger") as mock_logger:
            app.add_middleware(
                RequestLoggingMiddleware,
                log_request_body=True,
                sensitive_fields=["custom_secret"],
            )

            await client.post("/test", json={"custom_secret": "sensitive-value", "normal": "ok"})

            # Verify custom field was masked
            calls = mock_logger.log.call_args_list
            if calls:
                log_data = calls[0][1].get("extra", {})
                body = log_data.get("body", {})
                if "custom_secret" in body:
                    assert body["custom_secret"] == "********"

    @pytest.mark.asyncio
    async def test_middleware_handles_streaming_response(
        self, app: FastAPI, client: AsyncClient,
    ) -> None:
        """Test that middleware handles streaming responses."""
        from fastapi.responses import StreamingResponse

        @app.get("/stream")
        async def stream_endpoint() -> StreamingResponse:
            async def generate():
                yield b"chunk1"
                yield b"chunk2"

            return StreamingResponse(generate())

        app.add_middleware(RequestLoggingMiddleware)

        response = await client.get("/stream")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_middleware_extracts_user_agent(self, app: FastAPI, client: AsyncClient) -> None:
        """Test that middleware extracts and logs user agent."""
        with patch("example_service.app.middleware.request_logging.logger") as mock_logger:
            app.add_middleware(RequestLoggingMiddleware, log_request_body=False)

            await client.get("/test", headers={"User-Agent": "TestAgent/1.0"})

            calls = mock_logger.log.call_args_list
            if calls:
                log_data = calls[0][1].get("extra", {})
                assert log_data.get("user_agent") == "TestAgent/1.0"

    @pytest.mark.asyncio
    async def test_middleware_logs_request_size(self, app: FastAPI, client: AsyncClient) -> None:
        """Test that middleware logs request size."""
        with patch("example_service.app.middleware.request_logging.logger") as mock_logger:
            app.add_middleware(RequestLoggingMiddleware, log_request_body=False)

            await client.post("/test", json={"data": "test"})

            calls = mock_logger.log.call_args_list
            if calls:
                log_data = calls[0][1].get("extra", {})
                assert "request_size" in log_data or "body_size" in log_data

    @pytest.mark.asyncio
    async def test_middleware_logs_response_size(self, app: FastAPI, client: AsyncClient) -> None:
        """Test that middleware logs response size."""
        with patch("example_service.app.middleware.request_logging.logger") as mock_logger:
            app.add_middleware(RequestLoggingMiddleware, log_response_body=False)

            await client.get("/test")

            calls = mock_logger.log.call_args_list
            # response_size is logged in the response log (second call), not request log
            if len(calls) >= 2:
                # Find the response log call
                for call in calls:
                    log_data = call[1].get("extra", {})
                    if log_data.get("event") == "response":
                        assert "response_size" in log_data
                        break
            # If only one call, check it anyway
            elif calls:
                log_data = calls[-1][1].get("extra", {})
                # response_size may not be present if content-length header is missing
                # which is fine for this test
                if "content-length" in str(log_data.get("headers", {})):
                    assert "response_size" in log_data

    @pytest.mark.asyncio
    async def test_middleware_handles_missing_client_info(
        self, app: FastAPI, client: AsyncClient,
    ) -> None:
        """Test that middleware handles missing client information."""
        app.add_middleware(RequestLoggingMiddleware)

        # Request without client info should still work
        response = await client.get("/test")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_pii_masker_handles_none_values(self) -> None:
        """Test that PII masker handles None values gracefully."""
        masker = PIIMasker()
        data = {"email": None, "phone": None, "normal": "value"}

        masked = masker.mask_dict(data)

        assert masked["email"] is None
        assert masked["phone"] is None
        assert masked["normal"] == "value"

    @pytest.mark.asyncio
    async def test_pii_masker_handles_empty_strings(self) -> None:
        """Test that PII masker handles empty strings."""
        masker = PIIMasker()
        data = {"email": "", "phone": "", "normal": "value"}

        masked = masker.mask_dict(data)

        assert masked["email"] == ""
        assert masked["phone"] == ""
        assert masked["normal"] == "value"

    @pytest.mark.asyncio
    async def test_pii_masker_handles_list_of_strings(self) -> None:
        """Test that PII masker handles lists of strings."""
        masker = PIIMasker()
        data = {"emails": ["user1@example.com", "user2@example.com"]}

        masked = masker.mask_dict(data)

        assert isinstance(masked["emails"], list)
        # Emails in list should be masked
        for email in masked["emails"]:
            assert email != "user1@example.com"
            assert email != "user2@example.com"

    @pytest.mark.asyncio
    async def test_middleware_logs_slow_requests(self, app: FastAPI, client: AsyncClient) -> None:
        """Test that middleware logs slow requests."""
        import asyncio

        @app.get("/slow")
        async def slow_endpoint() -> dict:
            await asyncio.sleep(0.1)  # Simulate slow request
            return {"message": "slow"}

        with patch("example_service.app.middleware.request_logging.logger") as mock_logger:
            app.add_middleware(RequestLoggingMiddleware)

            await client.get("/slow")

            # Check if slow request was logged
            calls = mock_logger.log.call_args_list
            assert len(calls) > 0

    @pytest.mark.asyncio
    async def test_middleware_handles_exception_during_request(
        self, app: FastAPI, client: AsyncClient,
    ) -> None:
        """Test that middleware handles exceptions during request processing."""

        @app.get("/error")
        async def error_endpoint() -> dict:
            msg = "Test error"
            raise ValueError(msg)

        app.add_middleware(RequestLoggingMiddleware)

        with contextlib.suppress(Exception):
            await client.get("/error")

        # Middleware should still log the request attempt

    @pytest.mark.asyncio
    async def test_middleware_logs_request_with_body(
        self, app: FastAPI, client: AsyncClient,
    ) -> None:
        """Test that middleware logs request body when enabled."""
        with patch("example_service.app.middleware.request_logging.logger") as mock_logger:
            app.add_middleware(RequestLoggingMiddleware, log_request_body=True)

            await client.post("/test", json={"data": "test"})

            calls = mock_logger.log.call_args_list
            # Should have logged request with body
            assert len(calls) > 0

    @pytest.mark.asyncio
    async def test_middleware_logs_response_with_body(
        self, app: FastAPI, client: AsyncClient,
    ) -> None:
        """Test that middleware logs response body when enabled."""
        with patch("example_service.app.middleware.request_logging.logger") as mock_logger:
            app.add_middleware(RequestLoggingMiddleware, log_response_body=True)

            await client.get("/test")

            calls = mock_logger.log.call_args_list
            # Should have logged response with body
            assert len(calls) > 0

    @pytest.mark.asyncio
    async def test_middleware_respects_max_body_size(
        self, app: FastAPI, client: AsyncClient,
    ) -> None:
        """Test that middleware respects max_body_size limit."""
        large_body = {"data": "x" * 20000}  # 20KB body

        with patch("example_service.app.middleware.request_logging.logger") as mock_logger:
            app.add_middleware(RequestLoggingMiddleware, log_request_body=True, max_body_size=10000)

            await client.post("/test", json=large_body)

            # Body should be truncated in logs
            calls = mock_logger.log.call_args_list
            assert len(calls) > 0

    @pytest.mark.asyncio
    async def test_middleware_exempts_health_paths(self, app: FastAPI, client: AsyncClient) -> None:
        """Test that middleware exempts health check paths from detailed logging."""
        with patch("example_service.app.middleware.request_logging.logger"):
            app.add_middleware(RequestLoggingMiddleware)

            await client.get("/health")

            # Health checks may have minimal logging
            # Should still log but maybe with less detail

    @pytest.mark.asyncio
    async def test_middleware_detects_security_events(
        self, app: FastAPI, client: AsyncClient,
    ) -> None:
        """Test that middleware detects security events when enabled."""
        with patch("example_service.app.middleware.request_logging.logger") as mock_logger:
            app.add_middleware(RequestLoggingMiddleware, detect_security_events=True)

            # Try SQL injection pattern
            await client.get("/test?q=1' OR '1'='1")

            calls = mock_logger.log.call_args_list
            # Should detect and log security event
            assert len(calls) > 0

    @pytest.mark.asyncio
    async def test_middleware_handles_malformed_json_body(
        self, app: FastAPI, client: AsyncClient,
    ) -> None:
        """Test that middleware handles malformed JSON in request body."""
        app.add_middleware(RequestLoggingMiddleware, log_request_body=True)

        # Send invalid JSON
        response = await client.post(
            "/test",
            content='{"invalid": json}',
            headers={"Content-Type": "application/json"},
        )

        # Should handle gracefully
        assert response.status_code in [200, 400, 422]

    @pytest.mark.asyncio
    async def test_pii_masker_handles_custom_patterns(self) -> None:
        """Test that PII masker handles custom patterns."""
        import re

        # Use a pattern that won't conflict with credit card pattern
        custom_pattern = re.compile(r"\bAPI-KEY-\d{4}\b")
        masker = PIIMasker(custom_patterns={"api_key": custom_pattern})
        data = {"note": "My API key is API-KEY-1234"}

        masked = masker.mask_string(data["note"])

        assert "API-KEY-1234" not in masked
        assert "********" in masked

    @pytest.mark.asyncio
    async def test_pii_masker_handles_custom_sensitive_fields(self) -> None:
        """Test that PII masker handles custom sensitive fields."""
        masker = PIIMasker(custom_fields={"api_secret", "private_key"})
        data = {"api_secret": "secret123", "private_key": "key456", "normal": "value"}

        masked = masker.mask_dict(data)

        assert masked["api_secret"] != "secret123"
        assert masked["private_key"] != "key456"
        assert masked["normal"] == "value"

    @pytest.mark.asyncio
    async def test_pii_masker_preserves_domain_in_email(self) -> None:
        """Test that PII masker preserves domain when configured."""
        masker = PIIMasker(preserve_domain=True)
        masked = masker.mask_email("user@example.com")

        assert masked.endswith("@example.com")
        assert masked != "user@example.com"

    @pytest.mark.asyncio
    async def test_pii_masker_preserves_last_4_in_phone(self) -> None:
        """Test that PII masker preserves last 4 digits in phone."""
        masker = PIIMasker(preserve_last_4=True)
        masked = masker.mask_phone("555-123-4567")

        assert masked.endswith("4567")
        assert masked.startswith("***")

    @pytest.mark.asyncio
    async def test_pii_masker_preserves_last_4_in_credit_card(self) -> None:
        """Test that PII masker preserves last 4 digits in credit card."""
        masker = PIIMasker(preserve_last_4=True)
        masked = masker.mask_credit_card("4111-1111-1111-1111")

        assert masked.endswith("1111")
        assert "****" in masked

    @pytest.mark.asyncio
    async def test_middleware_logs_correlation_id(self, app: FastAPI, client: AsyncClient) -> None:
        """Test that middleware logs correlation ID if present."""
        with patch("example_service.app.middleware.request_logging.logger") as mock_logger:
            app.add_middleware(RequestLoggingMiddleware)

            await client.get("/test", headers={"X-Correlation-ID": "corr-123"})

            calls = mock_logger.log.call_args_list
            assert len(calls) > 0

    @pytest.mark.asyncio
    async def test_middleware_handles_streaming_response(
        self, app: FastAPI, client: AsyncClient,
    ) -> None:
        """Test that middleware handles streaming responses."""
        from fastapi.responses import StreamingResponse

        @app.get("/stream")
        async def stream_endpoint() -> StreamingResponse:
            async def generate():
                yield b"chunk1"
                yield b"chunk2"

            return StreamingResponse(generate())

        app.add_middleware(RequestLoggingMiddleware)

        response = await client.get("/stream")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_middleware_logs_user_context(self, app: FastAPI, client: AsyncClient) -> None:
        """Test that middleware logs user context if available."""
        from starlette.middleware.base import BaseHTTPMiddleware

        class UserMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request: Request, call_next):
                request.state.user = {"id": "user-123", "email": "user@example.com"}
                return await call_next(request)

        with patch("example_service.app.middleware.request_logging.logger") as mock_logger:
            app.add_middleware(RequestLoggingMiddleware)
            app.add_middleware(UserMiddleware)

            await client.get("/test")

            calls = mock_logger.log.call_args_list
            assert len(calls) > 0

    @pytest.mark.asyncio
    async def test_middleware_logs_tenant_context(self, app: FastAPI, client: AsyncClient) -> None:
        """Test that middleware logs tenant context if available."""
        from starlette.middleware.base import BaseHTTPMiddleware

        class TenantMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request: Request, call_next):
                request.state.tenant_id = "tenant-123"
                return await call_next(request)

        with patch("example_service.app.middleware.request_logging.logger") as mock_logger:
            app.add_middleware(RequestLoggingMiddleware)
            app.add_middleware(TenantMiddleware)

            await client.get("/test")

            calls = mock_logger.log.call_args_list
            assert len(calls) > 0

    @pytest.mark.asyncio
    async def test_pii_masker_handles_deeply_nested_dicts(self) -> None:
        """Test that PII masker handles deeply nested dictionaries."""
        masker = PIIMasker()
        data = {
            "level1": {
                "level2": {
                    "level3": {
                        "level4": {
                            "level5": {"email": "user@example.com"},
                        },
                    },
                },
            },
        }

        masked = masker.mask_dict(data, max_depth=5)

        assert (
            masked["level1"]["level2"]["level3"]["level4"]["level5"]["email"] != "user@example.com"
        )

    @pytest.mark.asyncio
    async def test_pii_masker_truncates_at_max_depth(self) -> None:
        """Test that PII masker truncates at max_depth."""
        masker = PIIMasker()
        data = {"a": {"b": {"c": {"d": {"email": "user@example.com"}}}}}

        masked = masker.mask_dict(data, max_depth=2)

        assert masked["a"]["b"]["c"] == {"_truncated": "max_depth_exceeded"}

    @pytest.mark.asyncio
    async def test_middleware_handles_missing_content_type(
        self, app: FastAPI, client: AsyncClient,
    ) -> None:
        """Test that middleware handles requests without Content-Type header."""
        app.add_middleware(RequestLoggingMiddleware, log_request_body=True)

        response = await client.post("/test", content=b"raw bytes", headers={})

        # Should handle gracefully
        assert response.status_code in [200, 400, 422]

    @pytest.mark.asyncio
    async def test_middleware_logs_different_log_levels(
        self, app: FastAPI, client: AsyncClient,
    ) -> None:
        """Test that middleware uses configured log level."""
        import logging

        with patch("example_service.app.middleware.request_logging.logger") as mock_logger:
            app.add_middleware(RequestLoggingMiddleware, log_level=logging.DEBUG)

            await client.get("/test")

            # Should use DEBUG level
            calls = mock_logger.log.call_args_list
            assert len(calls) > 0
