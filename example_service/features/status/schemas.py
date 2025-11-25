"""Status and health check response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from example_service.core.schemas.common import HealthStatus


class HealthResponse(BaseModel):
    """Health check response.

    Example:
        ```json
        {
            "status": "healthy",
            "timestamp": "2025-01-01T00:00:00Z",
            "service": "example-service",
            "version": "0.1.0",
            "checks": {
                "database": true,
                "cache": true
            }
        }
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
                "checks": {"database": True, "cache": True},
            }
        },
        json_encoders={datetime: lambda v: v.isoformat()},
        str_strip_whitespace=True,
    )


class ReadinessResponse(BaseModel):
    """Readiness check response.

    Example:
        ```json
        {
            "ready": true,
            "checks": {
                "database": true,
                "cache": true
            },
            "timestamp": "2025-01-01T00:00:00Z"
        }
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
                "checks": {"database": True, "cache": True},
                "timestamp": "2025-01-01T00:00:00Z",
            }
        },
        json_encoders={datetime: lambda v: v.isoformat()},
    )


class LivenessResponse(BaseModel):
    """Liveness check response.

    Example:
        ```json
        {
            "alive": true,
            "timestamp": "2025-01-01T00:00:00Z",
            "service": "example-service"
        }
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
    """Startup probe response.

    Example:
        ```json
        {
            "started": true,
            "timestamp": "2025-01-01T00:00:00Z"
        }
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
