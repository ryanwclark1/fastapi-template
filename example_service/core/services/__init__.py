"""Core services module.

This module provides service availability tracking and health monitoring
for external dependencies.

Service Availability:
    from example_service.core.services.availability import (
        ServiceName,
        get_service_registry,
    )

    registry = get_service_registry()
    if registry.is_available(ServiceName.DATABASE):
        ...

Health Monitoring:
    from example_service.core.services.health_monitor import (
        start_health_monitor,
        stop_health_monitor,
    )

    await start_health_monitor()
"""

from example_service.core.services.availability import (
    OverrideMode,
    ServiceAvailabilityRegistry,
    ServiceName,
    ServiceStatus,
    get_service_registry,
)
from example_service.core.services.health_monitor import (
    HealthMonitor,
    get_health_monitor,
    start_health_monitor,
    stop_health_monitor,
    trigger_health_check,
)
from example_service.core.services.requirements import (
    FEATURE_SERVICE_REQUIREMENTS,
    get_all_features_for_service,
    get_feature_requirements,
    get_service_impact_summary,
)

__all__ = [
    # Availability
    "OverrideMode",
    "ServiceAvailabilityRegistry",
    "ServiceName",
    "ServiceStatus",
    "get_service_registry",
    # Health Monitor
    "HealthMonitor",
    "get_health_monitor",
    "start_health_monitor",
    "stop_health_monitor",
    "trigger_health_check",
    # Requirements
    "FEATURE_SERVICE_REQUIREMENTS",
    "get_all_features_for_service",
    "get_feature_requirements",
    "get_service_impact_summary",
]
