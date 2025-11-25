"""Service dependencies for FastAPI.

Re-exports service factory functions from feature modules for
backwards compatibility and convenience.
"""

from __future__ import annotations

# Re-export from health feature for backwards compatibility
from example_service.features.health.service import (
    HealthService,
    HealthServiceDep,
    get_health_service,
)

__all__ = [
    "HealthService",
    "HealthServiceDep",
    "get_health_service",
]
