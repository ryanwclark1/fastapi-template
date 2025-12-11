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
import re
from typing import TYPE_CHECKING, Annotated, Any

try:
    from unittest.mock import MagicMock
except ImportError:  # pragma: no cover - unittest.mock always available, but guard just in case
    MagicMock = ()  # type: ignore[assignment]

from uuid import uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Path,
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
    CostEstimateRequest,
    CostEstimateResponse,
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
    RateLimitExceededError,
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
from example_service.infra.cache import get_cache
from example_service.infra.database.session import get_async_session as get_session
from example_service.infra.ratelimit.limiter import RateLimiter

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from example_service.infra.ai.pipelines.types import PipelineResult


def _is_magic_mock(value: Any) -> bool:
    """Best-effort detection for MagicMock instances."""
    if isinstance(MagicMock, tuple) and not MagicMock:  # guard when fallback tuple()
        return False
    return isinstance(value, MagicMock)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai/pipelines", tags=["AI Pipelines"])

EXECUTION_ID_PATTERN = r"exec-[A-Za-z0-9][A-Za-z0-9_-]*"
EXECUTION_ID_PARAM_PATTERN = r"[A-Za-z0-9][A-Za-z0-9_-]*"
ExecutionIdParam = Annotated[
    str,
    Path(
        description="Pipeline execution identifier (e.g., exec-12345).",
        pattern=EXECUTION_ID_PARAM_PATTERN,
    ),
]


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


async def get_ai_rate_limiter() -> RateLimiter | None:
    """Get rate limiter for AI pipelines.

    Returns None if rate limiting is disabled or Redis is unavailable.
    """
    from example_service.core.settings import get_settings

    settings = get_settings()
    ai_settings = getattr(settings, "ai", None)

    # Check if rate limiting is enabled
    if ai_settings and not getattr(ai_settings, "enable_rate_limiting", True):
        return None

    try:
        async with get_cache() as cache:
            redis_client: Redis = cache.get_client()
            return RateLimiter(
                redis_client,
                key_prefix="ai_pipeline_ratelimit",
                default_limit=getattr(ai_settings, "rate_limit_requests_per_minute", 60)
                if ai_settings
                else 60,
                default_window=getattr(ai_settings, "rate_limit_window_seconds", 60)
                if ai_settings
                else 60,
            )
    except Exception as e:
        logger.warning(f"Failed to initialize AI rate limiter: {e}")
        return None


async def check_rate_limit(
    tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> str:
    """Check rate limit for tenant before pipeline execution.

    Returns tenant_id if allowed, raises HTTPException if rate limited.
    """
    limiter = await get_ai_rate_limiter()
    if limiter is None:
        return tenant_id

    from example_service.core.settings import get_settings

    settings = get_settings()
    ai_settings = getattr(settings, "ai", None)

    limit = (
        getattr(ai_settings, "rate_limit_requests_per_minute", 60) if ai_settings else 60
    )
    window = getattr(ai_settings, "rate_limit_window_seconds", 60) if ai_settings else 60

    key = f"tenant:{tenant_id}:pipelines"
    allowed, metadata = await limiter.check_limit(
        key=key, limit=limit, window=window, endpoint="ai_pipeline_execute",
    )

    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "rate_limit_exceeded",
                "message": f"Rate limit exceeded. Maximum {limit} requests per {window} seconds.",
                "tenant_id": tenant_id,
                "limit": limit,
                "window_seconds": window,
                "retry_after_seconds": metadata.get("retry_after", window),
            },
            headers={"Retry-After": str(metadata.get("retry_after", window))},
        )

    return tenant_id


# Track concurrent executions per tenant
_concurrent_executions: dict[str, int] = {}

# Track cancellation requests - maps execution_id to cancellation timestamp
_cancellation_requests: dict[str, datetime] = {}


def request_cancellation(execution_id: str) -> None:
    """Mark an execution for cancellation."""
    _cancellation_requests[execution_id] = datetime.now(UTC)


def is_cancellation_requested(execution_id: str) -> bool:
    """Check if cancellation has been requested for an execution."""
    return execution_id in _cancellation_requests


def clear_cancellation(execution_id: str) -> None:
    """Clear cancellation request after processing."""
    _cancellation_requests.pop(execution_id, None)


