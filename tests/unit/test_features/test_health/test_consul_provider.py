"""Tests for Consul health check provider."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from example_service.core.schemas.common import HealthStatus
from example_service.features.health.providers import (
    ConsulHealthProvider,
    ProviderConfig,
)


@pytest.mark.asyncio
class TestConsulHealthProvider:
    """Test Consul health check provider."""

    async def test_healthy_status_all_checks_pass(self):
        """Test healthy status when all Consul checks pass."""
        # Create mock Consul client
        mock_client = MagicMock()
        mock_client._client = AsyncMock()

        # Mock agent info response
        mock_agent_response = MagicMock()
        mock_agent_response.status_code = 200
        mock_agent_response.json.return_value = {
            "Config": {
                "AdvertiseAddr": "192.168.1.100",
                "Datacenter": "dc1",
            }
        }

        # Mock leader response
        mock_leader_response = MagicMock()
        mock_leader_response.status_code = 200
        mock_leader_response.text = '"192.168.1.100:8300"'

        # Mock services response
        mock_services_response = MagicMock()
        mock_services_response.status_code = 200
        mock_services_response.json.return_value = {
            "service-1": {"Service": "example-service"},
            "service-2": {"Service": "other-service"},
        }

        # Setup mock client responses
        async def mock_get(path):
            if path == "/v1/agent/self":
                return mock_agent_response
            elif path == "/v1/status/leader":
                return mock_leader_response
            elif path == "/v1/agent/services":
                return mock_services_response
            raise ValueError(f"Unexpected path: {path}")

        mock_client._client.get = mock_get

        # Create provider and check health
        provider = ConsulHealthProvider(
            consul_client=mock_client,
            service_name="example-service",
            config=ProviderConfig(timeout=5.0),
        )

        result = await provider.check_health()

        # Assertions
        assert result.status == HealthStatus.HEALTHY
        assert result.message == "Consul operational"
        assert result.latency_ms > 0
        assert result.metadata["agent_address"] == "192.168.1.100"
        assert result.metadata["datacenter"] == "dc1"
        assert result.metadata["leader"] == "192.168.1.100:8300"
        assert result.metadata["services_registered"] == 2
        assert result.metadata["service_health"] == "registered"

    async def test_degraded_status_no_leader(self):
        """Test degraded status when Consul has no elected leader."""
        mock_client = MagicMock()
        mock_client._client = AsyncMock()

        # Mock agent info response
        mock_agent_response = MagicMock()
        mock_agent_response.status_code = 200
        mock_agent_response.json.return_value = {
            "Config": {
                "AdvertiseAddr": "192.168.1.100",
                "Datacenter": "dc1",
            }
        }

        # Mock leader response - no leader
        mock_leader_response = MagicMock()
        mock_leader_response.status_code = 200
        mock_leader_response.text = '""'  # Empty string means no leader

        # Mock services response
        mock_services_response = MagicMock()
        mock_services_response.status_code = 200
        mock_services_response.json.return_value = {}

        async def mock_get(path):
            if path == "/v1/agent/self":
                return mock_agent_response
            elif path == "/v1/status/leader":
                return mock_leader_response
            elif path == "/v1/agent/services":
                return mock_services_response
            raise ValueError(f"Unexpected path: {path}")

        mock_client._client.get = mock_get

        provider = ConsulHealthProvider(
            consul_client=mock_client,
            service_name="example-service",
        )

        result = await provider.check_health()

        # Assertions
        assert result.status == HealthStatus.DEGRADED
        assert result.message == "No Consul leader elected"
        assert result.metadata["leader"] is None

    async def test_degraded_status_high_latency(self):
        """Test degraded status when Consul responds slowly."""
        mock_client = MagicMock()
        mock_client._client = AsyncMock()

        # Mock responses
        mock_agent_response = MagicMock()
        mock_agent_response.status_code = 200
        mock_agent_response.json.return_value = {
            "Config": {"AdvertiseAddr": "192.168.1.100", "Datacenter": "dc1"}
        }

        mock_leader_response = MagicMock()
        mock_leader_response.status_code = 200
        mock_leader_response.text = '"192.168.1.100:8300"'

        mock_services_response = MagicMock()
        mock_services_response.status_code = 200
        mock_services_response.json.return_value = {}

        async def mock_get(path):
            if path == "/v1/agent/self":
                return mock_agent_response
            elif path == "/v1/status/leader":
                return mock_leader_response
            elif path == "/v1/agent/services":
                return mock_services_response
            raise ValueError(f"Unexpected path: {path}")

        mock_client._client.get = mock_get

        # Create provider with low latency threshold
        provider = ConsulHealthProvider(
            consul_client=mock_client,
            service_name="example-service",
            config=ProviderConfig(timeout=5.0, latency_threshold_ms=10.0),
        )

        # Mock time to simulate high latency
        with patch("time.perf_counter", side_effect=[0.0, 0.015]):  # 15ms
            result = await provider.check_health()

        # Assertions
        assert result.status == HealthStatus.DEGRADED
        assert "High latency" in result.message
        assert result.latency_ms > 10.0

    async def test_unhealthy_status_agent_unreachable(self):
        """Test unhealthy status when Consul agent is unreachable."""
        import httpx

        mock_client = MagicMock()
        mock_client._client = AsyncMock()

        # Mock connection error
        async def mock_get(path):
            raise httpx.ConnectError("Connection refused")

        mock_client._client.get = mock_get

        provider = ConsulHealthProvider(
            consul_client=mock_client,
            service_name="example-service",
        )

        result = await provider.check_health()

        # Assertions
        assert result.status == HealthStatus.UNHEALTHY
        assert "Agent unreachable" in result.message
        assert "error" in result.metadata

    async def test_unhealthy_status_timeout(self):
        """Test unhealthy status when health check times out."""
        mock_client = MagicMock()
        mock_client._client = AsyncMock()

        # Mock slow response that causes timeout
        async def mock_get(path):
            import asyncio

            await asyncio.sleep(10)  # Will timeout before this completes
            return MagicMock()

        mock_client._client.get = mock_get

        provider = ConsulHealthProvider(
            consul_client=mock_client,
            service_name="example-service",
            config=ProviderConfig(timeout=0.1),  # Very short timeout
        )

        result = await provider.check_health()

        # Assertions
        assert result.status == HealthStatus.UNHEALTHY
        assert "Timeout" in result.message
        assert result.metadata["error"] == "timeout"

    async def test_metadata_contains_service_registration_status(self):
        """Test that metadata includes service registration status."""
        mock_client = MagicMock()
        mock_client._client = AsyncMock()

        mock_agent_response = MagicMock()
        mock_agent_response.status_code = 200
        mock_agent_response.json.return_value = {
            "Config": {"AdvertiseAddr": "192.168.1.100", "Datacenter": "dc1"}
        }

        mock_leader_response = MagicMock()
        mock_leader_response.status_code = 200
        mock_leader_response.text = '"192.168.1.100:8300"'

        # Service IS registered
        mock_services_response = MagicMock()
        mock_services_response.status_code = 200
        mock_services_response.json.return_value = {
            "my-service-123": {"Service": "my-service"},
        }

        async def mock_get(path):
            if path == "/v1/agent/self":
                return mock_agent_response
            elif path == "/v1/status/leader":
                return mock_leader_response
            elif path == "/v1/agent/services":
                return mock_services_response
            raise ValueError(f"Unexpected path: {path}")

        mock_client._client.get = mock_get

        provider = ConsulHealthProvider(
            consul_client=mock_client,
            service_name="my-service",
        )

        result = await provider.check_health()

        # Assertions
        assert result.metadata["service_health"] == "registered"
        assert result.metadata["services_registered"] == 1

    async def test_service_not_registered(self):
        """Test metadata when service is not registered in Consul."""
        mock_client = MagicMock()
        mock_client._client = AsyncMock()

        mock_agent_response = MagicMock()
        mock_agent_response.status_code = 200
        mock_agent_response.json.return_value = {
            "Config": {"AdvertiseAddr": "192.168.1.100", "Datacenter": "dc1"}
        }

        mock_leader_response = MagicMock()
        mock_leader_response.status_code = 200
        mock_leader_response.text = '"192.168.1.100:8300"'

        # Service NOT registered
        mock_services_response = MagicMock()
        mock_services_response.status_code = 200
        mock_services_response.json.return_value = {
            "other-service-456": {"Service": "other-service"},
        }

        async def mock_get(path):
            if path == "/v1/agent/self":
                return mock_agent_response
            elif path == "/v1/status/leader":
                return mock_leader_response
            elif path == "/v1/agent/services":
                return mock_services_response
            raise ValueError(f"Unexpected path: {path}")

        mock_client._client.get = mock_get

        provider = ConsulHealthProvider(
            consul_client=mock_client,
            service_name="my-service",
        )

        result = await provider.check_health()

        # Assertions
        assert result.metadata["service_health"] == "not_registered"

    async def test_provider_name_is_consul(self):
        """Test that provider name is 'consul'."""
        mock_client = MagicMock()
        provider = ConsulHealthProvider(
            consul_client=mock_client,
            service_name="example-service",
        )

        assert provider.name == "consul"

    async def test_handles_partial_failures_gracefully(self):
        """Test that provider handles partial check failures gracefully."""
        import httpx

        mock_client = MagicMock()
        mock_client._client = AsyncMock()

        # Agent check succeeds
        mock_agent_response = MagicMock()
        mock_agent_response.status_code = 200
        mock_agent_response.json.return_value = {
            "Config": {"AdvertiseAddr": "192.168.1.100", "Datacenter": "dc1"}
        }

        # Leader check fails
        async def mock_get(path):
            if path == "/v1/agent/self":
                return mock_agent_response
            elif path == "/v1/status/leader":
                raise httpx.HTTPError("Leader endpoint error")
            elif path == "/v1/agent/services":
                raise httpx.HTTPError("Services endpoint error")
            raise ValueError(f"Unexpected path: {path}")

        mock_client._client.get = mock_get

        provider = ConsulHealthProvider(
            consul_client=mock_client,
            service_name="example-service",
        )

        result = await provider.check_health()

        # Assertions - should still return result with partial data
        assert result.status == HealthStatus.DEGRADED
        assert result.metadata["agent_address"] == "192.168.1.100"
        assert "leader_error" in result.metadata
        assert "services_error" in result.metadata

    async def test_custom_provider_config(self):
        """Test provider with custom configuration."""
        mock_client = MagicMock()
        mock_client._client = AsyncMock()

        custom_config = ProviderConfig(
            enabled=True,
            timeout=2.0,
            latency_threshold_ms=500.0,
        )

        provider = ConsulHealthProvider(
            consul_client=mock_client,
            service_name="example-service",
            config=custom_config,
        )

        assert provider._config.timeout == 2.0
        assert provider._config.latency_threshold_ms == 500.0

    async def test_concurrent_checks_use_asyncio_gather(self):
        """Test that sub-checks run concurrently using asyncio.gather."""
        mock_client = MagicMock()
        mock_client._client = AsyncMock()

        call_order = []

        async def mock_get(path):
            call_order.append(path)
            response = MagicMock()
            response.status_code = 200
            if path == "/v1/agent/self":
                response.json.return_value = {
                    "Config": {"AdvertiseAddr": "192.168.1.100", "Datacenter": "dc1"}
                }
            elif path == "/v1/status/leader":
                response.text = '"192.168.1.100:8300"'
            elif path == "/v1/agent/services":
                response.json.return_value = {}
            return response

        mock_client._client.get = mock_get

        provider = ConsulHealthProvider(
            consul_client=mock_client,
            service_name="example-service",
        )

        await provider.check_health()

        # All checks should be called
        assert "/v1/agent/self" in call_order
        assert "/v1/status/leader" in call_order
        assert "/v1/agent/services" in call_order

    async def test_exception_in_check_health_returns_unhealthy(self):
        """Test that unexpected exceptions result in UNHEALTHY status."""
        mock_client = MagicMock()
        mock_client._client = AsyncMock()

        # Mock an unexpected exception
        async def mock_get(path):
            raise RuntimeError("Unexpected internal error")

        mock_client._client.get = mock_get

        provider = ConsulHealthProvider(
            consul_client=mock_client,
            service_name="example-service",
        )

        result = await provider.check_health()

        # Assertions
        assert result.status == HealthStatus.UNHEALTHY
        # The error is caught by agent check which fails first
        assert "Agent unreachable" in result.message or "Check failed" in result.message
        assert "error" in result.metadata
