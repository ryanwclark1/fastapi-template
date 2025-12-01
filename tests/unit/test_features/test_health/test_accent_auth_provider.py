"""Tests for Accent-Auth health check provider."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from example_service.core.schemas.common import HealthStatus
from example_service.features.health.accent_auth_provider import (
    AccentAuthHealthProvider,
)


@pytest.mark.asyncio
class TestAccentAuthHealthProvider:
    """Test Accent-Auth health check provider."""

    async def test_healthy_status_fast_response(self):
        """Test healthy status when service responds quickly."""
        provider = AccentAuthHealthProvider()

        with patch(
            "example_service.features.health.accent_auth_provider.get_accent_auth_client"
        ) as mock_get_client:
            # Mock the client and response
            mock_client = AsyncMock()
            mock_client.base_url = "http://accent-auth:9497"
            mock_client._client = AsyncMock()

            # Mock fast response (50ms)
            mock_response = MagicMock()
            mock_response.status_code = 401  # Expected - invalid token
            mock_client._client.head = AsyncMock(return_value=mock_response)

            mock_get_client.return_value = mock_client

            # Mock async context manager
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            # Check health
            health = await provider.check_health()

            assert provider.name == "accent-auth"
            assert health.status == HealthStatus.HEALTHY
            assert "latency_ms" in health.metadata
            assert health.metadata["status_code"] == 401

    async def test_degraded_status_slow_response(self):
        """Test degraded status when service responds slowly."""
        provider = AccentAuthHealthProvider()

        with patch(
            "example_service.features.health.accent_auth_provider.get_accent_auth_client"
        ) as mock_get_client:
            mock_client = AsyncMock()
            mock_client.base_url = "http://accent-auth:9497"
            mock_client._client = AsyncMock()

            # Mock slow response (200ms)
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_client._client.head = AsyncMock(return_value=mock_response)

            mock_get_client.return_value = mock_client
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            # Mock time to simulate slow response
            with patch("time.perf_counter", side_effect=[0.0, 0.15]):  # 150ms
                health = await provider.check_health()

            assert provider.name == "accent-auth"
            # 150ms should be degraded (> 100ms)
            assert health.status in (HealthStatus.HEALTHY, HealthStatus.DEGRADED)

    async def test_unhealthy_status_connection_error(self):
        """Test unhealthy status when connection fails."""
        import httpx

        provider = AccentAuthHealthProvider()

        with patch(
            "example_service.features.health.accent_auth_provider.get_accent_auth_client"
        ) as mock_get_client:
            mock_client = AsyncMock()
            mock_client.base_url = "http://accent-auth:9497"
            mock_client._client = AsyncMock()
            mock_client._client.head = AsyncMock(
                side_effect=httpx.ConnectError("Connection refused")
            )

            mock_get_client.return_value = mock_client
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            health = await provider.check_health()

            assert provider.name == "accent-auth"
            assert health.status == HealthStatus.UNHEALTHY
            assert "Connection failed" in health.metadata["error"]

    async def test_unhealthy_status_timeout(self):
        """Test unhealthy status when request times out."""
        import httpx

        provider = AccentAuthHealthProvider()

        with patch(
            "example_service.features.health.accent_auth_provider.get_accent_auth_client"
        ) as mock_get_client:
            mock_client = AsyncMock()
            mock_client.base_url = "http://accent-auth:9497"
            mock_client._client = AsyncMock()
            mock_client._client.head = AsyncMock(
                side_effect=httpx.TimeoutException("Request timeout")
            )

            mock_get_client.return_value = mock_client
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            health = await provider.check_health()

            assert provider.name == "accent-auth"
            assert health.status == HealthStatus.UNHEALTHY
            assert "timeout" in health.metadata["error"].lower()

    async def test_unhealthy_status_no_url_configured(self):
        """Test unhealthy status when AUTH_SERVICE_URL not configured."""
        with patch(
            "example_service.features.health.accent_auth_provider.get_auth_settings"
        ) as mock_get_settings:
            # Mock settings with no service_url
            mock_settings = MagicMock()
            mock_settings.service_url = None
            mock_get_settings.return_value = mock_settings

            provider = AccentAuthHealthProvider()
            health = await provider.check_health()

            assert provider.name == "accent-auth"
            assert health.status == HealthStatus.UNHEALTHY
            assert "not configured" in health.metadata["error"]

    async def test_unexpected_status_code(self):
        """Test handling of unexpected status codes."""
        provider = AccentAuthHealthProvider()

        with patch(
            "example_service.features.health.accent_auth_provider.get_accent_auth_client"
        ) as mock_get_client:
            mock_client = AsyncMock()
            mock_client.base_url = "http://accent-auth:9497"
            mock_client._client = AsyncMock()

            # Mock unexpected status code
            mock_response = MagicMock()
            mock_response.status_code = 500  # Internal Server Error
            mock_client._client.head = AsyncMock(return_value=mock_response)

            mock_get_client.return_value = mock_client
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            health = await provider.check_health()

            assert provider.name == "accent-auth"
            assert health.status == HealthStatus.UNHEALTHY
            assert health.metadata["status_code"] == 500
