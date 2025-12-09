"""AI pipeline dependencies for FastAPI route handlers.

This module provides FastAPI-compatible dependencies for accessing
the AI infrastructure including the orchestrator, pipelines, and
observability services.

Usage:
    from example_service.core.dependencies.ai import (
        OrchestratorDep,
        BudgetServiceDep,
        get_orchestrator,
    )

    @router.post("/ai/analyze")
    async def analyze_content(
        data: AnalysisRequest,
        orchestrator: OrchestratorDep,
        tenant_id: str = Header(...),
    ):
        result = await orchestrator.execute(
            pipeline=get_pipeline("content_analysis"),
            input_data=data.model_dump(),
            tenant_id=tenant_id,
        )
        return result

    @router.get("/ai/budget")
    async def check_budget(
        budget: BudgetServiceDep,
        tenant_id: str = Header(...),
    ):
        check = await budget.check_budget(tenant_id)
        return {
            "allowed": check.action == BudgetAction.ALLOW,
            "remaining": str(check.remaining_budget),
        }
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, HTTPException, status

if TYPE_CHECKING:
    from example_service.infra.ai import InstrumentedOrchestrator
    from example_service.infra.ai.observability import (
        AIMetrics,
        AIObservabilityLogger,
        AITracer,
        BudgetService,
    )
    from example_service.infra.ai.pipelines import Pipeline


def get_orchestrator() -> InstrumentedOrchestrator | None:
    """Get the AI orchestrator instance.

    This is a thin wrapper that retrieves the orchestrator singleton.
    The import is deferred to runtime to avoid circular dependencies.

    Returns:
        InstrumentedOrchestrator | None: The orchestrator, or None if not initialized.
    """
    from example_service.infra.ai import get_instrumented_orchestrator

    return get_instrumented_orchestrator()


def get_ai_budget_service() -> BudgetService:
    """Get the AI budget service instance.

    Returns:
        BudgetService: The budget service for cost tracking/enforcement.
    """
    from example_service.infra.ai.observability import get_budget_service

    return get_budget_service()


def get_ai_tracer_dep() -> AITracer:
    """Get the AI tracer instance.

    Returns:
        AITracer: The AI-specific tracer for pipeline spans.
    """
    from example_service.infra.ai.observability import get_ai_tracer

    return get_ai_tracer()


def get_ai_metrics_dep() -> AIMetrics:
    """Get the AI metrics instance.

    Returns:
        AIMetrics: The AI metrics collector.
    """
    from example_service.infra.ai.observability import get_ai_metrics

    return get_ai_metrics()


def get_ai_logger_dep() -> AIObservabilityLogger:
    """Get the AI logger instance.

    Returns:
        AIObservabilityLogger: The AI observability logger.
    """
    from example_service.infra.ai.observability import get_ai_logger

    return get_ai_logger()


def get_pipeline_dep(name: str):
    """Factory for creating pipeline dependencies.

    Args:
        name: Name of the pipeline to retrieve.

    Returns:
        A dependency function that returns the named pipeline.

    Example:
        from example_service.core.dependencies.ai import get_pipeline_dep

        AnalysisPipeline = Annotated[Pipeline, Depends(get_pipeline_dep("analysis"))]

        @router.post("/analyze")
        async def analyze(pipeline: AnalysisPipeline, orchestrator: OrchestratorDep):
            return await orchestrator.execute(pipeline=pipeline, ...)
    """

    def _get_pipeline() -> Pipeline:
        from example_service.infra.ai import get_pipeline

        return get_pipeline(name)

    return _get_pipeline


async def require_orchestrator(
    orchestrator: Annotated[InstrumentedOrchestrator | None, Depends(get_orchestrator)],
) -> InstrumentedOrchestrator:
    """Dependency that requires AI orchestrator to be available.

    Use this when AI functionality is required for the endpoint.
    Raises HTTP 503 if AI infrastructure is not initialized.

    Args:
        orchestrator: Injected orchestrator from get_orchestrator

    Returns:
        InstrumentedOrchestrator: The orchestrator instance

    Raises:
        HTTPException: 503 Service Unavailable if not initialized
    """
    if orchestrator is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "ai_unavailable",
                "message": "AI infrastructure is not initialized",
            },
        )
    return orchestrator


async def optional_orchestrator(
    orchestrator: Annotated[InstrumentedOrchestrator | None, Depends(get_orchestrator)],
) -> InstrumentedOrchestrator | None:
    """Dependency that optionally provides AI orchestrator.

    Use this when AI functionality is optional. Allows graceful
    degradation when AI infrastructure is not available.

    Args:
        orchestrator: Injected orchestrator from get_orchestrator

    Returns:
        InstrumentedOrchestrator | None: The orchestrator if available, None otherwise
    """
    return orchestrator


# Type aliases for cleaner route signatures
OrchestratorDep = Annotated[InstrumentedOrchestrator, Depends(require_orchestrator)]
"""AI orchestrator dependency that requires it to be available.

Example:
    @router.post("/ai/execute")
    async def execute(data: dict, orchestrator: OrchestratorDep):
        return await orchestrator.execute(
            pipeline=get_pipeline("analysis"),
            input_data=data,
        )
"""

OptionalOrchestrator = Annotated[
    InstrumentedOrchestrator | None, Depends(optional_orchestrator)
]
"""AI orchestrator dependency that is optional.

Example:
    @router.post("/process")
    async def process(data: dict, ai: OptionalOrchestrator):
        if ai is None:
            return {"method": "fallback", "result": simple_process(data)}
        return await ai.execute(...)
"""

BudgetServiceDep = Annotated[BudgetService, Depends(get_ai_budget_service)]
"""AI budget service dependency for cost tracking.

Example:
    @router.get("/ai/budget")
    async def check_budget(budget: BudgetServiceDep, tenant_id: str):
        return await budget.check_budget(tenant_id)
"""

AITracerDep = Annotated[AITracer, Depends(get_ai_tracer_dep)]
"""AI tracer dependency for pipeline-level tracing.

Example:
    @router.post("/ai/custom")
    async def custom_ai(data: dict, tracer: AITracerDep):
        async with tracer.pipeline_span(...):
            ...
"""

AIMetricsDep = Annotated[AIMetrics, Depends(get_ai_metrics_dep)]
"""AI metrics dependency for recording pipeline metrics.

Example:
    @router.post("/ai/process")
    async def process(data: dict, metrics: AIMetricsDep):
        metrics.record_pipeline_started("custom")
        ...
"""

AILoggerDep = Annotated[AIObservabilityLogger, Depends(get_ai_logger_dep)]
"""AI logger dependency for structured logging.

Example:
    @router.post("/ai/analyze")
    async def analyze(data: dict, logger: AILoggerDep):
        logger.pipeline_started("analysis", execution_id, ...)
        ...
"""


__all__ = [
    "AILoggerDep",
    "AIMetricsDep",
    "AITracerDep",
    "BudgetServiceDep",
    "OptionalOrchestrator",
    "OrchestratorDep",
    "get_ai_budget_service",
    "get_ai_logger_dep",
    "get_ai_metrics_dep",
    "get_ai_tracer_dep",
    "get_orchestrator",
    "get_pipeline_dep",
    "optional_orchestrator",
    "require_orchestrator",
]
