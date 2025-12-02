"""Feature flag REST API endpoints.

Provides endpoints for managing and evaluating feature flags.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from example_service.core.dependencies.auth import get_current_user
from example_service.core.dependencies.database import get_db_session

from .dependencies import FeatureFlags, get_feature_flags
from .models import FlagStatus
from .schemas import (
    FeatureFlagCreate,
    FeatureFlagListResponse,
    FeatureFlagResponse,
    FeatureFlagUpdate,
    FlagEvaluationRequest,
    FlagEvaluationResponse,
    FlagOverrideCreate,
    FlagOverrideResponse,
)
from .service import FeatureFlagService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/feature-flags", tags=["feature-flags"])


# Flag management endpoints


@router.post(
    "",
    response_model=FeatureFlagResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create feature flag",
    description="Create a new feature flag.",
)
async def create_flag(
    data: FeatureFlagCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _user: Annotated[dict, Depends(get_current_user)],
) -> FeatureFlagResponse:
    """Create a new feature flag.

    Args:
        data: Flag configuration.

    Returns:
        Created feature flag.
    """
    service = FeatureFlagService(session)

    # Check if flag already exists
    existing = await service.get_by_key(data.key)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Feature flag '{data.key}' already exists",
        )

    flag = await service.create(data)
    return FeatureFlagResponse.model_validate(flag)


@router.get(
    "",
    response_model=FeatureFlagListResponse,
    summary="List feature flags",
    description="List all feature flags with optional filters.",
)
async def list_flags(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _user: Annotated[dict, Depends(get_current_user)],
    flag_status: Annotated[FlagStatus | None, Query(alias="status")] = None,
    enabled: Annotated[bool | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> FeatureFlagListResponse:
    """List feature flags.

    Args:
        flag_status: Filter by status.
        enabled: Filter by enabled state.
        limit: Maximum flags to return.
        offset: Number to skip.

    Returns:
        Paginated list of flags.
    """
    service = FeatureFlagService(session)
    return await service.list_flags(
        status=flag_status,
        enabled=enabled,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{key}",
    response_model=FeatureFlagResponse,
    summary="Get feature flag",
    description="Get a feature flag by key.",
)
async def get_flag(
    key: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _user: Annotated[dict, Depends(get_current_user)],
) -> FeatureFlagResponse:
    """Get a feature flag.

    Args:
        key: Flag key.

    Returns:
        Feature flag.
    """
    service = FeatureFlagService(session)
    flag = await service.get_by_key(key)

    if not flag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Feature flag '{key}' not found",
        )

    return FeatureFlagResponse.model_validate(flag)


@router.patch(
    "/{key}",
    response_model=FeatureFlagResponse,
    summary="Update feature flag",
    description="Update a feature flag.",
)
async def update_flag(
    key: str,
    data: FeatureFlagUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _user: Annotated[dict, Depends(get_current_user)],
) -> FeatureFlagResponse:
    """Update a feature flag.

    Args:
        key: Flag key.
        data: Update data.

    Returns:
        Updated feature flag.
    """
    service = FeatureFlagService(session)
    flag = await service.update(key, data)

    if not flag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Feature flag '{key}' not found",
        )

    return FeatureFlagResponse.model_validate(flag)


@router.delete(
    "/{key}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete feature flag",
    description="Delete a feature flag.",
)
async def delete_flag(
    key: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _user: Annotated[dict, Depends(get_current_user)],
) -> None:
    """Delete a feature flag.

    Args:
        key: Flag key.
    """
    service = FeatureFlagService(session)
    deleted = await service.delete(key)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Feature flag '{key}' not found",
        )


@router.post(
    "/{key}/enable",
    response_model=FeatureFlagResponse,
    summary="Enable feature flag",
    description="Quick enable a feature flag globally.",
)
async def enable_flag(
    key: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _user: Annotated[dict, Depends(get_current_user)],
) -> FeatureFlagResponse:
    """Enable a feature flag globally.

    Args:
        key: Flag key.

    Returns:
        Updated feature flag.
    """
    service = FeatureFlagService(session)
    flag = await service.update(
        key,
        FeatureFlagUpdate(status=FlagStatus.ENABLED, enabled=True),
    )

    if not flag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Feature flag '{key}' not found",
        )

    return FeatureFlagResponse.model_validate(flag)


@router.post(
    "/{key}/disable",
    response_model=FeatureFlagResponse,
    summary="Disable feature flag",
    description="Quick disable a feature flag globally.",
)
async def disable_flag(
    key: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _user: Annotated[dict, Depends(get_current_user)],
) -> FeatureFlagResponse:
    """Disable a feature flag globally.

    Args:
        key: Flag key.

    Returns:
        Updated feature flag.
    """
    service = FeatureFlagService(session)
    flag = await service.update(
        key,
        FeatureFlagUpdate(status=FlagStatus.DISABLED, enabled=False),
    )

    if not flag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Feature flag '{key}' not found",
        )

    return FeatureFlagResponse.model_validate(flag)


# Override endpoints


@router.post(
    "/overrides",
    response_model=FlagOverrideResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create flag override",
    description="Create an override for a specific user or tenant.",
)
async def create_override(
    data: FlagOverrideCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _user: Annotated[dict, Depends(get_current_user)],
) -> FlagOverrideResponse:
    """Create a flag override.

    Args:
        data: Override configuration.

    Returns:
        Created override.
    """
    service = FeatureFlagService(session)

    # Verify flag exists
    flag = await service.get_by_key(data.flag_key)
    if not flag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Feature flag '{data.flag_key}' not found",
        )

    override = await service.create_override(data)
    return FlagOverrideResponse.model_validate(override)


@router.get(
    "/overrides",
    response_model=list[FlagOverrideResponse],
    summary="List flag overrides",
    description="List flag overrides with optional filters.",
)
async def list_overrides(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _user: Annotated[dict, Depends(get_current_user)],
    flag_key: Annotated[str | None, Query()] = None,
    entity_type: Annotated[str | None, Query()] = None,
    entity_id: Annotated[str | None, Query()] = None,
) -> list[FlagOverrideResponse]:
    """List flag overrides.

    Args:
        flag_key: Filter by flag key.
        entity_type: Filter by entity type.
        entity_id: Filter by entity ID.

    Returns:
        List of overrides.
    """
    service = FeatureFlagService(session)
    overrides = await service.get_overrides(
        flag_key=flag_key,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    return [FlagOverrideResponse.model_validate(o) for o in overrides]


@router.delete(
    "/overrides/{flag_key}/{entity_type}/{entity_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete flag override",
    description="Delete a specific flag override.",
)
async def delete_override(
    flag_key: str,
    entity_type: str,
    entity_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _user: Annotated[dict, Depends(get_current_user)],
) -> None:
    """Delete a flag override.

    Args:
        flag_key: Flag key.
        entity_type: Entity type.
        entity_id: Entity ID.
    """
    service = FeatureFlagService(session)
    deleted = await service.delete_override(flag_key, entity_type, entity_id)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Override not found",
        )


# Evaluation endpoints


@router.post(
    "/evaluate",
    response_model=FlagEvaluationResponse,
    summary="Evaluate feature flags",
    description="Evaluate feature flags for a given context.",
)
async def evaluate_flags(
    context: FlagEvaluationRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _user: Annotated[dict, Depends(get_current_user)],
    keys: Annotated[list[str] | None, Query()] = None,
    include_details: Annotated[bool, Query()] = False,
) -> FlagEvaluationResponse:
    """Evaluate feature flags.

    Args:
        context: Evaluation context.
        keys: Specific flag keys to evaluate.
        include_details: Include evaluation details.

    Returns:
        Evaluated flag values.
    """
    service = FeatureFlagService(session)
    return await service.evaluate(
        context=context,
        flag_keys=keys,
        include_details=include_details,
    )


@router.get(
    "/evaluate/me",
    response_model=FlagEvaluationResponse,
    summary="Evaluate flags for current user",
    description="Evaluate all feature flags for the current request context.",
)
async def evaluate_my_flags(
    flags: Annotated[FeatureFlags, Depends(get_feature_flags)],
) -> FlagEvaluationResponse:
    """Evaluate flags for the current user.

    Uses the current request context (user, tenant, etc.) to evaluate flags.

    Returns:
        All evaluated flag values.
    """
    evaluated = await flags.get_all()
    return FlagEvaluationResponse(flags=evaluated)


@router.get(
    "/check/{key}",
    summary="Quick flag check",
    description="Quickly check if a flag is enabled for the current context.",
)
async def check_flag(
    key: str,
    flags: Annotated[FeatureFlags, Depends(get_feature_flags)],
) -> dict[str, bool]:
    """Quick check if a flag is enabled.

    Args:
        key: Flag key.

    Returns:
        Simple enabled status.
    """
    enabled = await flags.is_enabled(key)
    return {"key": key, "enabled": enabled}
