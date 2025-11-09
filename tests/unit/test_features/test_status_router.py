"""Unit tests for status router."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


@pytest.mark.unit
class TestStatusRouter:
    """Test suite for status router endpoints."""

    @pytest.mark.asyncio
    async def test_startup_endpoint_returns_started(self, app: FastAPI):
        """Test /startup endpoint returns started status."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/health/startup")

            assert response.status_code == 200
            data = response.json()

            assert "started" in data
            assert "timestamp" in data
            assert data["started"] is True

    @pytest.mark.asyncio
    async def test_health_endpoint_with_mock_service(self, app: FastAPI):
        """Test health endpoint with mocked health service."""
        mock_health_data = {
            "status": "healthy",
            "service": "test-service",
            "version": "1.0.0",
            "timestamp": "2025-01-01T00:00:00Z",
            "checks": {"database": True, "cache": True}
        }

        with patch("example_service.features.status.router.HealthService") as MockHealthService:
            mock_instance = AsyncMock()
            mock_instance.check_health = AsyncMock(return_value=mock_health_data)
            MockHealthService.return_value = mock_instance

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.get("/api/v1/health/")

                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_readiness_endpoint_with_mock_service(self, app: FastAPI):
        """Test readiness endpoint with mocked health service."""
        mock_readiness_data = {
            "ready": True,
            "checks": {"database": True},
            "timestamp": "2025-01-01T00:00:00Z"
        }

        with patch("example_service.features.status.router.HealthService") as MockHealthService:
            mock_instance = AsyncMock()
            mock_instance.readiness = AsyncMock(return_value=mock_readiness_data)
            MockHealthService.return_value = mock_instance

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.get("/api/v1/health/ready")

                assert response.status_code == 200
                data = response.json()
                assert data["ready"] is True

    @pytest.mark.asyncio
    async def test_liveness_endpoint_always_returns_alive(self, app: FastAPI):
        """Test liveness endpoint always returns alive."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/health/live")

            assert response.status_code == 200
            data = response.json()
            assert data["alive"] is True
            assert "timestamp" in data
