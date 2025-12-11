"""AI Workflow Observability Layer.

Provides comprehensive observability for AI workflows:
- Distributed tracing via OpenTelemetry
- Metrics via Prometheus
- Structured logging with trace correlation
- Budget tracking and enforcement

Quick Start:
    from example_service.infra.ai.observability import (
        get_ai_tracer,
        get_ai_metrics,
        get_ai_logger,
        get_budget_service,
    )

    # Get singletons
    tracer = get_ai_tracer()
    metrics = get_ai_metrics()
    ai_logger = get_ai_logger()
    budget = get_budget_service()

    # Use in pipeline execution
    async with tracer.pipeline_span(pipeline, context):
        metrics.record_pipeline_started(pipeline.name)
        ai_logger.pipeline_started(pipeline.name, execution_id, ...)
        check = await budget.check_budget(tenant_id)
        ...

Components:
    - AITracer: OpenTelemetry distributed tracing with pipeline/step/provider spans
    - AIMetrics: Prometheus metrics for pipelines, steps, providers, and budget
    - AIObservabilityLogger: Structured logging with automatic trace correlation
    - BudgetService: Cost tracking and budget enforcement per tenant
"""

# Budget
from example_service.infra.ai.observability.budget import (
    BudgetAction,
    BudgetCheckResult,
    BudgetConfig,
    BudgetExceededException,
    BudgetPeriod,
    BudgetPolicy,
    BudgetService,
    SpendRecord,
    configure_budget_service,
    get_budget_service,
)

# Logging
from example_service.infra.ai.observability.logging import (
    AIObservabilityLogger,
    LogContext,
    PipelineLogContext,
    StepLogContext,
    configure_ai_logger,
    get_ai_logger,
)

# Metrics
from example_service.infra.ai.observability.metrics import (
    AIMetrics,
    configure_ai_metrics,
    get_ai_metrics,
)

# Tracing
from example_service.infra.ai.observability.tracing import (
    AITracer,
    CompensationSpan,
    NoOpCompensationSpan,
    NoOpPipelineSpan,
    NoOpProviderSpan,
    NoOpStepSpan,
    PipelineSpan,
    ProviderSpan,
    StepSpan,
    configure_ai_tracer,
    get_ai_tracer,
)

__all__ = [
    # Metrics
    "AIMetrics",
    # Logging
    "AIObservabilityLogger",
    # Tracing
    "AITracer",
    # Budget
    "BudgetAction",
    "BudgetCheckResult",
    "BudgetConfig",
    "BudgetExceededException",
    "BudgetPeriod",
    "BudgetPolicy",
    "BudgetService",
    "CompensationSpan",
    "LogContext",
    "NoOpCompensationSpan",
    "NoOpPipelineSpan",
    "NoOpProviderSpan",
    "NoOpStepSpan",
    "PipelineLogContext",
    "PipelineSpan",
    "ProviderSpan",
    "SpendRecord",
    "StepLogContext",
    "StepSpan",
    "configure_ai_logger",
    "configure_ai_metrics",
    "configure_ai_tracer",
    "configure_budget_service",
    "get_ai_logger",
    "get_ai_metrics",
    "get_ai_tracer",
    "get_budget_service",
]
