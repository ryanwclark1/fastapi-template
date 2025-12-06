"""Mutation resolvers for feature flags.

Provides write operations for feature flags:
- createFeatureFlag: Create a new feature flag
- updateFeatureFlag: Update an existing feature flag
- toggleFeatureFlag: Toggle a flag's enabled state
- deleteFeatureFlag: Delete a feature flag
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.exc import IntegrityError
import strawberry

from example_service.features.featureflags.models import FeatureFlag, FlagStatus
from example_service.features.featureflags.repository import get_feature_flag_repository
from example_service.features.featureflags.schemas import (
    FeatureFlagResponse,
)
from example_service.features.graphql.events import (
    publish_feature_flag_event,
    serialize_model_for_event,
)
from example_service.features.graphql.types.featureflags import (
    CreateFeatureFlagInput,
    DeletePayload,
    FeatureFlagError,
    FeatureFlagErrorCode,
    FeatureFlagPayload,
    FeatureFlagSuccess,
    FeatureFlagType,
    UpdateFeatureFlagInput,
)

if TYPE_CHECKING:
    from strawberry.types import Info

    from example_service.features.graphql.context import GraphQLContext

logger = logging.getLogger(__name__)


async def create_feature_flag_mutation(
    info: Info[GraphQLContext, None],
    input: CreateFeatureFlagInput,
) -> FeatureFlagPayload:
    """Create a new feature flag.

    Args:
        info: Strawberry info with context
        input: Feature flag creation data

    Returns:
        FeatureFlagSuccess with the created flag, or FeatureFlagError
    """
    ctx = info.context

    # Convert GraphQL input to Pydantic for validation
    try:
        create_data = input.to_pydantic()
    except Exception as e:
        return FeatureFlagError(
            code=FeatureFlagErrorCode.VALIDATION_ERROR,
            message=f"Invalid input: {e!s}",
            field="input",
        )

    # Additional validation
    if not create_data.key or not create_data.key.strip():
        return FeatureFlagError(
            code=FeatureFlagErrorCode.VALIDATION_ERROR,
            message="Flag key is required",
            field="key",
        )

    if len(create_data.key) > 100:
        return FeatureFlagError(
            code=FeatureFlagErrorCode.VALIDATION_ERROR,
            message="Flag key must be 100 characters or less",
            field="key",
        )

    if not create_data.name or not create_data.name.strip():
        return FeatureFlagError(
            code=FeatureFlagErrorCode.VALIDATION_ERROR,
            message="Flag name is required",
            field="name",
        )

    try:
        # Create flag from Pydantic data
        flag = FeatureFlag(
            key=create_data.key.strip().lower(),
            name=create_data.name.strip(),
            description=create_data.description.strip() if create_data.description else None,
            status=create_data.status.value if create_data.status else FlagStatus.DISABLED.value,
            enabled=create_data.enabled,
            percentage=create_data.percentage,
            targeting_rules=[r.model_dump() for r in create_data.targeting_rules]
            if create_data.targeting_rules
            else None,
            context_data=create_data.metadata,
            starts_at=create_data.starts_at,
            ends_at=create_data.ends_at,
        )

        ctx.session.add(flag)
        await ctx.session.commit()
        await ctx.session.refresh(flag)

        logger.info(f"Created feature flag: {flag.id} ({flag.key})")

        # Publish event for real-time subscriptions
        await publish_feature_flag_event(
            event_type="CREATED",
            flag_data=serialize_model_for_event(flag),
        )

        # Convert: SQLAlchemy → Pydantic → GraphQL
        flag_pydantic = FeatureFlagResponse.from_orm(flag)
        return FeatureFlagSuccess(flag=FeatureFlagType.from_pydantic(flag_pydantic))

    except IntegrityError as e:
        await ctx.session.rollback()
        if "uq_feature_flags_key" in str(e) or "unique constraint" in str(e).lower():
            return FeatureFlagError(
                code=FeatureFlagErrorCode.DUPLICATE_KEY,
                message=f"Flag with key '{create_data.key}' already exists",
                field="key",
            )
        logger.exception(f"Error creating feature flag: {e}")
        return FeatureFlagError(
            code=FeatureFlagErrorCode.INTERNAL_ERROR,
            message="Failed to create feature flag",
        )
    except Exception as e:
        logger.exception(f"Error creating feature flag: {e}")
        await ctx.session.rollback()
        return FeatureFlagError(
            code=FeatureFlagErrorCode.INTERNAL_ERROR,
            message="Failed to create feature flag",
        )


async def update_feature_flag_mutation(
    info: Info[GraphQLContext, None],
    id: strawberry.ID,
    input: UpdateFeatureFlagInput,
) -> FeatureFlagPayload:
    """Update an existing feature flag.

    Args:
        info: Strawberry info with context
        id: Flag UUID
        input: Fields to update

    Returns:
        FeatureFlagSuccess with the updated flag, or FeatureFlagError
    """
    ctx = info.context
    repo = get_feature_flag_repository()

    try:
        flag_uuid = UUID(str(id))
    except ValueError:
        return FeatureFlagError(
            code=FeatureFlagErrorCode.VALIDATION_ERROR,
            message="Invalid feature flag ID format",
            field="id",
        )

    # Convert GraphQL input to Pydantic
    try:
        update_data = input.to_pydantic()
    except Exception as e:
        return FeatureFlagError(
            code=FeatureFlagErrorCode.VALIDATION_ERROR,
            message=f"Invalid input: {e!s}",
            field="input",
        )

    try:
        flag = await repo.get(ctx.session, flag_uuid)
        if flag is None:
            return FeatureFlagError(
                code=FeatureFlagErrorCode.NOT_FOUND,
                message=f"Feature flag with ID {id} not found",
            )

        # Update fields (only if provided)
        update_dict = update_data.model_dump(exclude_unset=True)

        if update_dict.get("name"):
            if not update_dict["name"].strip():
                return FeatureFlagError(
                    code=FeatureFlagErrorCode.VALIDATION_ERROR,
                    message="Flag name cannot be empty",
                    field="name",
                )
            flag.name = update_dict["name"].strip()

        if "description" in update_dict:
            flag.description = (
                update_dict["description"].strip() if update_dict["description"] else None
            )

        if update_dict.get("status"):
            flag.status = (
                update_dict["status"].value
                if hasattr(update_dict["status"], "value")
                else update_dict["status"]
            )

        if "enabled" in update_dict:
            flag.enabled = update_dict["enabled"]

        if "percentage" in update_dict:
            flag.percentage = update_dict["percentage"]

        if "targeting_rules" in update_dict:
            flag.targeting_rules = (
                [r.model_dump() for r in update_dict["targeting_rules"]]
                if update_dict["targeting_rules"]
                else None
            )

        if "metadata" in update_dict:
            flag.context_data = update_dict["metadata"]

        if "starts_at" in update_dict:
            flag.starts_at = update_dict["starts_at"]

        if "ends_at" in update_dict:
            flag.ends_at = update_dict["ends_at"]

        await ctx.session.commit()
        await ctx.session.refresh(flag)

        logger.info(f"Updated feature flag: {flag.id} ({flag.key})")

        # Publish event for real-time subscriptions
        await publish_feature_flag_event(
            event_type="UPDATED",
            flag_data=serialize_model_for_event(flag),
        )

        # Convert: SQLAlchemy → Pydantic → GraphQL
        flag_pydantic = FeatureFlagResponse.from_orm(flag)
        return FeatureFlagSuccess(flag=FeatureFlagType.from_pydantic(flag_pydantic))

    except IntegrityError as e:
        await ctx.session.rollback()
        logger.exception(f"Error updating feature flag: {e}")
        return FeatureFlagError(
            code=FeatureFlagErrorCode.INTERNAL_ERROR,
            message="Failed to update feature flag",
        )
    except Exception as e:
        logger.exception(f"Error updating feature flag: {e}")
        await ctx.session.rollback()
        return FeatureFlagError(
            code=FeatureFlagErrorCode.INTERNAL_ERROR,
            message="Failed to update feature flag",
        )


async def toggle_feature_flag_mutation(
    info: Info[GraphQLContext, None],
    id: strawberry.ID,
) -> FeatureFlagPayload:
    """Toggle a feature flag's enabled state.

    Convenience mutation for quickly enabling/disabling a flag.

    Args:
        info: Strawberry info with context
        id: Flag UUID

    Returns:
        FeatureFlagSuccess with the toggled flag, or FeatureFlagError
    """
    ctx = info.context
    repo = get_feature_flag_repository()

    try:
        flag_uuid = UUID(str(id))
    except ValueError:
        return FeatureFlagError(
            code=FeatureFlagErrorCode.VALIDATION_ERROR,
            message="Invalid feature flag ID format",
            field="id",
        )

    try:
        flag = await repo.get(ctx.session, flag_uuid)
        if flag is None:
            return FeatureFlagError(
                code=FeatureFlagErrorCode.NOT_FOUND,
                message=f"Feature flag with ID {id} not found",
            )

        # Capture previous state for event
        previous_enabled = flag.enabled

        # Toggle enabled state
        flag.enabled = not flag.enabled

        await ctx.session.commit()
        await ctx.session.refresh(flag)

        logger.info(f"Toggled feature flag: {flag.id} ({flag.key}) -> {flag.enabled}")

        # Publish event for real-time subscriptions
        flag_data = serialize_model_for_event(flag)
        flag_data["previous_enabled"] = previous_enabled
        await publish_feature_flag_event(
            event_type="TOGGLED",
            flag_data=flag_data,
        )

        # Convert: SQLAlchemy → Pydantic → GraphQL
        flag_pydantic = FeatureFlagResponse.from_orm(flag)
        return FeatureFlagSuccess(flag=FeatureFlagType.from_pydantic(flag_pydantic))

    except Exception as e:
        logger.exception(f"Error toggling feature flag: {e}")
        await ctx.session.rollback()
        return FeatureFlagError(
            code=FeatureFlagErrorCode.INTERNAL_ERROR,
            message="Failed to toggle feature flag",
        )


async def delete_feature_flag_mutation(
    info: Info[GraphQLContext, None],
    id: strawberry.ID,
) -> DeletePayload:
    """Delete a feature flag.

    Also deletes associated overrides.

    Args:
        info: Strawberry info with context
        id: Flag UUID

    Returns:
        DeletePayload indicating success or failure
    """
    ctx = info.context
    repo = get_feature_flag_repository()

    try:
        flag_uuid = UUID(str(id))
    except ValueError:
        return DeletePayload(
            success=False,
            message="Invalid feature flag ID format",
        )

    try:
        flag = await repo.get(ctx.session, flag_uuid)
        if flag is None:
            return DeletePayload(
                success=False,
                message=f"Feature flag with ID {id} not found",
            )

        flag_key = flag.key

        # Capture flag data for event before deletion
        flag_data = serialize_model_for_event(flag)

        # Delete associated overrides first
        from example_service.features.featureflags.repository import (
            get_flag_override_repository,
        )

        override_repo = get_flag_override_repository()
        deleted_overrides = await override_repo.delete_by_flag(ctx.session, flag_key)

        # Delete flag
        await repo.delete(ctx.session, flag)
        await ctx.session.commit()

        logger.info(
            f"Deleted feature flag: {flag_uuid} ({flag_key}), "
            f"removed {deleted_overrides} associated overrides"
        )

        # Publish event for real-time subscriptions
        await publish_feature_flag_event(
            event_type="DELETED",
            flag_data=flag_data,
        )

        return DeletePayload(
            success=True,
            message="Feature flag deleted successfully",
        )

    except Exception as e:
        logger.exception(f"Error deleting feature flag: {e}")
        await ctx.session.rollback()
        return DeletePayload(
            success=False,
            message="Failed to delete feature flag",
        )


__all__ = [
    "create_feature_flag_mutation",
    "delete_feature_flag_mutation",
    "toggle_feature_flag_mutation",
    "update_feature_flag_mutation",
]
