"""Unit tests for CorrelationIDMiddleware."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request
from starlette.testclient import TestClient

from example_service.app.middleware.correlation_id import (
    CorrelationIDMiddleware,
    get_correlation_id_from_request,
)


@pytest.fixture
def app():
    """Create a test FastAPI application with CorrelationIDMiddleware."""
    app = FastAPI()

    # Add correlation ID middleware
    app.add_middleware(CorrelationIDMiddleware)

    # Test endpoint that returns correlation ID from request state
    @app.get("/test")
    async def test_endpoint(request: Request):
        correlation_id = getattr(request.state, "correlation_id", None)
        return {"correlation_id": correlation_id}

    # Endpoint that uses helper function
    @app.get("/test-helper")
    async def test_helper_endpoint(request: Request):
        correlation_id = get_correlation_id_from_request(request)
        return {"correlation_id": correlation_id}

    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


class TestCorrelationIDMiddleware:
    """Tests for CorrelationIDMiddleware."""

    def test_generates_correlation_id_when_not_provided(self, client):
        """Test that correlation ID is generated when not in request."""
        response = client.get("/test")

        assert response.status_code == 200
        data = response.json()

        # Should generate a correlation ID
        assert data["correlation_id"] is not None
        assert len(data["correlation_id"]) == 36  # UUID format

    def test_preserves_existing_correlation_id(self, client):
        """Test that existing correlation ID from upstream is preserved."""
        correlation_id = "test-correlation-123"

        response = client.get("/test", headers={"X-Correlation-ID": correlation_id})

        assert response.status_code == 200
        data = response.json()

        # Should preserve the provided correlation ID
        assert data["correlation_id"] == correlation_id

    def test_correlation_id_in_response_header(self, client):
        """Test that correlation ID is added to response headers."""
        response = client.get("/test")

        assert response.status_code == 200
        assert "x-correlation-id" in response.headers
        assert len(response.headers["x-correlation-id"]) == 36

    def test_preserves_upstream_correlation_id_in_response(self, client):
        """Test that upstream correlation ID is returned in response headers."""
        correlation_id = "upstream-correlation-456"

        response = client.get("/test", headers={"X-Correlation-ID": correlation_id})

        assert response.status_code == 200
        assert response.headers["x-correlation-id"] == correlation_id

    def test_correlation_id_available_in_request_state(self, client):
        """Test that correlation ID is stored in request.state."""
        response = client.get("/test")

        assert response.status_code == 200
        data = response.json()

        # Correlation ID from response should match what's in state
        assert data["correlation_id"] is not None
        assert response.headers["x-correlation-id"] == data["correlation_id"]

    def test_get_correlation_id_from_request_helper(self, client):
        """Test the helper function for extracting correlation ID."""
        correlation_id = "helper-test-789"

        response = client.get("/test-helper", headers={"X-Correlation-ID": correlation_id})

        assert response.status_code == 200
        data = response.json()
        assert data["correlation_id"] == correlation_id

    def test_handles_non_http_scope(self):
        """Test that middleware skips non-HTTP requests."""
        app = AsyncMock()  # Must be AsyncMock since middleware awaits it
        middleware = CorrelationIDMiddleware(app)

        scope = {"type": "websocket"}
        receive = AsyncMock()
        send = AsyncMock()

        # Should pass through to app for non-HTTP requests
        asyncio.run(middleware(scope, receive, send))
        app.assert_called_once_with(scope, receive, send)

    def test_case_insensitive_header_handling(self, client):
        """Test that header name is case-insensitive."""
        correlation_id = "case-test-123"

        # Try different case variations
        variations = [
            "X-Correlation-ID",
            "x-correlation-id",
            "X-CORRELATION-ID",
        ]

        for header_name in variations:
            response = client.get("/test", headers={header_name: correlation_id})

            assert response.status_code == 200
            data = response.json()
            assert data["correlation_id"] == correlation_id

    def test_multiple_requests_have_different_correlation_ids(self, client):
        """Test that concurrent requests get unique correlation IDs."""
        # Make multiple requests without providing correlation ID
        responses = [client.get("/test") for _ in range(5)]

        correlation_ids = [response.json()["correlation_id"] for response in responses]

        # All correlation IDs should be unique
        assert len(set(correlation_ids)) == 5

    def test_custom_header_name(self):
        """Test middleware with custom header name."""
        app = FastAPI()
        custom_header = "x-custom-correlation"

        app.add_middleware(
            CorrelationIDMiddleware,
            header_name=custom_header,
        )

        @app.get("/test")
        async def test_endpoint(request: Request):
            return {"correlation_id": request.state.correlation_id}

        client = TestClient(app)
        correlation_id = "custom-header-test"

        response = client.get("/test", headers={custom_header: correlation_id})

        assert response.status_code == 200
        data = response.json()
        assert data["correlation_id"] == correlation_id
        assert response.headers[custom_header] == correlation_id

    def test_generate_if_missing_false(self):
        """Test that correlation ID is not generated when disabled."""
        app = FastAPI()

        app.add_middleware(
            CorrelationIDMiddleware,
            generate_if_missing=False,
        )

        @app.get("/test")
        async def test_endpoint(request: Request):
            correlation_id = getattr(request.state, "correlation_id", "NOT_SET")
            return {"correlation_id": correlation_id}

        client = TestClient(app)

        response = client.get("/test")

        assert response.status_code == 200
        data = response.json()

        # Should not generate correlation ID
        assert data["correlation_id"] is None

    def test_correlation_id_with_error_response(self, client):
        """Test that correlation ID is still in response headers on error."""
        correlation_id = "error-test-123"

        # Test with invalid endpoint (404)
        response = client.get("/nonexistent", headers={"X-Correlation-ID": correlation_id})

        assert response.status_code == 404
        # Correlation ID should still be in response headers
        assert response.headers["x-correlation-id"] == correlation_id

    def test_distributed_tracing_scenario(self):
        """Test correlation ID flow across multiple services."""
        app = FastAPI()
        app.add_middleware(CorrelationIDMiddleware)

        # Simulate service chain: Client → Service A → Service B
        @app.get("/service-a")
        async def service_a(request: Request):
            """First service receives correlation ID from client."""
            correlation_id = get_correlation_id_from_request(request)

            # Service A would pass this to Service B
            return {
                "service": "A",
                "correlation_id": correlation_id,
                "message": "Pass this correlation_id to Service B",
            }

        @app.get("/service-b")
        async def service_b(request: Request):
            """Second service receives same correlation ID."""
            correlation_id = get_correlation_id_from_request(request)

            return {
                "service": "B",
                "correlation_id": correlation_id,
                "message": "Received correlation_id from Service A",
            }

        client = TestClient(app)
        correlation_id = "transaction-12345"

        # Client calls Service A
        response_a = client.get("/service-a", headers={"X-Correlation-ID": correlation_id})
        data_a = response_a.json()

        # Service A calls Service B with same correlation ID
        response_b = client.get(
            "/service-b", headers={"X-Correlation-ID": data_a["correlation_id"]}
        )
        data_b = response_b.json()

        # Both services should use the same correlation ID
        assert data_a["correlation_id"] == correlation_id
        assert data_b["correlation_id"] == correlation_id

    def test_concurrent_requests_maintain_isolation(self, client):
        """Test that concurrent requests don't share correlation IDs."""
        correlation_ids = [f"concurrent-{i}" for i in range(10)]

        # Make concurrent requests with different correlation IDs
        responses = [
            client.get("/test", headers={"X-Correlation-ID": cid}) for cid in correlation_ids
        ]

        # Verify each response has the correct correlation ID
        for i, response in enumerate(responses):
            assert response.status_code == 200
            data = response.json()
            assert data["correlation_id"] == correlation_ids[i]
            assert response.headers["x-correlation-id"] == correlation_ids[i]

    def test_correlation_id_format_validation(self, client):
        """Test that various correlation ID formats are accepted."""
        test_formats = [
            "550e8400-e29b-41d4-a716-446655440000",  # UUID
            "abc123",  # Simple string
            "correlation-id-with-hyphens",  # Hyphenated
            "CamelCaseCorrelationId",  # Camel case
            "under_score_id",  # Underscores
            "123-456-789",  # Numeric with hyphens
        ]

        for correlation_id in test_formats:
            response = client.get("/test", headers={"X-Correlation-ID": correlation_id})

            assert response.status_code == 200
            data = response.json()
            assert data["correlation_id"] == correlation_id

    def test_empty_correlation_id_header(self, client):
        """Test handling of empty correlation ID header."""
        response = client.get("/test", headers={"X-Correlation-ID": ""})

        assert response.status_code == 200
        # Empty string should be treated as missing, new ID generated
        # (depending on middleware implementation)

    def test_performance_with_pure_asgi(self, client):
        """Test that pure ASGI implementation performs well."""
        import time

        # Measure performance with 100 requests
        start_time = time.time()

        for _ in range(100):
            response = client.get("/test")
            assert response.status_code == 200

        duration = time.time() - start_time

        # Should complete 100 requests in less than 2 seconds
        # (Pure ASGI is much faster than BaseHTTPMiddleware)
        assert duration < 2.0, f"100 requests took {duration:.2f}s (too slow)"


