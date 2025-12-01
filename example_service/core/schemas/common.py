"""Common schemas and validators."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class StatusEnum(str, Enum):
    """Common status enumeration."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING = "pending"
    DELETED = "deleted"


class HealthStatus(str, Enum):
    """Health check status values."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class MessageResponse(BaseModel):
    """Simple message response."""

    message: str = Field(min_length=1, max_length=1000, description="Response message")
    success: bool = Field(default=True, description="Operation success status")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"message": "Operation completed successfully", "success": True}
        },
        str_strip_whitespace=True,
    )
