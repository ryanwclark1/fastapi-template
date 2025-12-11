"""Service discovery dependencies for FastAPI route handlers.

This module provides FastAPI-compatible dependencies for accessing
Consul service discovery functionality.

Usage:
    from example_service.core.dependencies.discovery import (
        DiscoveryServiceDep,
        OptionalDiscoveryService,
    )

    @router.get("/services")
    async def list_services(
        discovery: DiscoveryServiceDep,
    ):
        services = await discovery.get_services()
        return {"services": services}

    @router.get("/service/{name}")
    async def get_service(
        name: str,
        discovery: OptionalDiscoveryService,
    ):
        if discovery is None:
            return {"error": "Service discovery is disabled"}
        instances = await discovery.get_service_instances(name)
        return {"instances": instances}
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status

from example_service.infra.discovery import ConsulService


def get_discovery_service_dep() -> ConsulService | None:
    """Get the Consul service discovery instance.

    This is a thin wrapper that retrieves the discovery service singleton.
    The import is deferred to runtime to avoid circular dependencies.

    Returns:
        ConsulService | None: The service instance, or None if not initialized.
    """
    from example_service.infra.discovery import get_discovery_service

    return get_discovery_service()


async def require_discovery_service(
    service: Annotated[ConsulService | None, Depends(get_discovery_service_dep)],
) -> ConsulService:
    """Dependency that requires discovery service to be available.

    Use this when service discovery is required for the endpoint.
    Raises HTTP 503 if Consul is not available.

    Args:
        service: Injected service from get_discovery_service_dep

    Returns:
        ConsulService: The Consul service instance

    Raises:
        HTTPException: 503 Service Unavailable if Consul is not available
    """
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "discovery_unavailable",
                "message": "Service discovery (Consul) is not available",
            },
        )
    return service


async def optional_discovery_service(
    service: Annotated[ConsulService | None, Depends(get_discovery_service_dep)],
) -> ConsulService | None:
    """Dependency that optionally provides discovery service.

    Use this when service discovery is optional. Allows graceful
    degradation when Consul is unavailable.

    Args:
        service: Injected service from get_discovery_service_dep

    Returns:
        ConsulService | None: The service if available, None otherwise
    """
    return service


DiscoveryServiceDep = Annotated[ConsulService, Depends(require_discovery_service)]
"""Discovery service dependency that requires Consul to be available.

Example:
    @router.get("/services")
    async def list_services(discovery: DiscoveryServiceDep):
        return await discovery.get_services()
"""

OptionalDiscoveryService = Annotated[
    ConsulService | None, Depends(optional_discovery_service),
]
"""Discovery service dependency that is optional.

Example:
    @router.get("/services")
    async def list_services(discovery: OptionalDiscoveryService):
        if discovery is None:
            return {"message": "Service discovery disabled"}
        return await discovery.get_services()
"""


__all__ = [
    "DiscoveryServiceDep",
    "OptionalDiscoveryService",
    "get_discovery_service_dep",
    "optional_discovery_service",
    "require_discovery_service",
]
