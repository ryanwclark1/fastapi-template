"""FastAPI router for pipeline-based AI processing.

This router provides the new capability-based, composable pipeline API.
It integrates with InstrumentedOrchestrator for:
- Pre-execution budget enforcement
- Full OpenTelemetry distributed tracing
- Prometheus metrics collection
- Real-time event streaming via WebSocket

Architecture Overview:
    Client → Router → InstrumentedOrchestrator → SagaCoordinator → PipelineExecutor
                ↓                ↓                       ↓
            Budget Check    Tracing/Metrics      Event Emission → WebSocket
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from decimal import Decimal
import logging
from typing import TYPE_CHECKING, Annotated, Any
from uuid import uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Query,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)

from example_service.features.ai.pipeline.schemas import (
    BudgetExceededError,
    BudgetStatusResponse,
    CapabilityInfoSchema,
    CapabilityListResponse,
    EventCategory,
    EventSchema,
    ExecutionNotFoundError,
    PipelineExecutionRequest,
    PipelineExecutionResponse,
    PipelineInfoSchema,
    PipelineListResponse,
    PipelineNotFoundError,
    PipelineResultResponse,
    PipelineStatus,
    ProgressResponse,
    ProviderInfoSchema,
    ProviderListResponse,
    SetBudgetRequest,
    SpendSummaryResponse,
    StepResultSchema,
    StepStatus,
)
from example_service.infra.ai.capabilities import (
    Capability,
    ProviderType,
    get_capability_registry,
)
from example_service.infra.ai.events import EventType, get_event_store
from example_service.infra.ai.instrumented_orchestrator import (
    InstrumentedOrchestrator,
    get_instrumented_orchestrator,
)
from example_service.infra.ai.observability import (
    BudgetAction,
    BudgetPeriod,
    BudgetPolicy,
    get_budget_service,
)
from example_service.infra.ai.pipelines import get_pipeline, list_pipelines
from example_service.infra.database.session import get_async_session as get_session

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from example_service.infra.ai.pipelines.types import PipelineResult

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai/pipelines", tags=["AI Pipelines"])


# =============================================================================
# Dependencies
# =============================================================================


async def get_current_tenant(
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
) -> str:
    """Extract tenant ID from request header.

    For production, this should integrate with your authentication system.
    Falls back to a default tenant for development/testing.
    """
    if x_tenant_id:
        return x_tenant_id
    # Default for development/testing
    return "default-tenant"


async def get_orchestrator(
    _session: Annotated[AsyncSession, Depends(get_session)],
) -> InstrumentedOrchestrator:
    """Get instrumented orchestrator for pipeline execution."""
    return get_instrumented_orchestrator()


async def validate_tenant_budget(
    tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> str:
    """Validate tenant has remaining budget before expensive operations."""
    budget_service = get_budget_service()
    if budget_service is None:
        return tenant_id

    check = await budget_service.check_budget(tenant_id)
    if check.action == BudgetAction.BLOCKED:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "budget_exceeded",
                "message": check.message,
                "current_spend_usd": str(check.current_spend_usd),
                "limit_usd": str(check.limit_usd) if check.limit_usd else None,
                "period": check.period.value if check.period else None,
            },
        )

    return tenant_id


# =============================================================================
# Pipeline Execution Endpoints
# =============================================================================


@router.post(
    "/execute",
    status_code=status.HTTP_202_ACCEPTED,  # Default for async, will be 200 for sync
    responses={
        402: {"model": BudgetExceededError, "description": "Budget exceeded"},
        404: {"model": PipelineNotFoundError, "description": "Pipeline not found"},
    },
    summary="Execute an AI pipeline",
    description="""
Execute a predefined or custom AI pipeline.

**Available Pipelines:**
- `transcription` - Basic audio transcription
- `transcription_with_redaction` - Transcription with PII redaction
- `call_analysis` - Full call analysis (transcription + summary + sentiment + coaching)
- `dual_channel_analysis` - Dual-channel call analysis
- `pii_detection` - Detect PII in text
- `text_summarization` - Summarize text

**Execution Modes:**
- `async_processing=true` (default): Returns immediately with execution_id
- `async_processing=false`: Waits for completion (use for short pipelines)

