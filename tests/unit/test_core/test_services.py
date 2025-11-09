"""Unit tests for core services."""
from __future__ import annotations

import pytest

from example_service.core.services.health import HealthService


@pytest.mark.asyncio
async def test_health_service_check_health():
    """Test HealthService.check_health returns expected structure.

    Verifies that the health check returns all required fields
    with correct types and values.
    """
    service = HealthService()
    result = await service.check_health()

    assert "status" in result
    assert result["status"] == "healthy"
    assert "timestamp" in result
    assert "service" in result
    assert result["service"] == "test-service"  # From test environment
    assert "version" in result


@pytest.mark.asyncio
async def test_health_service_readiness():
    """Test HealthService.readiness returns expected structure.

    Verifies that the readiness check returns all required fields
    and dependency check results.
    """
    service = HealthService()
    result = await service.readiness()

    assert "ready" in result
    assert "checks" in result
    assert isinstance(result["checks"], dict)
    assert "timestamp" in result


@pytest.mark.asyncio
async def test_health_service_liveness():
    """Test HealthService.liveness returns expected structure.

    Verifies that the liveness check returns alive status
    and timestamp.
    """
    service = HealthService()
    result = await service.liveness()

    assert "alive" in result
    assert result["alive"] is True
    assert "timestamp" in result
