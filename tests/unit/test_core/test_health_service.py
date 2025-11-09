"""Comprehensive unit tests for HealthService."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from example_service.core.services.health import HealthService


@pytest.mark.unit
class TestHealthServiceComprehensive:
    """Comprehensive test suite for HealthService."""

    @pytest.mark.asyncio
    async def test_check_health_all_checks_healthy(self):
        """Test check_health when all checks pass."""
        service = HealthService()
        result = await service.check_health()

        assert result["status"] == "healthy"
        assert "timestamp" in result
        assert "service" in result
        assert "version" in result
        assert "checks" in result

    @pytest.mark.asyncio
    async def test_check_health_with_database_configured(self):
        """Test health check when database is configured."""
        service = HealthService()

        with patch("example_service.core.services.health.get_db_settings") as mock_db_settings:
            mock_settings = AsyncMock()
            mock_settings.is_configured = True
            mock_db_settings.return_value = mock_settings

            with patch.object(service, "_check_database", return_value=True):
                result = await service.check_health()

                assert "checks" in result
                assert result["checks"]["database"] is True

    @pytest.mark.asyncio
    async def test_check_health_with_redis_configured(self):
        """Test health check when Redis is configured."""
        service = HealthService()

        with patch("example_service.core.services.health.get_redis_settings") as mock_redis_settings:
            mock_settings = AsyncMock()
            mock_settings.is_configured = True
            mock_redis_settings.return_value = mock_settings

            with patch.object(service, "_check_cache", return_value=True):
                result = await service.check_health()

                assert "checks" in result
                assert result["checks"]["cache"] is True

    @pytest.mark.asyncio
    async def test_check_health_with_auth_service_configured(self):
        """Test health check when auth service is configured."""
        service = HealthService()

        with patch("example_service.core.services.health.get_auth_settings") as mock_auth_settings:
            mock_settings = AsyncMock()
            mock_settings.is_configured = True
            mock_settings.service_url = "http://auth:8000"
            mock_auth_settings.return_value = mock_settings

            with patch.object(service, "_check_external_service", return_value=True):
                result = await service.check_health()

                assert "checks" in result
                assert result["checks"]["auth_service"] is True

    @pytest.mark.asyncio
    async def test_readiness_returns_structure(self):
        """Test readiness check returns expected structure."""
        service = HealthService()
        result = await service.readiness()

        assert "ready" in result
        assert "timestamp" in result
        assert "checks" in result
        assert isinstance(result["ready"], bool)

    @pytest.mark.asyncio
    async def test_readiness_with_database_check(self):
        """Test readiness when database is configured."""
        service = HealthService()

        with patch("example_service.core.services.health.get_db_settings") as mock_db_settings:
            mock_settings = AsyncMock()
            mock_settings.is_configured = True
            mock_db_settings.return_value = mock_settings

            with patch.object(service, "_check_database", return_value=True):
                result = await service.readiness()

                assert result["ready"] is True
                assert result["checks"]["database"] is True

    @pytest.mark.asyncio
    async def test_readiness_fails_when_database_down(self):
        """Test readiness fails when database check fails."""
        service = HealthService()

        with patch("example_service.core.services.health.get_db_settings") as mock_db_settings:
            mock_settings = AsyncMock()
            mock_settings.is_configured = True
            mock_db_settings.return_value = mock_settings

            with patch.object(service, "_check_database", return_value=False):
                result = await service.readiness()

                assert result["ready"] is False
                assert result["checks"]["database"] is False

    @pytest.mark.asyncio
    async def test_liveness_always_returns_true(self):
        """Test liveness always returns alive status."""
        service = HealthService()
        result = await service.liveness()

        assert result["alive"] is True
        assert "timestamp" in result

    @pytest.mark.asyncio
    async def test_perform_health_checks_returns_checks(self):
        """Test _perform_health_checks returns check results."""
        service = HealthService()

        # This will test with default (no services configured)
        checks = await service._perform_health_checks()

        assert isinstance(checks, dict)
        # When nothing is configured, checks should still return True
        assert checks.get("database") is True
        assert checks.get("cache") is True

    @pytest.mark.asyncio
    async def test_perform_readiness_checks_returns_checks(self):
        """Test _perform_readiness_checks returns check results."""
        service = HealthService()

        # This will test with default (no database configured)
        checks = await service._perform_readiness_checks()

        assert isinstance(checks, dict)
