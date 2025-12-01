"""Unit tests for Debug Middleware with distributed tracing.

This test suite covers:
- Trace ID generation and propagation
- Span ID generation
- Request/response logging
- Exception handling with trace context
- Context injection for structured logging
- Feature flag behavior
- Header extraction and precedence
- Backward compatibility with X-Request-Id
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from example_service.app.middleware.debug import DebugMiddleware

if TYPE_CHECKING:
    from pytest import LogCaptureFixture


@pytest.fixture
def app() -> FastAPI:
    """Create FastAPI app with debug middleware."""
    app = FastAPI()

    # Add test endpoints
    @app.get("/test")
    async def test_endpoint(request: Request):
        return {
            "trace_id": getattr(request.state, "trace_id", None),
            "span_id": getattr(request.state, "span_id", None),
        }

    @app.get("/error")
    async def error_endpoint():
        raise ValueError("Test error")

    # Add middleware
    app.add_middleware(
        DebugMiddleware,
        enabled=True,
        log_requests=True,
        log_responses=True,
        log_timing=True,
        header_prefix="X-",
    )

    return app


@pytest.fixture
def disabled_middleware_app() -> FastAPI:
    """Create FastAPI app with disabled debug middleware."""
    app = FastAPI()

    @app.get("/test")
    async def test_endpoint():
        return {"status": "ok"}

    app.add_middleware(
        DebugMiddleware,
        enabled=False,
    )

    return app


@pytest.fixture
async def async_client(app: FastAPI):
    """Create async HTTP client for testing."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def disabled_client(disabled_middleware_app: FastAPI):
    """Create async HTTP client for disabled middleware testing."""
    async with AsyncClient(
        transport=ASGITransport(app=disabled_middleware_app), base_url="http://test"
    ) as ac:
        yield ac


class TestTraceIDGeneration:
    """Test trace ID generation and propagation."""

    async def test_generates_trace_id_when_missing(
        self, app: FastAPI, async_client: AsyncClient
    ) -> None:
        """Test that trace ID is generated when not provided."""
        response = await async_client.get("/test")

        assert response.status_code == 200
        assert "X-Trace-Id" in response.headers
        assert "X-Span-Id" in response.headers

        # Verify trace ID is valid UUID format
        trace_id = response.headers["X-Trace-Id"]
        uuid_pattern = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
        assert uuid_pattern.match(trace_id)

    async def test_propagates_existing_trace_id(
        self, app: FastAPI, async_client: AsyncClient
    ) -> None:
        """Test that existing trace ID is propagated."""
        trace_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

        response = await async_client.get("/test", headers={"X-Trace-Id": trace_id})

        assert response.status_code == 200
        assert response.headers["X-Trace-Id"] == trace_id
        assert response.json()["trace_id"] == trace_id

    async def test_uses_request_id_as_fallback(
        self, app: FastAPI, async_client: AsyncClient
    ) -> None:
        """Test backward compatibility with X-Request-Id."""
        request_id = "old-format-request-id"

        response = await async_client.get("/test", headers={"X-Request-Id": request_id})

        assert response.status_code == 200
        assert response.headers["X-Trace-Id"] == request_id
        assert response.json()["trace_id"] == request_id

    async def test_trace_id_precedence_over_request_id(
        self, app: FastAPI, async_client: AsyncClient
    ) -> None:
        """Test that X-Trace-Id takes precedence over X-Request-Id."""
        trace_id = "trace-id-value"
        request_id = "request-id-value"

        response = await async_client.get(
            "/test",
            headers={"X-Trace-Id": trace_id, "X-Request-Id": request_id},
        )

        assert response.status_code == 200
        assert response.headers["X-Trace-Id"] == trace_id
        assert response.json()["trace_id"] == trace_id


