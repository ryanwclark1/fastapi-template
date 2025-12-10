"""Feature flag dependencies for FastAPI.

Provides injectable dependencies for feature flag evaluation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from fastapi import Depends, HTTPException, Request, status

from example_service.core.dependencies.database import get_db_session

from .service import FeatureFlagService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class FeatureFlags:
    """Request-scoped feature flag evaluator.

    Provides easy access to feature flag evaluation within request handlers.

    Usage:
        @router.get("/dashboard")
        async def get_dashboard(
            flags: Annotated[FeatureFlags, Depends(get_feature_flags)]
        ):
            if await flags.is_enabled("new_dashboard"):
                return new_dashboard_response()
            return old_dashboard_response()
    """

    def __init__(
        self,
        service: FeatureFlagService,
        user_id: str | None = None,
        tenant_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        """Initialize feature flags evaluator.

        Args:
            service: Feature flag service.
            user_id: Current user ID.
            tenant_id: Current tenant ID.
            attributes: Additional context attributes.
        """
        self.service = service
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.attributes = attributes or {}

    async def is_enabled(self, key: str, default: bool = False) -> bool:
        """Check if a flag is enabled.

        Args:
            key: Flag key.
            default: Default value if flag not found.

        Returns:
            True if flag is enabled.
        """
        return await self.service.is_enabled(
            key=key,
            user_id=self.user_id,
            tenant_id=self.tenant_id,
            attributes=self.attributes,
            default=default,
        )

    async def get_all(self, flag_keys: list[str] | None = None) -> dict[str, bool]:
        """Get all flag values.

        Args:
            flag_keys: Specific flags to get (all if None).

        Returns:
            Dictionary of flag keys to values.
        """
        from .schemas import FlagEvaluationRequest

        context = FlagEvaluationRequest(
            user_id=self.user_id,
            tenant_id=self.tenant_id,
            attributes=self.attributes,
        )
        result = await self.service.evaluate(context, flag_keys=flag_keys)
        return result.flags


async def get_feature_flags(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> FeatureFlags:
    """Get feature flags evaluator for the current request.

    Extracts user and tenant context from the request.

    Args:
        request: Current request.
        session: Database session.

    Returns:
        FeatureFlags evaluator.
    """
    # Extract context from request state (set by auth middleware)
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        user = getattr(request.state, "user", None)
        if user:
            user_id = getattr(user, "user_id", None) or getattr(user, "id", None)

    tenant_id = getattr(request.state, "tenant_uuid", None)

    # Build attributes from request
    attributes = {
        "path": str(request.url.path),
        "method": request.method,
    }

    # Add user attributes if available
    user = getattr(request.state, "user", None)
    if user:
        if hasattr(user, "permissions"):
            attributes["acl_patterns"] = user.permissions
        if hasattr(user, "plan"):
            attributes["plan"] = user.plan
        if hasattr(user, "roles") and user.roles is not None:
            attributes["roles"] = list(user.roles)

    service = FeatureFlagService(session)
    return FeatureFlags(
        service=service,
        user_id=str(user_id) if user_id else None,
        tenant_id=str(tenant_id) if tenant_id else None,
        attributes=attributes,
    )


def require_feature(flag_key: str, allow_missing: bool = False): # type: ignore[no-untyped-def]
    """Dependency factory that requires a feature flag to be enabled.

    Usage:
        @router.get(
            "/beta-feature",
            dependencies=[Depends(require_feature("beta_feature"))]
        )
        async def beta_feature():
            ...

    Args:
        flag_key: Required flag key.
        allow_missing: If True, allow when flag doesn't exist.

    Returns:
        Dependency function.
    """

    async def dependency(
        flags: Annotated[FeatureFlags, Depends(get_feature_flags)]
    ) -> None:
        """Check if feature is enabled."""
        is_enabled = await flags.is_enabled(flag_key, default=allow_missing)
        if not is_enabled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Feature '{flag_key}' is not enabled",
            )

    return dependency


__all__ = [
    "FeatureFlags",
    "get_feature_flags",
    "require_feature",
]
