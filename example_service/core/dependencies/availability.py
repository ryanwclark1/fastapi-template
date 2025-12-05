"""Service availability dependencies for FastAPI routes.

This module provides FastAPI dependencies that check service availability
before allowing request processing. When required services are unavailable,
endpoints return 503 Service Unavailable responses.

The pattern allows declarative service requirements:
- Add RequireX type alias as first endpoint parameter
- FastAPI's DI automatically validates availability
- No explicit availability checks needed in endpoint code

Example:
    from example_service.core.dependencies.availability import (
        RequireDatabase,
        RequireCache,
    )

    @router.get("/items")
    async def list_items(
        _: RequireDatabase,  # Validates database is available
        service: ItemService = Depends(get_item_service),
    ) -> list[Item]:
        return await service.list_items()

    @router.get("/analytics")
    async def get_analytics(
        _: Annotated[dict, require_services(ServiceName.DATABASE, ServiceName.CACHE)],
        service: AnalyticsService = Depends(get_analytics_service),
    ) -> Analytics:
        return await service.get_analytics()
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from example_service.core.exceptions import ServiceUnavailableException
from example_service.core.services.availability import ServiceName, get_service_registry


def require_services(*services: ServiceName):
    """Create a dependency that validates service availability.

    This factory function creates a FastAPI dependency that checks if
    all specified services are available. If any service is unavailable,
    it raises ServiceUnavailableException (503 response).

    The dependency can be used directly or wrapped in Annotated type alias:

        # Direct usage
        @router.get("/items")
        async def list_items(
            _: Annotated[dict, require_services(ServiceName.DATABASE)],
        ):
            ...

        # Or use pre-built type aliases
        @router.get("/items")
        async def list_items(_: RequireDatabase):
            ...

    Args:
        *services: Variable number of ServiceName values to require.

    Returns:
        FastAPI dependency function.
    """

    async def dependency() -> dict[str, bool]:
        """Check availability of required services.

        Returns:
            Dictionary mapping service names to True (all available).

        Raises:
            ServiceUnavailableException: If any required service is unavailable.
        """
        registry = get_service_registry()
        unavailable = [s for s in services if not registry.is_available(s)]

        if unavailable:
            # Track unavailability in metrics
            from example_service.infra.metrics.availability import (
                service_unavailable_responses_total,
            )

            for service in unavailable:
                service_unavailable_responses_total.labels(
                    service_name=service.value,
                    endpoint="unknown",  # Would need request context for actual endpoint
                ).inc()

            raise ServiceUnavailableException(
                detail=f"Required service(s) unavailable: {', '.join(s.value for s in unavailable)}",
                type="service-dependency-unavailable",
                extra={
                    "unavailable_services": [s.value for s in unavailable],
                    "retry_after": 30,
                },
            )

        return {s.value: True for s in services}

    return Depends(dependency)


# ══════════════════════════════════════════════════════════════════════════════
# Pre-built type aliases for common service requirements
# ══════════════════════════════════════════════════════════════════════════════
# Use these as the first parameter in your endpoint functions.
# The underscore convention indicates the value isn't used directly.
#
# Example:
#     @router.get("/items")
#     async def list_items(
#         _: RequireDatabase,
#         service: ItemService = Depends(get_item_service),
#     ) -> list[Item]:
#         ...

RequireDatabase = Annotated[dict, require_services(ServiceName.DATABASE)]
"""Dependency that requires database to be available."""

RequireCache = Annotated[dict, require_services(ServiceName.CACHE)]
"""Dependency that requires cache (Redis) to be available."""

RequireBroker = Annotated[dict, require_services(ServiceName.BROKER)]
"""Dependency that requires message broker (RabbitMQ) to be available."""

RequireStorage = Annotated[dict, require_services(ServiceName.STORAGE)]
"""Dependency that requires object storage to be available."""

RequireAuth = Annotated[dict, require_services(ServiceName.AUTH)]
"""Dependency that requires auth service to be available."""

RequireConsul = Annotated[dict, require_services(ServiceName.CONSUL)]
"""Dependency that requires Consul to be available."""

# Combined requirements for features needing multiple services
RequireDatabaseAndCache = Annotated[
    dict, require_services(ServiceName.DATABASE, ServiceName.CACHE)
]
"""Dependency that requires both database and cache to be available."""

RequireDatabaseAndBroker = Annotated[
    dict, require_services(ServiceName.DATABASE, ServiceName.BROKER)
]
"""Dependency that requires both database and message broker to be available."""


__all__ = [
    "RequireAuth",
    "RequireBroker",
    "RequireCache",
    "RequireConsul",
    "RequireDatabase",
    "RequireDatabaseAndBroker",
    "RequireDatabaseAndCache",
    "RequireStorage",
    "require_services",
]
