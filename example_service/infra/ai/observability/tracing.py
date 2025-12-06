"""OpenTelemetry tracing for AI workflows.

Provides distributed tracing for:
- Pipeline execution spans
- Individual step spans
- Provider call spans
- Retry and fallback tracking

Integration:
    The tracing module integrates with OpenTelemetry's standard
    tracing infrastructure. Configure your exporter (Jaeger, Zipkin,
    OTLP) as usual, and AI workflow traces will flow through.

Span Hierarchy:
    ai.pipeline.execute (root)
    ├── ai.step.transcribe
    │   ├── ai.provider.deepgram (attempt 1 - failed)
    │   └── ai.provider.openai (attempt 2 - success)
    ├── ai.step.redact_pii
    │   └── ai.provider.accent_redaction
    └── ai.step.summarize
        └── ai.provider.anthropic

Attributes:
    - ai.pipeline.name: Pipeline name
    - ai.step.name: Step name
    - ai.provider.name: Provider name
    - ai.capability: Capability being executed
    - ai.cost_usd: Cost incurred
    - ai.tokens.input: Input tokens (LLM)
    - ai.tokens.output: Output tokens (LLM)
    - ai.duration_seconds: Audio duration (transcription)

Example:
    from example_service.infra.ai.observability.tracing import AITracer

    tracer = AITracer()

    async with tracer.pipeline_span(pipeline, context) as span:
        async with tracer.step_span(step, context) as step_span:
            result = await execute_step()
            step_span.record_result(result)
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from typing import TYPE_CHECKING, Any

try:
    from opentelemetry import trace
    from opentelemetry.trace import Span, SpanKind, Status, StatusCode

    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False
    trace = None  # type: ignore[assignment]
    Span = None  # type: ignore[assignment, misc]
    SpanKind = None  # type: ignore[assignment, misc]
    Status = None  # type: ignore[assignment, misc]
    StatusCode = None  # type: ignore[assignment, misc]

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from decimal import Decimal

    from example_service.infra.ai.capabilities.types import OperationResult
    from example_service.infra.ai.pipelines.types import (
        PipelineContext,
        PipelineDefinition,
        PipelineStep,
        StepResult,
    )

logger = logging.getLogger(__name__)


class AITracer:
    """OpenTelemetry tracer for AI workflows.

    Provides context managers for creating spans at different levels:
    - pipeline_span: Root span for entire pipeline execution
    - step_span: Span for individual step execution
    - provider_span: Span for provider calls

    Thread Safety:
        The tracer is stateless and safe for concurrent use.
        Each span operates in its own context.

    Example:
        tracer = AITracer()

        async with tracer.pipeline_span(pipeline, context) as pipeline_span:
            for step in pipeline.steps:
                async with tracer.step_span(step, context) as step_span:
                    result = await execute_step(step)
                    step_span.record_result(result)
    """

    # Semantic convention prefixes
    PIPELINE_PREFIX = "ai.pipeline"
    STEP_PREFIX = "ai.step"
    PROVIDER_PREFIX = "ai.provider"

    def __init__(
        self,
        tracer_name: str = "ai.workflows",
        enabled: bool = True,
    ) -> None:
        """Initialize AI tracer.

        Args:
            tracer_name: Name for the OpenTelemetry tracer
            enabled: Whether tracing is enabled
        """
        self.tracer_name = tracer_name
        self.enabled = enabled and OTEL_AVAILABLE

        if self.enabled:
            if trace is None:
                raise RuntimeError("OpenTelemetry trace module not available")
            self._tracer = trace.get_tracer(tracer_name)
        else:
            self._tracer = None  # type: ignore[assignment]

        if not OTEL_AVAILABLE and enabled:
            logger.warning(
                "OpenTelemetry not available. Install with: "
                "pip install opentelemetry-api opentelemetry-sdk"
            )

    @asynccontextmanager
    async def pipeline_span(
        self,
        pipeline: PipelineDefinition,
        context: PipelineContext,
    ) -> AsyncIterator[PipelineSpan]:
        """Create a span for pipeline execution.

        Args:
            pipeline: Pipeline being executed
            context: Execution context

        Yields:
            PipelineSpan wrapper for recording results
        """
        if not self.enabled:
            yield NoOpPipelineSpan()  # type: ignore[misc]
            return

        span_name = f"{self.PIPELINE_PREFIX}.{pipeline.name}"

        if self._tracer is None:
            raise RuntimeError("Tracer not initialized")
        with self._tracer.start_as_current_span(
            span_name,
            kind=SpanKind.INTERNAL,
            attributes={
                f"{self.PIPELINE_PREFIX}.name": pipeline.name,
                f"{self.PIPELINE_PREFIX}.version": pipeline.version,
                f"{self.PIPELINE_PREFIX}.step_count": len(pipeline.steps),
                f"{self.PIPELINE_PREFIX}.execution_id": context.execution_id,
                f"{self.PIPELINE_PREFIX}.tenant_id": context.tenant_id or "",
            },
        ) as span:
            pipeline_span = PipelineSpan(span, self.PIPELINE_PREFIX)
            try:
                yield pipeline_span
            except Exception as e:
                pipeline_span.record_error(e)
                raise

    @asynccontextmanager
    async def step_span(
        self,
        step: PipelineStep,
        context: PipelineContext,
        step_index: int = 0,
    ) -> AsyncIterator[StepSpan]:
        """Create a span for step execution.

        Args:
            step: Step being executed
            context: Execution context
            step_index: Index of step in pipeline

        Yields:
            StepSpan wrapper for recording results
        """
        if not self.enabled:
            yield NoOpStepSpan()  # type: ignore[misc]
            return

        span_name = f"{self.STEP_PREFIX}.{step.name}"

        if self._tracer is None:
            raise RuntimeError("Tracer not initialized")
        with self._tracer.start_as_current_span(
            span_name,
            kind=SpanKind.INTERNAL,
            attributes={
                f"{self.STEP_PREFIX}.name": step.name,
                f"{self.STEP_PREFIX}.index": step_index,
                f"{self.STEP_PREFIX}.capability": step.capability.value if step.capability else "",
                f"{self.STEP_PREFIX}.execution_id": context.execution_id,
                f"{self.STEP_PREFIX}.provider_preference": ",".join(step.provider_preference),
                f"{self.STEP_PREFIX}.timeout_seconds": step.timeout_seconds,
            },
        ) as span:
            step_span = StepSpan(span, self.STEP_PREFIX)
            try:
                yield step_span
            except Exception as e:
                step_span.record_error(e)
                raise

    @asynccontextmanager
    async def provider_span(
        self,
        provider_name: str,
        capability: str,
        context: PipelineContext,
        attempt: int = 1,
    ) -> AsyncIterator[ProviderSpan]:
        """Create a span for provider call.

        Args:
            provider_name: Name of provider being called
            capability: Capability being executed
            context: Execution context
            attempt: Attempt number (for retries)

        Yields:
            ProviderSpan wrapper for recording results
        """
        if not self.enabled:
            yield NoOpProviderSpan()  # type: ignore[misc]
            return

        span_name = f"{self.PROVIDER_PREFIX}.{provider_name}"

        if self._tracer is None:
            raise RuntimeError("Tracer not initialized")
        with self._tracer.start_as_current_span(
            span_name,
            kind=SpanKind.CLIENT,  # External API call
            attributes={
                f"{self.PROVIDER_PREFIX}.name": provider_name,
                f"{self.PROVIDER_PREFIX}.capability": capability,
                f"{self.PROVIDER_PREFIX}.attempt": attempt,
                f"{self.PROVIDER_PREFIX}.execution_id": context.execution_id,
            },
        ) as span:
            provider_span = ProviderSpan(span, self.PROVIDER_PREFIX)
            try:
                yield provider_span
            except Exception as e:
                provider_span.record_error(e)
                raise


class PipelineSpan:
    """Wrapper for pipeline execution span."""

    def __init__(self, span: Span, prefix: str) -> None:
        self._span = span
        self._prefix = prefix

    def set_attribute(self, key: str, value: Any) -> None:
        """Set a span attribute."""
        self._span.set_attribute(f"{self._prefix}.{key}", value)

    def record_success(
        self,
        completed_steps: list[str],
        total_cost_usd: Decimal,
        duration_ms: float,
    ) -> None:
        """Record successful pipeline completion."""
        self._span.set_attribute(f"{self._prefix}.completed_steps", len(completed_steps))
        self._span.set_attribute(f"{self._prefix}.cost_usd", float(total_cost_usd))
        self._span.set_attribute(f"{self._prefix}.duration_ms", duration_ms)
        self._span.set_status(Status(StatusCode.OK))

    def record_failure(
        self,
        failed_step: str | None,
        error: str,
        completed_steps: list[str],
        total_cost_usd: Decimal,
    ) -> None:
        """Record pipeline failure."""
        self._span.set_attribute(f"{self._prefix}.failed_step", failed_step or "")
        self._span.set_attribute(f"{self._prefix}.error", error)
        self._span.set_attribute(f"{self._prefix}.completed_steps", len(completed_steps))
        self._span.set_attribute(f"{self._prefix}.cost_usd", float(total_cost_usd))
        self._span.set_status(Status(StatusCode.ERROR, error))

    def record_error(self, exception: Exception) -> None:
        """Record an exception."""
        self._span.record_exception(exception)
        self._span.set_status(Status(StatusCode.ERROR, str(exception)))


class StepSpan:
    """Wrapper for step execution span."""

    def __init__(self, span: Span, prefix: str) -> None:
        self._span = span
        self._prefix = prefix

    def set_attribute(self, key: str, value: Any) -> None:
        """Set a span attribute."""
        self._span.set_attribute(f"{self._prefix}.{key}", value)

    def record_result(self, result: StepResult) -> None:
        """Record step execution result."""
        self._span.set_attribute(f"{self._prefix}.status", result.status.value)
        self._span.set_attribute(f"{self._prefix}.provider_used", result.provider_used or "")
        self._span.set_attribute(f"{self._prefix}.fallbacks_count", len(result.fallbacks_attempted))
        self._span.set_attribute(f"{self._prefix}.retries", result.retries)
        self._span.set_attribute(f"{self._prefix}.cost_usd", float(result.cost_usd))

        if result.duration_ms:
            self._span.set_attribute(f"{self._prefix}.duration_ms", result.duration_ms)

        if result.error:
            self._span.set_status(Status(StatusCode.ERROR, result.error))
        else:
            self._span.set_status(Status(StatusCode.OK))

    def record_skip(self, reason: str) -> None:
        """Record step skip."""
        self._span.set_attribute(f"{self._prefix}.skipped", True)
        self._span.set_attribute(f"{self._prefix}.skip_reason", reason)
        self._span.set_status(Status(StatusCode.OK))

    def record_error(self, exception: Exception) -> None:
        """Record an exception."""
        self._span.record_exception(exception)
        self._span.set_status(Status(StatusCode.ERROR, str(exception)))


class ProviderSpan:
    """Wrapper for provider call span."""

    def __init__(self, span: Span, prefix: str) -> None:
        self._span = span
        self._prefix = prefix

    def set_attribute(self, key: str, value: Any) -> None:
        """Set a span attribute."""
        self._span.set_attribute(f"{self._prefix}.{key}", value)

    def record_result(self, result: OperationResult) -> None:
        """Record provider call result."""
        self._span.set_attribute(f"{self._prefix}.success", result.success)
        self._span.set_attribute(f"{self._prefix}.cost_usd", float(result.cost_usd or 0))

        if result.latency_ms:
            self._span.set_attribute(f"{self._prefix}.latency_ms", result.latency_ms)

        # Record usage metrics
        if result.usage:
            for key, value in result.usage.items():
                if isinstance(value, (int, float)):
                    self._span.set_attribute(f"{self._prefix}.usage.{key}", value)

        if result.error:
            self._span.set_attribute(f"{self._prefix}.error", result.error)
            self._span.set_attribute(f"{self._prefix}.error_code", result.error_code or "")
            self._span.set_attribute(f"{self._prefix}.retryable", result.retryable)
            self._span.set_status(Status(StatusCode.ERROR, result.error))
        else:
            self._span.set_status(Status(StatusCode.OK))

    def record_error(self, exception: Exception) -> None:
        """Record an exception."""
        self._span.record_exception(exception)
        self._span.set_status(Status(StatusCode.ERROR, str(exception)))


# No-op implementations for when tracing is disabled


class NoOpPipelineSpan:
    """No-op pipeline span when tracing is disabled."""

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def record_success(self, *args: Any, **kwargs: Any) -> None:
        pass

    def record_failure(self, *args: Any, **kwargs: Any) -> None:
        pass

    def record_error(self, exception: Exception) -> None:
        pass


class NoOpStepSpan:
    """No-op step span when tracing is disabled."""

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def record_result(self, result: Any) -> None:
        pass

    def record_skip(self, reason: str) -> None:
        pass

    def record_error(self, exception: Exception) -> None:
        pass


class NoOpProviderSpan:
    """No-op provider span when tracing is disabled."""

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def record_result(self, result: Any) -> None:
        pass

    def record_error(self, exception: Exception) -> None:
        pass


# Singleton instance
_tracer: AITracer | None = None


def get_ai_tracer() -> AITracer:
    """Get the global AI tracer singleton.

    Returns:
        The singleton AITracer instance
    """
    global _tracer
    if _tracer is None:
        _tracer = AITracer()
    return _tracer


def configure_ai_tracer(
    tracer_name: str = "ai.workflows",
    enabled: bool = True,
) -> AITracer:
    """Configure and return the global AI tracer.

    Args:
        tracer_name: Name for the OpenTelemetry tracer
        enabled: Whether tracing is enabled

    Returns:
        Configured AITracer instance
    """
    global _tracer
    _tracer = AITracer(tracer_name=tracer_name, enabled=enabled)
    return _tracer
