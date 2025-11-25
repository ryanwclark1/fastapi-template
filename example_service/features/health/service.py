"""Health check service and dependency injection helpers.

This module provides the feature-level health service that wraps the core
health service implementation, along with type aliases for cleaner
dependency injection in route handlers.

Example:
    >>> from example_service.features.health.service import HealthServiceDep
    >>>
    >>> @router.get("/health")
    >>> async def health(service: HealthServiceDep):
    ...     return await service.check_health()
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from example_service.core.services.health import HealthService
from example_service.features.health.aggregator import (
    HealthAggregator,
    get_global_aggregator,
)

__all__ = [
    "HealthAggregator",
    "HealthAggregatorDep",
    "HealthService",
    "HealthServiceDep",
    "get_health_aggregator",
    "get_health_service",
]


# =============================================================================
# Dependency Factories
# =============================================================================


def get_health_service() -> HealthService:
    """Factory function to create a HealthService instance.

    This factory is used as a FastAPI dependency to inject the health
    service into route handlers. It auto-configures providers based on
    application settings.

    Returns:
        HealthService instance for performing health checks.

    Example:
        >>> @router.get("/health")
        >>> async def health(
        ...     service: HealthService = Depends(get_health_service)
        ... ):
        ...     return await service.check_health()
    """
    return HealthService()


def get_health_aggregator() -> HealthAggregator:
    """Factory function to get the health aggregator.

    Returns the global health aggregator instance, which can be
    pre-configured at application startup with custom providers.

    Returns:
        HealthAggregator instance for managing health providers.

    Example:
        >>> @router.get("/health/providers")
        >>> async def list_providers(
        ...     aggregator: HealthAggregator = Depends(get_health_aggregator)
        ... ):
        ...     return {"providers": aggregator.list_providers()}
    """
    return get_global_aggregator()


# =============================================================================
# Type Aliases for Dependency Injection
# =============================================================================

# Use these type aliases for cleaner route handler signatures

HealthServiceDep = Annotated[HealthService, Depends(get_health_service)]
"""Type alias for HealthService dependency injection.

Example:
    >>> @router.get("/health")
    >>> async def health(service: HealthServiceDep):
    ...     return await service.check_health()
"""

HealthAggregatorDep = Annotated[HealthAggregator, Depends(get_health_aggregator)]
"""Type alias for HealthAggregator dependency injection.

Example:
    >>> @router.get("/health/providers")
    >>> async def providers(aggregator: HealthAggregatorDep):
    ...     return {"providers": aggregator.list_providers()}
"""
