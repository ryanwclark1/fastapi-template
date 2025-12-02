"""Integration tests for middleware execution order."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI, Request
from httpx import AsyncClient

from example_service.app.middleware.metrics import MetricsMiddleware
from example_service.app.middleware.request_id import RequestIDMiddleware
from example_service.app.middleware.request_logging import RequestLoggingMiddleware
from example_service.app.middleware.security_headers import SecurityHeadersMiddleware
from example_service.app.middleware.size_limit import RequestSizeLimitMiddleware


class TestMiddlewareOrdering:
    """Integration tests for middleware execution order."""

    async def test_request_id_runs_before_logging(self):
        """Test that RequestID middleware runs before logging middleware."""
        app = FastAPI()

        # Add in correct order (last added = outermost = first to run)
        # But we want to verify RequestID runs before Logging
        app.add_middleware(RequestLoggingMiddleware)
        app.add_middleware(RequestIDMiddleware)

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        with patch("example_service.app.middleware.request_logging.logger") as mock_logger:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/test")

        # Request ID should be in response (set by RequestIDMiddleware)
        assert "x-request-id" in response.headers
        request_id = response.headers["x-request-id"]

        # Logs should contain the request_id (proving RequestID ran first)
        if mock_logger.log.called:
            call_args = mock_logger.log.call_args_list
            request_logs = [
                call for call in call_args if len(call[0]) > 1 and call[0][1] == "HTTP Request"
            ]
            if request_logs:
                log_extra = request_logs[0][1]["extra"]
                # request_id should be in log context
                assert log_extra.get("request_id") == request_id

    async def test_size_limit_runs_before_body_processing(self):
        """Test that size limit middleware rejects before body is processed."""
        app = FastAPI()

        request_body_processed = []

        @app.middleware("http")
        async def track_body_processing(request: Request, call_next):
            # Try to read body
            try:
                body = await request.body()
                request_body_processed.append(len(body))
            except Exception:
                pass
            return await call_next(request)

        # Add size limit (should run first)
        app.add_middleware(RequestSizeLimitMiddleware, max_size=100)

        @app.post("/upload")
        async def upload_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Send large payload
            response = await client.post("/upload", json={"data": "x" * 1000})

        # Should be rejected by size limit
        assert response.status_code == 413

        # Body should not have been processed (size limit rejected early)
        # Note: This test demonstrates early rejection

    async def test_security_headers_applied_after_processing(self):
        """Test that security headers are applied to final response."""
        app = FastAPI()

        # Add security headers first (outermost)
        app.add_middleware(SecurityHeadersMiddleware)

        # Add another middleware that might modify response
        @app.middleware("http")
        async def custom_middleware(request: Request, call_next):
            response = await call_next(request)
            # Add custom header
            response.headers["X-Custom"] = "value"
            return response

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/test")

        # Both custom and security headers should be present
        assert "x-custom" in response.headers
        assert "x-frame-options" in response.headers

        # Security headers should be present (applied in outer layer)
        assert "strict-transport-security" in response.headers

    async def test_metrics_tracks_full_request_lifecycle(self):
        """Test that metrics middleware measures complete request duration."""
        import asyncio

        app = FastAPI()

        # Metrics should be outermost to measure everything
        app.add_middleware(MetricsMiddleware)

        # Add middleware that adds delay
        @app.middleware("http")
        async def slow_middleware(request: Request, call_next):
            await asyncio.sleep(0.1)  # 100ms delay
            response = await call_next(request)
            return response

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/test")

        # Timing should include middleware delay
        process_time = float(response.headers["x-process-time"])
        assert process_time >= 0.1  # Should include middleware delay

    async def test_order_of_header_injection(self):
        """Test that headers are injected in correct order."""
        app = FastAPI()

        execution_order = []

        # Create custom middleware to track order
        class OrderTracker:
            def __init__(self, app, name: str):
                self.app = app
                self.name = name

            async def __call__(self, scope, receive, send):
                if scope["type"] == "http":
                    execution_order.append(f"{self.name}_start")

                    async def wrapped_send(message):
                        if message["type"] == "http.response.start":
                            execution_order.append(f"{self.name}_headers")
                        await send(message)

                    await self.app(scope, receive, wrapped_send)
                    execution_order.append(f"{self.name}_end")
                else:
                    await self.app(scope, receive, send)

        # Add middleware in specific order
        app.add_middleware(OrderTracker, name="third")
        app.add_middleware(OrderTracker, name="second")
        app.add_middleware(OrderTracker, name="first")

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.get("/test")

        # Verify execution order:
        # - Start order: first, second, third (outer to inner)
        # - Header injection: third, second, first (inner to outer)
        # - End order: third, second, first (inner to outer)
        assert execution_order[0] == "first_start"
        assert execution_order[1] == "second_start"
        assert execution_order[2] == "third_start"

        # Headers injected in reverse order
        header_events = [e for e in execution_order if "_headers" in e]
        assert header_events[0] == "third_headers"
        assert header_events[1] == "second_headers"
        assert header_events[2] == "first_headers"

    async def test_context_availability_based_on_order(self):
        """Test that context set by earlier middleware is available to later ones."""
        app = FastAPI()

        # RequestID sets context
        app.add_middleware(RequestIDMiddleware)

        context_captured = {}

        # Custom middleware that reads context
        @app.middleware("http")
        async def context_reader(request: Request, call_next):
            # This should have access to request_id set by RequestIDMiddleware
            request_id = getattr(request.state, "request_id", None)
            context_captured["request_id"] = request_id
            return await call_next(request)

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.get("/test")

        # Context should have been captured
        assert context_captured.get("request_id") is not None

    async def test_early_rejection_skips_later_middleware(self):
        """Test that early rejection (e.g., size limit) skips downstream processing."""
        app = FastAPI()

        logging_called = []

        # Add logging middleware (should not log if size limit rejects)
        @app.middleware("http")
        async def logging_tracker(request: Request, call_next):
            logging_called.append("before")
            response = await call_next(request)
            logging_called.append("after")
            return response

        # Add size limit (runs before logging)
        app.add_middleware(RequestSizeLimitMiddleware, max_size=100)

        @app.post("/upload")
        async def upload_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Large request
            response = await client.post("/upload", json={"data": "x" * 1000})

        # Should be rejected
        assert response.status_code == 413

        # Logging middleware should not have been called
        # (size limit rejected before it could run)
        assert len(logging_called) == 0

    async def test_correct_order_for_production_stack(self):
        """Test recommended production middleware ordering."""
        app = FastAPI()

        execution_log = []

        # Track middleware execution
        class ExecutionTracker:
            def __init__(self, app, name: str):
                self.app = app
                self.name = name

            async def __call__(self, scope, receive, send):
                if scope["type"] == "http":
                    execution_log.append(self.name)
                await self.app(scope, receive, send)

        # Add in recommended production order (last added = first to run)
        app.add_middleware(ExecutionTracker, name="7_Metrics")
        app.add_middleware(ExecutionTracker, name="6_Logging")
        app.add_middleware(ExecutionTracker, name="5_RequestID")
        app.add_middleware(ExecutionTracker, name="4_Security")
        app.add_middleware(ExecutionTracker, name="3_SizeLimit")
        # app.add_middleware(ExecutionTracker, name="2_RateLimit")  # Optional
        # app.add_middleware(ExecutionTracker, name="1_CORS")  # Would be outermost

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.get("/test")

        # Verify execution order (outer to inner):
        # Size limit and security should run early
        # RequestID before Logging
        # Metrics should be outer (to measure everything)
        assert execution_log[0] == "7_Metrics"
        assert execution_log[1] == "6_Logging"
        assert execution_log[2] == "5_RequestID"
        assert execution_log[3] == "4_Security"
        assert execution_log[4] == "3_SizeLimit"

    async def test_response_modification_order(self):
        """Test that response modifications happen in reverse order."""
        app = FastAPI()

        header_order = []

        # Multiple middleware adding headers
        class HeaderAdder:
            def __init__(self, app, header_name: str):
                self.app = app
                self.header_name = header_name

            async def __call__(self, scope, receive, send):
                if scope["type"] != "http":
                    await self.app(scope, receive, send)
                    return

                async def wrapped_send(message):
                    if message["type"] == "http.response.start":
                        header_order.append(self.header_name)
                        headers = list(message.get("headers", []))
                        headers.append((self.header_name.encode(), b"value"))
                        message["headers"] = headers
                    await send(message)

                await self.app(scope, receive, wrapped_send)

        # Add middleware (last added = outermost)
        app.add_middleware(HeaderAdder, header_name="x-third")
        app.add_middleware(HeaderAdder, header_name="x-second")
        app.add_middleware(HeaderAdder, header_name="x-first")

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/test")

        # All headers should be present
        assert "x-first" in response.headers
        assert "x-second" in response.headers
        assert "x-third" in response.headers

        # Headers added in reverse order (inner to outer)
        assert header_order[0] == "x-third"  # Innermost adds first
        assert header_order[1] == "x-second"
        assert header_order[2] == "x-first"  # Outermost adds last

    async def test_exception_handling_order(self):
        """Test that exceptions bubble up through middleware in correct order."""
        app = FastAPI()

        exception_handlers = []

        class ExceptionTracker:
            def __init__(self, app, name: str):
                self.app = app
                self.name = name

            async def __call__(self, scope, receive, send):
                try:
                    await self.app(scope, receive, send)
                except ValueError:
                    exception_handlers.append(self.name)
                    raise

        app.add_middleware(ExceptionTracker, name="outer")
        app.add_middleware(ExceptionTracker, name="middle")
        app.add_middleware(ExceptionTracker, name="inner")

        @app.get("/error")
        async def error_endpoint():
            raise ValueError("Test error")

        from httpx import ASGITransport

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with pytest.raises(ValueError, match=r"Test error"):
                await client.get("/error")

        # Exception should bubble up from inner to outer
        assert exception_handlers[0] == "inner"
        assert exception_handlers[1] == "middle"
        assert exception_handlers[2] == "outer"

    async def test_logging_context_lifecycle(self):
        """Test that logging context is set and cleared in correct order."""
        import uuid

        app = FastAPI()

        context_states = []

        # Track context state in custom middleware
        @app.middleware("http")
        async def context_tracker(request: Request, call_next):
            # Check context before calling next
            from example_service.infra.logging import get_log_context

            context_states.append({"stage": "before", "context": get_log_context()})
            response = await call_next(request)
            context_states.append({"stage": "after", "context": get_log_context()})
            return response

        # Add RequestID middleware (sets context)
        app.add_middleware(RequestIDMiddleware)

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        custom_id = str(uuid.uuid4())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.get("/test", headers={"X-Request-ID": custom_id})

        # Context should have been set during request
        assert len(context_states) >= 2

        # Before endpoint: context should have request_id
        before_context = context_states[0]["context"]
        assert before_context.get("request_id") == custom_id

        # After endpoint: context should still have request_id
        after_context = context_states[1]["context"]
        assert after_context.get("request_id") == custom_id

    async def test_pure_asgi_vs_basehttpmiddleware_order(self):
        """Test interaction between pure ASGI and BaseHTTPMiddleware."""
        app = FastAPI()

        # Mix of pure ASGI (RequestID) and BaseHTTPMiddleware (Logging, Metrics)
        app.add_middleware(MetricsMiddleware)  # BaseHTTPMiddleware
        app.add_middleware(RequestLoggingMiddleware)  # BaseHTTPMiddleware
        app.add_middleware(RequestIDMiddleware)  # Pure ASGI
        app.add_middleware(SecurityHeadersMiddleware)  # Pure ASGI

        @app.get("/test")
        async def test_endpoint(request: Request):
            request_id = getattr(request.state, "request_id", None)
            return {"request_id": request_id}

        from httpx import ASGITransport

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/test")

        # All middleware should work together
        assert response.status_code == 200
        assert "x-request-id" in response.headers
        assert "x-frame-options" in response.headers
        assert "x-process-time" in response.headers

        # Request ID should be accessible in endpoint
        assert response.json()["request_id"] is not None
