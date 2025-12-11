"""Query resolvers for feature flags.

Provides read operations for feature flags:
- feature_flag(id): Get a single flag by ID
- feature_flags(first, after, ...): List flags with cursor pagination
- feature_flag_by_key(key): Get a flag by its unique key
- evaluate_flag(key, context): Evaluate if a flag is enabled for a context
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from sqlalchemy import select
import strawberry

from example_service.features.featureflags.models import FeatureFlag
from example_service.features.featureflags.schemas import (
    FeatureFlagResponse,
    FlagEvaluationRequest,
)
from example_service.features.featureflags.service import get_feature_flag_service
from example_service.features.graphql.types.base import PageInfoType
from example_service.features.graphql.types.featureflags import (
    FeatureFlagConnection,
    FeatureFlagEdge,
    FeatureFlagType,
    FlagEvaluationInput,
    FlagEvaluationResult,
)

if TYPE_CHECKING:
    from strawberry.types import Info

    from example_service.features.graphql.context import GraphQLContext

logger = logging.getLogger(__name__)

# Type aliases for annotated arguments
FirstArg = Annotated[
    int, strawberry.argument(description="Number of items to return (forward pagination)"),
]
AfterArg = Annotated[
    str | None, strawberry.argument(description="Cursor to start after (forward pagination)"),
]
LastArg = Annotated[
    int | None, strawberry.argument(description="Number of items to return (backward pagination)"),
]
BeforeArg = Annotated[
    str | None, strawberry.argument(description="Cursor to start before (backward pagination)"),
]


async def feature_flag_query(
    info: Info[GraphQLContext, None],
    id: strawberry.ID,
) -> FeatureFlagType | None:
    """Get a single feature flag by ID.

    Uses DataLoader for efficient batching if called multiple times.

    Args:
        info: Strawberry info with context
        id: Flag UUID

    Returns:
        FeatureFlagType if found, None otherwise
    """
    ctx = info.context
    try:
        flag_uuid = UUID(str(id))
    except ValueError:
        return None

    flag = await ctx.loaders.feature_flags.load(flag_uuid)
    if flag is None:
        return None

    # Convert: SQLAlchemy → Pydantic → GraphQL
    flag_pydantic = FeatureFlagResponse.from_orm(flag)
    return FeatureFlagType.from_pydantic(flag_pydantic)


async def feature_flags_query(
    info: Info[GraphQLContext, None],
    first: FirstArg = 50,
    after: AfterArg = None,
    last: LastArg = None,
    before: BeforeArg = None,
) -> FeatureFlagConnection:
    """List feature flags with Relay-style cursor pagination.

    Args:
        info: Strawberry info with context
        first: Items for forward pagination
        after: Cursor for forward pagination
        last: Items for backward pagination
        before: Cursor for backward pagination

    Returns:
        FeatureFlagConnection with edges and page_info
    """
    ctx = info.context
    from example_service.features.featureflags.repository import (
        get_feature_flag_repository,
    )

    repo = get_feature_flag_repository()

    # Build base statement
    stmt = select(FeatureFlag)

    # Use cursor pagination
    connection = await repo.paginate_cursor(
        ctx.session,
        stmt,
        first=first if last is None else None,
        after=after,
        last=last,
        before=before,
        order_by=[
            (FeatureFlag.key, "asc"),
            (FeatureFlag.id, "asc"),
        ],
        include_total=True,
    )

    # Convert to GraphQL types via Pydantic
    edges = [
        FeatureFlagEdge(
            node=FeatureFlagType.from_pydantic(FeatureFlagResponse.from_orm(edge.node)),
            cursor=edge.cursor,
        )
        for edge in connection.edges
    ]

    page_info = PageInfoType(
        has_previous_page=connection.page_info.has_previous_page,
        has_next_page=connection.page_info.has_next_page,
        start_cursor=connection.page_info.start_cursor,
        end_cursor=connection.page_info.end_cursor,
        total_count=connection.page_info.total_count,
    )

    return FeatureFlagConnection(edges=edges, page_info=page_info)


async def feature_flag_by_key_query(
    info: Info[GraphQLContext, None],
    key: str,
) -> FeatureFlagType | None:
    """Get a feature flag by its unique key.

    Uses DataLoader for efficient batching by key.

    Args:
        info: Strawberry info with context
        key: Flag key (e.g., "new_dashboard")

    Returns:
        FeatureFlagType if found, None otherwise
    """
    ctx = info.context

    flag = await ctx.loaders.feature_flags_by_key.load(key)
    if flag is None:
        return None

    # Convert: SQLAlchemy → Pydantic → GraphQL
    flag_pydantic = FeatureFlagResponse.from_orm(flag)
    return FeatureFlagType.from_pydantic(flag_pydantic)


async def evaluate_flag_query(
    info: Info[GraphQLContext, None],
    key: str,
    context: FlagEvaluationInput | None = None,
) -> FlagEvaluationResult:
    """Evaluate whether a feature flag is enabled for a given context.

    This query evaluates a single flag based on:
    - User/tenant overrides
    - Time-based activation windows
    - Percentage-based rollout (consistent hashing)
    - Targeting rules

    Args:
        info: Strawberry info with context
        key: Flag key to evaluate
        context: Optional evaluation context (user_id, tenant_id, attributes)

    Returns:
        FlagEvaluationResult with enabled status and reason
    """
    ctx = info.context

    # Build evaluation request
    eval_context = context if context else FlagEvaluationInput()
    eval_request = FlagEvaluationRequest(
        user_id=eval_context.user_id,
        tenant_id=eval_context.tenant_id,
        attributes=eval_context.attributes,
    )

    # Get service and evaluate
    service = await get_feature_flag_service(ctx.session)
    result = await service.evaluate(
        eval_request,
        flag_keys=[key],
        include_details=True,
    )

    # Extract result for this flag
    if result.details and len(result.details) > 0:
        pydantic_result = result.details[0]
        return FlagEvaluationResult.from_pydantic(pydantic_result)

    # Flag not found or error
    return FlagEvaluationResult(
        key=key,
        enabled=False,
        reason="flag_not_found",
    )


__all__ = [
    "evaluate_flag_query",
    "feature_flag_by_key_query",
    "feature_flag_query",
    "feature_flags_query",
]
