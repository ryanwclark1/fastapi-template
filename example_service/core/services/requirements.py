"""Feature-to-service requirements mapping.

This module defines which external services each feature requires.
The mapping is used by the availability dependency to determine which
services must be available before an endpoint can handle requests.

The mapping is declarative - features don't need to explicitly check
availability; they just add the appropriate RequireX dependency.

Example:
    from example_service.core.services.requirements import (
        get_feature_requirements,
        ServiceName,
    )

    # Get requirements for a feature
    requirements = get_feature_requirements("items")
    # Returns [ServiceName.DATABASE]

Customization:
    Modify FEATURE_SERVICE_REQUIREMENTS to match your application's
    feature modules and their service dependencies. The feature name
    should match the directory name under features/.
"""

from __future__ import annotations

from example_service.core.services.availability import ServiceName

# Mapping of feature names to their required external services.
# Feature name should match the directory name under features/.
#
# Services (customize based on your infrastructure):
#   DATABASE - PostgreSQL/MySQL (user data, items, etc.)
#   CACHE - Redis (sessions, rate limits, caching)
#   BROKER - RabbitMQ (async messaging, events)
#   STORAGE - S3/MinIO (file uploads, documents)
#   AUTH - External auth service (if separate from your app)
#   CONSUL - Service discovery (if used)

FEATURE_SERVICE_REQUIREMENTS: dict[str, list[ServiceName]] = {
    # === DATABASE-based features ===
    # Features that require database access
    "items": [ServiceName.DATABASE],
    "users": [ServiceName.DATABASE],
    # === CACHE-dependent features ===
    # Features that require Redis cache
    "sessions": [ServiceName.CACHE],
    # === Multi-service features ===
    # Features requiring multiple services
    "analytics": [ServiceName.DATABASE, ServiceName.CACHE],
    # === Features with no external service requirements ===
    # These features don't require external services or handle
    # service availability internally.
    "health": [],  # Health endpoints should always be available
    "status": [],  # Status endpoints should always be available
}


def get_feature_requirements(feature_name: str) -> list[ServiceName]:
    """Get the service requirements for a feature.

    Args:
        feature_name: The feature name (directory name under features/).

    Returns:
        List of required ServiceNames, or empty list if feature has no
        external requirements or is not found.
    """
    return FEATURE_SERVICE_REQUIREMENTS.get(feature_name, [])


def get_all_features_for_service(service: ServiceName) -> list[str]:
    """Get all features that require a specific service.

    Useful for understanding the impact of a service outage.

    Args:
        service: The service to look up.

    Returns:
        List of feature names that require this service.
    """
    return [
        feature
        for feature, requirements in FEATURE_SERVICE_REQUIREMENTS.items()
        if service in requirements
    ]


def get_service_impact_summary() -> dict[ServiceName, list[str]]:
    """Get a summary of which features are impacted by each service.

    Returns:
        Dictionary mapping service names to lists of dependent features.
    """
    impact: dict[ServiceName, list[str]] = {service: [] for service in ServiceName}
    for feature, requirements in FEATURE_SERVICE_REQUIREMENTS.items():
        for service in requirements:
            impact[service].append(feature)
    return impact


__all__ = [
    "FEATURE_SERVICE_REQUIREMENTS",
    "ServiceName",
    "get_all_features_for_service",
    "get_feature_requirements",
    "get_service_impact_summary",
]
