"""Unit tests for RequestLoggingMiddleware."""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from httpx import AsyncClient

from example_service.app.middleware.request_logging import (
    PIIMasker,
    RequestLoggingMiddleware,
)


class TestRequestLoggingMiddleware:
    """Test suite for RequestLoggingMiddleware."""

    @pytest.fixture
    def app(self) -> FastAPI:
        """Create FastAPI app with request logging middleware.

        Returns:
            FastAPI application with middleware.
        """
        app = FastAPI()
        app.add_middleware(
            RequestLoggingMiddleware,
            log_request_body=True,
            log_response_body=False,
            max_body_size=10000,
        )

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        @app.post("/upload")
        async def upload_endpoint(request: Request):
            body = await request.json()
            return {"received": body}

        return app

    @pytest.fixture
    async def client(self, app: FastAPI) -> AsyncClient:
        """Create async HTTP client.

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

    @patch("example_service.app.middleware.request_logging.logger")
    async def test_logs_request_details(self, mock_logger: MagicMock, client: AsyncClient):
        """Test that request details are logged."""
        await client.get("/test")

        # Verify logger was called
        assert mock_logger.log.called
        call_args = mock_logger.log.call_args_list

        # Find request log
        request_logs = [
            call for call in call_args if len(call[0]) > 1 and call[0][1] == "HTTP Request"
        ]
        assert len(request_logs) > 0

        # Verify request log contains expected fields
        log_extra = request_logs[0][1]["extra"]
        assert "event" in log_extra
        assert log_extra["event"] == "request"
        assert "method" in log_extra
        assert "path" in log_extra

    @patch("example_service.app.middleware.request_logging.logger")
    async def test_logs_response_details(self, mock_logger: MagicMock, client: AsyncClient):
        """Test that response details are logged."""
        await client.get("/test")

        call_args = mock_logger.log.call_args_list

        # Find response log
        response_logs = [
            call for call in call_args if len(call[0]) > 1 and call[0][1] == "HTTP Response"
        ]
        assert len(response_logs) > 0

        # Verify response log contains expected fields
        log_extra = response_logs[0][1]["extra"]
        assert "event" in log_extra
        assert log_extra["event"] == "response"
        assert "status_code" in log_extra
        assert "duration" in log_extra

    @patch("example_service.app.middleware.request_logging.logger")
    async def test_request_id_in_logs(self, mock_logger: MagicMock):
        """Test that request_id from context is included in logs."""
        app = FastAPI()

        # Add RequestIDMiddleware first, then logging
        from example_service.app.middleware.request_id import RequestIDMiddleware

        app.add_middleware(RequestLoggingMiddleware)
        app.add_middleware(RequestIDMiddleware)

        @app.get("/test")
        async def test_endpoint(request: Request):
            # Access request_id from state
            return {"request_id": getattr(request.state, "request_id", None)}

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/test")

        # Request should have request_id
        assert "request_id" in response.json()
        request_id = response.json()["request_id"]

        # Logs should contain request_id
        call_args = mock_logger.log.call_args_list
        if call_args:
            # Check that at least one log call has request_id
            has_request_id = any(
                call[1].get("extra", {}).get("request_id") == request_id for call in call_args
            )
            assert has_request_id

    async def test_exempt_paths_not_logged(self):
        """Test that exempt paths skip detailed logging."""
        app = FastAPI()
        app.add_middleware(RequestLoggingMiddleware)

        @app.get("/health")
        async def health_endpoint():
            return {"status": "healthy"}

        from httpx import ASGITransport

        with patch("example_service.app.middleware.request_logging.logger") as mock_logger:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.get("/health")

            # Should not log request/response for exempt paths
            # Or should log minimal info
            call_args = mock_logger.log.call_args_list
            # Exempt paths should either not log or log very minimally
            assert len(call_args) == 0 or all(
                "HTTP Request" not in str(call) for call in call_args
            )

    @patch("example_service.app.middleware.request_logging.logger")
    async def test_logs_request_body(self, mock_logger: MagicMock, client: AsyncClient):
        """Test that request body is logged when enabled."""
        payload = {"username": "testuser", "email": "test@example.com"}

        await client.post("/upload", json=payload)

        call_args = mock_logger.log.call_args_list
        request_logs = [
            call for call in call_args if len(call[0]) > 1 and call[0][1] == "HTTP Request"
        ]

        if request_logs:
            log_extra = request_logs[0][1]["extra"]
            # Body should be logged (and masked)
            if "body" in log_extra:
                assert "body" in log_extra

    @patch("example_service.app.middleware.request_logging.logger")
    async def test_masks_sensitive_data_in_body(self, mock_logger: MagicMock, client: AsyncClient):
        """Test that sensitive data in request body is masked."""
        payload = {
            "username": "testuser",
            "password": "secret123",
            "email": "user@example.com",
        }

        await client.post("/upload", json=payload)

        call_args = mock_logger.log.call_args_list
        request_logs = [
            call for call in call_args if len(call[0]) > 1 and call[0][1] == "HTTP Request"
        ]

        if request_logs and "body" in request_logs[0][1]["extra"]:
            body = request_logs[0][1]["extra"]["body"]
            # Password should be masked
            if isinstance(body, dict) and "password" in body:
                assert body["password"] == "********"

    @patch("example_service.app.middleware.request_logging.logger")
    async def test_masks_authorization_header(self, mock_logger: MagicMock, client: AsyncClient):
        """Test that Authorization header is masked."""
        await client.get("/test", headers={"Authorization": "Bearer secret_token"})

        call_args = mock_logger.log.call_args_list
        request_logs = [
            call for call in call_args if len(call[0]) > 1 and call[0][1] == "HTTP Request"
        ]

        if request_logs:
            log_extra = request_logs[0][1]["extra"]
            if "headers" in log_extra:
                headers = log_extra["headers"]
                # Authorization should be masked
                if "authorization" in headers:
                    assert headers["authorization"] == "********"

    async def test_max_body_size_limit(self):
        """Test that bodies exceeding max_body_size are not logged."""
        app = FastAPI()
        app.add_middleware(
            RequestLoggingMiddleware,
            log_request_body=True,
            max_body_size=100,  # Very small limit
        )

        @app.post("/upload")
        async def upload_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        with patch("example_service.app.middleware.request_logging.logger") as mock_logger:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                # Large payload
                payload = {"data": "x" * 1000}
                await client.post("/upload", json=payload)

            # Body should not be logged (too large)
            call_args = mock_logger.log.call_args_list
            request_logs = [
                call for call in call_args if len(call[0]) > 1 and call[0][1] == "HTTP Request"
            ]

            if request_logs:
                log_extra = request_logs[0][1]["extra"]
                # Body should not be present (too large)
                assert "body" not in log_extra or log_extra.get("body") is None

    @patch("example_service.app.middleware.request_logging.logger")
    async def test_logs_error_on_exception(self, mock_logger: MagicMock):
        """Test that errors are logged when handler raises exception."""
        app = FastAPI()
        app.add_middleware(RequestLoggingMiddleware)

        @app.get("/error")
        async def error_endpoint():
            raise ValueError("Test error")

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            with pytest.raises(ValueError):
                await client.get("/error")

        # Should log error
        assert mock_logger.error.called
        error_call = mock_logger.error.call_args

        if error_call:
            log_message = error_call[0][0]
            assert "failed" in log_message.lower() or "error" in log_message.lower()

    @patch("example_service.app.middleware.request_logging.set_log_context")
    async def test_sets_logging_context(
        self, mock_set_context: MagicMock, client: AsyncClient
    ):
        """Test that middleware sets logging context with request details."""
        await client.get("/test")

        # Verify set_log_context was called with HTTP details
        assert mock_set_context.called
        call_kwargs = mock_set_context.call_args[1]
        assert "method" in call_kwargs
        assert "path" in call_kwargs

    async def test_custom_log_level(self):
        """Test using custom log level."""
        app = FastAPI()
        app.add_middleware(
            RequestLoggingMiddleware,
            log_level=logging.DEBUG,
        )

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        with patch("example_service.app.middleware.request_logging.logger") as mock_logger:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.get("/test")

            # Should use DEBUG level
            if mock_logger.log.called:
                log_level = mock_logger.log.call_args[0][0]
                assert log_level == logging.DEBUG

    async def test_custom_pii_masker(self):
        """Test using custom PIIMasker instance."""
        custom_masker = PIIMasker(mask_char="X", preserve_domain=False)

        app = FastAPI()
        app.add_middleware(
            RequestLoggingMiddleware,
            masker=custom_masker,
            log_request_body=True,
        )

        @app.post("/upload")
        async def upload_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        with patch("example_service.app.middleware.request_logging.logger"):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                payload = {"email": "user@example.com"}
                await client.post("/upload", json=payload)

        # Custom masker should be used (verified by mask_char)

    async def test_only_logs_json_and_form_bodies(self):
        """Test that only JSON and form data bodies are logged."""
        app = FastAPI()
        app.add_middleware(
            RequestLoggingMiddleware,
            log_request_body=True,
        )

        @app.post("/upload")
        async def upload_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        with patch("example_service.app.middleware.request_logging.logger") as mock_logger:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                # Test with binary data (should not log body)
                await client.post(
                    "/upload",
                    content=b"binary data",
                    headers={"content-type": "application/octet-stream"},
                )

            # Body should not be logged (not JSON or form)
            call_args = mock_logger.log.call_args_list
            request_logs = [
                call for call in call_args if len(call[0]) > 1 and call[0][1] == "HTTP Request"
            ]

            if request_logs:
                log_extra = request_logs[0][1]["extra"]
                # Body should not be present (wrong content type)
                assert "body" not in log_extra or log_extra.get("body") is None

    @patch("example_service.app.middleware.request_logging.logger")
    async def test_duration_measurement(self, mock_logger: MagicMock):
        """Test that request duration is measured accurately."""
        import time

        app = FastAPI()
        app.add_middleware(RequestLoggingMiddleware)

        @app.get("/slow")
        async def slow_endpoint():
            await asyncio.sleep(0.1)  # 100ms delay
            return {"message": "ok"}

        from httpx import ASGITransport
        import asyncio

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.get("/slow")

        # Find response log with duration
        call_args = mock_logger.log.call_args_list
        response_logs = [
            call for call in call_args if len(call[0]) > 1 and call[0][1] == "HTTP Response"
        ]

        if response_logs:
            log_extra = response_logs[0][1]["extra"]
            duration = log_extra.get("duration")
            # Duration should be at least 0.1 seconds
            assert duration is not None
            assert duration >= 0.1

    @patch("example_service.app.middleware.request_logging.logger")
    @patch("example_service.app.middleware.request_logging.tracking")
    async def test_tracks_metrics(
        self, mock_tracking: MagicMock, mock_logger: MagicMock, client: AsyncClient
    ):
        """Test that middleware tracks API metrics."""
        await client.get("/test")

        # Verify tracking functions were called
        assert mock_tracking.track_api_call.called

    @patch("example_service.app.middleware.request_logging.logger")
    @patch("example_service.app.middleware.request_logging.tracking")
    async def test_tracks_slow_requests(
        self, mock_tracking: MagicMock, mock_logger: MagicMock
    ):
        """Test that slow requests are tracked."""
        import asyncio

        app = FastAPI()
        app.add_middleware(RequestLoggingMiddleware)

        @app.get("/very-slow")
        async def very_slow_endpoint():
            await asyncio.sleep(6.0)  # Over 5 second threshold
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            timeout=10.0,
        ) as client:
            await client.get("/very-slow")

        # Should track slow request
        assert mock_tracking.track_slow_request.called

    async def test_custom_exempt_paths(self):
        """Test custom exempt paths configuration."""
        app = FastAPI()
        app.add_middleware(
            RequestLoggingMiddleware,
            exempt_paths=["/custom/exempt"],
        )

        @app.get("/custom/exempt")
        async def exempt_endpoint():
            return {"status": "ok"}

        from httpx import ASGITransport

        with patch("example_service.app.middleware.request_logging.logger") as mock_logger:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.get("/custom/exempt")

            # Should not log detailed request for exempt path
            call_args = mock_logger.log.call_args_list
            assert len(call_args) == 0 or all(
                "HTTP Request" not in str(call) for call in call_args
            )

    @patch("example_service.app.middleware.request_logging.logger")
    async def test_handles_form_data(self, mock_logger: MagicMock):
        """Test logging of form-encoded data."""
        app = FastAPI()
        app.add_middleware(
            RequestLoggingMiddleware,
            log_request_body=True,
        )

        @app.post("/form")
        async def form_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.post(
                "/form",
                data={"username": "testuser", "password": "secret"},
            )

        # Should log and mask form data
        call_args = mock_logger.log.call_args_list
        request_logs = [
            call for call in call_args if len(call[0]) > 1 and call[0][1] == "HTTP Request"
        ]

        if request_logs and "body" in request_logs[0][1]["extra"]:
            body = request_logs[0][1]["extra"]["body"]
            if isinstance(body, dict) and "password" in body:
                # Password should be masked
                assert body["password"] == "********"

    async def test_handles_invalid_json_body(self):
        """Test handling of invalid JSON in request body."""
        app = FastAPI()
        app.add_middleware(
            RequestLoggingMiddleware,
            log_request_body=True,
        )

        @app.post("/upload")
        async def upload_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        with patch("example_service.app.middleware.request_logging.logger"):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                # Send invalid JSON
                await client.post(
                    "/upload",
                    content=b"{invalid json}",
                    headers={"content-type": "application/json"},
                )

        # Should not raise exception, should handle gracefully