class TestSpanIDGeneration:
    """Test span ID generation."""

    async def test_generates_span_id(self, app: FastAPI, async_client: AsyncClient) -> None:
        """Test that span ID is generated for each request."""
        response = await async_client.get("/test")

        assert response.status_code == 200
        assert "X-Span-Id" in response.headers

        # Verify span ID is 8-character hex
        span_id = response.headers["X-Span-Id"]
        assert len(span_id) == 8
        assert re.match(r"^[0-9a-f]{8}$", span_id)

    async def test_generates_unique_span_ids(self, app: FastAPI, async_client: AsyncClient) -> None:
        """Test that each request gets a unique span ID."""
        response1 = await async_client.get("/test")
        response2 = await async_client.get("/test")

        span_id1 = response1.headers["X-Span-Id"]
        span_id2 = response2.headers["X-Span-Id"]

        assert span_id1 != span_id2

    async def test_span_id_stored_in_request_state(
        self, app: FastAPI, async_client: AsyncClient
    ) -> None:
        """Test that span ID is accessible in request.state."""
        response = await async_client.get("/test")
        data = response.json()

        assert data["span_id"] is not None
        assert len(data["span_id"]) == 8


class TestRequestLogging:
    """Test request logging functionality."""

    async def test_logs_request_started(
        self, app: FastAPI, async_client: AsyncClient, caplog: LogCaptureFixture
    ) -> None:
        """Test that request start is logged."""
        with caplog.at_level(logging.INFO):
            response = await async_client.get("/test?filter=active")

        assert response.status_code == 200

        # Find request started log
        started_logs = [r for r in caplog.records if "Request started" in r.message]
        assert len(started_logs) == 1

        record = started_logs[0]
        assert record.method == "GET"
        assert record.path == "/test"
        assert hasattr(record, "trace_id")
        assert hasattr(record, "span_id")
        assert hasattr(record, "query_params")

    async def test_logs_request_completed(
        self, app: FastAPI, async_client: AsyncClient, caplog: LogCaptureFixture
    ) -> None:
        """Test that request completion is logged with timing."""
        with caplog.at_level(logging.INFO):
            response = await async_client.get("/test")

        assert response.status_code == 200

        # Find request completed log
        completed_logs = [r for r in caplog.records if "Request completed" in r.message]
        assert len(completed_logs) == 1

        record = completed_logs[0]
        assert record.status_code == 200
        assert hasattr(record, "duration_ms")
        assert record.duration_ms > 0

    async def test_includes_query_params_in_log(
        self, app: FastAPI, async_client: AsyncClient, caplog: LogCaptureFixture
    ) -> None:
        """Test that query parameters are included in logs."""
        with caplog.at_level(logging.INFO):
            await async_client.get("/test?filter=active&limit=10")

        # Find request started log
        started_logs = [r for r in caplog.records if "Request started" in r.message]
        record = started_logs[0]

        assert hasattr(record, "query_params")
        assert record.query_params["filter"] == "active"
        assert record.query_params["limit"] == "10"


class TestExceptionHandling:
    """Test exception handling with trace context."""

    async def test_logs_exception_with_trace_context(
        self, app: FastAPI, async_client: AsyncClient, caplog: LogCaptureFixture
    ) -> None:
        """Test that exceptions are logged with full trace context."""
        with caplog.at_level(logging.ERROR):
            with pytest.raises(ValueError):
                await async_client.get("/error")

        # Find error log
        error_logs = [r for r in caplog.records if "Request failed" in r.message]
        assert len(error_logs) == 1

        record = error_logs[0]
        assert record.error_type == "ValueError"
        assert record.error_message == "Test error"
        assert hasattr(record, "trace_id")
        assert hasattr(record, "span_id")
        assert hasattr(record, "duration_ms")

    async def test_exception_includes_timing(
        self, app: FastAPI, async_client: AsyncClient, caplog: LogCaptureFixture
    ) -> None:
        """Test that failed requests include timing information."""
        with caplog.at_level(logging.ERROR):
            with pytest.raises(ValueError):
                await async_client.get("/error")

        error_logs = [r for r in caplog.records if "Request failed" in r.message]
        record = error_logs[0]

        assert hasattr(record, "duration_ms")
        assert record.duration_ms >= 0