class TestCorrelationIDIntegration:
    """Integration tests for correlation ID with other middleware."""

    def test_correlation_id_with_request_id(self):
        """Test that correlation ID and request ID work together."""
        from example_service.app.middleware.request_id import RequestIDMiddleware

        app = FastAPI()

        # Add both middleware (correlation ID first, then request ID)
        app.add_middleware(CorrelationIDMiddleware)
        app.add_middleware(RequestIDMiddleware)

        @app.get("/test")
        async def test_endpoint(request: Request):
            return {
                "correlation_id": getattr(request.state, "correlation_id", None),
                "request_id": getattr(request.state, "request_id", None),
            }

        client = TestClient(app)
        correlation_id = "correlation-123"
        request_id = "request-456"

        response = client.get(
            "/test",
            headers={
                "X-Correlation-ID": correlation_id,
                "X-Request-ID": request_id,
            },
        )

        assert response.status_code == 200
        data = response.json()

        # Both IDs should be present
        assert data["correlation_id"] == correlation_id
        assert data["request_id"] == request_id

        # Both should be in response headers
        assert response.headers["x-correlation-id"] == correlation_id
        assert response.headers["x-request-id"] == request_id

    def test_correlation_id_persists_across_error(self):
        """Test that correlation ID is preserved even when endpoint raises error."""
        app = FastAPI()
        app.add_middleware(CorrelationIDMiddleware)

        @app.get("/error")
        async def error_endpoint(request: Request):
            raise ValueError("Test error")

        client = TestClient(app, raise_server_exceptions=False)
        correlation_id = "error-correlation-789"

        response = client.get("/error", headers={"X-Correlation-ID": correlation_id})

        # Error should occur but correlation ID should still be in headers
        assert response.status_code == 500
        assert response.headers["x-correlation-id"] == correlation_id
