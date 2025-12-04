"""AI Pipeline Composition Layer.

This module provides composable AI pipelines with:
- Fluent builder DSL for pipeline construction
- Provider fallback chains for resilience
- Saga pattern compensation for rollback
- Fine-grained progress tracking
- Cost aggregation

Architecture:
    Pipeline DSL (builder.py)
        ↓
    PipelineDefinition (types.py)
        ↓
    PipelineExecutor (executor.py)
        ↓
    CapabilityRegistry → ProviderAdapters

Quick Start:
    from example_service.infra.ai.pipelines import (
        Pipeline,
        PipelineExecutor,
        get_call_analysis_pipeline,
    )

    # Option 1: Use a predefined pipeline
    pipeline = get_call_analysis_pipeline()

    # Option 2: Build a custom pipeline
    pipeline = (
        Pipeline("my_pipeline")
        .step("transcribe")
            .capability(Capability.TRANSCRIPTION)
            .prefer_providers("deepgram")
            .done()
        .step("summarize")
            .capability(Capability.SUMMARIZATION)
            .prefer_providers("anthropic")
            .done()
        .build()
    )

    # Execute the pipeline
    executor = PipelineExecutor()
    result = await executor.execute(
        pipeline=pipeline,
        input_data={"audio": audio_bytes},
    )

    if result.success:
        print(f"Summary: {result.output['summary']}")
        print(f"Total cost: ${result.total_cost_usd}")
"""

# Types
# Builder DSL
from example_service.infra.ai.pipelines.builder import (
    Pipeline,
    PipelineBuilder,
    Step,
    StepBuilder,
)

# Executor
from example_service.infra.ai.pipelines.executor import (
    PipelineExecutionError,
    PipelineExecutor,
    PipelineExecutorFactory,
)

# Predefined pipelines
from example_service.infra.ai.pipelines.predefined import (
    PREDEFINED_PIPELINES,
    get_call_analysis_pipeline,
    get_dual_channel_analysis_pipeline,
    get_pii_detection_pipeline,
    get_pipeline,
    get_text_summarization_pipeline,
    get_transcription_pipeline,
    get_transcription_with_redaction_pipeline,
    list_pipelines,
)
from example_service.infra.ai.pipelines.types import (
    CompensationAction,
    ConditionalOperator,
    FallbackConfig,
    PipelineContext,
    PipelineDefinition,
    PipelineResult,
    PipelineStep,
    ProgressCallback,
    RetryPolicy,
    StepCondition,
    StepResult,
    StepStatus,
    StepTransformType,
)

__all__ = [
    # Predefined pipelines
    "PREDEFINED_PIPELINES",
    # Types
    "CompensationAction",
    "ConditionalOperator",
    "FallbackConfig",
    # Builder DSL
    "Pipeline",
    "PipelineBuilder",
    "PipelineContext",
    "PipelineDefinition",
    # Executor
    "PipelineExecutionError",
    "PipelineExecutor",
    "PipelineExecutorFactory",
    "PipelineResult",
    "PipelineStep",
    "ProgressCallback",
    "RetryPolicy",
    "Step",
    "StepBuilder",
    "StepCondition",
    "StepResult",
    "StepStatus",
    "StepTransformType",
    "get_call_analysis_pipeline",
    "get_dual_channel_analysis_pipeline",
    "get_pii_detection_pipeline",
    "get_pipeline",
    "get_text_summarization_pipeline",
    "get_transcription_pipeline",
    "get_transcription_with_redaction_pipeline",
    "list_pipelines",
]
