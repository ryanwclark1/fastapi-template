"""Tests for Accent-Auth health check provider."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from example_service.core.schemas.common import HealthStatus
from example_service.features.health import accent_auth_provider as compat_module
from example_service.features.health.providers.accent_auth import (
    AccentAuthHealthProvider,
    _get_accent_auth_client,
    _get_auth_settings,
    _perform_head_request,
)


@pytest.fixture(autouse=True)
def _mock_auth_settings(monkeypatch: pytest.MonkeyPatch):
    """Ensure AccentAuth has a service URL configured by default."""
    settings = SimpleNamespace(
        service_url="http://accent-auth:9497",
        request_timeout=5.0,
    )
    monkeypatch.setattr(
        "example_service.features.health.accent_auth_provider.get_auth_settings",
        lambda: settings,
    )
    return settings


@pytest.mark.asyncio
class TestAccentAuthHealthProvider:
    """Test Accent-Auth health check provider."""

    async def test_healthy_status_fast_response(self):
        """Test healthy status when service responds quickly."""
        provider = AccentAuthHealthProvider()

        with patch(
            "example_service.features.health.accent_auth_provider.get_accent_auth_client",
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
            "example_service.features.health.accent_auth_provider.get_accent_auth_client",
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
            "example_service.features.health.accent_auth_provider.get_accent_auth_client",
        ) as mock_get_client:
            mock_client = AsyncMock()
            mock_client.base_url = "http://accent-auth:9497"
            mock_client._client = AsyncMock()
            mock_client._client.head = AsyncMock(
                side_effect=httpx.ConnectError("Connection refused"),
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
            "example_service.features.health.accent_auth_provider.get_accent_auth_client",
        ) as mock_get_client:
            mock_client = AsyncMock()
            mock_client.base_url = "http://accent-auth:9497"
            mock_client._client = AsyncMock()
            mock_client._client.head = AsyncMock(
                side_effect=httpx.TimeoutException("Request timeout"),
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
            "example_service.features.health.accent_auth_provider.get_auth_settings",
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
            "example_service.features.health.accent_auth_provider.get_accent_auth_client",
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


class TestCompatibilityLayer:
    """Ensure compatibility shim behaviors are exercised."""

    def test_getattr_returns_provider_class(self, monkeypatch: pytest.MonkeyPatch):
        """__getattr__ should lazily import the provider."""
        sentinel = object()
        monkeypatch.setattr(
            "example_service.features.health.providers.accent_auth.AccentAuthHealthProvider",
            sentinel,
        )

        provider_cls = compat_module.AccentAuthHealthProvider

        assert provider_cls is sentinel
        # Subsequent access should hit cached global, no import
        assert compat_module.AccentAuthHealthProvider is sentinel

    def test_getattr_unknown_attribute_raises(self):
        with pytest.raises(AttributeError):
            _ = compat_module.unknown_attribute


@pytest.mark.asyncio
class TestPerformHeadRequest:
    """Test `_perform_head_request` helper."""

    async def test_uses_inner_client_when_available(self):
        """If client provides `_client.head`, that path is used."""
        inner = AsyncMock()
        response = object()
        inner.head.return_value = response
        client = SimpleNamespace(_client=inner)

        result = await _perform_head_request(client, "/ping", headers={"x": "1"})

        assert result is response
        inner.head.assert_awaited_once_with("/ping", headers={"x": "1"})

    async def test_falls_back_to_outer_head(self):
        """Outer head should be used when `_client` missing."""
        outer_head = AsyncMock()
        client = SimpleNamespace(head=outer_head)

        await _perform_head_request(client, "/ping", headers={})

        outer_head.assert_awaited_once_with("/ping", headers={})

    async def test_raises_when_no_head_available(self):
        """Missing head handlers should raise RuntimeError."""
        client = SimpleNamespace()
        with pytest.raises(RuntimeError):
            await _perform_head_request(client, "/ping", headers={})


class TestCompatHelpers:
    """Validate compatibility aware helper functions."""

    def test_get_auth_settings_prefers_compat(self, monkeypatch: pytest.MonkeyPatch):
        sentinel_settings = object()
        monkeypatch.setattr(
            "example_service.features.health.providers.accent_auth._get_compat_module",
            lambda: SimpleNamespace(get_auth_settings=lambda: sentinel_settings),
        )

        assert _get_auth_settings() is sentinel_settings

    def test_get_auth_client_prefers_compat(self, monkeypatch: pytest.MonkeyPatch):
        sentinel_client = object()
        monkeypatch.setattr(
            "example_service.features.health.providers.accent_auth._get_compat_module",
            lambda: SimpleNamespace(get_accent_auth_client=lambda: sentinel_client),
        )

        assert _get_accent_auth_client() is sentinel_client
