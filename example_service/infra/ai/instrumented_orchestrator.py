"""Instrumented AI Workflow Orchestrator - Production-ready executor with full observability.

This module provides the top-level API for executing AI workflows with:
- Distributed tracing (OpenTelemetry)
- Prometheus metrics
- Event emission (WebSocket/SSE ready)
- Budget enforcement
- Saga compensation

This is the NEW recommended entry point for production use, replacing the
legacy orchestrator with a capability-based, composable pipeline architecture.

Architecture:
    InstrumentedOrchestrator
        ├── SagaCoordinator (execution + events)
        ├── AITracer (distributed tracing)
        ├── AIMetrics (Prometheus metrics)
        └── BudgetService (cost tracking)

Migration from Legacy:
    # Old way (legacy orchestrator.py)
    orchestrator = AIOrchestrator(session, provider_factory)
    result = await orchestrator.execute_workflow(WorkflowRequest(...))

    # New way (instrumented orchestrator)
    from example_service.infra.ai import InstrumentedOrchestrator
    from example_service.infra.ai.pipelines import get_call_analysis_pipeline

    orchestrator = InstrumentedOrchestrator(api_keys={...})
    result = await orchestrator.execute(
        pipeline=get_call_analysis_pipeline(),
        input_data={"audio": audio_bytes},
        tenant_id="tenant-123",
    )

Example:
    from example_service.infra.ai import InstrumentedOrchestrator
    from example_service.infra.ai.pipelines import get_call_analysis_pipeline

    # Initialize orchestrator
    orchestrator = InstrumentedOrchestrator(
        api_keys={
            "openai": "sk-...",
            "anthropic": "sk-ant-...",
            "deepgram": "...",
        },
    )

    # Execute workflow
    result = await orchestrator.execute(
        pipeline=get_call_analysis_pipeline(),
        input_data={"audio": audio_bytes},
        tenant_id="tenant-123",
    )

    # Result includes full observability data
    print(f"Success: {result.success}")
    print(f"Cost: ${result.total_cost_usd}")
    print(f"Duration: {result.total_duration_ms}ms")
    print(f"Transcript: {result.output.get('transcript')}")

WebSocket Integration:
    # Stream real-time events to client
    @app.websocket("/ws/workflow/{execution_id}")
    async def workflow_stream(websocket, execution_id: str):
        await websocket.accept()
        async for event in orchestrator.stream_events(execution_id):
            await websocket.send_json(event.to_dict())
"""

from __future__ import annotations

from decimal import Decimal
import logging
from typing import TYPE_CHECKING, Any

