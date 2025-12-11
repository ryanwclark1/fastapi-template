"""GraphQL types for feature flags.

Provides Strawberry GraphQL types for feature flag management with full Pydantic integration.
Feature flags enable gradual rollout and A/B testing of new features.

Auto-generated from Pydantic schemas:
- FeatureFlagType: Auto-generated from FeatureFlagResponse
- CreateFeatureFlagInput: Auto-generated from FeatureFlagCreate
- UpdateFeatureFlagInput: Auto-generated from FeatureFlagUpdate
"""

from __future__ import annotations

from enum import Enum

import strawberry

from example_service.features.featureflags.models import FlagStatus as ModelFlagStatus
from example_service.features.featureflags.schemas import (
    FeatureFlagCreate,
    FeatureFlagResponse,
    FeatureFlagUpdate,
)
from example_service.features.featureflags.schemas import (
    FlagEvaluationResult as PydanticFlagEvaluationResult,
)
from example_service.features.featureflags.schemas import (
    TargetingRule as PydanticTargetingRule,
)
from example_service.features.graphql.types.base import PageInfoType
from example_service.features.graphql.types.pydantic_bridge import (
    pydantic_field,
    pydantic_input,
    pydantic_type,
)
from example_service.utils.runtime_dependencies import require_runtime_dependency

require_runtime_dependency(PageInfoType)

# ============================================================================
# Enums
# ============================================================================

# Use the model's FlagStatus StrEnum directly
FlagStatus = strawberry.enum(ModelFlagStatus, description="Feature flag status")


# ============================================================================
# Nested Types
# ============================================================================


@strawberry.type(description="Targeting rule for feature flags")
class TargetingRule:
    """Targeting rule for conditional flag enablement.

    Rules can target based on:
    - User IDs
    - Tenant IDs
    - User attributes (role, plan, etc.)
    """

    type: str = strawberry.field(description="Rule type (user_id, tenant_id, attribute)")
    operator: str = strawberry.field(description="Comparison operator (eq, in, contains)")
    value: strawberry.scalars.JSON = strawberry.field(description="Value to compare against")
    attribute: str | None = strawberry.field(
        default=None, description="Attribute name for attribute rules",
    )

    @staticmethod
    def from_pydantic(rule: PydanticTargetingRule) -> TargetingRule:
        """Convert from Pydantic TargetingRule."""
        return TargetingRule(
            type=rule.type,
            operator=rule.operator,
            value=rule.value,
            attribute=rule.attribute,
        )


# ============================================================================
# Feature Flag Type (Output)
# ============================================================================


@pydantic_type(model=FeatureFlagResponse, description="A feature flag for gradual rollout")
class FeatureFlagType:
    """Feature flag type auto-generated from FeatureFlagResponse.

    Feature flags enable:
    - Gradual rollout (percentage-based)
    - A/B testing
    - Targeted enablement (specific users/tenants)
    - Time-based activation

    All fields are auto-generated from the Pydantic FeatureFlagResponse schema.
    """

    # Override ID field
    id: strawberry.ID = pydantic_field(description="Unique identifier for the flag")

    # Complex fields that need custom handling
    @strawberry.field(description="Targeting rules for conditional enablement")
    def targeting_rules(self) -> list[TargetingRule] | None:
        """Get targeting rules with proper type conversion."""
        if hasattr(self, "_targeting_rules") and self._targeting_rules:
            return [TargetingRule.from_pydantic(rule) for rule in self._targeting_rules]
        return None

    @strawberry.field(description="Additional metadata")
    def metadata(self) -> strawberry.scalars.JSON | None:
        """Get metadata as JSON."""
        if hasattr(self, "_metadata"):
            return self._metadata
        return None

    # Computed fields
    @strawberry.field(description="Whether the flag is currently active (within time window)")
    def is_active(self) -> bool:
        """Check if flag is currently active based on time window."""
        from datetime import UTC, datetime

        now = datetime.now(UTC)

        # Check start time
        if hasattr(self, "starts_at") and self.starts_at and now < self.starts_at:
            return False

        # Check end time
        if hasattr(self, "ends_at") and self.ends_at and now > self.ends_at:
            return False

        return self.enabled


# ============================================================================
# Input Types
# ============================================================================


@pydantic_input(
    model=FeatureFlagCreate,
    fields=["key", "name", "description", "enabled", "percentage"],
    description="Input for creating a feature flag",
)
class CreateFeatureFlagInput:
    """Input for creating a feature flag.

    Auto-generated from FeatureFlagCreate Pydantic schema.
    Pydantic validators run automatically:
    - key: lowercase, alphanumeric with underscores
    - percentage: 0-100
    """


