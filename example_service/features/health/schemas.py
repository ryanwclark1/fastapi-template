"""Health check response schemas.

Pydantic models for health check API responses, providing structured
and validated response data for Kubernetes probes and monitoring systems.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from example_service.core.schemas.common import HealthStatus


class HealthResponse(BaseModel):
    """Comprehensive health check response.

    Returns the overall health status of the service including
    individual dependency checks for database, cache, messaging, etc.

    Example:
        ```json
        {
            "status": "healthy",
            "timestamp": "2025-01-01T00:00:00Z",
            "service": "example-service",
            "version": "0.1.0",
            "checks": {
                "database": true,
                "cache": true,
                "messaging": true
            }
        }
        ```
    """

    status: HealthStatus = Field(description="Health status (healthy, degraded, unhealthy)")
    timestamp: datetime = Field(description="Check timestamp")
    service: str = Field(min_length=1, max_length=100, description="Service name")
    version: str = Field(min_length=1, max_length=50, description="Service version")
    checks: dict[str, bool] = Field(
        default_factory=dict, description="Individual dependency health checks"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "healthy",
                "timestamp": "2025-01-01T00:00:00Z",
                "service": "example-service",
                "version": "0.1.0",
                "checks": {"database": True, "cache": True, "messaging": True},
            }
        },
        str_strip_whitespace=True,
    )


class ComponentHealthDetail(BaseModel):
    """Detailed health information for a single component."""

    healthy: bool = Field(description="Whether component is healthy")
    status: HealthStatus = Field(description="Component health status")
    message: str = Field(default="", description="Status message")
    latency_ms: float = Field(description="Check latency in milliseconds")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "healthy": True,
                "status": "healthy",
                "message": "Database operational",
                "latency_ms": 5.23,
            }
        }
    )


class DetailedHealthResponse(BaseModel):
    """Detailed health check response with latency metrics.

    Extends the basic health response with per-component latency
    information and status messages for debugging and monitoring.

    Example:
        ```json
        {
            "status": "healthy",
            "timestamp": "2025-01-01T00:00:00Z",
            "service": "example-service",
            "version": "0.1.0",
            "duration_ms": 15.5,
            "from_cache": false,
            "checks": {
                "database": {
                    "healthy": true,
                    "status": "healthy",
                    "message": "Database operational",
                    "latency_ms": 5.2
                }
            }
        }
        ```
    """

    status: HealthStatus = Field(description="Overall health status")
    timestamp: datetime = Field(description="Check timestamp")
    service: str = Field(min_length=1, max_length=100, description="Service name")
    version: str = Field(min_length=1, max_length=50, description="Service version")
    duration_ms: float = Field(description="Total check duration in milliseconds")
    from_cache: bool = Field(default=False, description="Whether result was served from cache")
    checks: dict[str, Any] = Field(
        default_factory=dict, description="Detailed per-component health info"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "healthy",
                "timestamp": "2025-01-01T00:00:00Z",
                "service": "example-service",
                "version": "0.1.0",
                "duration_ms": 15.5,
                "from_cache": False,
                "checks": {
                    "database": {
                        "healthy": True,
                        "status": "healthy",
                        "message": "Database operational",
                        "latency_ms": 5.2,
                    },
                    "cache": {
                        "healthy": True,
                        "status": "healthy",
                        "message": "Cache operational",
                        "latency_ms": 2.1,
                    },
                },
            }
        },
        str_strip_whitespace=True,
    )


class ReadinessResponse(BaseModel):
    """Kubernetes readiness probe response.

    Indicates whether the service is ready to accept traffic.
    Returns 200 if ready, 503 if not ready.

    Example:
        ```json
        {
            "ready": true,
            "checks": {
                "database": true
            },
            "timestamp": "2025-01-01T00:00:00Z"
        }
        ```
    """

    ready: bool = Field(description="Overall readiness status")
    checks: dict[str, bool] = Field(
        default_factory=dict, description="Individual dependency checks"
    )
    timestamp: datetime = Field(description="Check timestamp")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "ready": True,
                "checks": {"database": True},
                "timestamp": "2025-01-01T00:00:00Z",
            }
        },
    )


class LivenessResponse(BaseModel):
    """Kubernetes liveness probe response.

    Simple check that the service process is running and responsive.
    Used by Kubernetes to determine if the pod should be restarted.

    Example:
        ```json
        {
            "alive": true,
            "timestamp": "2025-01-01T00:00:00Z",
            "service": "example-service"
        }
        ```
    """

    alive: bool = Field(description="Liveness status")
    timestamp: datetime = Field(description="Check timestamp")
    service: str = Field(min_length=1, max_length=100, description="Service name")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "alive": True,
                "timestamp": "2025-01-01T00:00:00Z",
                "service": "example-service",
            }
        },
        str_strip_whitespace=True,
    )


class StartupResponse(BaseModel):
    """Kubernetes startup probe response.

    Indicates whether the application has completed initialization.
    Kubernetes uses this to know when to start liveness and readiness probes.

    Example:
        ```json
        {
            "started": true,
            "timestamp": "2025-01-01T00:00:00Z"
        }
        ```
    """

    started: bool = Field(description="Startup completion status")
    timestamp: datetime = Field(description="Check timestamp")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "started": True,
                "timestamp": "2025-01-01T00:00:00Z",
            }
        },
    )


# =============================================================================
# History & Statistics Schemas
# =============================================================================


class HealthHistoryEntry(BaseModel):
    """A single entry in the health check history.

    Example:
        ```json
        {
            "timestamp": "2025-01-01T00:00:00Z",
            "status": "healthy",
            "duration_ms": 15.2,
            "checks": {
                "database": "healthy",
                "cache": "healthy"
            }
        }
        ```
    """

    timestamp: str = Field(description="When the check was performed (ISO format)")
    status: str = Field(description="Overall health status at that time")
    duration_ms: float = Field(description="How long the check took")
    checks: dict[str, str] | None = Field(
        default=None, description="Individual provider statuses"
    )
    provider_status: str | None = Field(
        default=None, description="Status for filtered provider"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "timestamp": "2025-01-01T00:00:00Z",
                "status": "healthy",
                "duration_ms": 15.2,
                "checks": {"database": "healthy", "cache": "healthy"},
            }
        }
    )


class HealthHistoryResponse(BaseModel):
    """Health check history response.

    Returns a list of recent health check results for trend analysis.

    Example:
        ```json
        {
            "entries": [
                {
                    "timestamp": "2025-01-01T00:00:05Z",
                    "status": "healthy",
                    "duration_ms": 12.5,
                    "checks": {"database": "healthy"}
                },
                {
                    "timestamp": "2025-01-01T00:00:00Z",
                    "status": "degraded",
                    "duration_ms": 1015.2,
                    "checks": {"database": "degraded"}
                }
            ],
            "total_entries": 2,
            "provider_filter": null
        }
        ```
    """

    entries: list[HealthHistoryEntry] = Field(description="History entries (most recent first)")
    total_entries: int = Field(description="Total number of entries returned")
    provider_filter: str | None = Field(default=None, description="Provider filter applied")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "entries": [
                    {
                        "timestamp": "2025-01-01T00:00:05Z",
                        "status": "healthy",
                        "duration_ms": 12.5,
                        "checks": {"database": "healthy", "cache": "healthy"},
                    },
                    {
                        "timestamp": "2025-01-01T00:00:00Z",
                        "status": "degraded",
                        "duration_ms": 1015.2,
                        "checks": {"database": "degraded", "cache": "healthy"},
                    },
                ],
                "total_entries": 2,
                "provider_filter": None,
            }
        }
    )


class ProviderStatsDetail(BaseModel):
    """Statistics for a single health provider."""

    total_checks: int = Field(description="Total number of checks")
    healthy_count: int = Field(description="Number of healthy checks")
    degraded_count: int = Field(description="Number of degraded checks")
    unhealthy_count: int = Field(description="Number of unhealthy checks")
    uptime_percentage: float = Field(description="Percentage uptime (healthy + degraded)")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "total_checks": 100,
                "healthy_count": 95,
                "degraded_count": 3,
                "unhealthy_count": 2,
                "uptime_percentage": 98.0,
            }
        }
    )


class HealthStatsResponse(BaseModel):
    """Health statistics response.

    Aggregated statistics over the health check history window,
    including uptime percentage, average latency, and per-provider stats.

    Example:
        ```json
        {
            "total_checks": 100,
            "healthy_count": 95,
            "degraded_count": 3,
            "unhealthy_count": 2,
            "uptime_percentage": 98.0,
            "avg_duration_ms": 15.5,
            "current_status": "healthy",
            "last_status_change": "2025-01-01T00:00:00Z",
            "provider_stats": {
                "database": {
                    "total_checks": 100,
                    "healthy_count": 98,
                    "uptime_percentage": 98.0
                }
            }
        }
        ```
    """

    total_checks: int = Field(description="Total number of health checks in history")
    healthy_count: int = Field(description="Number of healthy checks")
    degraded_count: int = Field(description="Number of degraded checks")
    unhealthy_count: int = Field(description="Number of unhealthy checks")
    uptime_percentage: float = Field(description="Overall uptime percentage")
    avg_duration_ms: float = Field(description="Average check duration in milliseconds")
    current_status: str | None = Field(default=None, description="Current health status")
    last_status_change: datetime | None = Field(
        default=None, description="When status last changed"
    )
    provider_stats: dict[str, ProviderStatsDetail] = Field(
        default_factory=dict, description="Per-provider statistics"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "total_checks": 100,
                "healthy_count": 95,
                "degraded_count": 3,
                "unhealthy_count": 2,
                "uptime_percentage": 98.0,
                "avg_duration_ms": 15.5,
                "current_status": "healthy",
                "last_status_change": "2025-01-01T00:00:00Z",
                "provider_stats": {
                    "database": {
                        "total_checks": 100,
                        "healthy_count": 98,
                        "degraded_count": 1,
                        "unhealthy_count": 1,
                        "uptime_percentage": 99.0,
                    },
                    "cache": {
                        "total_checks": 100,
                        "healthy_count": 95,
                        "degraded_count": 3,
                        "unhealthy_count": 2,
                        "uptime_percentage": 98.0,
                    },
                },
            }
        },
    )


class CacheInfoResponse(BaseModel):
    """Cache information response.

    Shows the current state of the health check result cache.

    Example:
        ```json
        {
            "ttl_seconds": 10.0,
            "is_valid": true,
            "age_seconds": 5.2,
            "has_cached_result": true
        }
        ```
    """

    ttl_seconds: float = Field(description="Cache TTL in seconds")
    is_valid: bool = Field(description="Whether cache is currently valid")
    age_seconds: float | None = Field(default=None, description="Age of cached result")
    has_cached_result: bool = Field(description="Whether there is a cached result")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "ttl_seconds": 10.0,
                "is_valid": True,
                "age_seconds": 5.2,
                "has_cached_result": True,
            }
        }
    )


class ProvidersResponse(BaseModel):
    """List of registered health providers.

    Example:
        ```json
        {
            "providers": ["database", "cache", "messaging"],
            "count": 3
        }
        ```
    """

    providers: list[str] = Field(description="List of registered provider names")
    count: int = Field(description="Number of providers")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "providers": ["database", "cache", "messaging"],
                "count": 3,
            }
        }
    )


class ProtectionDetail(BaseModel):
    """Detail for a single protection mechanism."""

    status: HealthStatus = Field(description="Protection status")
    message: str = Field(description="Status message")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional details")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "healthy",
                "message": "Rate limiting protection active",
                "metadata": {
                    "protection_status": "active",
                    "consecutive_failures": 0,
                },
            }
        }
    )


class ProtectionHealthResponse(BaseModel):
    """Security protection health response.

    Returns the status of security protection mechanisms like
    rate limiting. Used for security dashboards and alerting.

    Example:
        ```json
        {
            "status": "healthy",
            "timestamp": "2025-01-01T00:00:00Z",
            "protections": {
                "rate_limiter": {
                    "status": "healthy",
                    "message": "Rate limiting protection active",
                    "metadata": {
                        "protection_status": "active",
                        "consecutive_failures": 0
                    }
                }
            }
        }
        ```
    """

    status: HealthStatus = Field(description="Overall protection status")
    timestamp: datetime = Field(description="Check timestamp")
    protections: dict[str, ProtectionDetail] = Field(
        default_factory=dict, description="Individual protection mechanism statuses"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "healthy",
                "timestamp": "2025-01-01T00:00:00Z",
                "protections": {
                    "rate_limiter": {
                        "status": "healthy",
                        "message": "Rate limiting protection active",
                        "metadata": {
                            "protection_status": "active",
                            "consecutive_failures": 0,
                        },
                    }
                },
            }
        },
    )


__all__ = [
    "CacheInfoResponse",
    "ComponentHealthDetail",
    "DetailedHealthResponse",
    "HealthHistoryEntry",
    "HealthHistoryResponse",
    "HealthResponse",
    "HealthStatsResponse",
    "LivenessResponse",
    "ProtectionDetail",
    "ProtectionHealthResponse",
    "ProviderStatsDetail",
    "ProvidersResponse",
    "ReadinessResponse",
    "StartupResponse",
]
