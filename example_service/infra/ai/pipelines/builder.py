"""Fluent Pipeline Builder DSL.

This module provides a fluent interface for building AI pipelines
in a clean, readable way.

Design Goals:
1. Readable: Pipeline definitions read like natural language
2. Type-safe: Full IDE support with type hints
3. Composable: Reuse steps and partial pipelines
4. Validated: Errors caught at build time, not runtime

Example:
    from example_service.infra.ai.pipelines.builder import Pipeline

    # Build a call analysis pipeline
    pipeline = (
        Pipeline("call_analysis")
        .version("1.0.0")
        .description("Full call analysis with transcription, PII redaction, and insights")
        .timeout(600)

        # Step 1: Transcription with speaker diarization
        .step("transcribe")
            .capability(Capability.TRANSCRIPTION_DIARIZATION)
            .prefer_providers("deepgram", "openai")
            .output_as("transcript")
            .with_fallback(max_fallbacks=2)
            .with_retry(max_attempts=3)
            .timeout(300)
            .done()

        # Step 2: PII Redaction
        .step("redact_pii")
            .capability(Capability.PII_REDACTION)
            .prefer_providers("accent_redaction")
            .input_from("transcript", transform=lambda t: {"segments": t.segments})
            .output_as("redacted")
            .done()

        # Step 3: Summarization (only if transcript is long enough)
        .step("summarize")
            .capability(Capability.SUMMARIZATION)
            .prefer_providers("anthropic")
            .when(lambda ctx: len(ctx.get("redacted", {}).get("text", "")) > 500)
            .input_from("redacted")
            .output_as("summary")
            .done()

        .build()
    )
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any, Self

from example_service.infra.ai.pipelines.types import (
    CompensationAction,
    ConditionalOperator,
    FallbackConfig,
    PipelineDefinition,
    PipelineStep,
    RetryPolicy,
    StepCondition,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from example_service.infra.ai.capabilities.types import Capability, QualityTier


class StepBuilder:
    """Builder for a single pipeline step.

    Provides fluent interface for configuring step properties.

    Example:
        step = (
            StepBuilder("transcribe")
            .capability(Capability.TRANSCRIPTION)
            .prefer_providers("deepgram")
            .with_retry(max_attempts=3)
            .timeout(300)
            .build()
        )
    """

    def __init__(self, name: str, pipeline_builder: PipelineBuilder | None = None) -> None:
        """Initialize step builder.

        Args:
            name: Step name (unique within pipeline)
            pipeline_builder: Parent pipeline builder for chaining
        """
        self._name = name
        self._pipeline_builder = pipeline_builder
        self._description = ""
        self._capability: Capability | None = None
        self._provider_preference: list[str] = []
        self._required_quality_tier: QualityTier | None = None
        self._options: dict[str, Any] = {}
        self._input_key: str | None = None
        self._output_key: str | None = None
        self._input_transform: Callable[[dict[str, Any]], Any] | None = None
        self._output_transform: Callable[[Any], Any] | None = None
        self._condition: StepCondition | None = None
        self._condition_func: Callable[[dict[str, Any]], bool] | None = None
        self._continue_on_failure = False
        self._required = True
        self._fallback_config = FallbackConfig()
        self._retry_policy = RetryPolicy()
        self._timeout_seconds = 120
        self._compensation: CompensationAction | None = None
        self._progress_weight = 1.0

    def description(self, desc: str) -> Self:
        """Set step description.

        Args:
            desc: Human-readable description

        Returns:
            Self for chaining
        """
        self._description = desc
        return self

    def capability(self, cap: Capability) -> Self:
        """Set the capability this step executes.

        Args:
            cap: Capability enum value

        Returns:
            Self for chaining
        """
        self._capability = cap
        return self

    def prefer_providers(self, *providers: str) -> Self:
        """Set preferred provider order.

        Providers are tried in order until one succeeds.

        Args:
            *providers: Provider names in preference order

        Returns:
            Self for chaining
        """
        self._provider_preference = list(providers)
        return self

    def require_quality(self, tier: QualityTier) -> Self:
        """Require a specific quality tier.

        Args:
            tier: Minimum quality tier

        Returns:
            Self for chaining
        """
        self._required_quality_tier = tier
        return self

    def with_options(self, **options: Any) -> Self:
        """Set options passed to the adapter execute method.

        Args:
            **options: Key-value options

        Returns:
            Self for chaining
        """
        self._options.update(options)
        return self

    def input_from(
        self,
        key: str,
        transform: Callable[[Any], Any] | None = None,
    ) -> Self:
        """Configure input from a context key.

        Args:
            key: Context key to read input from
            transform: Optional transform function

        Returns:
            Self for chaining
        """
        self._input_key = key
        if transform:
            def _transform(ctx: dict[str, Any]) -> Any:
                return transform(ctx.get(key))
            self._input_transform = _transform
        return self

    def input_transform(self, transform: Callable[[dict[str, Any]], Any]) -> Self:
        """Set a custom input transform function.

        The transform receives the full context and returns the input.

        Args:
            transform: Transform function

        Returns:
            Self for chaining
        """
        self._input_transform = transform
        return self

    def output_as(self, key: str) -> Self:
        """Set the output key in context.

        Args:
            key: Key to store step output

        Returns:
            Self for chaining
        """
        self._output_key = key
        return self

    def output_transform(self, transform: Callable[[Any], Any]) -> Self:
        """Set a custom output transform function.

        The transform receives the step output and returns the value to store.

        Args:
            transform: Transform function

        Returns:
            Self for chaining
        """
        self._output_transform = transform
        return self

    def when(
        self,
        condition: Callable[[dict[str, Any]], bool] | StepCondition,
    ) -> Self:
        """Set execution condition.

        Step is skipped if condition evaluates to False.

        Args:
            condition: Condition function or StepCondition

        Returns:
            Self for chaining
        """
        if isinstance(condition, StepCondition):
            self._condition = condition
        else:
            self._condition_func = condition
        return self

    def when_exists(self, context_path: str) -> Self:
        """Execute step only if context path exists.

        Args:
            context_path: Dot-notation path in context

        Returns:
            Self for chaining
        """
        self._condition = StepCondition(
            context_path=context_path,
            operator=ConditionalOperator.EXISTS,
        )
        return self

    def when_equals(self, context_path: str, value: Any) -> Self:
        """Execute step only if context value equals specified value.

        Args:
            context_path: Dot-notation path in context
            value: Value to compare

        Returns:
            Self for chaining
        """
        self._condition = StepCondition(
            context_path=context_path,
            operator=ConditionalOperator.EQUALS,
            value=value,
        )
        return self

    def optional(self) -> Self:
        """Mark step as optional (pipeline continues if step fails).

        Returns:
            Self for chaining
        """
        self._required = False
        self._continue_on_failure = True
        return self

    def continue_on_failure(self) -> Self:
        """Continue pipeline even if this step fails.

        Returns:
            Self for chaining
        """
        self._continue_on_failure = True
        return self

    def with_fallback(
        self,
        max_fallbacks: int = 3,
        allow_quality_degradation: bool = True,
        exclude_providers: list[str] | None = None,
    ) -> Self:
        """Configure fallback behavior.

        Args:
            max_fallbacks: Maximum number of fallback attempts
            allow_quality_degradation: Allow lower quality on fallback
            exclude_providers: Providers to exclude from fallback

        Returns:
            Self for chaining
        """
        self._fallback_config = FallbackConfig(
            enabled=True,
            max_fallbacks=max_fallbacks,
            fallback_quality_degradation=allow_quality_degradation,
            excluded_providers=exclude_providers or [],
        )
        return self

    def no_fallback(self) -> Self:
        """Disable fallback for this step.

        Returns:
            Self for chaining
        """
        self._fallback_config = FallbackConfig(enabled=False)
        return self

    def with_retry(
        self,
        max_attempts: int = 3,
        initial_delay_ms: int = 1000,
        exponential_backoff: bool = True,
    ) -> Self:
        """Configure retry behavior.

        Args:
            max_attempts: Maximum retry attempts
            initial_delay_ms: Initial delay between retries
            exponential_backoff: Use exponential backoff

        Returns:
            Self for chaining
        """
        self._retry_policy = RetryPolicy(
            max_attempts=max_attempts,
            initial_delay_ms=initial_delay_ms,
            exponential_backoff=exponential_backoff,
        )
        return self

    def no_retry(self) -> Self:
        """Disable retry for this step.

        Returns:
            Self for chaining
        """
        self._retry_policy = RetryPolicy(max_attempts=1)
        return self

    def timeout(self, seconds: int) -> Self:
        """Set step timeout.

        Args:
            seconds: Timeout in seconds

        Returns:
            Self for chaining
        """
        self._timeout_seconds = seconds
        return self

    def compensate_with(
        self,
        handler: Callable[[dict[str, Any]], Any],
        description: str = "",
    ) -> Self:
        """Set compensation action for saga rollback.

        Args:
            handler: Compensation function
            description: Human-readable description

        Returns:
            Self for chaining
        """
        self._compensation = CompensationAction(
            handler=handler,
            description=description,
        )
        return self

    def progress_weight(self, weight: float) -> Self:
        """Set relative progress weight.

        Higher weight = more progress contribution.

        Args:
            weight: Relative weight (default 1.0)

        Returns:
            Self for chaining
        """
        self._progress_weight = weight
        return self

    def build(self) -> PipelineStep:
        """Build the pipeline step.

        Returns:
            Configured PipelineStep

        Raises:
            ValueError: If required fields are missing
        """
        if not self._capability:
            msg = f"Step '{self._name}' requires a capability"
            raise ValueError(msg)

        # If we have a condition function, wrap it in a special condition
        actual_condition = self._condition
        if self._condition_func:
            # Create a wrapper condition that uses the function
            actual_condition = _FunctionalCondition(self._condition_func)

        return PipelineStep(
            name=self._name,
            description=self._description,
            capability=self._capability,
            provider_preference=self._provider_preference,
            required_quality_tier=self._required_quality_tier,
            options=self._options,
            input_key=self._input_key,
            output_key=self._output_key,
            input_transform=self._input_transform,
            output_transform=self._output_transform,
            condition=actual_condition,
            continue_on_failure=self._continue_on_failure,
            required=self._required,
            fallback_config=self._fallback_config,
            retry_policy=self._retry_policy,
            timeout_seconds=self._timeout_seconds,
            compensation=self._compensation,
            progress_weight=self._progress_weight,
        )

    def done(self) -> PipelineBuilder:
        """Finish configuring step and return to pipeline builder.

        Returns:
            Parent PipelineBuilder for chaining

        Raises:
            ValueError: If not building within a pipeline
        """
        if not self._pipeline_builder:
            msg = "done() can only be called when building within a pipeline"
            raise ValueError(msg)

        step = self.build()
        self._pipeline_builder._steps.append(step)
        return self._pipeline_builder


class _FunctionalCondition(StepCondition):
    """Special condition type that wraps a function.

    This allows using lambda conditions while maintaining
    the StepCondition interface.
    """

    def __init__(self, func: Callable[[dict[str, Any]], bool]) -> None:
        super().__init__(context_path="", operator=ConditionalOperator.EXISTS)
        self._func = func

    def evaluate(self, context: dict[str, Any]) -> bool:
        """Evaluate the wrapped function."""
        return self._func(context)


class PipelineBuilder:
    """Builder for pipeline definitions.

    Provides fluent interface for building complete pipelines.

    Example:
        pipeline = (
            Pipeline("call_analysis")
            .version("1.0.0")
            .description("Full call analysis pipeline")
            .step("transcribe")
                .capability(Capability.TRANSCRIPTION)
                .done()
            .step("summarize")
                .capability(Capability.SUMMARIZATION)
                .done()
            .build()
        )
    """

    def __init__(self, name: str) -> None:
        """Initialize pipeline builder.

        Args:
            name: Pipeline name
        """
        self._name = name
        self._version = "1.0.0"
        self._description = ""
        self._tags: list[str] = []
        self._steps: list[PipelineStep] = []
        self._timeout_seconds = 600
        self._max_concurrent_steps = 1
        self._fail_fast = True
        self._enable_compensation = True
        self._compensation_timeout_seconds = 120
        self._progress_checkpoints: list[str] = []
        self._estimated_duration_seconds: int | None = None
        self._estimated_cost_usd: Decimal | None = None

    def version(self, ver: str) -> Self:
        """Set pipeline version.

        Args:
            ver: Semantic version string

        Returns:
            Self for chaining
        """
        self._version = ver
        return self

    def description(self, desc: str) -> Self:
        """Set pipeline description.

        Args:
            desc: Human-readable description

        Returns:
            Self for chaining
        """
        self._description = desc
        return self

    def tags(self, *tags: str) -> Self:
        """Add tags for categorization.

        Args:
            *tags: Tag strings

        Returns:
            Self for chaining
        """
        self._tags.extend(tags)
        return self

    def timeout(self, seconds: int) -> Self:
        """Set overall pipeline timeout.

        Args:
            seconds: Timeout in seconds

        Returns:
            Self for chaining
        """
        self._timeout_seconds = seconds
        return self

    def max_concurrent(self, steps: int) -> Self:
        """Set maximum concurrent steps (for parallel execution).

        Args:
            steps: Maximum parallel steps

        Returns:
            Self for chaining
        """
        self._max_concurrent_steps = steps
        return self

    def no_fail_fast(self) -> Self:
        """Continue execution even after step failures.

        Returns:
            Self for chaining
        """
        self._fail_fast = False
        return self

    def with_compensation(self, timeout_seconds: int = 120) -> Self:
        """Enable saga compensation with timeout.

        Args:
            timeout_seconds: Compensation timeout

        Returns:
            Self for chaining
        """
        self._enable_compensation = True
        self._compensation_timeout_seconds = timeout_seconds
        return self

    def no_compensation(self) -> Self:
        """Disable saga compensation.

        Returns:
            Self for chaining
        """
        self._enable_compensation = False
        return self

    def checkpoint(self, step_name: str) -> Self:
        """Mark a step as a progress checkpoint.

        Args:
            step_name: Step name to mark as checkpoint

        Returns:
            Self for chaining
        """
        self._progress_checkpoints.append(step_name)
        return self

    def estimated_duration(self, seconds: int) -> Self:
        """Set estimated duration for progress estimation.

        Args:
            seconds: Estimated duration

        Returns:
            Self for chaining
        """
        self._estimated_duration_seconds = seconds
        return self

    def estimated_cost(self, usd: Decimal | float | str) -> Self:
        """Set estimated cost for budget tracking.

        Args:
            usd: Estimated cost in USD

        Returns:
            Self for chaining
        """
        self._estimated_cost_usd = Decimal(str(usd))
        return self

    def step(self, name: str) -> StepBuilder:
        """Start building a new step.

        Args:
            name: Step name (unique within pipeline)

        Returns:
            StepBuilder for configuring the step
        """
        return StepBuilder(name, pipeline_builder=self)

    def add_step(self, step: PipelineStep) -> Self:
        """Add a pre-built step.

        Args:
            step: PipelineStep to add

        Returns:
            Self for chaining
        """
        self._steps.append(step)
        return self

    def add_steps(self, *steps: PipelineStep) -> Self:
        """Add multiple pre-built steps.

        Args:
            *steps: PipelineSteps to add

        Returns:
            Self for chaining
        """
        self._steps.extend(steps)
        return self

    def build(self) -> PipelineDefinition:
        """Build the pipeline definition.

        Returns:
            Configured PipelineDefinition

        Raises:
            ValueError: If pipeline is invalid
        """
        if not self._steps:
            msg = f"Pipeline '{self._name}' has no steps"
            raise ValueError(msg)

        return PipelineDefinition(
            name=self._name,
            version=self._version,
            description=self._description,
            tags=self._tags,
            steps=self._steps,
            timeout_seconds=self._timeout_seconds,
            max_concurrent_steps=self._max_concurrent_steps,
            fail_fast=self._fail_fast,
            enable_compensation=self._enable_compensation,
            compensation_timeout_seconds=self._compensation_timeout_seconds,
            progress_checkpoints=self._progress_checkpoints,
            estimated_duration_seconds=self._estimated_duration_seconds,
            estimated_cost_usd=self._estimated_cost_usd,
        )


# Convenience function for starting pipeline construction
def Pipeline(name: str) -> PipelineBuilder:
    """Create a new pipeline builder.

    This is the entry point for the pipeline DSL.

    Example:
        pipeline = (
            Pipeline("my_pipeline")
            .step("step1")
                .capability(Capability.TRANSCRIPTION)
                .done()
            .build()
        )

    Args:
        name: Pipeline name

    Returns:
        PipelineBuilder instance
    """
    return PipelineBuilder(name)


# Convenience function for creating standalone steps
def Step(name: str) -> StepBuilder:
    """Create a standalone step builder.

    Use this for building reusable steps outside a pipeline.

    Example:
        transcribe_step = (
            Step("transcribe")
            .capability(Capability.TRANSCRIPTION)
            .prefer_providers("deepgram")
            .build()
        )

    Args:
        name: Step name

    Returns:
        StepBuilder instance
    """
    return StepBuilder(name)
