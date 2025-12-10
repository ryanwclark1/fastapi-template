"""REST API endpoints for AI Agent run management.

This module provides endpoints for:
- Listing and filtering runs
- Getting run details and timeline
- Retrying failed runs
- Resuming paused runs
- Cancelling running runs
- Cost and statistics reporting

Endpoints:
    GET  /api/v1/ai/agents/runs           - List runs with filtering
    GET  /api/v1/ai/agents/runs/{id}      - Get run details
    GET  /api/v1/ai/agents/runs/{id}/timeline - Get run timeline
    POST /api/v1/ai/agents/runs/{id}/retry    - Retry failed run
    POST /api/v1/ai/agents/runs/{id}/resume   - Resume paused run
    POST /api/v1/ai/agents/runs/{id}/cancel   - Cancel running run
    GET  /api/v1/ai/agents/stats          - Get run statistics
    GET  /api/v1/ai/agents/costs          - Get cost summary
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from example_service.core.database import get_async_session
from example_service.core.models.user import User
from example_service.features.auth.dependencies import get_current_user
from example_service.infra.ai.agents.run_manager import (
    RunFilter,
    RunManager,
)

router = APIRouter(prefix="/agents", tags=["AI Agents"])


# =============================================================================
# Request/Response Schemas
# =============================================================================


class RunResponse(BaseModel):
    """Response schema for a run."""

    id: UUID
    tenant_id: str
    agent_type: str
    agent_version: str
    run_name: str | None
    status: str
    status_message: str | None

    # Progress
    current_step: int
    total_steps: int | None
    progress_percent: float

    # Cost
    total_cost_usd: float
    total_input_tokens: int
    total_output_tokens: int

    # Timing
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    duration_seconds: float | None

    # Error info
    error_message: str | None
    error_code: str | None

    # Retry info
    retry_count: int
    max_retries: int

    # Tags
    tags: list[str]

    class Config:
        from_attributes = True


class RunDetailResponse(RunResponse):
    """Detailed response including state and output."""

    input_data: dict[str, Any]
    output_data: dict[str, Any] | None
    config: dict[str, Any]
    state: dict[str, Any]
    context: dict[str, Any]
    metadata_json: dict[str, Any]


class RunListResponse(BaseModel):
    """Response for listing runs."""

    runs: list[RunResponse]
    total_count: int
    page: int
    page_size: int
    has_next: bool
    has_prev: bool


class TimelineEventResponse(BaseModel):
    """Response for a timeline event."""

    timestamp: str
    type: str
    details: dict[str, Any]


class StatsResponse(BaseModel):
    """Response for run statistics."""

    total_runs: int
    running: int
    completed: int
    failed: int
    pending: int
    cancelled: int
    paused: int
    average_duration_seconds: float | None
    success_rate: float | None
    average_cost_usd: float


class CostSummaryResponse(BaseModel):
    """Response for cost summary."""

    total_cost_usd: float
    total_runs: int
    successful_runs: int
    failed_runs: int
    total_input_tokens: int
    total_output_tokens: int
    average_cost_per_run: float
    cost_by_agent: dict[str, float]
    cost_by_status: dict[str, float]
    daily_costs: list[dict[str, Any]]


class RetryRequest(BaseModel):
    """Request to retry a run."""

    max_additional_retries: int | None = None


class ResumeRequest(BaseModel):
    """Request to resume a run."""

    checkpoint_id: UUID | None = None
    human_input: dict[str, Any] | None = None


class CancelRequest(BaseModel):
    """Request to cancel a run."""

    reason: str = "User cancelled"


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/runs", response_model=RunListResponse)
async def list_runs(
    agent_type: str | None = Query(None, description="Filter by agent type"),
    status: str | None = Query(None, description="Filter by status"),
    start_date: datetime | None = Query(None, description="Filter by start date"),
    end_date: datetime | None = Query(None, description="Filter by end date"),
    min_cost_usd: float | None = Query(None, description="Minimum cost filter"),
    max_cost_usd: float | None = Query(None, description="Maximum cost filter"),
    has_error: bool | None = Query(None, description="Filter by error presence"),
    search: str | None = Query(None, description="Search query"),
    tags: list[str] | None = Query(None, description="Filter by tags"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    order_by: str = Query("created_at", description="Order by field"),
    order_desc: bool = Query(True, description="Order descending"),
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> RunListResponse:
    """List agent runs with filtering and pagination.

    Supports filtering by:
    - Agent type
    - Status (pending, running, completed, failed, etc.)
    - Date range
    - Cost range
    - Error presence
    - Tags
    - Free text search
    """
    manager = RunManager(session)

    filter_ = RunFilter(
        tenant_id=current_user.tenant_id,
        agent_type=agent_type,
        status=status,
        start_date=start_date,
        end_date=end_date,
        min_cost_usd=min_cost_usd,
        max_cost_usd=max_cost_usd,
        has_error=has_error,
        search_query=search,
        tags=tags,
    )

    result = await manager.list_runs(
        filter_=filter_,
        page=page,
        page_size=page_size,
        order_by=order_by,
        order_desc=order_desc,
    )

    return RunListResponse(
        runs=[_run_to_response(run) for run in result.runs],
        total_count=result.total_count,
        page=result.page,
        page_size=result.page_size,
        has_next=result.has_next,
        has_prev=result.has_prev,
    )


@router.get("/runs/{run_id}", response_model=RunDetailResponse)
async def get_run(
    run_id: UUID,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> RunDetailResponse:
    """Get detailed information about a specific run."""
    manager = RunManager(session)

    run = await manager.get_run(
        run_id,
        include_steps=True,
        include_messages=True,
        include_checkpoints=True,
    )

    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run {run_id} not found",
        )

    # Verify tenant access
    if run.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    return _run_to_detail_response(run)


@router.get("/runs/{run_id}/timeline", response_model=list[TimelineEventResponse])
async def get_run_timeline(
    run_id: UUID,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> list[TimelineEventResponse]:
    """Get timeline of events for a run."""
    manager = RunManager(session)

    # Verify access
    run = await manager.get_run(run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run {run_id} not found",
        )
    if run.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    timeline = await manager.get_run_timeline(run_id)
    return [TimelineEventResponse(**event) for event in timeline]


@router.post("/runs/{run_id}/retry", response_model=RunResponse)
async def retry_run(
    run_id: UUID,
    request: RetryRequest | None = None,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> RunResponse:
    """Retry a failed run.

    Creates a new run with the same input as the original failed run.
    The original run's retry count is incremented.
    """
    manager = RunManager(session)

    # Verify access
    run = await manager.get_run(run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run {run_id} not found",
        )
    if run.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    if run.status not in ("failed", "timeout", "cancelled"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Run is not in a retryable state: {run.status}",
        )

    if run.retry_count >= run.max_retries:
        max_additional = (
            request.max_additional_retries if request else None
        )
        if max_additional is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Run has exceeded retry limit ({run.max_retries})",
            )

    # Note: Actual retry requires agent factory - return updated run info
    run.retry_count += 1
    await session.flush()

    return _run_to_response(run)


@router.post("/runs/{run_id}/resume", response_model=RunResponse)
async def resume_run(
    run_id: UUID,
    request: ResumeRequest | None = None,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> RunResponse:
    """Resume a paused run from checkpoint.

    Resumes execution from the specified checkpoint, or the latest
    valid checkpoint if not specified.
    """
    manager = RunManager(session)

    run = await manager.get_run(run_id, include_checkpoints=True)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run {run_id} not found",
        )
    if run.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    if run.status not in ("paused", "waiting_input"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Run is not in a resumable state: {run.status}",
        )

    # Verify checkpoint if provided
    if request and request.checkpoint_id:
        valid_checkpoints = [c.id for c in run.checkpoints if c.is_valid]
        if request.checkpoint_id not in valid_checkpoints:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid checkpoint: {request.checkpoint_id}",
            )

    # Update status to indicate resumption pending
    run.status = "pending"
    run.paused_at = None
    await session.flush()

    return _run_to_response(run)


@router.post("/runs/{run_id}/cancel", response_model=RunResponse)
async def cancel_run(
    run_id: UUID,
    request: CancelRequest | None = None,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> RunResponse:
    """Cancel a running or pending run."""
    manager = RunManager(session)

    run = await manager.get_run(run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run {run_id} not found",
        )
    if run.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    reason = request.reason if request else "User cancelled"
    success = await manager.cancel_run(run_id, reason)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Run cannot be cancelled: {run.status}",
        )

    # Refresh run
    run = await manager.get_run(run_id)
    return _run_to_response(run)


@router.get("/stats", response_model=StatsResponse)
async def get_stats(
    agent_type: str | None = Query(None, description="Filter by agent type"),
    start_date: datetime | None = Query(None, description="Start date"),
    end_date: datetime | None = Query(None, description="End date"),
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> StatsResponse:
    """Get run statistics for the tenant."""
    manager = RunManager(session)

    stats = await manager.get_stats(
        tenant_id=current_user.tenant_id,
        agent_type=agent_type,
        start_date=start_date,
        end_date=end_date,
    )

    return StatsResponse(
        total_runs=stats.total_runs,
        running=stats.running,
        completed=stats.completed,
        failed=stats.failed,
        pending=stats.pending,
        cancelled=stats.cancelled,
        paused=stats.paused,
        average_duration_seconds=stats.average_duration_seconds,
        success_rate=stats.success_rate,
        average_cost_usd=float(stats.average_cost_usd),
    )


@router.get("/costs", response_model=CostSummaryResponse)
async def get_costs(
    start_date: datetime | None = Query(None, description="Start date"),
    end_date: datetime | None = Query(None, description="End date"),
    include_daily: bool = Query(True, description="Include daily breakdown"),
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> CostSummaryResponse:
    """Get cost summary for the tenant."""
    manager = RunManager(session)

    summary = await manager.get_cost_summary(
        tenant_id=current_user.tenant_id,
        start_date=start_date,
        end_date=end_date,
        group_by_day=include_daily,
    )

    return CostSummaryResponse(
        total_cost_usd=float(summary.total_cost_usd),
        total_runs=summary.total_runs,
        successful_runs=summary.successful_runs,
        failed_runs=summary.failed_runs,
        total_input_tokens=summary.total_input_tokens,
        total_output_tokens=summary.total_output_tokens,
        average_cost_per_run=float(summary.average_cost_per_run),
        cost_by_agent={k: float(v) for k, v in summary.cost_by_agent.items()},
        cost_by_status={k: float(v) for k, v in summary.cost_by_status.items()},
        daily_costs=summary.daily_costs,
    )


@router.get("/recent", response_model=list[RunResponse])
async def get_recent_runs(
    limit: int = Query(10, ge=1, le=50, description="Maximum runs to return"),
    include_children: bool = Query(False, description="Include child runs"),
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> list[RunResponse]:
    """Get recent runs for the tenant."""
    manager = RunManager(session)

    runs = await manager.get_recent_runs(
        tenant_id=current_user.tenant_id,
        limit=limit,
        include_children=include_children,
    )

    return [_run_to_response(run) for run in runs]


# =============================================================================
# Helper Functions
# =============================================================================


def _run_to_response(run: Any) -> RunResponse:
    """Convert database run to response model."""
    return RunResponse(
        id=run.id,
        tenant_id=run.tenant_id,
        agent_type=run.agent_type,
        agent_version=run.agent_version,
        run_name=run.run_name,
        status=run.status,
        status_message=run.status_message,
        current_step=run.current_step,
        total_steps=run.total_steps,
        progress_percent=run.progress_percent,
        total_cost_usd=run.total_cost_usd,
        total_input_tokens=run.total_input_tokens,
        total_output_tokens=run.total_output_tokens,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        duration_seconds=run.duration_seconds,
        error_message=run.error_message,
        error_code=run.error_code,
        retry_count=run.retry_count,
        max_retries=run.max_retries,
        tags=run.tags,
    )


def _run_to_detail_response(run: Any) -> RunDetailResponse:
    """Convert database run to detailed response model."""
    return RunDetailResponse(
        id=run.id,
        tenant_id=run.tenant_id,
        agent_type=run.agent_type,
        agent_version=run.agent_version,
        run_name=run.run_name,
        status=run.status,
        status_message=run.status_message,
        current_step=run.current_step,
        total_steps=run.total_steps,
        progress_percent=run.progress_percent,
        total_cost_usd=run.total_cost_usd,
        total_input_tokens=run.total_input_tokens,
        total_output_tokens=run.total_output_tokens,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        duration_seconds=run.duration_seconds,
        error_message=run.error_message,
        error_code=run.error_code,
        retry_count=run.retry_count,
        max_retries=run.max_retries,
        tags=run.tags,
        input_data=run.input_data,
        output_data=run.output_data,
        config=run.config,
        state=run.state,
        context=run.context,
        metadata_json=run.metadata_json,
    )
