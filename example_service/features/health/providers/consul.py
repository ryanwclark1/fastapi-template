"""Consul service discovery health check provider.

Monitors Consul connectivity, leader health, and service registration status.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from example_service.core.schemas.common import HealthStatus
from example_service.core.settings.health import ProviderConfig

from .protocol import HealthCheckResult

if TYPE_CHECKING:
    from example_service.infra.discovery.client import ConsulClient

logger = logging.getLogger(__name__)


class ConsulHealthProvider:
    """Health provider for Consul service discovery.

    Monitors Consul connectivity, leader health, and service registration
    status. Essential for microservices architectures using Consul for
    service discovery.

    Checks performed:
    - **Consul agent connectivity**: Verifies local agent is reachable
    - **Leader election status**: Ensures cluster has an elected leader
    - **Service registration count**: Reports number of registered services
    - **Health check status**: Monitors this service's health in Consul

    Status determination:
    - HEALTHY: All checks pass, latency acceptable
    - DEGRADED: Connected but no leader or high latency
    - UNHEALTHY: Cannot connect to agent or API errors

    Example:
        >>> from example_service.infra.discovery import ConsulClient
        >>> from example_service.core.settings import get_consul_settings
        >>>
        >>> settings = get_consul_settings()
        >>> client = ConsulClient(settings)
        >>> provider = ConsulHealthProvider(
        ...     consul_client=client,
        ...     service_name="example-service",
        ... )
        >>> result = await provider.check_health()
        >>> print(result.status)  # HealthStatus.HEALTHY
    """

    def __init__(
        self,
        consul_client: ConsulClient,
        service_name: str,
        config: ProviderConfig | None = None,
    ) -> None:
        """Initialize Consul health provider.

        Args:
            consul_client: ConsulClient instance for API communication
            service_name: Name of this service in Consul
            config: Optional configuration (timeout, thresholds)
        """
        self._client = consul_client
        self._service_name = service_name
        self._config = config or ProviderConfig()

    @property
    def name(self) -> str:
        """Return provider name."""
        return "consul"

    async def check_health(self) -> HealthCheckResult:
        """Check Consul health.

        Performs multiple checks in parallel:
        1. Agent self info (connectivity)
        2. Leader status (cluster health)
        3. Registered services (registration status)

        Returns:
            HealthCheckResult with Consul status and metadata
        """
        start_time = time.perf_counter()

        try:
            async with asyncio.timeout(self._config.timeout):
                # Run checks in parallel for speed
                results = await asyncio.gather(
                    self._check_agent(),
                    self._check_leader(),
                    self._check_services(),
                    return_exceptions=True,
                )

            agent_info: dict[str, Any] | BaseException = results[0]
            leader_info: dict[str, Any] | BaseException = results[1]
            services_info: dict[str, Any] | BaseException = results[2]

            latency_ms = (time.perf_counter() - start_time) * 1000

            # Determine overall status from sub-checks
            if isinstance(agent_info, BaseException):
                return HealthCheckResult(
                    status=HealthStatus.UNHEALTHY,
                    message=f"Agent unreachable: {agent_info}",
                    latency_ms=latency_ms,
                    metadata={"error": str(agent_info)},
                )

            # Build metadata from successful checks
            metadata: dict[str, Any] = {}

            if not isinstance(agent_info, BaseException):
                metadata["agent_address"] = agent_info.get("agent_address", "unknown")
                metadata["datacenter"] = agent_info.get("datacenter", "unknown")

            if not isinstance(leader_info, BaseException):
                metadata["leader"] = leader_info.get("leader", "unknown")
                has_leader = bool(leader_info.get("leader"))
            else:
                has_leader = False
                metadata["leader_error"] = str(leader_info)

            if not isinstance(services_info, BaseException):
                metadata["services_registered"] = services_info.get("count", 0)
                metadata["service_health"] = services_info.get("service_health", "unknown")
            else:
                metadata["services_error"] = str(services_info)

            # Determine status
            if not has_leader:
                return HealthCheckResult(
                    status=HealthStatus.DEGRADED,
                    message="No Consul leader elected",
                    latency_ms=latency_ms,
                    metadata=metadata,
                )

            if latency_ms > self._config.degraded_threshold_ms:
                return HealthCheckResult(
                    status=HealthStatus.DEGRADED,
                    message=f"High latency: {latency_ms:.2f}ms",
                    latency_ms=latency_ms,
                    metadata=metadata,
                )

            return HealthCheckResult(
                status=HealthStatus.HEALTHY,
                message="Consul operational",
                latency_ms=latency_ms,
                metadata=metadata,
            )

        except TimeoutError:
            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(
                "Consul health check timed out",
                extra={"timeout": self._config.timeout, "latency_ms": latency_ms},
            )
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Timeout after {self._config.timeout}s",
                latency_ms=latency_ms,
                metadata={"error": "timeout"},
            )

        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.warning("Consul health check failed", extra={"error": str(e)})
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Check failed: {e}",
                latency_ms=latency_ms,
                metadata={"error": str(e), "error_type": type(e).__name__},
            )

    async def _check_agent(self) -> dict[str, Any]:
        """Check Consul agent connectivity and info.

        Returns:
            Dict with agent address and datacenter
        """
        import httpx

        try:
            response = await self._client._client.get("/v1/agent/self")
            response.raise_for_status()
            data = response.json()

            # Extract key info
            config = data.get("Config", {})
            return {
                "agent_address": config.get("AdvertiseAddr", "unknown"),
                "datacenter": config.get("Datacenter", "unknown"),
            }

        except httpx.HTTPError as e:
            logger.debug("Agent check failed", extra={"error": str(e)})
            raise

    async def _check_leader(self) -> dict[str, Any]:
        """Check Consul leader election status.

        Returns:
            Dict with leader address
        """
        import httpx

        try:
            response = await self._client._client.get("/v1/status/leader")
            response.raise_for_status()

            # Leader is returned as quoted string, e.g., "192.168.1.100:8300"
            leader = response.text.strip('"')
            return {
                "leader": leader if leader else None,
            }

        except httpx.HTTPError as e:
            logger.debug("Leader check failed", extra={"error": str(e)})
            raise

    async def _check_services(self) -> dict[str, Any]:
        """Check registered services and this service's health.

        Returns:
            Dict with service count and health status
        """
        import httpx

        try:
            # Get all registered services
            response = await self._client._client.get("/v1/agent/services")
            response.raise_for_status()
            services = response.json()

            # Check if our service is registered
            service_health = "not_registered"
            for _service_id, service_data in services.items():
                if service_data.get("Service") == self._service_name:
                    service_health = "registered"
                    break

            return {
                "count": len(services),
                "service_health": service_health,
            }

        except httpx.HTTPError as e:
            logger.debug("Services check failed", extra={"error": str(e)})
            raise
