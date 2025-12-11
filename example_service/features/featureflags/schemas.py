"""Feature flag schemas for API requests and responses."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from example_service.utils.runtime_dependencies import require_runtime_dependency

from .models import FlagStatus

require_runtime_dependency(datetime, FlagStatus)


class TargetingRule(BaseModel):
    """A single targeting rule for feature flags.

    Rules can target based on:
    - User IDs
    - Tenant IDs
    - User attributes (role, plan, etc.)
    - Custom attributes
    """

    type: str = Field(description="Rule type (user_id, tenant_id, attribute)")
    operator: str = Field(description="Comparison operator (eq, in, contains, etc.)")
    value: Any = Field(description="Value to compare against")
    attribute: str | None = Field(default=None, description="Attribute name for attribute rules")


class FeatureFlagCreate(BaseModel):
    """Schema for creating a feature flag."""

    key: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[a-z][a-z0-9_]*$",
        description="Unique flag key (lowercase, underscores allowed)",
    )
    name: str = Field(min_length=1, max_length=200, description="Human-readable name")
    description: str | None = Field(default=None, description="Flag description")
    status: FlagStatus = Field(default=FlagStatus.DISABLED, description="Initial status")
    enabled: bool = Field(default=False, description="Global enabled state")
    percentage: int = Field(default=0, ge=0, le=100, description="Rollout percentage")
    targeting_rules: list[TargetingRule] | None = Field(
        default=None, description="Targeting rules",
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Additional metadata",
        validation_alias="context_data",
        serialization_alias="metadata",
    )
    starts_at: datetime | None = Field(default=None, description="Activation start time")
    ends_at: datetime | None = Field(default=None, description="Activation end time")

    @field_validator("key")
    @classmethod
    def validate_key(cls, v: str) -> str:
        """Ensure key is lowercase."""
        return v.lower()

    model_config = {
        "populate_by_name": True,
        "json_schema_extra": {
            "example": {
                "key": "new_dashboard",
                "name": "New Dashboard Feature",
                "description": "Enable the redesigned dashboard",
                "status": "percentage",
                "percentage": 25,
            },
        },
    }


class FeatureFlagUpdate(BaseModel):
    """Schema for updating a feature flag."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None)
    status: FlagStatus | None = Field(default=None)
    enabled: bool | None = Field(default=None)
    percentage: int | None = Field(default=None, ge=0, le=100)
    targeting_rules: list[TargetingRule] | None = Field(default=None)
    metadata: dict[str, Any] | None = Field(
        default=None,
        validation_alias="context_data",
        serialization_alias="metadata",
    )
    starts_at: datetime | None = Field(default=None)
    ends_at: datetime | None = Field(default=None)

    model_config = {"populate_by_name": True}


class FeatureFlagResponse(BaseModel):
    """Response schema for a feature flag."""

    id: str
    key: str
    name: str
    description: str | None
    status: FlagStatus
    enabled: bool
    percentage: int
    targeting_rules: list[TargetingRule] | None
    metadata: dict[str, Any] | None = Field(
        description="Additional metadata",
        validation_alias="context_data",
        serialization_alias="metadata",
    )
    starts_at: datetime | None
    ends_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}


class FeatureFlagListResponse(BaseModel):
    """Response schema for listing feature flags."""

    items: list[FeatureFlagResponse]
    total: int


class FlagOverrideCreate(BaseModel):
    """Schema for creating a flag override."""

    flag_key: str = Field(description="Feature flag key")
    entity_type: str = Field(description="Entity type (user, tenant)")
    entity_id: str = Field(description="Entity ID")
    enabled: bool = Field(description="Override value")
    reason: str | None = Field(default=None, description="Reason for override")

    @field_validator("entity_type")
    @classmethod
    def validate_entity_type(cls, v: str) -> str:
        """Validate entity type."""
        allowed = {"user", "tenant"}
        if v.lower() not in allowed:
            msg = f"entity_type must be one of: {allowed}"
            raise ValueError(msg)
        return v.lower()


class FlagOverrideResponse(BaseModel):
    """Response schema for a flag override."""

    id: str
    flag_key: str
    entity_type: str
    entity_id: str
    enabled: bool
    reason: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FlagEvaluationRequest(BaseModel):
    """Request to evaluate feature flags for a context."""

    user_id: str | None = Field(default=None, description="User ID for evaluation")
    tenant_id: str | None = Field(default=None, description="Tenant ID for evaluation")
    attributes: dict[str, Any] | None = Field(
        default=None, description="Additional attributes for targeting",
    )


class FlagEvaluationResult(BaseModel):
    """Result of evaluating a single flag."""

    key: str
    enabled: bool
    reason: str = Field(description="Why this value was returned")


class FlagEvaluationResponse(BaseModel):
    """Response with evaluated flag values."""

    flags: dict[str, bool] = Field(description="Map of flag keys to their evaluated values")
    details: list[FlagEvaluationResult] | None = Field(
        default=None, description="Detailed evaluation results",
    )


__all__ = [
    "FeatureFlagCreate",
    "FeatureFlagListResponse",
    "FeatureFlagResponse",
    "FeatureFlagUpdate",
    "FlagEvaluationRequest",
    "FlagEvaluationResponse",
    "FlagEvaluationResult",
    "FlagOverrideCreate",
    "FlagOverrideResponse",
    "TargetingRule",
]
