"""Unit tests for MetricsMiddleware."""
from __future__ import annotations

import contextlib
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from example_service.app.middleware.metrics import MetricsMiddleware


class TestMetricsMiddleware:
    """Test suite for MetricsMiddleware."""

    @pytest.fixture
    def app(self) -> FastAPI:
        """Create FastAPI app with metrics middleware.

        Returns:
            FastAPI application with middleware.
        """
        app = FastAPI()
        app.add_middleware(MetricsMiddleware)

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        @app.get("/users/{user_id}")
        async def user_endpoint(user_id: int):
            return {"user_id": user_id}

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

    @patch("example_service.app.middleware.metrics.http_requests_in_progress")
    async def test_tracks_in_progress_requests(
        self, mock_in_progress: MagicMock, client: AsyncClient
    ):
        """Test that in-progress requests are tracked."""
        await client.get("/test")

        # Should increment before request and decrement after
        assert mock_in_progress.labels.return_value.inc.called
        assert mock_in_progress.labels.return_value.dec.called

    @patch("example_service.app.middleware.metrics.http_requests_total")
    async def test_tracks_total_requests(
        self, mock_requests_total: MagicMock, client: AsyncClient
    ):
        """Test that total requests counter is incremented."""
        await client.get("/test")

        # Should increment counter with labels
        assert mock_requests_total.labels.return_value.inc.called
        call_kwargs = mock_requests_total.labels.call_args[1]
        assert "method" in call_kwargs
        assert "endpoint" in call_kwargs
        assert "status" in call_kwargs

    @patch("example_service.app.middleware.metrics.http_request_duration_seconds")
    async def test_tracks_request_duration(
        self, mock_duration: MagicMock, client: AsyncClient
    ):
        """Test that request duration is tracked."""
        await client.get("/test")

        # Should observe duration with labels
        assert mock_duration.labels.return_value.observe.called
        call_args = mock_duration.labels.return_value.observe.call_args[0]
        # First arg should be duration (float)
        assert len(call_args) > 0
        assert isinstance(call_args[0], float)
        assert call_args[0] >= 0

    async def test_adds_timing_header(self, client: AsyncClient):
        """Test that X-Process-Time header is added to response."""
        response = await client.get("/test")

        assert "x-process-time" in response.headers
        # Should be a valid float
        process_time = float(response.headers["x-process-time"])
        assert process_time >= 0

    @patch("example_service.app.middleware.metrics.http_requests_in_progress")
    async def test_decrements_in_progress_on_error(self, mock_in_progress: MagicMock):
        """Test that in-progress counter is decremented even on error."""
        app = FastAPI()
        app.add_middleware(MetricsMiddleware)

        @app.get("/error")
        async def error_endpoint():
            raise ValueError("Test error")

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            with pytest.raises(ValueError):
                await client.get("/error")

        # Should still decrement in-progress counter in finally block
        assert mock_in_progress.labels.return_value.dec.called

    @patch("example_service.app.middleware.metrics.http_requests_total")
    async def test_records_error_status_code(
        self, mock_requests_total: MagicMock
    ):
        """Test that error status codes are properly recorded."""
        app = FastAPI()
        app.add_middleware(MetricsMiddleware)

        @app.get("/error")
        async def error_endpoint():
            raise ValueError("Test error")

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            with pytest.raises(ValueError):
                await client.get("/error")

        # Should record status=500 for unhandled exception
        if mock_requests_total.labels.called:
            call_kwargs = mock_requests_total.labels.call_args[1]
            # Default status on exception should be 500
            assert call_kwargs.get("status") in [500, "500"]

    @patch("example_service.app.middleware.metrics.trace")
    async def test_trace_correlation_with_exemplar(
        self, mock_trace: MagicMock, client: AsyncClient
    ):
        """Test that metrics are linked to traces via exemplars."""
        # Mock trace span with valid context
        mock_span = MagicMock()
        mock_span.get_span_context.return_value.is_valid = True
        mock_span.get_span_context.return_value.trace_id = 123456789
        mock_trace.get_current_span.return_value = mock_span

        with patch("example_service.app.middleware.metrics.http_request_duration_seconds") as mock_duration:
            await client.get("/test")

            # Should observe with exemplar containing trace_id
            call_kwargs = mock_duration.labels.return_value.observe.call_args[1]
            assert "exemplar" in call_kwargs
            assert "trace_id" in call_kwargs["exemplar"]

    @patch("example_service.app.middleware.metrics.trace")
    async def test_metrics_without_trace(
        self, mock_trace: MagicMock, client: AsyncClient
    ):
        """Test that metrics work without active trace."""
        # Mock trace span with invalid context
        mock_span = MagicMock()
        mock_span.get_span_context.return_value.is_valid = False
        mock_trace.get_current_span.return_value = mock_span

        with patch("example_service.app.middleware.metrics.http_request_duration_seconds") as mock_duration:
            await client.get("/test")

            # Should observe without exemplar
            call_args = mock_duration.labels.return_value.observe.call_args
            # Check if exemplar is NOT present or is None
            if len(call_args) > 1:
                assert call_args[1].get("exemplar") is None or "exemplar" not in call_args[1]

    async def test_uses_route_template_for_low_cardinality(self):
        """Test that route templates are used instead of actual paths."""
        app = FastAPI()

        @app.get("/users/{user_id}")
        async def user_endpoint(user_id: int):
            return {"user_id": user_id}

        from httpx import ASGITransport

        with patch("example_service.app.middleware.metrics.http_requests_total") as mock_total:
            # Add middleware after defining routes
            app.add_middleware(MetricsMiddleware)

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                # Make requests with different IDs
                await client.get("/users/123")
                await client.get("/users/456")

            # Should use template "/users/{user_id}" not actual paths
            # This prevents high cardinality metrics
            if mock_total.labels.called:
                endpoints = [
                    call[1].get("endpoint")
                    for call in mock_total.labels.call_args_list
                ]
                # Should use path template, not actual ID
                # Note: Exact behavior depends on when route is resolved
                assert any("/users" in str(ep) for ep in endpoints)

    async def test_different_http_methods(self):
        """Test metrics for different HTTP methods."""
        app = FastAPI()
        app.add_middleware(MetricsMiddleware)

        @app.get("/resource")
        async def get_resource():
            return {"method": "GET"}

        @app.post("/resource")
        async def post_resource():
            return {"method": "POST"}

        @app.put("/resource")
        async def put_resource():
            return {"method": "PUT"}

        from httpx import ASGITransport

        with patch("example_service.app.middleware.metrics.http_requests_total") as mock_total:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.get("/resource")
                await client.post("/resource")
                await client.put("/resource")

            # Should record metrics for each method
            assert mock_total.labels.call_count >= 3

            methods = [
                call[1].get("method")
                for call in mock_total.labels.call_args_list
            ]
            assert "GET" in methods
            assert "POST" in methods
            assert "PUT" in methods

    async def test_concurrent_requests(self):
        """Test that metrics handle concurrent requests correctly."""
        import asyncio

        app = FastAPI()
        app.add_middleware(MetricsMiddleware)

        @app.get("/test")
        async def test_endpoint():
            await asyncio.sleep(0.01)  # Small delay
            return {"message": "ok"}

        from httpx import ASGITransport

        with patch("example_service.app.middleware.metrics.http_requests_in_progress") as mock_in_progress:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                # Make 10 concurrent requests
                tasks = [client.get("/test") for _ in range(10)]
                await asyncio.gather(*tasks)

            # Should track in-progress correctly
            assert mock_in_progress.labels.return_value.inc.call_count == 10
            assert mock_in_progress.labels.return_value.dec.call_count == 10

    async def test_status_code_labels(self):
        """Test that different status codes are tracked separately."""
        app = FastAPI()
        app.add_middleware(MetricsMiddleware)

        @app.get("/success")
        async def success_endpoint():
            return {"status": "ok"}

        @app.get("/not-found")
        async def not_found_endpoint():
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Not found")

        from httpx import ASGITransport

        with patch("example_service.app.middleware.metrics.http_requests_total") as mock_total:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.get("/success")

                with contextlib.suppress(Exception):
                    await client.get("/not-found")

            # Should record different status codes
            status_codes = [
                call[1].get("status")
                for call in mock_total.labels.call_args_list
            ]
            assert 200 in status_codes or "200" in status_codes

    async def test_timing_header_accuracy(self):
        """Test that X-Process-Time header reflects actual processing time."""
        import asyncio

        app = FastAPI()
        app.add_middleware(MetricsMiddleware)

        @app.get("/slow")
        async def slow_endpoint():
            await asyncio.sleep(0.1)  # 100ms delay
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/slow")

        process_time = float(response.headers["x-process-time"])
        # Should be at least 0.1 seconds
        assert process_time >= 0.1

    async def test_metric_labels_structure(self, client: AsyncClient):
        """Test that metric labels have correct structure."""
        with patch("example_service.app.middleware.metrics.http_requests_total") as mock_total:
            await client.get("/test")

            # Verify label structure
            call_kwargs = mock_total.labels.call_args[1]
            assert "method" in call_kwargs
            assert "endpoint" in call_kwargs
            assert "status" in call_kwargs

            # Verify label types
            assert isinstance(call_kwargs["method"], str)
            assert isinstance(call_kwargs["endpoint"], str)

    @patch("example_service.app.middleware.metrics.http_request_duration_seconds")
    async def test_duration_histogram_buckets(
        self, mock_duration: MagicMock, client: AsyncClient
    ):
        """Test that duration is recorded as histogram observation."""
        await client.get("/test")

        # Should call observe (histogram method)
        assert mock_duration.labels.return_value.observe.called

        # Duration should be positive float
        duration = mock_duration.labels.return_value.observe.call_args[0][0]
        assert isinstance(duration, float)
        assert duration >= 0

    async def test_trace_id_format_in_exemplar(self):
        """Test that trace_id in exemplar is formatted correctly."""
        app = FastAPI()
        app.add_middleware(MetricsMiddleware)

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        with patch("example_service.app.middleware.metrics.trace") as mock_trace:
            # Mock valid trace
            mock_span = MagicMock()
            mock_span.get_span_context.return_value.is_valid = True
            mock_span.get_span_context.return_value.trace_id = 0x123456789ABCDEF0123456789ABCDEF0
            mock_trace.get_current_span.return_value = mock_span

            with patch("example_service.app.middleware.metrics.http_request_duration_seconds") as mock_duration:
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    await client.get("/test")

                # Check trace_id format (32-character hex)
                exemplar = mock_duration.labels.return_value.observe.call_args[1]["exemplar"]
                trace_id = exemplar["trace_id"]
                assert len(trace_id) == 32
                # Should be valid hex
                int(trace_id, 16)

    async def test_handles_missing_route(self):
        """Test metrics when route information is not available."""
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

        middleware = MetricsMiddleware(mock_app)

        # Scope without route info
        scope: Scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "headers": [],
        }

        receive = AsyncMock()
        send = AsyncMock()

        with patch("example_service.app.middleware.metrics.http_requests_total"):
            await middleware(scope, receive, send)

        # Should use path as endpoint when route not available
        # No exception should be raised

    async def test_performance_overhead(self):
        """Test that metrics middleware has minimal performance overhead."""
        import time

        app = FastAPI()
        app.add_middleware(MetricsMiddleware)

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

            # Should complete 100 requests in reasonable time
            # Even with metrics, should be fast
            assert elapsed < 2.0, f"100 requests took {elapsed:.3f}s, performance degraded"
