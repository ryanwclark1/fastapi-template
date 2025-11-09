"""Common schemas and validators."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


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

    message: str = Field(description="Response message")
    success: bool = Field(default=True, description="Operation success status")

    class Config:
        """Pydantic configuration."""

        json_schema_extra = {
            "example": {"message": "Operation completed successfully", "success": True}
        }