@pydantic_input(
    model=FeatureFlagUpdate,
    fields=["name", "description", "enabled", "percentage"],
    description="Input for updating a feature flag",
)
class UpdateFeatureFlagInput:
    """Input for updating a feature flag.

    All fields are optional - only provided fields are updated.
    Auto-generated from FeatureFlagUpdate Pydantic schema.
    """


@strawberry.input(description="Input for evaluating a feature flag")
class FlagEvaluationInput:
    """Input for evaluating whether a flag is enabled for a context."""

    user_id: str | None = strawberry.field(default=None, description="User ID for evaluation")
    tenant_id: str | None = strawberry.field(default=None, description="Tenant ID for evaluation")
    attributes: strawberry.scalars.JSON | None = strawberry.field(
        default=None, description="Additional attributes for targeting",
    )


# ============================================================================
# Response Types
# ============================================================================


@strawberry.type(description="Result of evaluating a feature flag")
class FlagEvaluationResult:
    """Result of evaluating a single flag."""

    key: str = strawberry.field(description="Flag key")
    enabled: bool = strawberry.field(description="Whether flag is enabled")
    reason: str = strawberry.field(description="Why this value was returned")

    @staticmethod
    def from_pydantic(result: PydanticFlagEvaluationResult) -> FlagEvaluationResult:
        """Convert from Pydantic FlagEvaluationResult."""
        return FlagEvaluationResult(
            key=result.key,
            enabled=result.enabled,
            reason=result.reason,
        )


# ============================================================================
# Union Types for Responses
# ============================================================================


@strawberry.type(description="Feature flag created or updated successfully")
class FeatureFlagSuccess:
    """Successful feature flag operation response."""

    flag: FeatureFlagType


@strawberry.enum(description="Feature flag error codes")
class FeatureFlagErrorCode(str, Enum):
    """Error codes for feature flag operations."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    DUPLICATE_KEY = "DUPLICATE_KEY"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@strawberry.type(description="Feature flag operation error")
class FeatureFlagError:
    """Error response for feature flag operations."""

    code: FeatureFlagErrorCode
    message: str
    field: str | None = None


# Union type for mutations
FeatureFlagPayload = strawberry.union("FeatureFlagPayload", (FeatureFlagSuccess, FeatureFlagError))


@strawberry.type(description="Generic success/failure response")
class DeletePayload:
    """Response for delete operations."""

    success: bool
    message: str


# ============================================================================
# Edge and Connection Types for Pagination
# ============================================================================


@strawberry.type(description="Edge containing a feature flag node and cursor")
class FeatureFlagEdge:
    """Edge in a Relay-style connection."""

    node: FeatureFlagType
    cursor: str


@strawberry.type(description="Paginated list of feature flags")
class FeatureFlagConnection:
    """Relay-style connection for feature flag pagination."""

    edges: list[FeatureFlagEdge]
    page_info: PageInfoType


# ============================================================================
# Subscription Event Types
# ============================================================================


@strawberry.enum(description="Types of feature flag events for subscriptions")
class FeatureFlagEventType(str, Enum):
    """Event types for feature flag subscriptions.

    Clients can subscribe to specific event types or all events.
    """

    CREATED = "CREATED"
    UPDATED = "UPDATED"
    TOGGLED = "TOGGLED"  # Specifically for enabled state changes
    DELETED = "DELETED"


@strawberry.type(description="Real-time feature flag event via subscription")
class FeatureFlagEvent:
    """Event payload for feature flag subscriptions.

    Pushed to subscribed clients when flags are created, updated, toggled, or deleted.
    Useful for real-time feature rollout monitoring and A/B test tracking.
    """

    event_type: FeatureFlagEventType = strawberry.field(description="Type of event that occurred")
    flag: FeatureFlagType | None = strawberry.field(
        default=None,
        description="Flag data (null for DELETED events)",
    )
    flag_id: strawberry.ID = strawberry.field(description="Flag ID")
    previous_enabled: bool | None = strawberry.field(
        default=None,
        description="Previous enabled state (for TOGGLED events)",
    )


__all__ = [
    # Inputs
    "CreateFeatureFlagInput",
    "DeletePayload",
    "FeatureFlagConnection",
    # Pagination
    "FeatureFlagEdge",
    "FeatureFlagError",
    "FeatureFlagErrorCode",
    "FeatureFlagEvent",
    "FeatureFlagEventType",
    "FeatureFlagPayload",
    # Responses
    "FeatureFlagSuccess",
    # Types
    "FeatureFlagType",
    "FlagEvaluationInput",
    "FlagEvaluationResult",
    # Enums
    "FlagStatus",
    "TargetingRule",
    "UpdateFeatureFlagInput",
]