**Real-time Updates:**
Connect to the WebSocket endpoint for real-time progress updates:
`/ws/ai/pipelines/{execution_id}/events`
""",
)
async def execute_pipeline(
    request: PipelineExecutionRequest,
    background_tasks: BackgroundTasks,
    tenant_id: Annotated[str, Depends(validate_tenant_budget)],
    orchestrator: Annotated[InstrumentedOrchestrator, Depends(get_orchestrator)],
    response: Response,
) -> PipelineExecutionResponse | PipelineResultResponse:
    """Execute an AI processing pipeline."""
    # Look up the pipeline definition
    pipeline = get_pipeline(request.pipeline_name)
    if pipeline is None:
        # Get available pipelines, handling both dict and PipelineDefinition objects
        pipelines = list_pipelines()
        available = [p.name if hasattr(p, "name") else p.get("name", "unknown") for p in pipelines]
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "pipeline_not_found",
                "message": f"Pipeline '{request.pipeline_name}' not found",
                "requested_pipeline": request.pipeline_name,
                "available_pipelines": available,
            },
        )

    execution_id = f"exec-{uuid4()}"
    created_at = datetime.now(UTC)

    logger.info(
        "Starting pipeline execution",
        extra={
            "execution_id": execution_id,
            "pipeline_name": request.pipeline_name,
            "tenant_id": tenant_id,
            "async": request.async_processing,
        },
    )

    if request.async_processing:
        # Queue for background execution
        background_tasks.add_task(
            _execute_pipeline_background,
            orchestrator=orchestrator,
            pipeline=pipeline,
            input_data=request.input_data,
            options=request.options,
            execution_id=execution_id,
            tenant_id=tenant_id,
            _budget_limit=request.budget_limit_usd,
        )

        return PipelineExecutionResponse(
            execution_id=execution_id,
            pipeline_name=pipeline.name,
            pipeline_version=pipeline.version,
            status=PipelineStatus.PENDING,
            created_at=created_at,
            estimated_duration_seconds=pipeline.estimated_duration_seconds,
            estimated_cost_usd=str(pipeline.estimated_cost_usd)
            if pipeline.estimated_cost_usd
            else None,
            stream_url=f"/ws/ai/pipelines/{execution_id}/events",
        )

    # Execute synchronously
    result = await orchestrator.execute(
        pipeline=pipeline,
        input_data=request.input_data,
        tenant_id=tenant_id,
        budget_limit_usd=request.budget_limit_usd,
    )

    # For sync execution, return result response
    step_results: dict[str, StepResultSchema] = {}
    for step_name, step_data in getattr(result, "step_results", {}).items():
        step_results[step_name] = StepResultSchema(
            step_name=step_name,
            status=StepStatus(step_data.get("status", "completed")),
            provider_used=step_data.get("provider_used"),
            fallbacks_attempted=step_data.get("fallbacks_attempted", []),
            retries=step_data.get("retries", 0),
            duration_ms=step_data.get("duration_ms"),
            cost_usd=str(step_data.get("cost", Decimal(0))),
            error=step_data.get("error"),
            skipped_reason=step_data.get("skipped_reason"),
        )

    # Return result response with 200 status for sync execution
    response.status_code = status.HTTP_200_OK
    return PipelineResultResponse(
        execution_id=result.execution_id,
        pipeline_name=result.pipeline_name,
        pipeline_version=result.pipeline_version,
        status=_map_result_status(result),
        success=result.success,
        output=result.output,
        completed_steps=result.completed_steps,
        failed_step=result.failed_step,
        step_results=step_results,
        total_duration_ms=result.total_duration_ms,
        total_cost_usd=str(result.total_cost_usd),
        started_at=result.started_at,
        completed_at=result.completed_at,
        compensation_performed=result.compensation_performed,
        compensated_steps=result.compensated_steps,
        error=result.error,
    )


async def _execute_pipeline_background(
    orchestrator: InstrumentedOrchestrator,
    pipeline: Any,
    input_data: dict[str, Any],
    options: dict[str, Any],  # noqa: ARG001
    execution_id: str,
    tenant_id: str,
    _budget_limit: Decimal | None,
) -> None:
    """Execute pipeline in background task."""
    try:
        await orchestrator.execute(
            pipeline=pipeline,
            input_data=input_data,
            tenant_id=tenant_id,
            budget_limit_usd=_budget_limit,
        )
    except Exception as e:
        logger.exception(
            "Background pipeline execution failed",
            extra={"execution_id": execution_id, "error": str(e)},
        )


# =============================================================================
# Pipeline Discovery Endpoints (must be before parameterized routes)
# =============================================================================


@router.get(
    "",
    response_model=PipelineListResponse,
    summary="List available pipelines",
    description="Get list of all available predefined pipelines.",
)
async def list_available_pipelines(
    tags: Annotated[
        list[str] | None,
        Query(description="Filter by tags"),
    ] = None,
) -> PipelineListResponse:
    """List all available pipelines."""
    pipelines = list_pipelines()

    # Handle both dict and PipelineDefinition objects (for testing)
    def to_dict(p: Any) -> dict[str, Any]:
        if isinstance(p, dict):
            return p
        # Convert PipelineDefinition to dict
        from example_service.infra.ai.pipelines.types import PipelineDefinition

        if isinstance(p, PipelineDefinition):
            return {
                "name": p.name,
                "version": p.version,
                "description": p.description,
                "tags": p.tags,
                "step_count": len(p.steps),
                "estimated_duration_seconds": p.estimated_duration_seconds,
                "estimated_cost_usd": str(p.estimated_cost_usd) if p.estimated_cost_usd else None,
                "required_capabilities": [
                    step.capability.value for step in p.steps if step.capability
                ],
            }
        # Fallback: convert to dict if possible, otherwise raise
        if hasattr(p, "__dict__"):
            return dict(p.__dict__)
        raise TypeError(f"Unable to convert {type(p)} to dict")

    pipelines = [to_dict(p) for p in pipelines]

    # Filter by tags if specified
    if tags:
        tag_set = set(tags)
        pipelines = [p for p in pipelines if tag_set.intersection(set(p.get("tags", [])))]

    pipeline_schemas = [
        PipelineInfoSchema(
            name=p["name"],
            version=p["version"],
            description=p["description"],
            tags=p["tags"],
            step_count=p["step_count"],
            estimated_duration_seconds=p.get("estimated_duration_seconds"),
            estimated_cost_usd=p.get("estimated_cost_usd"),
            required_capabilities=p.get("required_capabilities", []),
        )
        for p in pipelines
    ]

    return PipelineListResponse(
        pipelines=pipeline_schemas,
        total=len(pipeline_schemas),
    )


@router.get(
    "/capabilities",
    response_model=CapabilityListResponse,
    summary="List available capabilities",
    description="Get list of all available capabilities and their providers.",
)
async def list_capabilities() -> CapabilityListResponse:
    """List all available capabilities."""
    registry = get_capability_registry()

    capability_schemas = []
    for capability in Capability:
        providers = registry.get_providers_for_capability(capability)
        if providers:
            # Get default (highest priority) provider
            default_provider = providers[0].provider_name if providers else None
            # Ensure provider_name is a string (handle MagicMock in tests)
            if default_provider and not isinstance(default_provider, str):
                default_provider = str(default_provider)

            capability_schemas.append(
                CapabilityInfoSchema(
                    capability=capability.value,
                    providers=[
                        str(p.provider_name)
                        if not isinstance(p.provider_name, str)
                        else p.provider_name
                        for p in providers
                    ],
                    default_provider=default_provider,
                )
            )

    return CapabilityListResponse(capabilities=capability_schemas)


@router.get(
    "/providers",
    response_model=ProviderListResponse,
    summary="List registered providers",
    description="Get list of all registered AI providers.",
)
async def list_providers() -> ProviderListResponse:
    """List all registered providers."""
    registry = get_capability_registry()

    providers = registry.get_all_providers()

    provider_schemas = [
        ProviderInfoSchema(
            name=p.provider_name,
            provider_type=p.provider_type.value
            if isinstance(p.provider_type, ProviderType)
            else str(p.provider_type),
            is_available=True,  # Assume available if registered
            capabilities=[cap.capability.value for cap in p.capabilities],
            requires_api_key=p.requires_api_key,
            documentation_url=getattr(p, "documentation_url", None),
        )
        for p in providers
    ]

    return ProviderListResponse(
        providers=provider_schemas,
        total=len(provider_schemas),
    )


@router.get(
    "/{pipeline_name}",
    response_model=PipelineInfoSchema,
    summary="Get pipeline definition",
    description="Get detailed information about a specific pipeline.",
)
async def get_pipeline_info(
    pipeline_name: str,
) -> PipelineInfoSchema:
    """Get detailed information about a specific pipeline."""
    pipeline = get_pipeline(pipeline_name)
    if pipeline is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "pipeline_not_found",
                "message": f"Pipeline '{pipeline_name}' not found",
                "requested_pipeline": pipeline_name,
            },
        )

    return PipelineInfoSchema(
        name=pipeline.name,
        version=pipeline.version,
        description=pipeline.description,
        tags=pipeline.tags,
        step_count=len(pipeline.steps),
        estimated_duration_seconds=pipeline.estimated_duration_seconds,
        estimated_cost_usd=str(pipeline.estimated_cost_usd)
        if pipeline.estimated_cost_usd
        else None,
        required_capabilities=[step.capability.value for step in pipeline.steps if step.capability],
    )


# =============================================================================
# Budget Endpoints (must be before parameterized routes)
# =============================================================================


@router.get(
    "/budget/status",
    response_model=BudgetStatusResponse,
    summary="Get budget status",
    description="Get current budget status for the tenant.",
)
async def get_budget_status(
    tenant_id: Annotated[str, Depends(get_current_tenant)],
    period: Annotated[str, Query(description="Budget period: daily, weekly, monthly")] = "monthly",
) -> BudgetStatusResponse:
    """Get current budget status."""
    budget_service = get_budget_service()
    if budget_service is None:
        return BudgetStatusResponse(
            tenant_id=tenant_id,
            period=period,
            current_spend_usd="0",
            limit_usd=None,
            remaining_usd=None,
            percent_used=None,
            is_exceeded=False,
            policy="warn",
        )

    with contextlib.suppress(ValueError):
        BudgetPeriod(period)

    check = await budget_service.check_budget(tenant_id)

    remaining = None
    percent_used = check.percent_used
    if check.limit_usd is not None and check.limit_usd > 0:
        remaining = max(Decimal(0), check.limit_usd - check.current_spend_usd)

    return BudgetStatusResponse(
        tenant_id=tenant_id,
        period=period,
        current_spend_usd=str(check.current_spend_usd),
        limit_usd=str(check.limit_usd) if check.limit_usd else None,
        remaining_usd=str(remaining) if remaining is not None else None,
        percent_used=percent_used,
        is_exceeded=check.action in (BudgetAction.BLOCKED,),
        policy="warn",  # Default policy
    )


@router.get(
    "/budget/spend",
    response_model=SpendSummaryResponse,
    summary="Get spend summary",
    description="Get detailed spend breakdown for a time period.",
)
async def get_spend_summary(
    tenant_id: Annotated[str, Depends(get_current_tenant)],
    period: Annotated[str, Query(description="Time period: day, week, month")] = "month",
) -> SpendSummaryResponse:
    """Get detailed spend summary."""
    budget_service = get_budget_service()

    now = datetime.now(UTC)

    # Calculate date range based on period
    if period == "day":
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_date = start_date.replace(day=start_date.day - start_date.weekday())
    else:  # month
        start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    if budget_service is None:
        return SpendSummaryResponse(
            tenant_id=tenant_id,
            period=period,
            start_date=start_date,
            end_date=now,
            total_spend_usd="0",
            record_count=0,
            by_pipeline={},
            by_provider={},
            by_capability={},
        )

    # Get spend summary from budget service
    try:
        budget_period_enum = BudgetPeriod(period)
    except ValueError:
        budget_period_enum = BudgetPeriod.MONTHLY

    summary = await budget_service.get_spend_summary(
        tenant_id,
        period=budget_period_enum,
    )

    return SpendSummaryResponse(
        tenant_id=tenant_id,
        period=period,
        start_date=start_date,
        end_date=now,
        total_spend_usd=str(summary.get("total", Decimal(0))),
        record_count=summary.get("record_count", 0),
        by_pipeline={k: str(v) for k, v in summary.get("by_pipeline", {}).items()},
        by_provider={k: str(v) for k, v in summary.get("by_provider", {}).items()},
        by_capability={k: str(v) for k, v in summary.get("by_capability", {}).items()},
    )


@router.post(
    "/budget",
    summary="Set budget limits",
    description="Configure budget limits for the tenant.",
)
async def set_budget(
    request: dict[str, Any],
    tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> dict[str, Any]:
    """Set budget limits for tenant (legacy endpoint)."""
    budget_service = get_budget_service()
    if budget_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Budget service not available",
        )

    limit_usd = Decimal(request.get("limit_usd", "0"))
    period = request.get("period", "daily")

    try:
        budget_period = BudgetPeriod(period)
    except ValueError:
        budget_period = BudgetPeriod.DAILY

    if budget_period == BudgetPeriod.DAILY:
        await budget_service.set_budget(
            tenant_id=tenant_id,
            daily_limit_usd=limit_usd,
            monthly_limit_usd=None,
            warn_threshold_percent=80.0,
            policy=BudgetPolicy.WARN,
        )
    else:
        await budget_service.set_budget(
            tenant_id=tenant_id,
            daily_limit_usd=None,
            monthly_limit_usd=limit_usd,
            warn_threshold_percent=80.0,
            policy=BudgetPolicy.WARN,
        )

    return {
        "success": True,
        "tenant_id": tenant_id,
        "limit_usd": str(limit_usd),
        "period": period,
    }


@router.get(
    "/budget",
    response_model=BudgetStatusResponse,
    summary="Get budget status",
    description="Get current budget status for the tenant.",
)
async def get_budget(
    tenant_id: Annotated[str, Depends(get_current_tenant)],
    period: Annotated[str, Query(description="Budget period: daily, weekly, monthly")] = "monthly",
) -> BudgetStatusResponse:
    """Get current budget status (legacy endpoint)."""
    return await get_budget_status(tenant_id, period)


@router.put(
    "/budget/limits",
    summary="Set budget limits",
    description="Configure budget limits for the tenant.",
)
async def set_budget_limits(
    request: SetBudgetRequest,
    tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> dict[str, Any]:
    """Set budget limits for tenant."""
    budget_service = get_budget_service()
    if budget_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Budget service not available",
        )

    try:
        policy = BudgetPolicy(request.policy)
    except ValueError:
        policy = BudgetPolicy.WARN

    await budget_service.set_budget(
        tenant_id=tenant_id,
        daily_limit_usd=request.daily_limit_usd,
        monthly_limit_usd=request.monthly_limit_usd,
        warn_threshold_percent=request.warn_threshold_percent,
        policy=policy,
    )

    return {
        "success": True,
        "tenant_id": tenant_id,
        "daily_limit_usd": str(request.daily_limit_usd) if request.daily_limit_usd else None,
        "monthly_limit_usd": str(request.monthly_limit_usd) if request.monthly_limit_usd else None,
        "policy": policy.value,
    }


# =============================================================================
# Health Check (must be before parameterized routes)
# =============================================================================


@router.get(
    "/health",
    summary="AI Pipeline health check",
    description="Check health of AI pipeline infrastructure.",
)
async def pipeline_health() -> dict[str, Any]:
    """Check health of AI pipeline infrastructure."""
    registry = get_capability_registry()
    event_store = get_event_store()
    budget_service = get_budget_service()

    # Check provider availability
    provider_count = len(registry.get_all_providers()) if registry else 0
    capability_count = sum(
        1
        for cap in Capability
        if (registry is not None and registry.get_providers_for_capability(cap) is not None)
    )

    return {
        "status": "healthy" if provider_count > 0 else "degraded",
        "providers": {
            "registered": provider_count,
            "capabilities_covered": capability_count,
        },
        "services": {
            "event_store": "available" if event_store else "unavailable",
            "budget_service": "available" if budget_service else "unavailable",
        },
        "pipelines": {
            "predefined_count": len(list_pipelines()),
        },
    }


# =============================================================================
# Execution Status Endpoints (parameterized routes - must come after specific routes)
# =============================================================================


@router.get(
    "/executions/{execution_id}",
    response_model=PipelineResultResponse,
    responses={404: {"model": ExecutionNotFoundError}},
    summary="Get execution result",
    description="Get full result of a completed pipeline execution.",
)
async def get_execution(
    execution_id: str,
    _tenant_id: Annotated[str, Depends(get_current_tenant)],
    orchestrator: Annotated[InstrumentedOrchestrator, Depends(get_orchestrator)],
) -> PipelineResultResponse:
    """Get full result of a completed pipeline execution."""
    result = await orchestrator.get_execution(execution_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "execution_not_found",
                "message": f"Execution '{execution_id}' not found",
                "execution_id": execution_id,
            },
        )

    return PipelineResultResponse(
        execution_id=result.execution_id,
        pipeline_name=result.pipeline_name,
        pipeline_version=result.pipeline_version,
        status=_map_result_status(result),
        success=result.success,
        output=result.output,
        completed_steps=result.completed_steps,
        failed_step=result.failed_step,
        step_results={},
        total_duration_ms=result.total_duration_ms,
        total_cost_usd=str(result.total_cost_usd),
        started_at=result.started_at,
        completed_at=result.completed_at,
        compensation_performed=result.compensation_performed,
        compensated_steps=result.compensated_steps,
        error=result.error,
    )


@router.get(
    "/executions/{execution_id}/progress",
    response_model=ProgressResponse,
    responses={404: {"model": ExecutionNotFoundError}},
    summary="Get execution progress",
    description="Get current progress of a pipeline execution.",
)
async def get_execution_progress(
    execution_id: str,
    _tenant_id: Annotated[str, Depends(get_current_tenant)],
    orchestrator: Annotated[InstrumentedOrchestrator, Depends(get_orchestrator)],
) -> ProgressResponse:
    """Get current progress of a pipeline execution."""
    progress = await orchestrator.get_progress(execution_id)
    if progress is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "execution_not_found",
                "message": f"Execution '{execution_id}' not found",
                "execution_id": execution_id,
            },
        )

    # Map progress dict to ProgressResponse
    status_str = progress.get("status", "running")
    try:
        pipeline_status = PipelineStatus(status_str)
    except ValueError:
        pipeline_status = PipelineStatus.RUNNING

    completed_steps_list = progress.get("completed_steps", [])
    total_steps = progress.get("total_steps", 1)
    current_step = progress.get("current_step")

    return ProgressResponse(
        execution_id=execution_id,
        status=pipeline_status,
        progress_percent=progress.get("progress_percent", 0),
        message=f"Processing step {len(completed_steps_list) + 1} of {total_steps}"
        if current_step
        else "Processing",
        current_step=current_step,
        steps_completed=len(completed_steps_list),
        total_steps=total_steps,
        estimated_remaining_seconds=progress.get("estimated_remaining_seconds"),
        current_cost_usd=progress.get("current_cost_usd", "0"),
    )


@router.get(
    "/{execution_id}",
    response_model=ProgressResponse,
    responses={404: {"model": ExecutionNotFoundError}},
    summary="Get execution progress",
    description="Get current progress of a pipeline execution.",
)
async def get_execution_progress_legacy(
    execution_id: str,
    _tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> ProgressResponse:
    """Get current progress of a pipeline execution (legacy endpoint)."""
    event_store = get_event_store()
    if event_store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Event store not available",
        )

    # Get events for this execution
    events = await event_store.get_events(
        execution_id=execution_id,
        event_types=[
            EventType.WORKFLOW_STARTED,
            EventType.STEP_STARTED,
            EventType.STEP_COMPLETED,
            EventType.PROGRESS_UPDATE,
            EventType.WORKFLOW_COMPLETED,
            EventType.WORKFLOW_FAILED,
        ],
    )

    if not events:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "execution_not_found",
                "message": f"Execution '{execution_id}' not found",
                "execution_id": execution_id,
            },
        )

    # Reconstruct state from events
    state = await event_store.get_workflow_state(execution_id)

    # Calculate progress
    total_steps = state.get("total_steps", 1) if state else 1
    completed_steps = len(state.get("completed_steps", [])) if state else 0
    progress_percent = (completed_steps / total_steps) * 100 if total_steps > 0 else 0

    # Determine status
    status_str = state.get("status", "pending") if state else "pending"
    try:
        pipeline_status = PipelineStatus(status_str)
    except ValueError:
        pipeline_status = PipelineStatus.RUNNING

    # Get current step from most recent step event
    current_step = state.get("current_step") if state else None

    return ProgressResponse(
        execution_id=execution_id,
        status=pipeline_status,
        progress_percent=min(progress_percent, 100),
        message=state.get("message", f"Processing step {completed_steps + 1} of {total_steps}")
        if state
        else f"Processing step {completed_steps + 1} of {total_steps}",
        current_step=current_step,
        steps_completed=completed_steps,
        total_steps=total_steps,
        estimated_remaining_seconds=state.get("estimated_remaining_seconds") if state else None,
        current_cost_usd=str(state.get("total_cost", Decimal(0))) if state else "0",
    )


@router.get(
    "/{execution_id}/result",
    response_model=PipelineResultResponse,
    responses={404: {"model": ExecutionNotFoundError}},
    summary="Get execution result",
    description="Get full result of a completed pipeline execution.",
)
async def get_execution_result(
    execution_id: str,
    _tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> PipelineResultResponse:
    """Get full result of a completed pipeline execution."""
    event_store = get_event_store()
    if event_store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Event store not available",
        )

    # Reconstruct full state from events
    state = await event_store.get_workflow_state(execution_id)

    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "execution_not_found",
                "message": f"Execution '{execution_id}' not found",
                "execution_id": execution_id,
            },
        )

    # Check if execution is complete
    status_str = state.get("status", "pending")
    if status_str not in ("completed", "failed", "cancelled"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "execution_not_complete",
                "message": f"Execution is still {status_str}",
                "status": status_str,
            },
        )

    # Build step results
    step_results: dict[str, StepResultSchema] = {}
    for step_name, step_data in state.get("step_results", {}).items():
        step_results[step_name] = StepResultSchema(
            step_name=step_name,
            status=StepStatus(step_data.get("status", "completed")),
            provider_used=step_data.get("provider_used"),
            fallbacks_attempted=step_data.get("fallbacks_attempted", []),
            retries=step_data.get("retries", 0),
            duration_ms=step_data.get("duration_ms"),
            cost_usd=str(step_data.get("cost", Decimal(0))),
            error=step_data.get("error"),
            skipped_reason=step_data.get("skipped_reason"),
        )

    try:
        pipeline_status = PipelineStatus(status_str)
    except ValueError:
        pipeline_status = PipelineStatus.COMPLETED

    return PipelineResultResponse(
        execution_id=execution_id,
        pipeline_name=state.get("pipeline_name", "unknown"),
        pipeline_version=state.get("pipeline_version", "1.0.0"),
        status=pipeline_status,
        success=status_str == "completed",
        output=state.get("output", {}),
        completed_steps=state.get("completed_steps", []),
        failed_step=state.get("failed_step"),
        step_results=step_results,
        total_duration_ms=state.get("total_duration_ms", 0),
        total_cost_usd=str(state.get("total_cost", Decimal(0))),
        started_at=state.get("started_at"),
        completed_at=state.get("completed_at"),
        compensation_performed=state.get("compensation_performed", False),
        compensated_steps=state.get("compensated_steps", []),
        error=state.get("error"),
    )


@router.delete(
    "/{execution_id}",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Cancel execution",
    description="Request cancellation of a running pipeline execution.",
)
async def cancel_execution(
    execution_id: str,
    tenant_id: Annotated[str, Depends(get_current_tenant)],
    orchestrator: Annotated[InstrumentedOrchestrator, Depends(get_orchestrator)],
) -> dict[str, Any]:
    """Request cancellation of a running pipeline execution.

    Note: Pipeline cancellation is not yet fully implemented. This endpoint
    accepts cancellation requests and logs them, but active pipeline executions
    will continue to completion. Full cancellation support will be added in a
    future release.
    """
    logger.info(
        "Cancellation requested",
        extra={"execution_id": execution_id, "tenant_id": tenant_id},
    )

    # Check if execution exists
    state = await orchestrator.get_workflow_state(execution_id)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "execution_not_found",
                "message": f"Execution '{execution_id}' not found",
                "execution_id": execution_id,
            },
        )

    return {
        "execution_id": execution_id,
        "cancellation_requested": True,
        "message": "Cancellation request logged. Note: Full cancellation support is not yet implemented.",
        "status": "pending",
        "note": "Active pipeline executions will continue to completion. Full cancellation support coming soon.",
    }


# =============================================================================
# WebSocket Event Streaming
# =============================================================================


@router.websocket("/{execution_id}/events")
async def stream_execution_events(
    websocket: WebSocket,
    execution_id: str,
    categories: Annotated[
        str | None,
        Query(description="Comma-separated event categories to filter"),
    ] = None,
) -> None:
    """Stream real-time events for a pipeline execution.

    Connect to receive live updates as the pipeline executes.
    Events include: step progress, cost updates, errors, completion.

    Query Parameters:
        categories: Filter by category (workflow, step, progress, cost, compensation)

    Message Format:
        {"event_id": "...", "event_type": "step_completed", "data": {...}, ...}

    Close Codes:
        1000: Normal completion (pipeline finished)
        1001: Going away (client disconnected)
        1011: Internal error
    """
    await websocket.accept()

    event_store = get_event_store()
    if event_store is None:
        await websocket.close(
            code=status.WS_1011_INTERNAL_ERROR,
            reason="Event store not available",
        )
        return

    # Parse category filter
    category_filter: set[EventCategory] | None = None
    if categories:
        with contextlib.suppress(ValueError):
            category_filter = {EventCategory(c.strip()) for c in categories.split(",") if c.strip()}

    # Map event types to categories
    def event_matches_filter(event: Any) -> bool:
        if category_filter is None:
            return True

        event_type = event.event_type if hasattr(event, "event_type") else event.get("event_type")

        # Categorize event types
        if event_type in (
            EventType.WORKFLOW_STARTED,
            EventType.WORKFLOW_COMPLETED,
            EventType.WORKFLOW_FAILED,
            EventType.WORKFLOW_CANCELLED,
        ):
            return EventCategory.WORKFLOW in category_filter
        if event_type in (
            EventType.STEP_STARTED,
            EventType.STEP_COMPLETED,
            EventType.STEP_FAILED,
            EventType.STEP_SKIPPED,
            EventType.STEP_RETRYING,
        ):
            return EventCategory.STEP in category_filter
        if event_type in (EventType.PROGRESS_UPDATE,):
            return EventCategory.PROGRESS in category_filter
        if event_type in (EventType.COST_INCURRED,):
            return EventCategory.COST in category_filter
        if event_type in (
            EventType.COMPENSATION_STARTED,
            EventType.COMPENSATION_STEP,
            EventType.COMPENSATION_COMPLETED,
            EventType.COMPENSATION_FAILED,
        ):
            return EventCategory.COMPENSATION in category_filter

        return True

    logger.info(
        "WebSocket event stream connected",
        extra={"execution_id": execution_id, "categories": categories},
    )

    try:
        # Send historical events first
        historical = await event_store.get_events(execution_id=execution_id)
        for event in historical:
            if event_matches_filter(event):
                schema = _event_to_schema(event)
                await websocket.send_json(schema.model_dump(mode="json"))

        # Check if workflow already completed
        state = await event_store.get_workflow_state(execution_id)
        if state and state.get("status") in ("completed", "failed", "cancelled"):
            await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)
            return

        # Subscribe to live events
        async for event in event_store.subscribe(execution_id=execution_id):  # type: ignore[attr-defined]
            if event_matches_filter(event):
                schema = _event_to_schema(event)
                await websocket.send_json(schema.model_dump(mode="json"))

                # Close on terminal events
                event_type = (
                    event.event_type if hasattr(event, "event_type") else event.get("event_type")
                )
                if event_type in (
                    EventType.WORKFLOW_COMPLETED,
                    EventType.WORKFLOW_FAILED,
                    EventType.WORKFLOW_CANCELLED,
                ):
                    await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)
                    return

    except WebSocketDisconnect:
        logger.debug(
            "WebSocket event stream disconnected",
            extra={"execution_id": execution_id},
        )
    except Exception as e:
        logger.exception(
            "WebSocket event stream error",
            extra={"execution_id": execution_id, "error": str(e)},
        )
        await websocket.close(
            code=status.WS_1011_INTERNAL_ERROR,
            reason=str(e)[:100],
        )


def _event_to_schema(event: Any) -> EventSchema:
    """Convert internal event to API schema."""
    if hasattr(event, "model_dump"):
        data = event.model_dump()
    elif isinstance(event, dict):
        data = event
    else:
        data = vars(event)

    event_type = data.get("event_type", "unknown")
    if hasattr(event_type, "value"):
        event_type = event_type.value

    # Determine category
    category = EventCategory.WORKFLOW
    if "step" in str(event_type).lower():
        category = EventCategory.STEP
    elif "progress" in str(event_type).lower():
        category = EventCategory.PROGRESS
    elif "cost" in str(event_type).lower():
        category = EventCategory.COST
    elif "compensation" in str(event_type).lower():
        category = EventCategory.COMPENSATION

    return EventSchema(
        event_id=str(data.get("event_id", uuid4())),
        event_type=event_type,
        execution_id=data.get("execution_id", data.get("workflow_id", "")),
        timestamp=data.get("timestamp", datetime.now(UTC)),
        category=category,
        data={
            k: v
            for k, v in data.items()
            if k not in ("event_id", "event_type", "execution_id", "workflow_id", "timestamp")
        },
    )


def _map_result_status(result: PipelineResult) -> PipelineStatus:
    """Map pipeline result to API status."""
    if result.success:
        return PipelineStatus.COMPLETED
    if result.failed_step:
        return PipelineStatus.FAILED
    return PipelineStatus.FAILED
