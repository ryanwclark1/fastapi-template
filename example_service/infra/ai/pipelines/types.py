"""Pipeline types for composable AI workflows.

This module defines the core types for the pipeline system:

- PipelineStep: A single step in a pipeline with capability and configuration
- PipelineDefinition: Complete pipeline specification with steps and metadata
- PipelineContext: Runtime context passed through pipeline execution
- PipelineResult: Final result from pipeline execution
- StepResult: Result from a single pipeline step

Design Principles:
1. Immutable Definitions: Pipeline definitions are immutable and can be reused
2. Rich Context: Context flows through steps, carrying data and state
3. Compensation Support: Steps can define compensation actions for rollback
4. Progress Tracking: Fine-grained progress events for real-time updates

Example:
    from example_service.infra.ai.pipelines.types import (
        PipelineDefinition,
        PipelineStep,
        StepTransformType,
    )

    # Define a transcription + redaction pipeline
    pipeline = PipelineDefinition(
        name="transcribe_and_redact",
        steps=[
            PipelineStep(
                name="transcribe",
                capability=Capability.TRANSCRIPTION_DIARIZATION,
                provider_preference=["deepgram", "openai"],
                output_key="transcript",
            ),
            PipelineStep(
                name="redact_pii",
                capability=Capability.PII_REDACTION,
                provider_preference=["accent_redaction"],
                input_transform=lambda ctx: {"segments": ctx["transcript"].segments},
                output_key="redacted_transcript",
            ),
        ],
    )
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any, TypeVar
import uuid

if TYPE_CHECKING:
    from example_service.infra.ai.capabilities.types import (
        Capability,
        OperationResult,
        QualityTier,
    )


class StepStatus(str, Enum):
    """Status of a pipeline step."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"


class StepTransformType(str, Enum):
    """Type of data transformation between steps."""

    PASSTHROUGH = "passthrough"  # Pass context unchanged
    MAP = "map"  # Map output to specific input format
    EXTRACT = "extract"  # Extract specific field from context
    MERGE = "merge"  # Merge multiple context fields


class ConditionalOperator(str, Enum):
    """Operators for conditional step execution."""

    EQUALS = "eq"
    NOT_EQUALS = "neq"
    CONTAINS = "contains"
    EXISTS = "exists"
    NOT_EXISTS = "not_exists"
    GREATER_THAN = "gt"
    LESS_THAN = "lt"


@dataclass
class StepCondition:
    """Condition for conditional step execution.

    Conditions allow steps to be skipped based on context values.

    Example:
        # Only run PII redaction if transcript contains potential PII
        condition = StepCondition(
            context_path="transcript.contains_pii",
            operator=ConditionalOperator.EQUALS,
            value=True,
        )
    """

    context_path: str  # Dot-notation path in context (e.g., "transcript.language")
    operator: ConditionalOperator
    value: Any = None

    def evaluate(self, context: dict[str, Any]) -> bool:
        """Evaluate condition against context.

        Args:
            context: Current pipeline context

        Returns:
            True if condition is met, False otherwise
        """
        # Navigate dot-notation path
        current: Any = context
        try:
            for part in self.context_path.split("."):
                if isinstance(current, dict):
                    current = current.get(part)
                elif hasattr(current, part):
                    current = getattr(current, part)
                else:
                    current = None
                    break
        except Exception:
            current = None

        # Evaluate operator
        if self.operator == ConditionalOperator.EXISTS:
            return bool(current is not None)
        if self.operator == ConditionalOperator.NOT_EXISTS:
            return bool(current is None)
        if self.operator == ConditionalOperator.EQUALS:
            return bool(current == self.value)
        if self.operator == ConditionalOperator.NOT_EQUALS:
            return bool(current != self.value)
        if self.operator == ConditionalOperator.CONTAINS:
            if current is None:
                return False
            try:
                return bool(self.value in current)
            except TypeError:
                return False
        elif self.operator == ConditionalOperator.GREATER_THAN:
            if current is None:
                return False
            try:
                return bool(current > self.value)
            except TypeError:
                return False
        elif self.operator == ConditionalOperator.LESS_THAN:
            if current is None:
                return False
            try:
                return bool(current < self.value)
            except TypeError:
                return False

        return False


