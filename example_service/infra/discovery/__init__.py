"""Consul service discovery infrastructure.

This package provides optional Consul service discovery integration with:
- Automatic service registration and deregistration
- TTL and HTTP health check modes
- OpenTelemetry tracing and Prometheus metrics
- Mock client for testing

Key characteristics:
- NEVER blocks application startup
- Graceful degradation when Consul is unavailable
- Full observability for production monitoring

Usage:
    # In lifespan.py - startup
    from example_service.infra.discovery import start_discovery, stop_discovery

    success = await start_discovery()
    if success:
        logger.info("Service discovery started")

    # In lifespan.py - shutdown
    await stop_discovery()

Configuration:
    # Environment variables
    CONSUL_ENABLED=true
    CONSUL_HOST=consul.service.consul
    CONSUL_PORT=8500
    CONSUL_HEALTH_CHECK_MODE=ttl  # or "http"

Testing:
    from example_service.infra.discovery import ConsulService, MockConsulClient

    mock_client = MockConsulClient()
    service = ConsulService(client=mock_client)
    await service.start()

    # Verify behavior
    assert mock_client.services
"""

from example_service.infra.discovery.client import ConsulClient
from example_service.infra.discovery.mock_client import MockConsulClient
from example_service.infra.discovery.protocols import ConsulClientProtocol
from example_service.infra.discovery.service import (
    ConsulService,
    get_discovery_service,
    start_discovery,
    stop_discovery,
)

__all__ = [
    # Protocol
    "ConsulClientProtocol",
    # Clients
    "ConsulClient",
    "MockConsulClient",
    # Service
    "ConsulService",
    # Lifecycle functions
    "start_discovery",
    "stop_discovery",
    "get_discovery_service",
]
