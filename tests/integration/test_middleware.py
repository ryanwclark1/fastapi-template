"""Integration tests for middleware."""
from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
async def test_request_id_middleware_adds_header(client: AsyncClient):
    """Test that RequestID middleware adds X-Request-ID header."""
    response = await client.get("/api/v1/health/")

    assert "X-Request-ID" in response.headers
    request_id = response.headers["X-Request-ID"]
    assert len(request_id) > 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_request_id_middleware_preserves_existing(client: AsyncClient):
    """Test that RequestID middleware preserves existing request ID."""
    custom_id = "test-request-id-123"

    response = await client.get(
        "/api/v1/health/",
        headers={"X-Request-ID": custom_id}
    )

    assert response.headers["X-Request-ID"] == custom_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_timing_middleware_adds_header(client: AsyncClient):
    """Test that Timing middleware adds X-Process-Time header."""
    response = await client.get("/api/v1/health/")

    assert "X-Process-Time" in response.headers
    process_time = float(response.headers["X-Process-Time"])
    assert process_time >= 0
    assert process_time < 10.0  # Should be very fast


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cors_headers_present(client: AsyncClient):
    """Test that CORS headers are present in responses."""
    # CORS headers are only added when Origin header is present
    response = await client.get(
        "/api/v1/health/",
        headers={"Origin": "http://localhost:3000"}
    )

    # CORS headers should be present
    assert "access-control-allow-origin" in response.headers
    # Specific method/header CORS headers are only in preflight (OPTIONS)
    # For regular requests, just verify allow-origin is present