@dataclass
class RetryPolicy:
    """Retry policy for pipeline steps.

    Configures how steps should retry on failure.

    Example:
        policy = RetryPolicy(
            max_attempts=3,
            initial_delay_ms=1000,
            exponential_backoff=True,
            max_delay_ms=30000,
            retryable_errors=["timeout", "rate_limit"],
        )
    """

    max_attempts: int = 3
    initial_delay_ms: int = 1000
    exponential_backoff: bool = True
    backoff_multiplier: float = 2.0
    max_delay_ms: int = 30000
    retryable_errors: list[str] | None = None  # None = retry all retryable errors

    def get_delay_ms(self, attempt: int) -> int:
        """Calculate delay for a given attempt number.

        Args:
            attempt: Current attempt number (1-indexed)

        Returns:
            Delay in milliseconds before next retry
        """
        if attempt <= 1:
            return self.initial_delay_ms

        if self.exponential_backoff:
            delay = self.initial_delay_ms * (self.backoff_multiplier ** (attempt - 1))
        else:
            delay = self.initial_delay_ms

        return min(int(delay), self.max_delay_ms)


@dataclass
class FallbackConfig:
    """Configuration for step fallback behavior.

    Controls how the pipeline handles provider failures.

    Example:
        config = FallbackConfig(
            enabled=True,
            max_fallbacks=3,
            fallback_quality_degradation=True,
            excluded_providers=["openai"],  # Don't use OpenAI as fallback
        )
    """

    enabled: bool = True
    max_fallbacks: int = 3
    fallback_quality_degradation: bool = True  # Allow lower quality tier on fallback
    excluded_providers: list[str] = field(default_factory=list)
    prefer_same_quality: bool = True


@dataclass
class CompensationAction:
    """Compensation action for saga pattern.

    Defines how to compensate/rollback a completed step when
    a later step fails.

    Example:
        compensation = CompensationAction(
            handler=delete_uploaded_audio,
            description="Delete uploaded audio from storage",
            timeout_seconds=30,
        )
    """

    handler: Callable[[dict[str, Any]], Any]  # Compensation function
    description: str = ""
    timeout_seconds: int = 30
    required: bool = True  # If True, pipeline fails if compensation fails

    async def execute(self, context: dict[str, Any]) -> bool:
        """Execute compensation action.

        Args:
            context: Pipeline context at time of compensation

        Returns:
            True if compensation succeeded
        """
        import asyncio

        try:
            result = self.handler(context)
            if asyncio.iscoroutine(result):
                await result
            return True
        except Exception:
            return False