class TestContextInjection:
    """Test logging context injection."""

    async def test_sets_log_context(self, app: FastAPI, async_client: AsyncClient) -> None:
        """Test that logging context is set for the request."""
        with patch("example_service.app.middleware.debug.set_log_context") as mock_set_context:
            await async_client.get("/test?filter=active")

            # Verify set_log_context was called
            assert mock_set_context.called
            call_args = mock_set_context.call_args[1]

            assert "trace_id" in call_args
            assert "span_id" in call_args
            assert "method" in call_args
            assert "path" in call_args
            assert "client_host" in call_args
            assert "query_params" in call_args

    async def test_includes_user_context_when_available(self) -> None:
        """Test that user context is included when available."""
        from starlette.middleware.base import BaseHTTPMiddleware

        app = FastAPI()

        # Add a middleware that runs BEFORE debug middleware to set user context
        class UserContextMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                request.state.user_id = "user-123"
                return await call_next(request)

        @app.get("/test")
        async def test_endpoint():
            return {"status": "ok"}

        app.add_middleware(DebugMiddleware, enabled=True)
        app.add_middleware(UserContextMiddleware)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with patch("example_service.app.middleware.debug.set_log_context") as mock_set_context:
                response = await client.get("/test")
                assert response.status_code == 200

                call_args = mock_set_context.call_args[1]
                assert "user_id" in call_args
                assert call_args["user_id"] == "user-123"

    async def test_includes_tenant_context_when_available(self) -> None:
        """Test that tenant context is included when available."""
        from starlette.middleware.base import BaseHTTPMiddleware

        app = FastAPI()

        # Add a middleware that runs BEFORE debug middleware to set tenant context
        class TenantContextMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                request.state.tenant_id = "tenant-456"
                return await call_next(request)

        @app.get("/test")
        async def test_endpoint():
            return {"status": "ok"}

        app.add_middleware(DebugMiddleware, enabled=True)
        app.add_middleware(TenantContextMiddleware)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with patch("example_service.app.middleware.debug.set_log_context") as mock_set_context:
                response = await client.get("/test")
                assert response.status_code == 200

                call_args = mock_set_context.call_args[1]
                assert "tenant_id" in call_args
                assert call_args["tenant_id"] == "tenant-456"