async def check_concurrent_limit(
    tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> str:
    """Check concurrent execution limit for tenant.

    This is an in-memory check for concurrent executions.
    For distributed deployments, this should use Redis.
    """
    from example_service.core.settings import get_settings

    settings = get_settings()
    ai_settings = getattr(settings, "ai", None)

    max_concurrent = (
        getattr(ai_settings, "rate_limit_concurrent_executions", 10) if ai_settings else 10
    )

    current = _concurrent_executions.get(tenant_id, 0)
    if current >= max_concurrent:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "concurrent_limit_exceeded",
                "message": f"Maximum concurrent executions ({max_concurrent}) reached. Please wait for current executions to complete.",
                "tenant_id": tenant_id,
                "current_executions": current,
                "max_concurrent": max_concurrent,
            },
        )

    return tenant_id


def increment_concurrent(tenant_id: str) -> None:
    """Increment concurrent execution count for tenant."""
    _concurrent_executions[tenant_id] = _concurrent_executions.get(tenant_id, 0) + 1


def decrement_concurrent(tenant_id: str) -> None:
    """Decrement concurrent execution count for tenant."""
    if tenant_id in _concurrent_executions:
        _concurrent_executions[tenant_id] = max(0, _concurrent_executions[tenant_id] - 1)
        if _concurrent_executions[tenant_id] == 0:
            del _concurrent_executions[tenant_id]


# =============================================================================
# Helpers
# =============================================================================


def _is_execution_identifier(candidate: str) -> bool:
    return bool(re.fullmatch(EXECUTION_ID_PATTERN, candidate))


async def _build_legacy_progress_response(execution_id: str) -> ProgressResponse:
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


# =============================================================================
# Pipeline Execution Endpoints
# =============================================================================


