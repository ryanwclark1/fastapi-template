"""Query resolvers for the AI feature.

Provides:
- aiJob: Get a single AI job by ID
- aiJobs: List AI jobs with cursor pagination
- aiUsageLogs: List AI usage logs with pagination
- aiUsageStats: Get aggregated AI usage statistics
- tenantAIConfig: Get tenant AI configuration
- tenantAIFeatures: Get tenant AI feature settings
- estimateAICost: Estimate cost for an AI operation
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from sqlalchemy import func, select
import strawberry

from example_service.features.ai.models import (
    AIJob,
    AIUsageLog,
    TenantAIConfig,
    TenantAIFeature,
)
from example_service.features.graphql.types.ai import (
    AICostEstimateType,
    AIJobConnection,
    AIJobEdge,
    AIJobFilterInput,
    AIJobStatusEnum,
    AIJobType,
    AIJobTypeEnum,
    AIUsageFilterInput,
    AIUsageLogConnection,
    AIUsageLogEdge,
    AIUsageLogType,
    AIUsageStatsType,
    EstimateAICostInput,
    TenantAIConfigType,
    TenantAIFeatureType,
)
from example_service.features.graphql.types.base import PageInfoType

if TYPE_CHECKING:
    from strawberry.types import Info

    from example_service.features.graphql.context import GraphQLContext

logger = logging.getLogger(__name__)

# Type aliases for annotated arguments
FirstArg = Annotated[
    int, strawberry.argument(description="Number of items to return (forward pagination)")
]
AfterArg = Annotated[
    str | None, strawberry.argument(description="Cursor to start after")
]
LastArg = Annotated[
    int | None, strawberry.argument(description="Number of items to return (backward pagination)")
]
BeforeArg = Annotated[
    str | None, strawberry.argument(description="Cursor to start before")
]


@strawberry.field(description="Get a single AI job by ID")
async def ai_job_query(
    info: Info[GraphQLContext, None],
    id: strawberry.ID,
) -> AIJobType | None:
    """Get a single AI job by ID.

    Args:
        info: Strawberry info with context
        id: AI job UUID

    Returns:
        AIJobType if found, None otherwise
    """
    ctx = info.context
    try:
        job_uuid = UUID(str(id))
    except ValueError:
        return None

    stmt = select(AIJob).where(AIJob.id == job_uuid)
    result = await ctx.session.execute(stmt)
    job = result.scalar_one_or_none()

    if job is None:
        return None

    return AIJobType.from_model(job)


@strawberry.field(description="List AI jobs with cursor pagination")
async def ai_jobs_query(
    info: Info[GraphQLContext, None],
    first: FirstArg = 50,
    after: AfterArg = None,
    filter: AIJobFilterInput | None = None,
) -> AIJobConnection:
    """List AI jobs with Relay-style cursor pagination.

    Args:
        info: Strawberry info with context
        first: Items for forward pagination
        after: Cursor for forward pagination
        filter: Optional filters

    Returns:
        AIJobConnection with edges and page_info
    """
    ctx = info.context

    # Build base query
    stmt = select(AIJob)

    # Apply filters
    if filter:
        if filter.status:
            stmt = stmt.where(AIJob.status == filter.status.value)
        if filter.job_type:
            stmt = stmt.where(AIJob.job_type == filter.job_type.value)
        if filter.created_after:
            stmt = stmt.where(AIJob.created_at >= filter.created_after)
        if filter.created_before:
            stmt = stmt.where(AIJob.created_at <= filter.created_before)

    # Order by created_at desc
    stmt = stmt.order_by(AIJob.created_at.desc())

    # Simple offset-based pagination using cursor
    offset = 0
    if after:
        try:
            offset = int(after)
        except ValueError:
            pass

    stmt = stmt.offset(offset).limit(first + 1)

    result = await ctx.session.execute(stmt)
    jobs = list(result.scalars().all())

    has_next = len(jobs) > first
    if has_next:
        jobs = jobs[:first]

    edges = [
        AIJobEdge(
            node=AIJobType.from_model(job),
            cursor=str(offset + i),
        )
        for i, job in enumerate(jobs)
    ]

    page_info = PageInfoType(
        has_previous_page=offset > 0,
        has_next_page=has_next,
        start_cursor=edges[0].cursor if edges else None,
        end_cursor=edges[-1].cursor if edges else None,
    )

    return AIJobConnection(edges=edges, page_info=page_info)


@strawberry.field(description="List AI usage logs with cursor pagination")
async def ai_usage_logs_query(
    info: Info[GraphQLContext, None],
    first: FirstArg = 50,
    after: AfterArg = None,
    filter: AIUsageFilterInput | None = None,
) -> AIUsageLogConnection:
    """List AI usage logs with Relay-style cursor pagination.

    Args:
        info: Strawberry info with context
        first: Items for forward pagination
        after: Cursor for forward pagination
        filter: Optional filters

    Returns:
        AIUsageLogConnection with edges and page_info
    """
    ctx = info.context

    # Build base query
    stmt = select(AIUsageLog)

    # Apply filters
    if filter:
        if filter.provider_name:
            stmt = stmt.where(AIUsageLog.provider_name == filter.provider_name)
        if filter.operation_type:
            stmt = stmt.where(AIUsageLog.operation_type == filter.operation_type)
        if filter.success is not None:
            stmt = stmt.where(AIUsageLog.success == filter.success)
        if filter.created_after:
            stmt = stmt.where(AIUsageLog.created_at >= filter.created_after)
        if filter.created_before:
            stmt = stmt.where(AIUsageLog.created_at <= filter.created_before)

    # Order by created_at desc
    stmt = stmt.order_by(AIUsageLog.created_at.desc())

    # Simple offset-based pagination
    offset = 0
    if after:
        try:
            offset = int(after)
        except ValueError:
            pass

    stmt = stmt.offset(offset).limit(first + 1)

    result = await ctx.session.execute(stmt)
    logs = list(result.scalars().all())

    has_next = len(logs) > first
    if has_next:
        logs = logs[:first]

    edges = [
        AIUsageLogEdge(
            node=AIUsageLogType.from_model(log),
            cursor=str(offset + i),
        )
        for i, log in enumerate(logs)
    ]

    page_info = PageInfoType(
        has_previous_page=offset > 0,
        has_next_page=has_next,
        start_cursor=edges[0].cursor if edges else None,
        end_cursor=edges[-1].cursor if edges else None,
    )

    return AIUsageLogConnection(edges=edges, page_info=page_info)


@strawberry.field(description="Get aggregated AI usage statistics")
async def ai_usage_stats_query(
    info: Info[GraphQLContext, None],
    days: int = 30,
) -> AIUsageStatsType:
    """Get aggregated AI usage statistics for the specified period.

    Args:
        info: Strawberry info with context
        days: Number of days to include in statistics

    Returns:
        AIUsageStatsType with aggregated statistics
    """
    ctx = info.context
    since = datetime.now(UTC) - timedelta(days=days)

    # Get job counts by status
    job_stats = await ctx.session.execute(
        select(
            AIJob.status,
            func.count(AIJob.id).label("count"),
        )
        .where(AIJob.created_at >= since)
        .group_by(AIJob.status)
    )
    job_counts = {row.status: row.count for row in job_stats}

    # Get usage aggregates
    usage_stats = await ctx.session.execute(
        select(
            func.sum(AIUsageLog.cost_usd).label("total_cost"),
            func.sum(AIUsageLog.input_tokens + AIUsageLog.output_tokens).label("total_tokens"),
            func.sum(AIUsageLog.audio_seconds).label("total_audio"),
            func.avg(AIJob.duration_seconds).label("avg_duration"),
        )
        .select_from(AIUsageLog)
        .outerjoin(AIJob, AIUsageLog.job_id == AIJob.id)
        .where(AIUsageLog.created_at >= since)
    )
    usage = usage_stats.first()

    # Get cost by provider
    provider_costs = await ctx.session.execute(
        select(
            AIUsageLog.provider_name,
            func.sum(AIUsageLog.cost_usd).label("cost"),
        )
        .where(AIUsageLog.created_at >= since)
        .group_by(AIUsageLog.provider_name)
    )
    cost_by_provider = {row.provider_name: float(row.cost or 0) for row in provider_costs}

    # Get cost by operation
    operation_costs = await ctx.session.execute(
        select(
            AIUsageLog.operation_type,
            func.sum(AIUsageLog.cost_usd).label("cost"),
        )
        .where(AIUsageLog.created_at >= since)
        .group_by(AIUsageLog.operation_type)
    )
    cost_by_operation = {row.operation_type: float(row.cost or 0) for row in operation_costs}

    total_jobs = sum(job_counts.values())

    return AIUsageStatsType(
        total_jobs=total_jobs,
        completed_jobs=job_counts.get("completed", 0),
        failed_jobs=job_counts.get("failed", 0),
        pending_jobs=job_counts.get("pending", 0) + job_counts.get("processing", 0),
        total_cost_usd=float(usage.total_cost or 0) if usage else 0,
        total_tokens=int(usage.total_tokens or 0) if usage else 0,
        total_audio_seconds=float(usage.total_audio or 0) if usage else 0,
        avg_job_duration_seconds=float(usage.avg_duration) if usage and usage.avg_duration else None,
        cost_by_provider=cost_by_provider,
        cost_by_operation=cost_by_operation,
    )


@strawberry.field(description="Get tenant AI configuration")
async def tenant_ai_config_query(
    info: Info[GraphQLContext, None],
    tenant_id: str,
) -> list[TenantAIConfigType]:
    """Get AI configurations for a tenant.

    Args:
        info: Strawberry info with context
        tenant_id: Tenant identifier

    Returns:
        List of tenant AI configurations
    """
    ctx = info.context

    stmt = select(TenantAIConfig).where(
        TenantAIConfig.tenant_id == tenant_id,
        TenantAIConfig.is_active == True,  # noqa: E712
    )
    result = await ctx.session.execute(stmt)
    configs = result.scalars().all()

    return [TenantAIConfigType.from_model(config) for config in configs]


@strawberry.field(description="Get tenant AI feature settings")
async def tenant_ai_features_query(
    info: Info[GraphQLContext, None],
    tenant_id: str,
) -> TenantAIFeatureType | None:
    """Get AI feature settings for a tenant.

    Args:
        info: Strawberry info with context
        tenant_id: Tenant identifier

    Returns:
        TenantAIFeatureType if found, None otherwise
    """
    ctx = info.context

    stmt = select(TenantAIFeature).where(TenantAIFeature.tenant_id == tenant_id)
    result = await ctx.session.execute(stmt)
    feature = result.scalar_one_or_none()

    if feature is None:
        return None

    return TenantAIFeatureType.from_model(feature)


@strawberry.field(description="Estimate cost for an AI operation")
async def estimate_ai_cost_query(
    info: Info[GraphQLContext, None],
    input: EstimateAICostInput,
) -> AICostEstimateType:
    """Estimate the cost of an AI operation before running it.

    Args:
        info: Strawberry info with context
        input: Cost estimation input

    Returns:
        AICostEstimateType with estimated costs
    """
    # Cost estimates based on typical usage patterns
    # These would be refined based on actual provider pricing
    cost_estimates = {
        AIJobTypeEnum.TRANSCRIPTION: {
            "cost_per_minute": 0.006,  # Deepgram Nova-2
            "provider": "deepgram",
            "model": "nova-2",
        },
        AIJobTypeEnum.SUMMARY: {
            "cost_per_1k_tokens": 0.003,  # GPT-4o-mini
            "provider": "openai",
            "model": "gpt-4o-mini",
        },
        AIJobTypeEnum.SENTIMENT: {
            "cost_per_1k_tokens": 0.001,
            "provider": "openai",
            "model": "gpt-4o-mini",
        },
        AIJobTypeEnum.PII_REDACTION: {
            "cost_per_1k_chars": 0.002,
            "provider": "presidio",
            "model": "default",
        },
        AIJobTypeEnum.COACHING: {
            "cost_per_1k_tokens": 0.01,  # GPT-4
            "provider": "openai",
            "model": "gpt-4",
        },
        AIJobTypeEnum.FULL_ANALYSIS: {
            "cost_per_minute": 0.05,  # Combined estimate
            "provider": "multiple",
            "model": "various",
        },
    }

    estimate_config = cost_estimates.get(
        input.job_type,
        {"cost_per_minute": 0.01, "provider": "unknown", "model": "unknown"},
    )

    # Extract input parameters for estimation
    input_data = input.input_data or {}
    audio_seconds = input_data.get("audio_duration_seconds", 60)
    text_length = input_data.get("text_length", 1000)

    # Calculate estimated cost based on job type
    if input.job_type == AIJobTypeEnum.TRANSCRIPTION:
        estimated_cost = (audio_seconds / 60) * estimate_config.get("cost_per_minute", 0.006)
        estimated_duration = audio_seconds * 0.1  # ~10% of audio duration
        estimated_tokens = None
    elif input.job_type in [AIJobTypeEnum.SUMMARY, AIJobTypeEnum.SENTIMENT, AIJobTypeEnum.COACHING]:
        # Estimate tokens from text length (roughly 4 chars per token)
        estimated_tokens = text_length // 4
        estimated_cost = (estimated_tokens / 1000) * estimate_config.get("cost_per_1k_tokens", 0.003)
        estimated_duration = estimated_tokens * 0.01  # ~10ms per token
    elif input.job_type == AIJobTypeEnum.PII_REDACTION:
        estimated_cost = (text_length / 1000) * estimate_config.get("cost_per_1k_chars", 0.002)
        estimated_duration = text_length * 0.001
        estimated_tokens = None
    else:  # FULL_ANALYSIS
        estimated_cost = (audio_seconds / 60) * estimate_config.get("cost_per_minute", 0.05)
        estimated_duration = audio_seconds * 0.5
        estimated_tokens = text_length // 4

    return AICostEstimateType(
        job_type=input.job_type,
        estimated_cost_usd=round(estimated_cost, 6),
        estimated_tokens=estimated_tokens,
        estimated_duration_seconds=round(estimated_duration, 2) if estimated_duration else None,
        provider=estimate_config.get("provider", "unknown"),
        model=estimate_config.get("model", "unknown"),
        confidence=0.8,  # Moderate confidence in estimates
    )


__all__ = [
    "ai_job_query",
    "ai_jobs_query",
    "ai_usage_logs_query",
    "ai_usage_stats_query",
    "estimate_ai_cost_query",
    "tenant_ai_config_query",
    "tenant_ai_features_query",
]