from example_service.infra.ai.capabilities.registry import (
    CapabilityRegistry,
    get_capability_registry,
)
from example_service.infra.ai.events import (
    EventStore,
    EventType,
    SagaCoordinator,
    get_event_store,
)
from example_service.infra.ai.observability import (
    AIMetrics,
    AITracer,
    BudgetCheckResult,
    BudgetExceededException,
    BudgetPolicy,
    BudgetService,
    get_ai_metrics,
    get_ai_tracer,
    get_budget_service,
)
from example_service.infra.ai.observability.logging import (
    AIObservabilityLogger,
    get_ai_logger,
)
from example_service.infra.ai.pipelines.types import (
    PipelineDefinition,
    PipelineResult,
    StepStatus,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from example_service.infra.ai.events.types import BaseEvent

logger = logging.getLogger(__name__)


class InstrumentedOrchestrator:
    """Production-ready AI workflow orchestrator with full observability.

    Integrates all new components for full-featured AI workflow execution:
    - Capability-based provider discovery
    - Pipeline composition with fallback chains
    - Saga compensation on failure
    - Distributed tracing (OpenTelemetry)
    - Prometheus metrics
    - Event streaming (WebSocket/SSE ready)
    - Budget enforcement

    This replaces the legacy AIOrchestrator with a more flexible,
    composable architecture.

    Example:
        orchestrator = InstrumentedOrchestrator(
            api_keys={"openai": "sk-...", "anthropic": "sk-ant-..."},
            default_budget_policy=BudgetPolicy.SOFT_BLOCK,
        )

        # Execute with full observability
        result = await orchestrator.execute(
            pipeline=my_pipeline,
            input_data={"audio": audio_bytes},
            tenant_id="tenant-123",
        )
    """

    def __init__(
        self,
        registry: CapabilityRegistry | None = None,
        event_store: EventStore | None = None,
        tracer: AITracer | None = None,
        metrics: AIMetrics | None = None,
        budget_service: BudgetService | None = None,
        ai_logger: AIObservabilityLogger | None = None,
        api_keys: dict[str, str] | None = None,
        model_overrides: dict[str, str] | None = None,
        default_budget_policy: BudgetPolicy = BudgetPolicy.WARN,
        enable_tracing: bool = True,
        enable_metrics: bool = True,
        enable_budget_enforcement: bool = True,
        enable_logging: bool = True,
    ) -> None:
        """Initialize orchestrator.

        Args:
            registry: Capability registry (uses global if None)
            event_store: Event store (uses global if None)
            tracer: AI tracer (uses global if None)
            metrics: AI metrics (uses global if None)
            budget_service: Budget service (uses global if None)
            ai_logger: AI observability logger (uses global if None)
            api_keys: API keys by provider name
            model_overrides: Model overrides by provider name
            default_budget_policy: Default budget policy for tenants
            enable_tracing: Enable OpenTelemetry tracing
            enable_metrics: Enable Prometheus metrics
            enable_budget_enforcement: Enable budget checks
            enable_logging: Enable structured AI logging
        """
        self.registry = registry or get_capability_registry()
        self.event_store = event_store or get_event_store()
        self.tracer = tracer or get_ai_tracer() if enable_tracing else None
        self.metrics = metrics or get_ai_metrics() if enable_metrics else None
        self.budget = budget_service or get_budget_service() if enable_budget_enforcement else None
        self.ai_logger = ai_logger or get_ai_logger() if enable_logging else None
        self.api_keys = api_keys or {}
        self.model_overrides = model_overrides or {}
        self.default_budget_policy = default_budget_policy

        # Initialize saga coordinator (requires non-None event_store)
        if self.event_store is None:
            msg = "EventStore is required for InstrumentedOrchestrator"
            raise ValueError(msg)
        self._saga = SagaCoordinator(
            registry=self.registry,
            event_store=self.event_store,
            api_keys=self.api_keys,
            model_overrides=self.model_overrides,
        )

        logger.info(
            "InstrumentedOrchestrator initialized",
            extra={
                "tracing_enabled": enable_tracing,
                "metrics_enabled": enable_metrics,
                "budget_enabled": enable_budget_enforcement,
                "logging_enabled": enable_logging,
                "provider_count": len(self.api_keys),
            },
        )

    async def execute(
        self,
        pipeline: PipelineDefinition,
        input_data: dict[str, Any],
        *,
        tenant_id: str | None = None,
        api_key_overrides: dict[str, str] | None = None,
        model_overrides: dict[str, str] | None = None,
        budget_limit_usd: Decimal | None = None,
        skip_budget_check: bool = False,
    ) -> PipelineResult:
        """Execute a pipeline with full observability.

        This is the main entry point for workflow execution.

        Args:
            pipeline: Pipeline definition to execute
            input_data: Initial input data
            tenant_id: Tenant identifier (for budget, metrics, tracing)
            api_key_overrides: Override API keys for this execution
            model_overrides: Override models for this execution
            budget_limit_usd: Override budget limit for this execution
            skip_budget_check: Skip pre-execution budget check

        Returns:
            PipelineResult with full execution details

        Raises:
            BudgetExceededException: If budget is exceeded and policy blocks
        """
        # Pre-execution budget check
        budget_check: BudgetCheckResult | None = None
        if self.budget and tenant_id and not skip_budget_check:
            budget_check = await self.budget.check_budget(
                tenant_id=tenant_id,
                estimated_cost_usd=pipeline.estimated_cost_usd,
            )

            # Log budget check result
            if self.ai_logger:
                self.ai_logger.budget_check(
                    tenant_id=tenant_id,
                    current_spend_usd=budget_check.current_spend_usd,
                    limit_usd=budget_check.limit_usd,
                    percent_used=budget_check.percent_used,
                    action=budget_check.action.value,
                    estimated_cost_usd=pipeline.estimated_cost_usd,
                    period=budget_check.period.value,
                    pipeline_name=pipeline.name,
                )

            if not budget_check.allowed:
                logger.warning(
                    f"Budget exceeded for tenant: {tenant_id}",
                    extra={
                        "tenant_id": tenant_id,
                        "pipeline": pipeline.name,
                        "budget_check": budget_check.message,
                    },
                )

                if self.ai_logger:
                    self.ai_logger.budget_exceeded(
                        tenant_id=tenant_id,
                        current_spend_usd=budget_check.current_spend_usd,
                        limit_usd=budget_check.limit_usd or Decimal(0),
                        period=budget_check.period.value,
                        blocked=True,
                    )

                if self.metrics:
                    self.metrics.record_budget_exceeded(tenant_id, "blocked")

                raise BudgetExceededException(
                    budget_check.message,
                    check_result=budget_check,
                )

            if budget_check.action.value == "warned":
                logger.warning(
                    f"Budget warning for tenant: {tenant_id}",
                    extra={
                        "tenant_id": tenant_id,
                        "pipeline": pipeline.name,
                        "budget_check": budget_check.message,
                    },
                )

        # Record pipeline started metrics and log
        if self.metrics:
            self.metrics.record_pipeline_started(pipeline.name, tenant_id)

        if self.ai_logger:
            self.ai_logger.pipeline_started(
                pipeline_name=pipeline.name,
                execution_id=_create_mock_context(pipeline.name, tenant_id).execution_id,
                tenant_id=tenant_id,
                step_count=len(pipeline.steps),
                estimated_cost_usd=pipeline.estimated_cost_usd,
                estimated_duration_seconds=pipeline.estimated_duration_seconds,
            )

        try:
            # Execute with tracing
            if self.tracer:
                async with self.tracer.pipeline_span(
                    pipeline,
                    _create_mock_context(pipeline.name, tenant_id),
                ) as span:
                    result = await self._execute_pipeline(
                        pipeline=pipeline,
                        input_data=input_data,
                        tenant_id=tenant_id,
                        api_key_overrides=api_key_overrides,
                        model_overrides=model_overrides,
                        budget_limit_usd=budget_limit_usd,
                    )

                    # Record to span
                    if result.success:
                        span.record_success(
                            completed_steps=result.completed_steps,
                            total_cost_usd=result.total_cost_usd,
                            duration_ms=result.total_duration_ms,
                        )
                    else:
                        span.record_failure(
                            failed_step=result.failed_step,
                            error=result.error or "Unknown error",
                            completed_steps=result.completed_steps,
                            total_cost_usd=result.total_cost_usd,
                        )
            else:
                result = await self._execute_pipeline(
                    pipeline=pipeline,
                    input_data=input_data,
                    tenant_id=tenant_id,
                    api_key_overrides=api_key_overrides,
                    model_overrides=model_overrides,
                    budget_limit_usd=budget_limit_usd,
                )

            # Record metrics
            self._record_execution_metrics(pipeline, result, tenant_id)

            # Log pipeline completion
            if self.ai_logger:
                if result.success:
                    self.ai_logger.pipeline_completed(
                        pipeline_name=pipeline.name,
                        execution_id=result.execution_id,
                        tenant_id=tenant_id,
                        success=True,
                        duration_ms=result.total_duration_ms,
                        total_cost_usd=result.total_cost_usd,
                        completed_steps=result.completed_steps,
                    )
                else:
                    self.ai_logger.pipeline_failed(
                        pipeline_name=pipeline.name,
                        execution_id=result.execution_id,
                        error=result.error or "Unknown error",
                        error_type="PipelineError",
                        failed_step=result.failed_step,
                        tenant_id=tenant_id,
                        duration_ms=result.total_duration_ms,
                        completed_steps=result.completed_steps,
                        total_cost_usd=result.total_cost_usd,
                        compensation_triggered=result.compensation_performed,
                    )

            # Track budget spend
            if self.budget and tenant_id and result.total_cost_usd > 0:
                await self.budget.track_spend(
                    tenant_id=tenant_id,
                    cost_usd=result.total_cost_usd,
                    pipeline_name=pipeline.name,
                    execution_id=result.execution_id,
                )

                # Log spend tracking
                if self.ai_logger:
                    self.ai_logger.spend_tracked(
                        tenant_id=tenant_id,
                        cost_usd=result.total_cost_usd,
                        pipeline_name=pipeline.name,
                        execution_id=result.execution_id,
                    )

            return result

        finally:
            # Record pipeline completed (for active gauge)
            if self.metrics:
                self.metrics.record_pipeline_completed(pipeline.name, tenant_id)

    def _record_execution_metrics(
        self,
        pipeline: PipelineDefinition,
        result: PipelineResult,
        tenant_id: str | None,
    ) -> None:
        """Record all execution metrics."""
        if not self.metrics:
            return

        # Pipeline metrics
        self.metrics.record_pipeline_execution(
            pipeline_name=pipeline.name,
            status="success" if result.success else "failure",
            duration_seconds=result.total_duration_ms / 1000,
            total_cost_usd=result.total_cost_usd,
            steps_completed=len(result.completed_steps),
            tenant_id=tenant_id,
        )

        # Step metrics
        for step_name, step_result in result.step_results.items():
            step = pipeline.get_step(step_name)
            if step and step_result.status in (StepStatus.COMPLETED, StepStatus.FAILED):
                self.metrics.record_step_execution(
                    pipeline_name=pipeline.name,
                    step_name=step_name,
                    capability=step.capability.value if step.capability else "unknown",
                    status=step_result.status.value,
                    duration_seconds=(step_result.duration_ms or 0) / 1000,
                    _cost_usd=step_result.cost_usd or 0,
                    retries=step_result.retries,
                    _provider_used=step_result.provider_used,
                )

                # Provider metrics
                if step_result.provider_used and step_result.operation_result:
                    op = step_result.operation_result
                    self.metrics.record_provider_request(
                        provider=step_result.provider_used,
                        capability=step.capability.value if step.capability else "unknown",
                        status="success" if op.success else "failure",
                        latency_seconds=(op.latency_ms or 0) / 1000,
                        cost_usd=op.cost_usd or Decimal(0),
                        error_code=op.error_code,
                        tenant_id=tenant_id,
                    )

                    # Usage metrics
                    if op.usage:
                        if "input_tokens" in op.usage or "output_tokens" in op.usage:
                            self.metrics.record_token_usage(
                                provider=step_result.provider_used,
                                capability=step.capability.value if step.capability else "unknown",
                                input_tokens=op.usage.get("input_tokens", 0),
                                output_tokens=op.usage.get("output_tokens", 0),
                            )
                        if "duration_seconds" in op.usage:
                            self.metrics.record_audio_duration(
                                provider=step_result.provider_used,
                                capability=step.capability.value if step.capability else "unknown",
                                duration_seconds=op.usage["duration_seconds"],
                            )

            elif step_result.status == StepStatus.SKIPPED:
                self.metrics.record_step_skipped(
                    pipeline_name=pipeline.name,
                    step_name=step_name,
                    reason=step_result.skipped_reason or "condition_not_met",
                )

        # Fallback metrics
        for step_name, step_result in result.step_results.items():
            if step_result.fallbacks_attempted:
                for i, failed_provider in enumerate(step_result.fallbacks_attempted):
                    next_provider = (
                        step_result.fallbacks_attempted[i + 1]
                        if i + 1 < len(step_result.fallbacks_attempted)
                        else step_result.provider_used
                    )
                    if next_provider:
                        self.metrics.record_step_fallback(
                            pipeline_name=pipeline.name,
                            step_name=step_name,
                            from_provider=failed_provider,
                            to_provider=next_provider,
                        )

        # Compensation metrics
        if result.compensation_performed:
            status = "success" if len(result.compensated_steps) > 0 else "failed"
            self.metrics.record_compensation_execution(
                pipeline_name=pipeline.name,
                status=status,
            )

    async def _execute_pipeline(
        self,
        pipeline: PipelineDefinition,
        input_data: dict[str, Any],
        tenant_id: str | None,
        api_key_overrides: dict[str, str] | None,
        model_overrides: dict[str, str] | None,
        budget_limit_usd: Decimal | None,
    ) -> PipelineResult:
        """Internal pipeline execution via saga coordinator."""
        return await self._saga.execute(
            pipeline=pipeline,
            input_data=input_data,
            tenant_id=tenant_id,
            api_key_overrides=api_key_overrides,
            model_overrides=model_overrides,
            budget_limit_usd=budget_limit_usd,
        )

    async def stream_events(
        self,
        execution_id: str,
        event_types: list[EventType] | None = None,
    ) -> AsyncIterator[BaseEvent]:
        """Stream events for a workflow execution.

        Use this for real-time WebSocket/SSE updates.

        Args:
            execution_id: Workflow execution ID
            event_types: Optional filter by event types

        Yields:
            Events as they occur
        """
        async for event in self.event_store.subscribe(  # type: ignore[attr-defined]
            execution_id=execution_id,
            event_types=event_types,
        ):
            yield event

    async def get_workflow_state(self, execution_id: str) -> dict[str, Any] | None:
        """Get current workflow state.

        Args:
            execution_id: Workflow execution ID

        Returns:
            Current state dict or None if not found
        """
        return await self.event_store.get_workflow_state(execution_id)

    async def get_execution(self, execution_id: str) -> PipelineResult | None:
        """Get execution result by ID.

        Args:
            execution_id: Execution ID

        Returns:
            PipelineResult or None if not found
        """
        state = await self.get_workflow_state(execution_id)
        if not state:
            return None

        # Convert state dict to PipelineResult
        from datetime import datetime
        from decimal import Decimal

        from example_service.infra.ai.pipelines.types import PipelineResult

        status_str = state.get("status", "pending")
        success = status_str == "completed"

        return PipelineResult(
            execution_id=execution_id,
            pipeline_name=state.get("pipeline_name", "unknown"),
            pipeline_version=state.get("pipeline_version", "1.0.0"),
            success=success,
            output=state.get("output", {}),
            completed_steps=state.get("completed_steps", []),
            failed_step=state.get("failed_step"),
            total_duration_ms=state.get("total_duration_ms", 0.0),
            total_cost_usd=Decimal(state.get("total_cost_usd", "0")),
            started_at=datetime.fromisoformat(state["started_at"])
            if state.get("started_at")
            else None,
            completed_at=datetime.fromisoformat(state["completed_at"])
            if state.get("completed_at")
            else None,
            compensation_performed=state.get("compensation_performed", False),
            compensated_steps=state.get("compensated_steps", []),
            error=state.get("error"),
        )

    async def get_progress(self, execution_id: str) -> dict[str, Any] | None:
        """Get execution progress.

        Args:
            execution_id: Execution ID

        Returns:
            Progress dict or None if not found
        """
        state = await self.get_workflow_state(execution_id)
        if not state:
            return None

        total_steps = state.get("total_steps", len(state.get("completed_steps", [])) + 1)
        completed_steps = state.get("completed_steps", [])
        progress_percent = (len(completed_steps) / total_steps * 100) if total_steps > 0 else 0

        return {
            "execution_id": execution_id,
            "status": state.get("status", "running"),
            "completed_steps": completed_steps,
            "current_step": state.get("current_step"),
            "progress_percent": min(progress_percent, 100),
            "total_steps": total_steps,
            "estimated_remaining_seconds": state.get("estimated_remaining_seconds"),
            "current_cost_usd": state.get(
                "total_cost_usd", "0",
            ),  # Keep as string for JSON serialization
        }

    async def get_budget_status(
        self,
        tenant_id: str,
    ) -> BudgetCheckResult | None:
        """Get current budget status for a tenant.

        Args:
            tenant_id: Tenant identifier

        Returns:
            BudgetCheckResult with current status
        """
        if not self.budget:
            return None

        return await self.budget.check_budget(tenant_id)

    async def get_spend_summary(
        self,
        tenant_id: str,
        period: str = "daily",
    ) -> dict[str, Any] | None:
        """Get spend summary for a tenant.

        Args:
            tenant_id: Tenant identifier
            period: Time period (daily, weekly, monthly)

        Returns:
            Spend summary dict
        """
        if not self.budget:
            return None

        from example_service.infra.ai.observability.budget import BudgetPeriod

        period_enum = BudgetPeriod(period)
        return await self.budget.get_spend_summary(tenant_id, period_enum)


def _create_mock_context(pipeline_name: str, tenant_id: str | None) -> Any:
    """Create a minimal context object for tracing."""
    from example_service.infra.ai.pipelines.types import PipelineContext

    return PipelineContext(
        pipeline_name=pipeline_name,
        tenant_id=tenant_id,
    )


# Singleton instance
_orchestrator: InstrumentedOrchestrator | None = None


def configure_orchestrator(orchestrator: InstrumentedOrchestrator | None) -> None:
    """Set the global orchestrator instance.

    Args:
        orchestrator: Orchestrator instance or None to clear
    """
    global _orchestrator
    _orchestrator = orchestrator


def get_instrumented_orchestrator() -> InstrumentedOrchestrator:
    """Get the global instrumented orchestrator singleton.

    Returns:
        The singleton InstrumentedOrchestrator instance
    """
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = InstrumentedOrchestrator()
    return _orchestrator


def configure_instrumented_orchestrator(
    api_keys: dict[str, str] | None = None,
    model_overrides: dict[str, str] | None = None,
    default_budget_policy: BudgetPolicy = BudgetPolicy.WARN,
    enable_tracing: bool = True,
    enable_metrics: bool = True,
    enable_budget_enforcement: bool = True,
) -> InstrumentedOrchestrator:
    """Configure and return the global instrumented orchestrator.

    Args:
        api_keys: API keys by provider name
        model_overrides: Model overrides by provider name
        default_budget_policy: Default budget policy
        enable_tracing: Enable OpenTelemetry tracing
        enable_metrics: Enable Prometheus metrics
        enable_budget_enforcement: Enable budget checks

    Returns:
        Configured InstrumentedOrchestrator instance
    """
    global _orchestrator
    _orchestrator = InstrumentedOrchestrator(
        api_keys=api_keys,
        model_overrides=model_overrides,
        default_budget_policy=default_budget_policy,
        enable_tracing=enable_tracing,
        enable_metrics=enable_metrics,
        enable_budget_enforcement=enable_budget_enforcement,
    )
    return _orchestrator