@router.post(
    "/execute",
    status_code=status.HTTP_202_ACCEPTED,  # Default for async, will be 200 for sync
    responses={
        402: {"model": BudgetExceededError, "description": "Budget exceeded"},
        404: {"model": PipelineNotFoundError, "description": "Pipeline not found"},
        429: {"model": RateLimitExceededError, "description": "Rate limit exceeded"},
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

**Rate Limits:**
- Per-tenant rate limiting applies (default: 60 requests/minute)
- Concurrent execution limit applies (default: 10 concurrent)
""",
)
async def execute_pipeline(
    request: PipelineExecutionRequest,
    background_tasks: BackgroundTasks,
    tenant_id: Annotated[str, Depends(validate_tenant_budget)],
    _rate_limited: Annotated[str, Depends(check_rate_limit)],
    _concurrent_limited: Annotated[str, Depends(check_concurrent_limit)],
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
        # Track concurrent execution
        increment_concurrent(tenant_id)

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

    # Execute synchronously - track concurrent execution
    increment_concurrent(tenant_id)
    try:
        result = await orchestrator.execute(
            pipeline=pipeline,
            input_data=request.input_data,
            tenant_id=tenant_id,
            budget_limit_usd=request.budget_limit_usd,
            options=request.options,
        )
    finally:
        decrement_concurrent(tenant_id)

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
        estimated_cost_usd=str(result.total_cost_usd),
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
    options: dict[str, Any],
    execution_id: str,
    tenant_id: str,
    _budget_limit: Decimal | None,
) -> None:
    """Execute pipeline in background task."""
    try:
        # Check if cancelled before starting
        if is_cancellation_requested(execution_id):
            logger.info(
                "Pipeline execution cancelled before start",
                extra={"execution_id": execution_id, "tenant_id": tenant_id},
            )
            # Emit cancellation event
            event_store = get_event_store()
            if event_store is not None:
                await event_store.emit(
                    execution_id=execution_id,
                    event_type=EventType.WORKFLOW_CANCELLED,
                    data={
                        "reason": "Cancelled before execution started",
                        "completed_steps": [],
                    },
                )
            return

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
    finally:
        # Always decrement concurrent count and clear cancellation request when done
        decrement_concurrent(tenant_id)
        clear_cancellation(execution_id)


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
        msg = f"Unable to convert {type(p)} to dict"
        raise TypeError(msg)

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
                ),
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

    def _serialize_capabilities(provider: Any) -> list[str]:
        """Convert provider capabilities into their string values."""
        serialized: list[str] = []
        for capability in getattr(provider, "capabilities", []):
            cap_value = getattr(capability, "capability", capability)
            if isinstance(cap_value, Capability):
                serialized.append(cap_value.value)
            else:
                serialized.append(str(cap_value))
        return serialized

    provider_schemas = []
    for provider in providers:
        provider_name = getattr(provider, "provider_name", None)
        if _is_magic_mock(provider_name):
            provider_name = None
        if not provider_name:
            provider_name = getattr(provider, "name", None)
        provider_name = str(provider_name) if provider_name is not None else "unknown"

        documentation_url = getattr(provider, "documentation_url", None)
        if _is_magic_mock(documentation_url):
            documentation_url = None
        if documentation_url is not None and not isinstance(documentation_url, str):
            documentation_url = str(documentation_url)

        provider_type = getattr(provider, "provider_type", ProviderType.EXTERNAL)
        if isinstance(provider_type, ProviderType):
            provider_type_value = provider_type.value
        else:
            provider_type_value = str(provider_type)

        provider_schemas.append(
            ProviderInfoSchema(
                name=provider_name,
                provider_type=provider_type_value,
                is_available=True,  # Assume available if registered
                capabilities=_serialize_capabilities(provider),
                requires_api_key=bool(getattr(provider, "requires_api_key", False)),
                documentation_url=documentation_url,
            ),
        )

    return ProviderListResponse(
        providers=provider_schemas,
        total=len(provider_schemas),
    )


# =============================================================================
# Cost Estimation Endpoint
# =============================================================================


@router.post(
    "/estimate",
    response_model=CostEstimateResponse,
    responses={
        404: {"model": PipelineNotFoundError, "description": "Pipeline not found"},
    },
    summary="Estimate pipeline execution cost",
    description="""
Estimate the cost of executing a pipeline before actually running it.

This endpoint returns:
- Estimated total cost based on pipeline steps
- Estimated duration
- Per-step cost breakdown (if available)
- Current budget status
- Whether execution is allowed based on budget limits

Use this endpoint to get user confirmation before expensive operations.
""",
)
async def estimate_pipeline_cost(
    request: CostEstimateRequest,
    tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> CostEstimateResponse:
    """Estimate cost for pipeline execution without actually executing."""
    # Look up the pipeline definition
    pipeline = get_pipeline(request.pipeline_name)
    if pipeline is None:
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

    # Get estimated cost from pipeline definition
    estimated_cost = pipeline.estimated_cost_usd or Decimal(0)

    # Try to get more accurate per-step estimates
    step_estimates: dict[str, str] = {}
    for step in pipeline.steps:
        # Basic estimate based on capability type
        step_cost = Decimal("0.01")  # Default per-step cost
        if step.capability:
            cap_name = step.capability.value.lower()
            if "transcription" in cap_name:
                step_cost = Decimal("0.02")  # Transcription typically costs more
            elif "llm" in cap_name or "generation" in cap_name:
                step_cost = Decimal("0.01")
            elif "embedding" in cap_name:
                step_cost = Decimal("0.001")
        step_estimates[step.name] = str(step_cost)

    # If no pipeline-level estimate, sum step estimates
    if estimated_cost == Decimal(0) and step_estimates:
        estimated_cost = sum(Decimal(v) for v in step_estimates.values())

    # Get budget status
    budget_service = get_budget_service()
    budget_status_response: BudgetStatusResponse | None = None
    can_execute = True
    warning: str | None = None

    if budget_service is not None:
        check = await budget_service.check_budget(tenant_id, estimated_cost_usd=estimated_cost)

        remaining = None
        if check.limit_usd is not None and check.limit_usd > 0:
            remaining = max(Decimal(0), check.limit_usd - check.current_spend_usd)

        budget_status_response = BudgetStatusResponse(
            tenant_id=tenant_id,
            period="monthly",
            current_spend_usd=str(check.current_spend_usd),
            limit_usd=str(check.limit_usd) if check.limit_usd else None,
            remaining_usd=str(remaining) if remaining is not None else None,
            percent_used=check.percent_used,
            is_exceeded=check.action == BudgetAction.BLOCKED,
            policy=check.policy.value if hasattr(check, "policy") and check.policy else "warn",
        )

        # Check if execution is allowed
        if check.action == BudgetAction.BLOCKED:
            can_execute = False
            warning = f"Budget exceeded. Current spend: ${check.current_spend_usd}, Limit: ${check.limit_usd}"
        elif check.percent_used and check.percent_used >= 80:
            warning = f"Budget warning: {check.percent_used:.1f}% of budget used. This execution would cost approximately ${estimated_cost}"

    return CostEstimateResponse(
        pipeline_name=pipeline.name,
        estimated_cost_usd=str(estimated_cost),
        estimated_duration_seconds=pipeline.estimated_duration_seconds,
        step_estimates=step_estimates,
        budget_status=budget_status_response,
        can_execute=can_execute,
        warning=warning,
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
    try:
        budget_period = BudgetPeriod(period)
    except ValueError:
        budget_period = BudgetPeriod.MONTHLY

    budget_service = get_budget_service()
    if budget_service is None:
        return BudgetStatusResponse(
            tenant_id=tenant_id,
            period=budget_period.value,
            current_spend_usd="0",
            limit_usd=None,
            remaining_usd=None,
            percent_used=None,
            is_exceeded=False,
            policy="warn",
        )

    check = await budget_service.check_budget(
        tenant_id,
        period=budget_period,
    )

    remaining = None
    percent_used = check.percent_used
    if check.limit_usd is not None and check.limit_usd > 0:
        remaining = max(Decimal(0), check.limit_usd - check.current_spend_usd)

    return BudgetStatusResponse(
        tenant_id=tenant_id,
        period=budget_period.value,
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


@router.get(
    "/{pipeline_name}",
    response_model=PipelineInfoSchema | ProgressResponse,
    summary="Get pipeline definition or legacy execution progress",
    description="Get detailed information about a specific pipeline or legacy execution progress.",
)
async def get_pipeline_info(
    pipeline_name: str,
) -> PipelineInfoSchema | ProgressResponse:
    """Get pipeline definition or legacy execution progress."""
    if _is_execution_identifier(pipeline_name):
        return await _build_legacy_progress_response(pipeline_name)

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
    execution_id: ExecutionIdParam,
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
    execution_id: ExecutionIdParam,
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
    execution_id: ExecutionIdParam,
    _tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> ProgressResponse:
    """Get current progress of a pipeline execution (legacy endpoint)."""
    return await _build_legacy_progress_response(execution_id)


@router.get(
    "/{execution_id}/result",
    response_model=PipelineResultResponse,
    responses={404: {"model": ExecutionNotFoundError}},
    summary="Get execution result",
    description="Get full result of a completed pipeline execution.",
)
async def get_execution_result(
    execution_id: ExecutionIdParam,
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
    description="""
Request cancellation of a running pipeline execution.

The cancellation is processed as follows:
- If the execution is still pending/queued, it will be cancelled immediately
- If the execution is running, it will be cancelled at the next step boundary
- Completed or already-cancelled executions cannot be cancelled

Cancellation will trigger compensation actions if configured on the pipeline.
""",
)
async def cancel_execution(
    execution_id: ExecutionIdParam,
    tenant_id: Annotated[str, Depends(get_current_tenant)],
    orchestrator: Annotated[InstrumentedOrchestrator, Depends(get_orchestrator)],
) -> dict[str, Any]:
    """Request cancellation of a running pipeline execution."""
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

    # Check current status
    current_status = state.get("status", "unknown")

    # Cannot cancel completed or already cancelled executions
    if current_status in ("completed", "failed", "cancelled"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "cannot_cancel",
                "message": f"Cannot cancel execution with status '{current_status}'",
                "execution_id": execution_id,
                "current_status": current_status,
            },
        )

    # Check if already requested
    if is_cancellation_requested(execution_id):
        return {
            "execution_id": execution_id,
            "cancellation_requested": True,
            "message": "Cancellation already requested and pending",
            "status": "cancellation_pending",
            "current_execution_status": current_status,
        }

    # Request cancellation
    request_cancellation(execution_id)

    # Emit cancellation event
    event_store = get_event_store()
    if event_store is not None:
        await event_store.emit(
            execution_id=execution_id,
            event_type=EventType.WORKFLOW_CANCELLED,
            data={
                "requested_by": tenant_id,
                "requested_at": datetime.now(UTC).isoformat(),
                "reason": "User requested cancellation",
                "completed_steps": state.get("completed_steps", []),
            },
        )

    logger.info(
        "Cancellation request registered",
        extra={
            "execution_id": execution_id,
            "tenant_id": tenant_id,
            "current_status": current_status,
        },
    )

    return {
        "execution_id": execution_id,
        "cancellation_requested": True,
        "message": "Cancellation requested. The execution will be cancelled at the next step boundary.",
        "status": "cancellation_pending",
        "current_execution_status": current_status,
        "completed_steps": state.get("completed_steps", []),
    }


# =============================================================================
# WebSocket Event Streaming
# =============================================================================


@router.websocket("/{execution_id}/events")
async def stream_execution_events(
    websocket: WebSocket,
    execution_id: ExecutionIdParam,
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
