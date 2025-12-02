"""Feature flags system.

Provides feature toggle capabilities:
- Simple on/off flags
- Percentage-based gradual rollout
- User/tenant targeting
- Time-based activation
- Override support

Usage:
    from example_service.features.featureflags import (
        FeatureFlagService,
        get_feature_flags,
        require_feature,
    )

    # In a route handler
    @router.get("/dashboard")
    async def get_dashboard(
        flags: Annotated[FeatureFlags, Depends(get_feature_flags)]
    ):
        if await flags.is_enabled("new_dashboard"):
            return new_dashboard()
        return old_dashboard()

    # Require a feature
    @router.get(
        "/beta",
        dependencies=[Depends(require_feature("beta_access"))]
    )
    async def beta_feature():
        ...
"""

from __future__ import annotations

from .dependencies import FeatureFlags, get_feature_flags, require_feature
from .models import FeatureFlag, FlagOverride, FlagStatus
from .router import router
from .schemas import (
    FeatureFlagCreate,
    FeatureFlagListResponse,
    FeatureFlagResponse,
    FeatureFlagUpdate,
    FlagEvaluationRequest,
    FlagEvaluationResponse,
    FlagEvaluationResult,
    FlagOverrideCreate,
    FlagOverrideResponse,
    TargetingRule,
)
from .service import FeatureFlagService, get_feature_flag_service

__all__ = [
    # Models
    "FeatureFlag",
    # Schemas
    "FeatureFlagCreate",
    "FeatureFlagListResponse",
    "FeatureFlagResponse",
    # Service
    "FeatureFlagService",
    "FeatureFlagUpdate",
    # Dependencies
    "FeatureFlags",
    "FlagEvaluationRequest",
    "FlagEvaluationResponse",
    "FlagEvaluationResult",
    "FlagOverride",
    "FlagOverrideCreate",
    "FlagOverrideResponse",
    "FlagStatus",
    "TargetingRule",
    "get_feature_flag_service",
    "get_feature_flags",
    "require_feature",
    # Router
    "router",
]
