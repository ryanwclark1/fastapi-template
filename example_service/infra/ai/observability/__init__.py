"""AI Workflow Observability Layer.

Provides comprehensive observability for AI workflows:
- Distributed tracing via OpenTelemetry
- Metrics via Prometheus
- Budget tracking and enforcement

Quick Start:
    from example_service.infra.ai.observability import (
        get_ai_tracer,
        get_ai_metrics,
        get_budget_service,
    )

    # Get singletons
    tracer = get_ai_tracer()
    metrics = get_ai_metrics()
    budget = get_budget_service()

    # Use in pipeline execution
    async with tracer.pipeline_span(pipeline, context):
        metrics.record_pipeline_started(pipeline.name)
        check = await budget.check_budget(tenant_id)
        ...
"""

# Tracing
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

# Metrics
from example_service.infra.ai.observability.metrics import (
    AIMetrics,
    configure_ai_metrics,
    get_ai_metrics,
)
from example_service.infra.ai.observability.tracing import (
    AITracer,
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
    "NoOpPipelineSpan",
    "NoOpProviderSpan",
    "NoOpStepSpan",
    "PipelineSpan",
    "ProviderSpan",
    "SpendRecord",
    "StepSpan",
    "configure_ai_metrics",
    "configure_ai_tracer",
    "configure_budget_service",
    "get_ai_metrics",
    "get_ai_tracer",
    "get_budget_service",
]
