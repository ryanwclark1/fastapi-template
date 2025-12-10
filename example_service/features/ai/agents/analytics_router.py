"""REST API endpoints for AI Agent analytics.

This module provides endpoints for:
- Usage metrics and statistics
- Cost analysis and reporting
- Agent performance metrics
- Usage reports generation

Endpoints:
    GET  /api/v1/ai/analytics/usage          - Get usage metrics
    GET  /api/v1/ai/analytics/agents/{type}  - Get agent-specific metrics
    GET  /api/v1/ai/analytics/costs          - Get cost analysis
    GET  /api/v1/ai/analytics/report         - Generate usage report
    GET  /api/v1/ai/analytics/trends         - Get usage trends
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from example_service.core.database import get_async_session
from example_service.core.models.user import User
from example_service.features.auth.dependencies import get_current_user
from example_service.infra.ai.agents.analytics import (
    AgentAnalytics,
    AgentMetrics,
    UsageMetrics,
)

router = APIRouter(prefix="/analytics", tags=["AI Analytics"])


# =============================================================================
# Response Schemas
# =============================================================================


class UsageMetricsResponse(BaseModel):
    """Response for usage metrics."""

    period_start: datetime
    period_end: datetime

    total_runs: int
    successful_runs: int
    failed_runs: int
    cancelled_runs: int
    timed_out_runs: int

    total_input_tokens: int
    total_output_tokens: int
    average_tokens_per_run: float

    total_cost_usd: float
    average_cost_per_run: float

    average_duration_seconds: float | None
    median_duration_seconds: float | None
    p95_duration_seconds: float | None
    p99_duration_seconds: float | None

    success_rate: float | None
    error_rate: float | None


class AgentMetricsResponse(BaseModel):
    """Response for agent-specific metrics."""

    agent_type: str
    agent_version: str | None

    total_runs: int
    unique_tenants: int
    unique_users: int

    average_duration_seconds: float | None
    average_iterations: float | None
    average_tool_calls: float | None

    total_cost_usd: float
    cost_per_run: float
    cost_per_1k_tokens: float

    success_rate: float | None
    retry_rate: float | None
    timeout_rate: float | None

    top_errors: list[dict[str, Any]]


class CostAnalysisResponse(BaseModel):
    """Response for cost analysis."""

    tenant_id: str
    period_start: datetime
    period_end: datetime

    total_cost_usd: float
    total_runs: int
    total_tokens: int

    cost_by_agent: dict[str, float]
    cost_by_model: dict[str, float]
    cost_by_day: list[dict[str, Any]]

    daily_average: float
    daily_trend: float | None
    projected_monthly: float

    cost_per_successful_run: float
    wasted_cost: float


class UsageReportResponse(BaseModel):
    """Response for usage report."""

    tenant_id: str
    report_period: str
    generated_at: datetime

    summary: UsageMetricsResponse | None
    metrics_by_agent: list[AgentMetricsResponse]
    cost_analysis: CostAnalysisResponse | None
    recommendations: list[str]


class TrendDataPoint(BaseModel):
    """A single data point in a trend series."""

    timestamp: datetime
    value: float
    label: str | None = None


class TrendsResponse(BaseModel):
    """Response for usage trends."""

    period_start: datetime
    period_end: datetime
    granularity: str  # hourly, daily, weekly

    runs_trend: list[TrendDataPoint]
    cost_trend: list[TrendDataPoint]
    success_rate_trend: list[TrendDataPoint]
    token_usage_trend: list[TrendDataPoint]


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/usage", response_model=UsageMetricsResponse)
async def get_usage_metrics(
    start_date: datetime | None = Query(
        None,
        description="Start date (defaults to 30 days ago)",
    ),
    end_date: datetime | None = Query(
        None,
        description="End date (defaults to now)",
    ),
    agent_type: str | None = Query(None, description="Filter by agent type"),
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> UsageMetricsResponse:
    """Get usage metrics for a time period.

    Provides aggregate statistics including:
    - Run counts by status
    - Token usage
    - Cost metrics
    - Duration percentiles
    - Success/error rates
    """
    now = datetime.now(UTC)
    start = start_date or (now - timedelta(days=30))
    end = end_date or now

    analytics = AgentAnalytics(session)

    metrics = await analytics.get_usage_metrics(
        tenant_id=str(current_user.tenant_id),
        start_date=start,
        end_date=end,
        agent_type=agent_type,
    )

    return _metrics_to_response(metrics)


@router.get("/agents", response_model=list[AgentMetricsResponse])
async def list_agent_metrics(
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> list[AgentMetricsResponse]:
    """Get metrics for all agent types used by the tenant."""
    from sqlalchemy import func, select

    from example_service.infra.ai.agents.models import AIAgentRun

    now = datetime.now(UTC)
    start = start_date or (now - timedelta(days=30))
    end = end_date or now

    # Get distinct agent types
    query = (
        select(func.distinct(AIAgentRun.agent_type))
        .where(
            AIAgentRun.tenant_id == current_user.tenant_id,
            AIAgentRun.created_at >= start,
            AIAgentRun.created_at <= end,
        )
    )
    result = await session.execute(query)
    agent_types = [r[0] for r in result.all()]

    analytics = AgentAnalytics(session)
    metrics_list = []

    for agent_type in agent_types:
        metrics = await analytics.get_agent_metrics(
            tenant_id=str(current_user.tenant_id),
            agent_type=agent_type,
            start_date=start,
            end_date=end,
        )
        metrics_list.append(_agent_metrics_to_response(metrics))

    return metrics_list


@router.get("/agents/{agent_type}", response_model=AgentMetricsResponse)
async def get_agent_metrics(
    agent_type: str,
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> AgentMetricsResponse:
    """Get detailed metrics for a specific agent type.

    Includes:
    - Usage statistics
    - Performance metrics
    - Cost breakdown
    - Reliability metrics
    - Top errors
    """
    now = datetime.now(UTC)
    start = start_date or (now - timedelta(days=30))
    end = end_date or now

    analytics = AgentAnalytics(session)

    metrics = await analytics.get_agent_metrics(
        tenant_id=str(current_user.tenant_id),
        agent_type=agent_type,
        start_date=start,
        end_date=end,
    )

    return _agent_metrics_to_response(metrics)


@router.get("/costs", response_model=CostAnalysisResponse)
async def get_cost_analysis(
    start_date: datetime | None = Query(
        None,
        description="Start date (defaults to 30 days ago)",
    ),
    end_date: datetime | None = Query(
        None,
        description="End date (defaults to now)",
    ),
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> CostAnalysisResponse:
    """Get detailed cost analysis.

    Provides:
    - Total costs and breakdowns
    - Cost by agent type
    - Daily cost trends
    - Projections
    - Wasted cost (failed runs)
    """
    now = datetime.now(UTC)
    start = start_date or (now - timedelta(days=30))
    end = end_date or now

    analytics = AgentAnalytics(session)

    analysis = await analytics.get_cost_analysis(
        tenant_id=str(current_user.tenant_id),
        start_date=start,
        end_date=end,
    )

    return CostAnalysisResponse(
        tenant_id=analysis.tenant_id,
        period_start=analysis.period_start,
        period_end=analysis.period_end,
        total_cost_usd=float(analysis.total_cost_usd),
        total_runs=analysis.total_runs,
        total_tokens=analysis.total_tokens,
        cost_by_agent={k: float(v) for k, v in analysis.cost_by_agent.items()},
        cost_by_model={k: float(v) for k, v in analysis.cost_by_model.items()},
        cost_by_day=analysis.cost_by_day,
        daily_average=float(analysis.daily_average),
        daily_trend=analysis.daily_trend,
        projected_monthly=float(analysis.projected_monthly),
        cost_per_successful_run=float(analysis.cost_per_successful_run),
        wasted_cost=float(analysis.wasted_cost),
    )


@router.get("/report", response_model=UsageReportResponse)
async def get_usage_report(
    start_date: datetime | None = Query(
        None,
        description="Report start date (defaults to 30 days ago)",
    ),
    end_date: datetime | None = Query(
        None,
        description="Report end date (defaults to now)",
    ),
    include_recommendations: bool = Query(
        True,
        description="Include optimization recommendations",
    ),
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> UsageReportResponse:
    """Generate comprehensive usage report.

    Includes:
    - Summary metrics
    - Per-agent breakdown
    - Cost analysis
    - Optimization recommendations
    """
    now = datetime.now(UTC)
    start = start_date or (now - timedelta(days=30))
    end = end_date or now

    analytics = AgentAnalytics(session)

    report = await analytics.get_usage_report(
        tenant_id=str(current_user.tenant_id),
        start_date=start,
        end_date=end,
        include_recommendations=include_recommendations,
    )

    return UsageReportResponse(
        tenant_id=report.tenant_id,
        report_period=report.report_period,
        generated_at=report.generated_at,
        summary=_metrics_to_response(report.summary) if report.summary else None,
        metrics_by_agent=[
            _agent_metrics_to_response(m) for m in report.metrics_by_agent
        ],
        cost_analysis=(
            CostAnalysisResponse(
                tenant_id=report.cost_analysis.tenant_id,
                period_start=report.cost_analysis.period_start,
                period_end=report.cost_analysis.period_end,
                total_cost_usd=float(report.cost_analysis.total_cost_usd),
                total_runs=report.cost_analysis.total_runs,
                total_tokens=report.cost_analysis.total_tokens,
                cost_by_agent={
                    k: float(v) for k, v in report.cost_analysis.cost_by_agent.items()
                },
                cost_by_model={
                    k: float(v) for k, v in report.cost_analysis.cost_by_model.items()
                },
                cost_by_day=report.cost_analysis.cost_by_day,
                daily_average=float(report.cost_analysis.daily_average),
                daily_trend=report.cost_analysis.daily_trend,
                projected_monthly=float(report.cost_analysis.projected_monthly),
                cost_per_successful_run=float(
                    report.cost_analysis.cost_per_successful_run
                ),
                wasted_cost=float(report.cost_analysis.wasted_cost),
            )
            if report.cost_analysis
            else None
        ),
        recommendations=report.recommendations,
    )


@router.get("/trends", response_model=TrendsResponse)
async def get_usage_trends(
    start_date: datetime | None = Query(
        None,
        description="Start date (defaults to 30 days ago)",
    ),
    end_date: datetime | None = Query(
        None,
        description="End date (defaults to now)",
    ),
    granularity: str = Query(
        "daily",
        regex="^(hourly|daily|weekly)$",
        description="Time granularity",
    ),
    agent_type: str | None = Query(None, description="Filter by agent type"),
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> TrendsResponse:
    """Get usage trends over time.

    Returns time series data for:
    - Run counts
    - Costs
    - Success rates
    - Token usage
    """
    from sqlalchemy import and_, case, func, select

    from example_service.infra.ai.agents.models import AIAgentRun

    now = datetime.now(UTC)
    start = start_date or (now - timedelta(days=30))
    end = end_date or now

    # Determine date truncation based on granularity
    if granularity == "hourly":
        date_trunc = func.date_trunc("hour", AIAgentRun.created_at)
    elif granularity == "weekly":
        date_trunc = func.date_trunc("week", AIAgentRun.created_at)
    else:
        date_trunc = func.date_trunc("day", AIAgentRun.created_at)

    # Build query conditions
    conditions = [
        AIAgentRun.tenant_id == current_user.tenant_id,
        AIAgentRun.created_at >= start,
        AIAgentRun.created_at <= end,
    ]
    if agent_type:
        conditions.append(AIAgentRun.agent_type == agent_type)

    # Query for trends
    query = (
        select(
            date_trunc.label("period"),
            func.count(AIAgentRun.id).label("total_runs"),
            func.sum(AIAgentRun.total_cost_usd).label("total_cost"),
            func.sum(
                case((AIAgentRun.status == "completed", 1), else_=0)
            ).label("successful_runs"),
            func.sum(
                AIAgentRun.total_input_tokens + AIAgentRun.total_output_tokens
            ).label("total_tokens"),
        )
        .where(and_(*conditions))
        .group_by(date_trunc)
        .order_by(date_trunc)
    )

    result = await session.execute(query)
    rows = result.all()

    runs_trend = []
    cost_trend = []
    success_rate_trend = []
    token_usage_trend = []

    for row in rows:
        timestamp = row.period
        total_runs = row.total_runs or 0
        total_cost = float(row.total_cost or 0)
        successful_runs = row.successful_runs or 0
        total_tokens = row.total_tokens or 0

        runs_trend.append(TrendDataPoint(timestamp=timestamp, value=total_runs))
        cost_trend.append(TrendDataPoint(timestamp=timestamp, value=total_cost))
        success_rate_trend.append(
            TrendDataPoint(
                timestamp=timestamp,
                value=(successful_runs / total_runs * 100) if total_runs > 0 else 0,
            )
        )
        token_usage_trend.append(
            TrendDataPoint(timestamp=timestamp, value=total_tokens)
        )

    return TrendsResponse(
        period_start=start,
        period_end=end,
        granularity=granularity,
        runs_trend=runs_trend,
        cost_trend=cost_trend,
        success_rate_trend=success_rate_trend,
        token_usage_trend=token_usage_trend,
    )


# =============================================================================
# Helper Functions
# =============================================================================


def _metrics_to_response(metrics: UsageMetrics) -> UsageMetricsResponse:
    """Convert usage metrics to response model."""
    return UsageMetricsResponse(
        period_start=metrics.period_start,
        period_end=metrics.period_end,
        total_runs=metrics.total_runs,
        successful_runs=metrics.successful_runs,
        failed_runs=metrics.failed_runs,
        cancelled_runs=metrics.cancelled_runs,
        timed_out_runs=metrics.timed_out_runs,
        total_input_tokens=metrics.total_input_tokens,
        total_output_tokens=metrics.total_output_tokens,
        average_tokens_per_run=metrics.average_tokens_per_run,
        total_cost_usd=float(metrics.total_cost_usd),
        average_cost_per_run=float(metrics.average_cost_per_run),
        average_duration_seconds=metrics.average_duration_seconds,
        median_duration_seconds=metrics.median_duration_seconds,
        p95_duration_seconds=metrics.p95_duration_seconds,
        p99_duration_seconds=metrics.p99_duration_seconds,
        success_rate=metrics.success_rate,
        error_rate=metrics.error_rate,
    )


def _agent_metrics_to_response(metrics: AgentMetrics) -> AgentMetricsResponse:
    """Convert agent metrics to response model."""
    return AgentMetricsResponse(
        agent_type=metrics.agent_type,
        agent_version=metrics.agent_version,
        total_runs=metrics.total_runs,
        unique_tenants=metrics.unique_tenants,
        unique_users=metrics.unique_users,
        average_duration_seconds=metrics.average_duration_seconds,
        average_iterations=metrics.average_iterations,
        average_tool_calls=metrics.average_tool_calls,
        total_cost_usd=float(metrics.total_cost_usd),
        cost_per_run=float(metrics.cost_per_run),
        cost_per_1k_tokens=float(metrics.cost_per_1k_tokens),
        success_rate=metrics.success_rate,
        retry_rate=metrics.retry_rate,
        timeout_rate=metrics.timeout_rate,
        top_errors=metrics.top_errors,
    )