@dataclass
class PipelineStep:
    """A single step in a pipeline.

    Steps define:
    - What capability to execute
    - Provider preferences and fallback behavior
    - Input/output transformations
    - Retry and error handling
    - Compensation for saga pattern

    Example:
        step = PipelineStep(
            name="transcribe",
            capability=Capability.TRANSCRIPTION_DIARIZATION,
            provider_preference=["deepgram", "openai"],
            fallback_config=FallbackConfig(max_fallbacks=2),
            retry_policy=RetryPolicy(max_attempts=3),
            output_key="transcript",
            timeout_seconds=300,
        )
    """

    # Identity
    name: str
    description: str = ""

    # Capability
    capability: Capability = field(default=None)  # type: ignore
    provider_preference: list[str] = field(default_factory=list)
    required_quality_tier: QualityTier | None = None

    # Options passed to adapter.execute()
    options: dict[str, Any] = field(default_factory=dict)

    # Input/Output
    input_key: str | None = None  # Key in context to use as input (default: full context)
    output_key: str | None = None  # Key in context to store output (default: step name)
    input_transform: Callable[[dict[str, Any]], Any] | None = (
        None  # Transform input before execution
    )
    output_transform: Callable[[Any], Any] | None = None  # Transform output before storing

    # Flow control
    condition: StepCondition | None = None  # Skip step if condition not met
    continue_on_failure: bool = False  # Continue pipeline if step fails
    required: bool = True  # If False and fails, pipeline continues

    # Resilience
    fallback_config: FallbackConfig = field(default_factory=FallbackConfig)
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    timeout_seconds: int = 120

    # Saga pattern
    compensation: CompensationAction | None = None

    # Progress tracking
    progress_weight: float = 1.0  # Relative weight for progress calculation

    def get_output_key(self) -> str:
        """Get the key used to store output in context."""
        return self.output_key or self.name

    def should_execute(self, context: dict[str, Any]) -> bool:
        """Check if step should be executed based on condition.

        Args:
            context: Current pipeline context

        Returns:
            True if step should execute
        """
        if self.condition is None:
            return True
        return self.condition.evaluate(context)

    def get_input(self, context: dict[str, Any]) -> Any:
        """Get input data for this step.

        Args:
            context: Current pipeline context

        Returns:
            Input data for the step
        """
        # Get raw input
        raw_input = context.get(self.input_key, context) if self.input_key else context

        # Apply transform if specified
        if self.input_transform:
            return self.input_transform(raw_input)

        return raw_input


@dataclass
class PipelineDefinition:
    """Complete pipeline specification.

    Defines a reusable pipeline with steps, metadata, and configuration.

    Example:
        pipeline = PipelineDefinition(
            name="call_analysis",
            version="1.0.0",
            description="Full call analysis pipeline",
            steps=[
                PipelineStep(name="transcribe", ...),
                PipelineStep(name="redact_pii", ...),
                PipelineStep(name="summarize", ...),
                PipelineStep(name="analyze_sentiment", ...),
            ],
            tags=["transcription", "analysis"],
            estimated_duration_seconds=120,
        )
    """

    # Identity
    name: str
    version: str = "1.0.0"
    description: str = ""
    tags: list[str] = field(default_factory=list)

    # Steps
    steps: list[PipelineStep] = field(default_factory=list)

    # Execution config
    timeout_seconds: int = 600  # Overall pipeline timeout
    max_concurrent_steps: int = 1  # For future parallel execution
    fail_fast: bool = True  # Stop on first failure (unless step has continue_on_failure)

    # Saga pattern
    enable_compensation: bool = True  # Run compensation on failure
    compensation_timeout_seconds: int = 120

    # Progress tracking
    progress_checkpoints: list[str] = field(
        default_factory=list,
    )  # Step names that mark progress checkpoints

    # Metadata
    estimated_duration_seconds: int | None = None
    estimated_cost_usd: Decimal | None = None

    def __post_init__(self) -> None:
        """Validate pipeline definition."""
        if not self.name:
            msg = "Pipeline name is required"
            raise ValueError(msg)

        step_names = set()
        for step in self.steps:
            if step.name in step_names:
                msg = f"Duplicate step name: {step.name}"
                raise ValueError(msg)
            step_names.add(step.name)

    def get_step(self, name: str) -> PipelineStep | None:
        """Get a step by name.

        Args:
            name: Step name

        Returns:
            PipelineStep if found, None otherwise
        """
        for step in self.steps:
            if step.name == name:
                return step
        return None

    def get_total_progress_weight(self) -> float:
        """Get total progress weight for all steps."""
        return sum(step.progress_weight for step in self.steps)


