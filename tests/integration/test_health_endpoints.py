"""Integration tests for health check endpoints."""
from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
async def test_health_endpoint_returns_200(client: AsyncClient):
    """Test main health endpoint returns 200 OK."""
    response = await client.get("/api/v1/health/")

    assert response.status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_health_endpoint_structure(client: AsyncClient):
    """Test health endpoint returns expected structure."""
    response = await client.get("/api/v1/health/")
    data = response.json()

    # Required fields
    assert "status" in data
    assert "service" in data
    assert "timestamp" in data
    assert "version" in data

    # Correct values
    assert data["status"] == "healthy"
    assert data["service"] == "test-service"  # From env var in conftest
    assert isinstance(data["timestamp"], str)
    assert isinstance(data["version"], str)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_readiness_endpoint_returns_200(client: AsyncClient):
    """Test readiness endpoint returns 200 OK."""
    response = await client.get("/api/v1/health/ready")

    assert response.status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_readiness_endpoint_structure(client: AsyncClient):
    """Test readiness endpoint returns expected structure."""
    response = await client.get("/api/v1/health/ready")
    data = response.json()

    # Required fields
    assert "ready" in data
    assert "checks" in data
    assert "timestamp" in data

    # Types
    assert isinstance(data["ready"], bool)
    assert isinstance(data["checks"], dict)
    assert isinstance(data["timestamp"], str)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_liveness_endpoint_returns_200(client: AsyncClient):
    """Test liveness endpoint returns 200 OK."""
    response = await client.get("/api/v1/health/live")

    assert response.status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_liveness_endpoint_structure(client: AsyncClient):
    """Test liveness endpoint returns expected structure."""
    response = await client.get("/api/v1/health/live")
    data = response.json()

    # Required fields
    assert "alive" in data
    assert "timestamp" in data

    # Values
    assert data["alive"] is True
    assert isinstance(data["timestamp"], str)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_health_endpoints_have_request_id(client: AsyncClient):
    """Test that health endpoints include X-Request-ID header."""
    response = await client.get("/api/v1/health/")

    assert "X-Request-ID" in response.headers
    assert len(response.headers["X-Request-ID"]) > 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_health_endpoints_have_process_time(client: AsyncClient):
    """Test that health endpoints include X-Process-Time header."""
    response = await client.get("/api/v1/health/")

    assert "X-Process-Time" in response.headers
    # Should be a valid float
    process_time = float(response.headers["X-Process-Time"])
    assert process_time >= 0
