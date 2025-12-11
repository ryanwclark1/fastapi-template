"""AI-specific structured logging with automatic observability integration.

Provides a unified logging interface for AI workflows that:
- Automatically correlates logs with distributed traces
- Records metrics alongside log events
- Provides structured context for debugging
- Supports log levels appropriate for production

Architecture:
    AIObservabilityLogger
        ├── Pipeline logging (start, complete, fail)
        ├── Step logging (start, complete, fail, skip, retry)
        ├── Provider logging (request, response, error)
        ├── Budget logging (check, exceeded, warning)
        └── Performance logging (slow operations, thresholds)

Usage:
    from example_service.infra.ai.observability.logging import get_ai_logger

    ai_logger = get_ai_logger()

    # Pipeline logging
    ai_logger.pipeline_started(pipeline_name="call_analysis", execution_id="exec-123")
    ai_logger.pipeline_completed(pipeline_name="call_analysis", execution_id="exec-123", ...)

    # Provider logging with automatic metrics
    ai_logger.provider_request(provider="openai", capability="llm_generation", ...)
    ai_logger.provider_response(provider="openai", success=True, latency_ms=150, ...)

Example with context manager:
    async with ai_logger.pipeline_context(pipeline, context) as log_ctx:
        async with log_ctx.step_context(step) as step_log:
            result = await execute_step()
            step_log.record_result(result)
"""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from example_service.infra.ai.pipelines.types import (
        PipelineContext,
        PipelineDefinition,
        PipelineStep,
        StepResult,
    )

# Try to import OpenTelemetry for trace correlation
try:
    from opentelemetry import trace as otel_trace

    OTEL_AVAILABLE = True