@dataclass
class StepResult:
    """Result from executing a single pipeline step.

    Contains the operation result, timing, provider used, and any errors.
    """

    step_name: str
    status: StepStatus
    operation_result: OperationResult | None = None
    provider_used: str | None = None
    fallbacks_attempted: list[str] = field(default_factory=list)
    retries: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    error_code: str | None = None
    skipped_reason: str | None = None

    @property
    def duration_ms(self) -> float | None:
        """Get step duration in milliseconds."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds() * 1000
        return None

    @property
    def cost_usd(self) -> Decimal:
        """Get step cost."""
        if self.operation_result:
            return self.operation_result.cost_usd or Decimal(0)
        return Decimal(0)


@dataclass
class PipelineContext:
    """Runtime context for pipeline execution.

    The context carries:
    - Input data and intermediate results
    - Execution metadata (IDs, timestamps)
    - Progress tracking state
    - Compensation state for saga pattern

    Context is mutable and flows through all steps.
    """

    # Execution identity
    execution_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    pipeline_name: str = ""
    tenant_id: str | None = None

    # Data storage
    data: dict[str, Any] = field(default_factory=dict)
    initial_input: dict[str, Any] = field(default_factory=dict)

    # Execution state
    current_step: str | None = None
    completed_steps: list[str] = field(default_factory=list)
    step_results: dict[str, StepResult] = field(default_factory=dict)

    # Progress tracking
    progress_percent: float = 0.0
    progress_message: str = ""
    last_checkpoint: str | None = None

    # Timing
    started_at: datetime | None = None
    last_updated_at: datetime | None = None

    # Saga compensation tracking
    compensated_steps: list[str] = field(default_factory=list)
    compensation_errors: list[str] = field(default_factory=list)

    # Error state
    failed_step: str | None = None
    failure_error: str | None = None

    def __getitem__(self, key: str) -> Any:
        """Get item from data dict."""
        return self.data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        """Set item in data dict."""
        self.data[key] = value
        self.last_updated_at = datetime.utcnow()

    def get(self, key: str, default: Any = None) -> Any:
        """Get item from data dict with default."""
        return self.data.get(key, default)

    def update(self, data: dict[str, Any]) -> None:
        """Update data dict."""
        self.data.update(data)
        self.last_updated_at = datetime.utcnow()

    def set_progress(self, percent: float, message: str = "") -> None:
        """Update progress state.

        Args:
            percent: Progress percentage (0-100)
            message: Optional progress message
        """
        self.progress_percent = min(100.0, max(0.0, percent))
        self.progress_message = message
        self.last_updated_at = datetime.utcnow()


@dataclass
class PipelineResult:
    """Final result from pipeline execution.

    Contains overall status, all step results, and aggregated metrics.
    """

    # Identity
    execution_id: str
    pipeline_name: str
    pipeline_version: str

    # Status
    success: bool
    completed_steps: list[str] = field(default_factory=list)
    failed_step: str | None = None
    error: str | None = None

    # Results
    output: dict[str, Any] = field(default_factory=dict)
    step_results: dict[str, StepResult] = field(default_factory=dict)

    # Metrics
    total_duration_ms: float = 0
    total_cost_usd: Decimal = field(default_factory=lambda: Decimal(0))

    # Timing
    started_at: datetime | None = None
    completed_at: datetime | None = None

    # Saga compensation
    compensation_performed: bool = False
    compensated_steps: list[str] = field(default_factory=list)

    def get_step_result(self, step_name: str) -> StepResult | None:
        """Get result for a specific step."""
        return self.step_results.get(step_name)

    def get_output(self, key: str, default: Any = None) -> Any:
        """Get output value by key."""
        return self.output.get(key, default)


# Type alias for step input transformers
StepInputTransform = Callable[[dict[str, Any]], Any]

# Type alias for step output transformers
StepOutputTransform = Callable[[Any], Any]

# Type alias for progress callbacks
ProgressCallback = Callable[[str, float, str], None]  # (execution_id, percent, message)

# Generic type for typed pipeline outputs
T = TypeVar("T")
