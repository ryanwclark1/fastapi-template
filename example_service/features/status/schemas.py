"""Status and health check response schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Health check response.

    Example:
        ```json
        {
            "status": "healthy",
            "timestamp": "2025-01-01T00:00:00Z",
            "service": "example-service",
            "version": "0.1.0"
        }
        ```
    """

    status: str = Field(description="Health status")
    timestamp: str = Field(description="Check timestamp in ISO format")
    service: str = Field(description="Service name")
    version: str = Field(description="Service version")

    class Config:
        """Pydantic configuration."""

        json_schema_extra = {
            "example": {
                "status": "healthy",
                "timestamp": "2025-01-01T00:00:00Z",
                "service": "example-service",
                "version": "0.1.0",
            }
        }


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
        ```
    """

    ready: bool = Field(description="Overall readiness status")
    checks: dict[str, bool] = Field(description="Individual dependency checks")
    timestamp: str = Field(description="Check timestamp in ISO format")

    class Config:
        """Pydantic configuration."""

        json_schema_extra = {
            "example": {
                "ready": True,
                "checks": {"database": True, "cache": True},
                "timestamp": "2025-01-01T00:00:00Z",
            }
        }


class LivenessResponse(BaseModel):
    """Liveness check response.

    Example:
        ```json
        {
            "alive": true,
            "timestamp": "2025-01-01T00:00:00Z"
        }
        ```
    """

    alive: bool = Field(description="Liveness status")
    timestamp: str = Field(description="Check timestamp in ISO format")

    class Config:
        """Pydantic configuration."""

        json_schema_extra = {
            "example": {
                "alive": True,
                "timestamp": "2025-01-01T00:00:00Z",
            }
        }
