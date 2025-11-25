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
        json_encoders={datetime: lambda v: v.isoformat()},
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
        json_encoders={datetime: lambda v: v.isoformat()},
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
        json_encoders={datetime: lambda v: v.isoformat()},
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
        json_encoders={datetime: lambda v: v.isoformat()},
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
        json_encoders={datetime: lambda v: v.isoformat()},
    )


__all__ = [
    "ComponentHealthDetail",
    "DetailedHealthResponse",
    "HealthResponse",
    "LivenessResponse",
    "ReadinessResponse",
    "StartupResponse",
]