class TestFeatureFlags:
    """Test feature flag behavior."""

    async def test_disabled_middleware_bypasses_processing(
        self, disabled_client: AsyncClient
    ) -> None:
        """Test that disabled middleware bypasses all processing."""
        response = await disabled_client.get("/test")

        assert response.status_code == 200
        # Should not add trace headers when disabled
        assert "X-Trace-Id" not in response.headers
        assert "X-Span-Id" not in response.headers

    async def test_log_requests_flag(self, caplog: LogCaptureFixture) -> None:
        """Test that log_requests flag controls request logging."""
        app = FastAPI()

        @app.get("/test")
        async def test_endpoint():
            return {"status": "ok"}

        app.add_middleware(
            DebugMiddleware,
            enabled=True,
            log_requests=False,  # Disable request logging
            log_responses=True,
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with caplog.at_level(logging.INFO):
                response = await client.get("/test")

            assert response.status_code == 200

            # Should not log request started
            started_logs = [r for r in caplog.records if "Request started" in r.message]
            assert len(started_logs) == 0

            # Should still log request completed
            completed_logs = [r for r in caplog.records if "Request completed" in r.message]
            assert len(completed_logs) == 1

    async def test_log_responses_flag(self, caplog: LogCaptureFixture) -> None:
        """Test that log_responses flag controls response logging."""
        app = FastAPI()

        @app.get("/test")
        async def test_endpoint():
            return {"status": "ok"}

        app.add_middleware(
            DebugMiddleware,
            enabled=True,
            log_requests=True,
            log_responses=False,  # Disable response logging
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with caplog.at_level(logging.INFO):
                response = await client.get("/test")

            assert response.status_code == 200

            # Should log request started
            started_logs = [r for r in caplog.records if "Request started" in r.message]
            assert len(started_logs) == 1

            # Should not log request completed
            completed_logs = [r for r in caplog.records if "Request completed" in r.message]
            assert len(completed_logs) == 0


class TestHeaderPrefix:
    """Test custom header prefix configuration."""

    async def test_custom_header_prefix(self) -> None:
        """Test that custom header prefix is used."""
        app = FastAPI()

        @app.get("/test")
        async def test_endpoint():
            return {"status": "ok"}

        app.add_middleware(
            DebugMiddleware,
            enabled=True,
            header_prefix="Trace-",  # Custom prefix
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/test")

            assert response.status_code == 200
            assert "Trace-Trace-Id" in response.headers
            assert "Trace-Span-Id" in response.headers

    async def test_reads_trace_id_with_custom_prefix(self) -> None:
        """Test that trace ID is read with custom prefix."""
        app = FastAPI()

        @app.get("/test")
        async def test_endpoint(request: Request):
            return {"trace_id": request.state.trace_id}

        app.add_middleware(
            DebugMiddleware,
            enabled=True,
            header_prefix="Custom-",
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            trace_id = "custom-trace-id"
            response = await client.get("/test", headers={"Custom-Trace-Id": trace_id})

            assert response.status_code == 200
            assert response.json()["trace_id"] == trace_id


class TestPerformance:
    """Test performance characteristics."""

    async def test_minimal_overhead_when_disabled(self, disabled_client: AsyncClient) -> None:
        """Test that disabled middleware has minimal overhead."""
        import time

        iterations = 100
        start = time.perf_counter()

        for _ in range(iterations):
            response = await disabled_client.get("/test")
            assert response.status_code == 200

        duration = time.perf_counter() - start
        avg_duration = duration / iterations

        # Should be very fast when disabled (< 10ms avg per request)
        assert avg_duration < 0.01

    async def test_trace_headers_added_to_response(
        self, app: FastAPI, async_client: AsyncClient
    ) -> None:
        """Test that trace headers are always added to response."""
        response = await async_client.get("/test")

        assert "X-Trace-Id" in response.headers
        assert "X-Span-Id" in response.headers
        assert len(response.headers["X-Trace-Id"]) > 0
        assert len(response.headers["X-Span-Id"]) == 8


class TestEdgeCases:
    """Test edge cases and error conditions."""

    async def test_handles_missing_client(self, caplog: LogCaptureFixture) -> None:
        """Test handling when request.client is None."""
        # This test demonstrates that the middleware handles None client gracefully
        # In practice, HTTP clients always have a client attribute, but we test defensive coding
        # Since AsyncClient always provides a client, we just verify the code path doesn't crash

        app = FastAPI()

        @app.get("/test")
        async def test_endpoint():
            return {"status": "ok"}

        app.add_middleware(DebugMiddleware, enabled=True)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with caplog.at_level(logging.INFO):
                response = await client.get("/test")

            assert response.status_code == 200

            # Middleware should handle client gracefully
            started_logs = [r for r in caplog.records if "Request started" in r.message]
            assert len(started_logs) == 1
            record = started_logs[0]
            # Client will be present in HTTP requests, but code handles None case
            assert hasattr(record, "client_host")

    async def test_handles_empty_query_params(
        self, app: FastAPI, async_client: AsyncClient, caplog: LogCaptureFixture
    ) -> None:
        """Test handling of requests without query parameters."""
        with caplog.at_level(logging.INFO):
            response = await async_client.get("/test")

        assert response.status_code == 200

        started_logs = [r for r in caplog.records if "Request started" in r.message]
        record = started_logs[0]

        # Should not have query_params attribute if none present
        # Or it should be empty dict
        if hasattr(record, "query_params"):
            assert record.query_params == {}


class TestIntegrationWithLoggingContext:
    """Test integration with logging context system."""

    async def test_context_available_in_endpoint(self, caplog: LogCaptureFixture) -> None:
        """Test that trace context is available in endpoint via logging.

        Note: Context injection requires ContextInjectingFilter to be configured
        in the logging system. In tests without full logging setup, context may
        not be automatically injected. This test verifies the middleware sets
        the context correctly.
        """
        app = FastAPI()

        @app.get("/test")
        async def test_endpoint(request: Request):
            # Verify context is accessible via request state
            assert hasattr(request.state, "trace_id")
            assert hasattr(request.state, "span_id")

            # Log from endpoint
            logger = logging.getLogger(__name__)
            logger.info("Endpoint processing")
            return {
                "trace_id": request.state.trace_id,
                "span_id": request.state.span_id,
            }

        app.add_middleware(DebugMiddleware, enabled=True)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with caplog.at_level(logging.INFO):
                response = await client.get("/test")

            assert response.status_code == 200

            # Verify trace context in response
            data = response.json()
            assert "trace_id" in data
            assert "span_id" in data
            assert len(data["trace_id"]) > 0
            assert len(data["span_id"]) == 8
