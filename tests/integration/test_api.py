"""Integration tests for API endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    """Test health check endpoint returns healthy status.

    Args:
        client: Async HTTP client fixture.
    """
    response = await client.get("/api/v1/health/")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "example-service"
    assert "timestamp" in data
    assert "version" in data


@pytest.mark.asyncio
async def test_readiness_check(client: AsyncClient):
    """Test readiness check endpoint.

    Args:
        client: Async HTTP client fixture.
    """
    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 200

    data = response.json()
    assert "ready" in data
    assert "checks" in data
    assert "timestamp" in data


@pytest.mark.asyncio
async def test_liveness_check(client: AsyncClient):
    """Test liveness check endpoint.

    Args:
        client: Async HTTP client fixture.
    """
    response = await client.get("/api/v1/health/live")
    assert response.status_code == 200

    data = response.json()
    assert data["alive"] is True
    assert "timestamp" in data