except ImportError:
    otel_trace = None  # type: ignore[assignment]
    OTEL_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class LogContext:
    """Context data for structured logging."""

    execution_id: str | None = None
    pipeline_name: str | None = None
    pipeline_version: str | None = None
    tenant_id: str | None = None
    step_name: str | None = None
    step_index: int | None = None
    capability: str | None = None
    provider: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert context to dictionary for logging."""
        result: dict[str, Any] = {}
        if self.execution_id:
            result["execution_id"] = self.execution_id
        if self.pipeline_name:
            result["pipeline_name"] = self.pipeline_name
        if self.pipeline_version:
            result["pipeline_version"] = self.pipeline_version
        if self.tenant_id:
            result["tenant_id"] = self.tenant_id
        if self.step_name:
            result["step_name"] = self.step_name
        if self.step_index is not None:
            result["step_index"] = self.step_index
        if self.capability:
            result["capability"] = self.capability
        if self.provider:
            result["provider"] = self.provider
        if self.trace_id:
            result["trace_id"] = self.trace_id
        if self.span_id:
            result["span_id"] = self.span_id
        result.update(self.extra)
        return result


class AIObservabilityLogger:
    """Structured logger for AI workflow observability.

    Provides methods for logging AI operations with:
    - Automatic trace correlation (when OpenTelemetry is available)
    - Structured context for filtering and debugging
    - Appropriate log levels for production use
    - Optional metrics recording

    Thread Safety:
        This class is stateless and safe for concurrent use.
        Each method operates independently.

    Example:
        ai_logger = AIObservabilityLogger()

        # Log pipeline execution
        ai_logger.pipeline_started(
            pipeline_name="call_analysis",
            execution_id="exec-123",
            tenant_id="tenant-456",
            step_count=5,
        )

        # Log with context
        with ai_logger.operation_context(
            operation="transcription",
            provider="deepgram"
        ) as ctx:
            ctx.info("Starting transcription")
            # ... do work ...
            ctx.info("Transcription complete", duration_ms=1500)
    """

    def __init__(
        self,
        logger_name: str = "example_service.ai",
        metrics: Any = None,  # AIMetrics instance
        include_trace_context: bool = True,
    ) -> None:
        """Initialize AI observability logger.

        Args:
            logger_name: Name for the underlying Python logger
            metrics: Optional AIMetrics instance for recording metrics
            include_trace_context: Whether to include trace IDs in logs
        """
        self._logger = logging.getLogger(logger_name)
        self._metrics = metrics
        self._include_trace_context = include_trace_context and OTEL_AVAILABLE

    def _get_trace_context(self) -> dict[str, str]:
        """Get current trace context from OpenTelemetry."""
        if not self._include_trace_context or otel_trace is None:
            return {}

        current_span = otel_trace.get_current_span()
        if current_span is None:
            return {}

        span_context = current_span.get_span_context()
        if span_context is None or not span_context.is_valid:
            return {}

        return {
            "trace_id": format(span_context.trace_id, "032x"),
            "span_id": format(span_context.span_id, "016x"),
        }

    def _log(
        self,
        level: int,
        message: str,
        context: LogContext | None = None,
        **kwargs: Any,
    ) -> None:
        """Internal log method with context enrichment."""
        extra = self._get_trace_context()
        if context:
            extra.update(context.to_dict())
        extra.update(kwargs)

        self._logger.log(level, message, extra=extra)

    # =========================================================================
    # Pipeline Logging
    # =========================================================================

    def pipeline_started(
        self,
        pipeline_name: str,
        execution_id: str,
        tenant_id: str | None = None,
        step_count: int = 0,
        estimated_cost_usd: Decimal | None = None,
        estimated_duration_seconds: float | None = None,
        input_summary: str | None = None,
        **extra: Any,
    ) -> None:
        """Log pipeline execution started."""
        context = LogContext(
            execution_id=execution_id,
            pipeline_name=pipeline_name,
            tenant_id=tenant_id,
            extra={
                "event": "pipeline_started",
                "step_count": step_count,
                **extra,
            },
        )
        if estimated_cost_usd is not None:
            context.extra["estimated_cost_usd"] = str(estimated_cost_usd)
        if estimated_duration_seconds is not None:
            context.extra["estimated_duration_seconds"] = estimated_duration_seconds
        if input_summary:
            context.extra["input_summary"] = input_summary[:200]  # Truncate

        self._log(
            logging.INFO,
            f"Pipeline started: {pipeline_name}",
            context,
        )

    def pipeline_completed(
        self,
        pipeline_name: str,
        execution_id: str,
        tenant_id: str | None = None,
        success: bool = True,
        duration_ms: float = 0,
        total_cost_usd: Decimal | None = None,
        completed_steps: list[str] | None = None,
        output_summary: str | None = None,
        **extra: Any,
    ) -> None:
        """Log pipeline execution completed."""
        context = LogContext(
            execution_id=execution_id,
            pipeline_name=pipeline_name,
            tenant_id=tenant_id,
            extra={
                "event": "pipeline_completed",
                "success": success,
                "duration_ms": duration_ms,
                "completed_step_count": len(completed_steps) if completed_steps else 0,
                **extra,
            },
        )
        if total_cost_usd is not None:
            context.extra["total_cost_usd"] = str(total_cost_usd)
        if completed_steps:
            context.extra["completed_steps"] = completed_steps
        if output_summary:
            context.extra["output_summary"] = output_summary[:200]

        level = logging.INFO if success else logging.WARNING
        status = "succeeded" if success else "failed"
        self._log(
            level,
            f"Pipeline {status}: {pipeline_name} ({duration_ms:.2f}ms)",
            context,
        )

    def pipeline_failed(
        self,
        pipeline_name: str,
        execution_id: str,
        error: str,
        error_type: str | None = None,
        failed_step: str | None = None,
        tenant_id: str | None = None,
        duration_ms: float = 0,
        completed_steps: list[str] | None = None,
        total_cost_usd: Decimal | None = None,
        compensation_triggered: bool = False,
        **extra: Any,
    ) -> None:
        """Log pipeline execution failed."""
        context = LogContext(
            execution_id=execution_id,
            pipeline_name=pipeline_name,
            tenant_id=tenant_id,
            step_name=failed_step,
            extra={
                "event": "pipeline_failed",
                "error": error,
                "error_type": error_type,
                "duration_ms": duration_ms,
                "completed_step_count": len(completed_steps) if completed_steps else 0,
                "compensation_triggered": compensation_triggered,
                **extra,
            },
        )
        if total_cost_usd is not None:
            context.extra["total_cost_usd"] = str(total_cost_usd)
        if completed_steps:
            context.extra["completed_steps"] = completed_steps

        self._log(
            logging.ERROR,
            f"Pipeline failed: {pipeline_name} - {error}",
            context,
        )

    # =========================================================================
    # Step Logging
    # =========================================================================

    def step_started(
        self,
        step_name: str,
        pipeline_name: str,
        execution_id: str,
        step_index: int = 0,
        capability: str | None = None,
        provider_preference: list[str] | None = None,
        timeout_seconds: float | None = None,
        **extra: Any,
    ) -> None:
        """Log step execution started."""
        context = LogContext(
            execution_id=execution_id,
            pipeline_name=pipeline_name,
            step_name=step_name,
            step_index=step_index,
            capability=capability,
            extra={
                "event": "step_started",
                **extra,
            },
        )
        if provider_preference:
            context.extra["provider_preference"] = provider_preference
        if timeout_seconds:
            context.extra["timeout_seconds"] = timeout_seconds

        self._log(
            logging.DEBUG,
            f"Step started: {step_name} ({capability or 'unknown'})",
            context,
        )

    def step_completed(
        self,
        step_name: str,
        pipeline_name: str,
        execution_id: str,
        provider_used: str | None = None,
        duration_ms: float = 0,
        cost_usd: Decimal | None = None,
        retries: int = 0,
        fallbacks_attempted: list[str] | None = None,
        **extra: Any,
    ) -> None:
        """Log step execution completed."""
        context = LogContext(
            execution_id=execution_id,
            pipeline_name=pipeline_name,
            step_name=step_name,
            provider=provider_used,
            extra={
                "event": "step_completed",
                "duration_ms": duration_ms,
                "retries": retries,
                **extra,
            },
        )
        if cost_usd is not None:
            context.extra["cost_usd"] = str(cost_usd)
        if fallbacks_attempted:
            context.extra["fallbacks_attempted"] = fallbacks_attempted
            context.extra["fallback_count"] = len(fallbacks_attempted)

        self._log(
            logging.DEBUG,
            f"Step completed: {step_name} via {provider_used or 'unknown'} ({duration_ms:.2f}ms)",
            context,
        )

    def step_failed(
        self,
        step_name: str,
        pipeline_name: str,
        execution_id: str,
        error: str,
        error_type: str | None = None,
        provider_used: str | None = None,
        duration_ms: float = 0,
        retries_exhausted: bool = False,
        fallbacks_exhausted: bool = False,
        **extra: Any,
    ) -> None:
        """Log step execution failed."""
        context = LogContext(
            execution_id=execution_id,
            pipeline_name=pipeline_name,
            step_name=step_name,
            provider=provider_used,
            extra={
                "event": "step_failed",
                "error": error,
                "error_type": error_type,
                "duration_ms": duration_ms,
                "retries_exhausted": retries_exhausted,
                "fallbacks_exhausted": fallbacks_exhausted,
                **extra,
            },
        )

        self._log(
            logging.WARNING,
            f"Step failed: {step_name} - {error}",
            context,
        )

    def step_skipped(
        self,
        step_name: str,
        pipeline_name: str,
        execution_id: str,
        reason: str,
        **extra: Any,
    ) -> None:
        """Log step skipped."""
        context = LogContext(
            execution_id=execution_id,
            pipeline_name=pipeline_name,
            step_name=step_name,
            extra={
                "event": "step_skipped",
                "skip_reason": reason,
                **extra,
            },
        )

        self._log(
            logging.DEBUG,
            f"Step skipped: {step_name} - {reason}",
            context,
        )

    def step_retrying(
        self,
        step_name: str,
        pipeline_name: str,
        execution_id: str,
        attempt: int,
        max_attempts: int,
        error: str,
        next_provider: str | None = None,
        backoff_seconds: float | None = None,
        **extra: Any,
    ) -> None:
        """Log step retry attempt."""
        context = LogContext(
            execution_id=execution_id,
            pipeline_name=pipeline_name,
            step_name=step_name,
            extra={
                "event": "step_retrying",
                "attempt": attempt,
                "max_attempts": max_attempts,
                "error": error,
                **extra,
            },
        )
        if next_provider:
            context.extra["next_provider"] = next_provider
        if backoff_seconds:
            context.extra["backoff_seconds"] = backoff_seconds

        self._log(
            logging.INFO,
            f"Step retrying: {step_name} (attempt {attempt}/{max_attempts})",
            context,
        )

    # =========================================================================
    # Provider Logging
    # =========================================================================

    def provider_request(
        self,
        provider: str,
        capability: str,
        execution_id: str | None = None,
        model: str | None = None,
        input_tokens: int | None = None,
        request_size_bytes: int | None = None,
        timeout_seconds: float | None = None,
        **extra: Any,
    ) -> None:
        """Log provider API request."""
        context = LogContext(
            execution_id=execution_id,
            provider=provider,
            capability=capability,
            extra={
                "event": "provider_request",
                **extra,
            },
        )
        if model:
            context.extra["model"] = model
        if input_tokens:
            context.extra["estimated_input_tokens"] = input_tokens
        if request_size_bytes:
            context.extra["request_size_bytes"] = request_size_bytes
        if timeout_seconds:
            context.extra["timeout_seconds"] = timeout_seconds

        self._log(
            logging.DEBUG,
            f"Provider request: {provider} ({capability})",
            context,
        )

    def provider_response(
        self,
        provider: str,
        capability: str,
        success: bool,
        latency_ms: float,
        execution_id: str | None = None,
        status_code: int | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cost_usd: Decimal | None = None,
        response_size_bytes: int | None = None,
        cached: bool = False,
        **extra: Any,
    ) -> None:
        """Log provider API response."""
        context = LogContext(
            execution_id=execution_id,
            provider=provider,
            capability=capability,
            extra={
                "event": "provider_response",
                "success": success,
                "latency_ms": latency_ms,
                "cached": cached,
                **extra,
            },
        )
        if status_code:
            context.extra["status_code"] = status_code
        if input_tokens:
            context.extra["input_tokens"] = input_tokens
        if output_tokens:
            context.extra["output_tokens"] = output_tokens
        if cost_usd is not None:
            context.extra["cost_usd"] = str(cost_usd)
        if response_size_bytes:
            context.extra["response_size_bytes"] = response_size_bytes

        level = logging.DEBUG if success else logging.WARNING
        status = "success" if success else "failed"
        self._log(
            level,
            f"Provider response: {provider} ({capability}) - {status} ({latency_ms:.2f}ms)",
            context,
        )

    def provider_error(
        self,
        provider: str,
        capability: str,
        error: str,
        error_type: str | None = None,
        error_code: str | None = None,
        retryable: bool = False,
        execution_id: str | None = None,
        latency_ms: float | None = None,
        status_code: int | None = None,
        **extra: Any,
    ) -> None:
        """Log provider API error."""
        context = LogContext(
            execution_id=execution_id,
            provider=provider,
            capability=capability,
            extra={
                "event": "provider_error",
                "error": error,
                "error_type": error_type,
                "error_code": error_code,
                "retryable": retryable,
                **extra,
            },
        )
        if latency_ms:
            context.extra["latency_ms"] = latency_ms
        if status_code:
            context.extra["status_code"] = status_code

        self._log(
            logging.WARNING,
            f"Provider error: {provider} ({capability}) - {error}",
            context,
        )

    # =========================================================================
    # Budget Logging
    # =========================================================================

    def budget_check(
        self,
        tenant_id: str,
        current_spend_usd: Decimal,
        limit_usd: Decimal | None,
        percent_used: float,
        action: str,
        estimated_cost_usd: Decimal | None = None,
        period: str = "monthly",
        **extra: Any,
    ) -> None:
        """Log budget check."""
        context = LogContext(
            tenant_id=tenant_id,
            extra={
                "event": "budget_check",
                "current_spend_usd": str(current_spend_usd),
                "percent_used": percent_used,
                "action": action,
                "period": period,
                **extra,
            },
        )
        if limit_usd is not None:
            context.extra["limit_usd"] = str(limit_usd)
        if estimated_cost_usd is not None:
            context.extra["estimated_cost_usd"] = str(estimated_cost_usd)

        level = logging.DEBUG
        if action == "blocked":
            level = logging.WARNING
        elif action == "warned":
            level = logging.INFO

        self._log(
            level,
            f"Budget check: {tenant_id} - {action} ({percent_used:.1f}% used)",
            context,
        )

    def budget_exceeded(
        self,
        tenant_id: str,
        current_spend_usd: Decimal,
        limit_usd: Decimal,
        period: str = "monthly",
        blocked: bool = True,
        **extra: Any,
    ) -> None:
        """Log budget exceeded event."""
        context = LogContext(
            tenant_id=tenant_id,
            extra={
                "event": "budget_exceeded",
                "current_spend_usd": str(current_spend_usd),
                "limit_usd": str(limit_usd),
                "period": period,
                "blocked": blocked,
                **extra,
            },
        )

        action = "blocked" if blocked else "warned"
        self._log(
            logging.WARNING,
            f"Budget exceeded: {tenant_id} - ${current_spend_usd}/{limit_usd} ({action})",
            context,
        )

    def spend_tracked(
        self,
        tenant_id: str,
        cost_usd: Decimal,
        pipeline_name: str | None = None,
        execution_id: str | None = None,
        provider: str | None = None,
        capability: str | None = None,
        **extra: Any,
    ) -> None:
        """Log spend tracked."""
        context = LogContext(
            tenant_id=tenant_id,
            execution_id=execution_id,
            pipeline_name=pipeline_name,
            provider=provider,
            capability=capability,
            extra={
                "event": "spend_tracked",
                "cost_usd": str(cost_usd),
                **extra,
            },
        )

        self._log(
            logging.DEBUG,
            f"Spend tracked: ${cost_usd} for {tenant_id}",
            context,
        )

    # =========================================================================
    # Performance Logging
    # =========================================================================

    def slow_operation(
        self,
        operation: str,
        duration_ms: float,
        threshold_ms: float,
        execution_id: str | None = None,
        details: dict[str, Any] | None = None,
        **extra: Any,
    ) -> None:
        """Log slow operation warning."""
        context = LogContext(
            execution_id=execution_id,
            extra={
                "event": "slow_operation",
                "operation": operation,
                "duration_ms": duration_ms,
                "threshold_ms": threshold_ms,
                "exceeded_by_ms": duration_ms - threshold_ms,
                **extra,
            },
        )
        if details:
            context.extra["details"] = details

        self._log(
            logging.WARNING,
            f"Slow operation: {operation} took {duration_ms:.2f}ms (threshold: {threshold_ms:.2f}ms)",
            context,
        )

    @contextmanager
    def timed_operation(
        self,
        operation: str,
        warn_threshold_ms: float = 5000,
        execution_id: str | None = None,
        **extra: Any,
    ) -> Iterator[dict[str, Any]]:
        """Context manager for timing operations with automatic slow logging.

        Example:
            with ai_logger.timed_operation("transcription", warn_threshold_ms=10000) as timing:
                result = await transcribe_audio()
                timing["details"] = {"audio_duration": 300}
        """
        timing_info: dict[str, Any] = {}
        start_time = time.perf_counter()
        try:
            yield timing_info
        finally:
            duration_ms = (time.perf_counter() - start_time) * 1000
            timing_info["duration_ms"] = duration_ms

            if duration_ms > warn_threshold_ms:
                self.slow_operation(
                    operation=operation,
                    duration_ms=duration_ms,
                    threshold_ms=warn_threshold_ms,
                    execution_id=execution_id,
                    details=timing_info.get("details"),
                    **extra,
                )

    # =========================================================================
    # Compensation Logging
    # =========================================================================

    def compensation_started(
        self,
        pipeline_name: str,
        execution_id: str,
        reason: str,
        steps_to_compensate: list[str],
        **extra: Any,
    ) -> None:
        """Log compensation started."""
        context = LogContext(
            execution_id=execution_id,
            pipeline_name=pipeline_name,
            extra={
                "event": "compensation_started",
                "reason": reason,
                "steps_to_compensate": steps_to_compensate,
                "step_count": len(steps_to_compensate),
                **extra,
            },
        )

        self._log(
            logging.INFO,
            f"Compensation started: {pipeline_name} ({len(steps_to_compensate)} steps)",
            context,
        )

    def compensation_completed(
        self,
        pipeline_name: str,
        execution_id: str,
        success: bool,
        compensated_steps: list[str],
        failed_steps: list[str] | None = None,
        duration_ms: float = 0,
        **extra: Any,
    ) -> None:
        """Log compensation completed."""
        context = LogContext(
            execution_id=execution_id,
            pipeline_name=pipeline_name,
            extra={
                "event": "compensation_completed",
                "success": success,
                "compensated_steps": compensated_steps,
                "compensated_count": len(compensated_steps),
                "duration_ms": duration_ms,
                **extra,
            },
        )
        if failed_steps:
            context.extra["failed_steps"] = failed_steps
            context.extra["failed_count"] = len(failed_steps)

        level = logging.INFO if success else logging.WARNING
        status = "succeeded" if success else "partially failed"
        self._log(
            level,
            f"Compensation {status}: {pipeline_name} ({len(compensated_steps)} steps)",
            context,
        )

    # =========================================================================
    # Generic Logging with Context
    # =========================================================================

    def info(self, message: str, **kwargs: Any) -> None:
        """Log info message with context."""
        self._log(logging.INFO, message, **kwargs)

    def debug(self, message: str, **kwargs: Any) -> None:
        """Log debug message with context."""
        self._log(logging.DEBUG, message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        """Log warning message with context."""
        self._log(logging.WARNING, message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        """Log error message with context."""
        self._log(logging.ERROR, message, **kwargs)

    # =========================================================================
    # Context Managers
    # =========================================================================

    @asynccontextmanager
    async def pipeline_context(
        self,
        pipeline: PipelineDefinition,
        context: PipelineContext,
    ) -> AsyncIterator[PipelineLogContext]:
        """Async context manager for pipeline execution logging.

        Automatically logs pipeline start/complete/fail with timing.

        Example:
            async with ai_logger.pipeline_context(pipeline, ctx) as log_ctx:
                for step in pipeline.steps:
                    async with log_ctx.step_context(step) as step_log:
                        result = await execute_step()
                        step_log.record_result(result)
        """
        start_time = time.perf_counter()

        self.pipeline_started(
            pipeline_name=pipeline.name,
            execution_id=context.execution_id,
            tenant_id=context.tenant_id,
            step_count=len(pipeline.steps),
            estimated_cost_usd=pipeline.estimated_cost_usd,
            estimated_duration_seconds=pipeline.estimated_duration_seconds,
        )

        log_ctx = PipelineLogContext(
            logger=self,
            pipeline=pipeline,
            context=context,
            start_time=start_time,
        )

        try:
            yield log_ctx
            # Log success
            duration_ms = (time.perf_counter() - start_time) * 1000
            self.pipeline_completed(
                pipeline_name=pipeline.name,
                execution_id=context.execution_id,
                tenant_id=context.tenant_id,
                success=True,
                duration_ms=duration_ms,
                total_cost_usd=log_ctx.total_cost_usd,
                completed_steps=log_ctx.completed_steps,
            )
        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            self.pipeline_failed(
                pipeline_name=pipeline.name,
                execution_id=context.execution_id,
                error=str(e),
                error_type=type(e).__name__,
                failed_step=log_ctx.current_step,
                tenant_id=context.tenant_id,
                duration_ms=duration_ms,
                completed_steps=log_ctx.completed_steps,
                total_cost_usd=log_ctx.total_cost_usd,
            )
            raise


@dataclass
class PipelineLogContext:
    """Context for pipeline-scoped logging."""

    logger: AIObservabilityLogger
    pipeline: PipelineDefinition
    context: PipelineContext
    start_time: float
    completed_steps: list[str] = field(default_factory=list)
    current_step: str | None = None
    total_cost_usd: Decimal = field(default_factory=lambda: Decimal(0))

    @asynccontextmanager
    async def step_context(
        self,
        step: PipelineStep,
        step_index: int = 0,
    ) -> AsyncIterator[StepLogContext]:
        """Async context manager for step execution logging."""
        step_start = time.perf_counter()
        self.current_step = step.name

        self.logger.step_started(
            step_name=step.name,
            pipeline_name=self.pipeline.name,
            execution_id=self.context.execution_id,
            step_index=step_index,
            capability=step.capability.value if step.capability else None,
            provider_preference=step.provider_preference,
            timeout_seconds=step.timeout_seconds,
        )

        step_ctx = StepLogContext(
            logger=self.logger,
            step=step,
            pipeline_name=self.pipeline.name,
            execution_id=self.context.execution_id,
            step_index=step_index,
            start_time=step_start,
        )

        try:
            yield step_ctx
            # Auto-log completion if result was recorded
            if step_ctx.result_recorded:
                self.completed_steps.append(step.name)
                self.total_cost_usd += step_ctx.cost_usd
        finally:
            self.current_step = None


@dataclass
class StepLogContext:
    """Context for step-scoped logging."""

    logger: AIObservabilityLogger
    step: PipelineStep
    pipeline_name: str
    execution_id: str
    step_index: int
    start_time: float
    result_recorded: bool = False
    cost_usd: Decimal = field(default_factory=lambda: Decimal(0))

    def record_result(self, result: StepResult) -> None:
        """Record step result."""
        duration_ms = (time.perf_counter() - self.start_time) * 1000
        self.result_recorded = True
        self.cost_usd = result.cost_usd

        if result.error:
            self.logger.step_failed(
                step_name=self.step.name,
                pipeline_name=self.pipeline_name,
                execution_id=self.execution_id,
                error=result.error,
                provider_used=result.provider_used,
                duration_ms=duration_ms,
            )
        else:
            self.logger.step_completed(
                step_name=self.step.name,
                pipeline_name=self.pipeline_name,
                execution_id=self.execution_id,
                provider_used=result.provider_used,
                duration_ms=duration_ms,
                cost_usd=result.cost_usd,
                retries=result.retries,
                fallbacks_attempted=result.fallbacks_attempted,
            )

    def record_skip(self, reason: str) -> None:
        """Record step skipped."""
        self.result_recorded = True
        self.logger.step_skipped(
            step_name=self.step.name,
            pipeline_name=self.pipeline_name,
            execution_id=self.execution_id,
            reason=reason,
        )


# Singleton instance
_ai_logger: AIObservabilityLogger | None = None


def get_ai_logger() -> AIObservabilityLogger:
    """Get the global AI observability logger singleton.

    Returns:
        The singleton AIObservabilityLogger instance
    """
    global _ai_logger
    if _ai_logger is None:
        _ai_logger = AIObservabilityLogger()
    return _ai_logger


def configure_ai_logger(
    logger_name: str = "example_service.ai",
    metrics: Any = None,
    include_trace_context: bool = True,
) -> AIObservabilityLogger:
    """Configure and return the global AI observability logger.

    Args:
        logger_name: Name for the underlying Python logger
        metrics: Optional AIMetrics instance for recording metrics
        include_trace_context: Whether to include trace IDs in logs

    Returns:
        Configured AIObservabilityLogger instance
    """
    global _ai_logger
    _ai_logger = AIObservabilityLogger(
        logger_name=logger_name,
        metrics=metrics,
        include_trace_context=include_trace_context,
    )
    return _ai_logger
