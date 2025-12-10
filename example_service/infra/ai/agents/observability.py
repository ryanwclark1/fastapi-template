"""Observability for AI agents.

This module provides comprehensive observability including:
- OpenTelemetry tracing for agent execution
- Prometheus metrics for monitoring
- Structured logging
- Event emission for real-time updates

Span Hierarchy:
    ai.agent.execute (root)
    ├── ai.agent.iteration.1
    │   ├── ai.agent.llm_call
    │   │   └── ai.provider.openai
    │   └── ai.agent.tool.web_search
    ├── ai.agent.iteration.2
    │   └── ai.agent.llm_call
    └── ai.agent.checkpoint

Metrics:
    - ai_agent_executions_total: Counter of agent executions
    - ai_agent_duration_seconds: Histogram of execution duration
    - ai_agent_cost_usd: Summary of costs
    - ai_agent_iterations_total: Counter of iterations
    - ai_agent_tool_calls_total: Counter of tool calls
    - ai_agent_errors_total: Counter of errors

Example:
    from example_service.infra.ai.agents.observability import AgentTracer

    tracer = AgentTracer()

    async with tracer.agent_span(agent) as span:
        async with tracer.iteration_span(1) as iter_span:
            result = await agent.run(input_data)
            iter_span.record_result(result)
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
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

try:
    from prometheus_client import Counter, Histogram, Summary

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    Counter = None  # type: ignore[assignment, misc]
    Histogram = None  # type: ignore[assignment, misc]
    Summary = None  # type: ignore[assignment, misc]

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from uuid import UUID

    from example_service.infra.ai.agents.base import (
        AgentResult,
        AgentState,
        BaseAgent,
        LLMResponse,
    )
    from example_service.infra.ai.agents.tools import ToolResult

logger = logging.getLogger(__name__)


# =============================================================================
# Prometheus Metrics
# =============================================================================

if PROMETHEUS_AVAILABLE:
    AGENT_EXECUTIONS = Counter(
        "ai_agent_executions_total",
        "Total number of agent executions",
        ["agent_type", "tenant_id", "status"],
    )

    AGENT_DURATION = Histogram(
        "ai_agent_duration_seconds",
        "Agent execution duration in seconds",
        ["agent_type", "tenant_id"],
        buckets=[1, 5, 10, 30, 60, 120, 300, 600],
    )

    AGENT_COST = Summary(
        "ai_agent_cost_usd",
        "Agent execution cost in USD",
        ["agent_type", "tenant_id"],
    )

    AGENT_ITERATIONS = Counter(
        "ai_agent_iterations_total",
        "Total number of agent iterations",
        ["agent_type", "tenant_id"],
    )

    AGENT_TOOL_CALLS = Counter(
        "ai_agent_tool_calls_total",
        "Total number of tool calls",
        ["agent_type", "tool_name", "tenant_id", "success"],
    )

    AGENT_LLM_CALLS = Counter(
        "ai_agent_llm_calls_total",
        "Total number of LLM calls",
        ["agent_type", "provider", "model", "tenant_id"],
    )

    AGENT_TOKENS = Counter(
        "ai_agent_tokens_total",
        "Total tokens consumed",
        ["agent_type", "tenant_id", "direction"],
    )

    AGENT_ERRORS = Counter(
        "ai_agent_errors_total",
        "Total number of agent errors",
        ["agent_type", "tenant_id", "error_code"],
    )

    AGENT_CHECKPOINTS = Counter(
        "ai_agent_checkpoints_total",
        "Total number of checkpoints created",
        ["agent_type", "tenant_id"],
    )

else:
    # No-op metrics when Prometheus is not available
    class NoOpMetric:
        def labels(self, *args: Any, **kwargs: Any) -> "NoOpMetric":
            return self

        def inc(self, *args: Any, **kwargs: Any) -> None:
            pass

        def observe(self, *args: Any, **kwargs: Any) -> None:
            pass

    AGENT_EXECUTIONS = NoOpMetric()  # type: ignore[assignment]
    AGENT_DURATION = NoOpMetric()  # type: ignore[assignment]
    AGENT_COST = NoOpMetric()  # type: ignore[assignment]
    AGENT_ITERATIONS = NoOpMetric()  # type: ignore[assignment]
    AGENT_TOOL_CALLS = NoOpMetric()  # type: ignore[assignment]
    AGENT_LLM_CALLS = NoOpMetric()  # type: ignore[assignment]
    AGENT_TOKENS = NoOpMetric()  # type: ignore[assignment]
    AGENT_ERRORS = NoOpMetric()  # type: ignore[assignment]
    AGENT_CHECKPOINTS = NoOpMetric()  # type: ignore[assignment]


# =============================================================================
# Agent Tracer
# =============================================================================


class AgentTracer:
    """OpenTelemetry tracer for AI agents.

    Provides context managers for creating spans at different levels:
    - agent_span: Root span for entire agent execution
    - iteration_span: Span for each iteration
    - llm_span: Span for LLM calls
    - tool_span: Span for tool executions
    """

    AGENT_PREFIX = "ai.agent"

    def __init__(
        self,
        tracer_name: str = "ai.agents",
        enabled: bool = True,
    ) -> None:
        """Initialize agent tracer.

        Args:
            tracer_name: Name for the OpenTelemetry tracer
            enabled: Whether tracing is enabled
        """
        self.tracer_name = tracer_name
        self.enabled = enabled and OTEL_AVAILABLE

        if self.enabled:
            if trace is None:
                msg = "OpenTelemetry trace module not available"
                raise RuntimeError(msg)
            self._tracer = trace.get_tracer(tracer_name)
        else:
            self._tracer = None  # type: ignore[assignment]

    @asynccontextmanager
    async def agent_span(
        self,
        agent: BaseAgent[Any, Any],
        run_id: UUID,
        tenant_id: str | None = None,
    ) -> AsyncIterator[AgentSpan]:
        """Create a span for agent execution.

        Args:
            agent: Agent being executed
            run_id: Unique run identifier
            tenant_id: Tenant ID

        Yields:
            AgentSpan wrapper for recording results
        """
        if not self.enabled:
            yield NoOpAgentSpan()  # type: ignore[misc]
            return

        span_name = f"{self.AGENT_PREFIX}.{agent.agent_type}"

        if self._tracer is None:
            msg = "Tracer not initialized"
            raise RuntimeError(msg)

        with self._tracer.start_as_current_span(
            span_name,
            kind=SpanKind.INTERNAL,
            attributes={
                f"{self.AGENT_PREFIX}.type": agent.agent_type,
                f"{self.AGENT_PREFIX}.version": agent.agent_version,
                f"{self.AGENT_PREFIX}.run_id": str(run_id),
                f"{self.AGENT_PREFIX}.tenant_id": tenant_id or "",
                f"{self.AGENT_PREFIX}.model": agent.config.model,
                f"{self.AGENT_PREFIX}.provider": agent.config.provider,
                f"{self.AGENT_PREFIX}.max_iterations": agent.config.max_iterations,
            },
        ) as span:
            agent_span = AgentSpan(span, self.AGENT_PREFIX, agent.agent_type, tenant_id)
            try:
                yield agent_span
            except Exception as e:
                agent_span.record_error(e)
                raise

    @asynccontextmanager
    async def iteration_span(
        self,
        agent_type: str,
        iteration: int,
        tenant_id: str | None = None,
    ) -> AsyncIterator[IterationSpan]:
        """Create a span for an agent iteration.

        Args:
            agent_type: Type of agent
            iteration: Iteration number
            tenant_id: Tenant ID

        Yields:
            IterationSpan wrapper
        """
        if not self.enabled:
            yield NoOpIterationSpan()  # type: ignore[misc]
            return

        span_name = f"{self.AGENT_PREFIX}.iteration.{iteration}"

        if self._tracer is None:
            msg = "Tracer not initialized"
            raise RuntimeError(msg)

        with self._tracer.start_as_current_span(
            span_name,
            kind=SpanKind.INTERNAL,
            attributes={
                f"{self.AGENT_PREFIX}.iteration": iteration,
                f"{self.AGENT_PREFIX}.type": agent_type,
            },
        ) as span:
            iter_span = IterationSpan(span, self.AGENT_PREFIX, agent_type, tenant_id)
            # Record iteration metric
            AGENT_ITERATIONS.labels(
                agent_type=agent_type,
                tenant_id=tenant_id or "",
            ).inc()
            try:
                yield iter_span
            except Exception as e:
                iter_span.record_error(e)
                raise

    @asynccontextmanager
    async def llm_span(
        self,
        agent_type: str,
        provider: str,
        model: str,
        tenant_id: str | None = None,
    ) -> AsyncIterator[LLMSpan]:
        """Create a span for an LLM call.

        Args:
            agent_type: Type of agent
            provider: LLM provider
            model: Model name
            tenant_id: Tenant ID

        Yields:
            LLMSpan wrapper
        """
        if not self.enabled:
            yield NoOpLLMSpan()  # type: ignore[misc]
            return

        span_name = f"{self.AGENT_PREFIX}.llm_call"

        if self._tracer is None:
            msg = "Tracer not initialized"
            raise RuntimeError(msg)

        with self._tracer.start_as_current_span(
            span_name,
            kind=SpanKind.CLIENT,
            attributes={
                f"{self.AGENT_PREFIX}.llm.provider": provider,
                f"{self.AGENT_PREFIX}.llm.model": model,
            },
        ) as span:
            llm_span = LLMSpan(span, self.AGENT_PREFIX, agent_type, tenant_id)
            # Record LLM call metric
            AGENT_LLM_CALLS.labels(
                agent_type=agent_type,
                provider=provider,
                model=model,
                tenant_id=tenant_id or "",
            ).inc()
            try:
                yield llm_span
            except Exception as e:
                llm_span.record_error(e)
                raise

    @asynccontextmanager
    async def tool_span(
        self,
        agent_type: str,
        tool_name: str,
        tenant_id: str | None = None,
    ) -> AsyncIterator[ToolSpan]:
        """Create a span for a tool call.

        Args:
            agent_type: Type of agent
            tool_name: Name of the tool
            tenant_id: Tenant ID

        Yields:
            ToolSpan wrapper
        """
        if not self.enabled:
            yield NoOpToolSpan()  # type: ignore[misc]
            return

        span_name = f"{self.AGENT_PREFIX}.tool.{tool_name}"

        if self._tracer is None:
            msg = "Tracer not initialized"
            raise RuntimeError(msg)

        with self._tracer.start_as_current_span(
            span_name,
            kind=SpanKind.INTERNAL,
            attributes={
                f"{self.AGENT_PREFIX}.tool.name": tool_name,
            },
        ) as span:
            tool_span = ToolSpan(span, self.AGENT_PREFIX, agent_type, tool_name, tenant_id)
            try:
                yield tool_span
            except Exception as e:
                tool_span.record_error(e)
                raise


# =============================================================================
# Span Wrappers
# =============================================================================


class AgentSpan:
    """Wrapper for agent execution span."""

    def __init__(
        self,
        span: Span,
        prefix: str,
        agent_type: str,
        tenant_id: str | None,
    ) -> None:
        self._span = span
        self._prefix = prefix
        self._agent_type = agent_type
        self._tenant_id = tenant_id
        self._started_at = datetime.now(UTC)

    def set_attribute(self, key: str, value: Any) -> None:
        """Set a span attribute."""
        self._span.set_attribute(f"{self._prefix}.{key}", value)

    def record_result(self, result: AgentResult[Any]) -> None:
        """Record agent execution result."""
        duration = (datetime.now(UTC) - self._started_at).total_seconds()

        self._span.set_attribute(f"{self._prefix}.success", result.success)
        self._span.set_attribute(f"{self._prefix}.iterations", result.iterations)
        self._span.set_attribute(f"{self._prefix}.steps", result.steps)
        self._span.set_attribute(f"{self._prefix}.tool_calls", result.tool_calls)
        self._span.set_attribute(
            f"{self._prefix}.cost_usd", float(result.total_cost_usd)
        )
        self._span.set_attribute(
            f"{self._prefix}.input_tokens", result.total_input_tokens
        )
        self._span.set_attribute(
            f"{self._prefix}.output_tokens", result.total_output_tokens
        )
        self._span.set_attribute(f"{self._prefix}.duration_seconds", duration)

        if result.error:
            self._span.set_attribute(f"{self._prefix}.error", result.error)
            self._span.set_attribute(
                f"{self._prefix}.error_code", result.error_code or ""
            )
            self._span.set_status(Status(StatusCode.ERROR, result.error))

            AGENT_ERRORS.labels(
                agent_type=self._agent_type,
                tenant_id=self._tenant_id or "",
                error_code=result.error_code or "unknown",
            ).inc()
        else:
            self._span.set_status(Status(StatusCode.OK))

        # Record metrics
        status = "success" if result.success else "failure"
        AGENT_EXECUTIONS.labels(
            agent_type=self._agent_type,
            tenant_id=self._tenant_id or "",
            status=status,
        ).inc()

        AGENT_DURATION.labels(
            agent_type=self._agent_type,
            tenant_id=self._tenant_id or "",
        ).observe(duration)

        AGENT_COST.labels(
            agent_type=self._agent_type,
            tenant_id=self._tenant_id or "",
        ).observe(float(result.total_cost_usd))

        AGENT_TOKENS.labels(
            agent_type=self._agent_type,
            tenant_id=self._tenant_id or "",
            direction="input",
        ).inc(result.total_input_tokens)

        AGENT_TOKENS.labels(
            agent_type=self._agent_type,
            tenant_id=self._tenant_id or "",
            direction="output",
        ).inc(result.total_output_tokens)

    def record_error(self, exception: Exception) -> None:
        """Record an exception."""
        self._span.record_exception(exception)
        self._span.set_status(Status(StatusCode.ERROR, str(exception)))

        AGENT_ERRORS.labels(
            agent_type=self._agent_type,
            tenant_id=self._tenant_id or "",
            error_code="exception",
        ).inc()


class IterationSpan:
    """Wrapper for iteration span."""

    def __init__(
        self,
        span: Span,
        prefix: str,
        agent_type: str,
        tenant_id: str | None,
    ) -> None:
        self._span = span
        self._prefix = prefix
        self._agent_type = agent_type
        self._tenant_id = tenant_id

    def set_attribute(self, key: str, value: Any) -> None:
        """Set a span attribute."""
        self._span.set_attribute(f"{self._prefix}.{key}", value)

    def record_state(self, state: AgentState) -> None:
        """Record iteration state."""
        self._span.set_attribute(f"{self._prefix}.step_count", state.step_count)
        self._span.set_attribute(
            f"{self._prefix}.tool_call_count", state.tool_call_count
        )
        self._span.set_attribute(
            f"{self._prefix}.cost_usd", float(state.total_cost_usd)
        )
        self._span.set_attribute(f"{self._prefix}.is_complete", state.is_complete)

    def record_error(self, exception: Exception) -> None:
        """Record an exception."""
        self._span.record_exception(exception)
        self._span.set_status(Status(StatusCode.ERROR, str(exception)))


class LLMSpan:
    """Wrapper for LLM call span."""

    def __init__(
        self,
        span: Span,
        prefix: str,
        agent_type: str,
        tenant_id: str | None,
    ) -> None:
        self._span = span
        self._prefix = prefix
        self._agent_type = agent_type
        self._tenant_id = tenant_id

    def set_attribute(self, key: str, value: Any) -> None:
        """Set a span attribute."""
        self._span.set_attribute(f"{self._prefix}.{key}", value)

    def record_response(self, response: LLMResponse) -> None:
        """Record LLM response."""
        self._span.set_attribute(
            f"{self._prefix}.llm.input_tokens", response.input_tokens
        )
        self._span.set_attribute(
            f"{self._prefix}.llm.output_tokens", response.output_tokens
        )
        self._span.set_attribute(
            f"{self._prefix}.llm.cost_usd", float(response.cost_usd)
        )
        self._span.set_attribute(
            f"{self._prefix}.llm.tool_calls", len(response.tool_calls)
        )
        if response.latency_ms:
            self._span.set_attribute(
                f"{self._prefix}.llm.latency_ms", response.latency_ms
            )
        self._span.set_status(Status(StatusCode.OK))

        # Record token metrics
        AGENT_TOKENS.labels(
            agent_type=self._agent_type,
            tenant_id=self._tenant_id or "",
            direction="input",
        ).inc(response.input_tokens)

        AGENT_TOKENS.labels(
            agent_type=self._agent_type,
            tenant_id=self._tenant_id or "",
            direction="output",
        ).inc(response.output_tokens)

    def record_error(self, exception: Exception) -> None:
        """Record an exception."""
        self._span.record_exception(exception)
        self._span.set_status(Status(StatusCode.ERROR, str(exception)))


class ToolSpan:
    """Wrapper for tool call span."""

    def __init__(
        self,
        span: Span,
        prefix: str,
        agent_type: str,
        tool_name: str,
        tenant_id: str | None,
    ) -> None:
        self._span = span
        self._prefix = prefix
        self._agent_type = agent_type
        self._tool_name = tool_name
        self._tenant_id = tenant_id

    def set_attribute(self, key: str, value: Any) -> None:
        """Set a span attribute."""
        self._span.set_attribute(f"{self._prefix}.{key}", value)

    def record_result(self, result: ToolResult[Any]) -> None:
        """Record tool result."""
        self._span.set_attribute(f"{self._prefix}.tool.success", result.is_success)
        self._span.set_attribute(f"{self._prefix}.tool.status", result.status.value)
        if result.duration_ms:
            self._span.set_attribute(
                f"{self._prefix}.tool.duration_ms", result.duration_ms
            )
        if result.error:
            self._span.set_attribute(f"{self._prefix}.tool.error", result.error)
            self._span.set_status(Status(StatusCode.ERROR, result.error))
        else:
            self._span.set_status(Status(StatusCode.OK))

        # Record metric
        AGENT_TOOL_CALLS.labels(
            agent_type=self._agent_type,
            tool_name=self._tool_name,
            tenant_id=self._tenant_id or "",
            success=str(result.is_success).lower(),
        ).inc()

    def record_error(self, exception: Exception) -> None:
        """Record an exception."""
        self._span.record_exception(exception)
        self._span.set_status(Status(StatusCode.ERROR, str(exception)))

        AGENT_TOOL_CALLS.labels(
            agent_type=self._agent_type,
            tool_name=self._tool_name,
            tenant_id=self._tenant_id or "",
            success="false",
        ).inc()


# =============================================================================
# No-Op Implementations
# =============================================================================


class NoOpAgentSpan:
    """No-op agent span when tracing is disabled."""

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def record_result(self, result: Any) -> None:
        pass

    def record_error(self, exception: Exception) -> None:
        pass


class NoOpIterationSpan:
    """No-op iteration span when tracing is disabled."""

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def record_state(self, state: Any) -> None:
        pass

    def record_error(self, exception: Exception) -> None:
        pass


class NoOpLLMSpan:
    """No-op LLM span when tracing is disabled."""

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def record_response(self, response: Any) -> None:
        pass

    def record_error(self, exception: Exception) -> None:
        pass


class NoOpToolSpan:
    """No-op tool span when tracing is disabled."""

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def record_result(self, result: Any) -> None:
        pass

    def record_error(self, exception: Exception) -> None:
        pass


# =============================================================================
# Singleton
# =============================================================================

_tracer: AgentTracer | None = None


def get_agent_tracer() -> AgentTracer:
    """Get the global agent tracer singleton."""
    global _tracer
    if _tracer is None:
        _tracer = AgentTracer()
    return _tracer


def configure_agent_tracer(
    tracer_name: str = "ai.agents",
    enabled: bool = True,
) -> AgentTracer:
    """Configure and return the global agent tracer."""
    global _tracer
    _tracer = AgentTracer(tracer_name=tracer_name, enabled=enabled)
    return _tracer


# =============================================================================
# Agent Logger
# =============================================================================


class AgentLogger:
    """Structured logger for agent operations.

    Provides consistent log formatting with agent context.
    """

    def __init__(
        self,
        agent_type: str,
        run_id: UUID | None = None,
        tenant_id: str | None = None,
    ) -> None:
        self.agent_type = agent_type
        self.run_id = run_id
        self.tenant_id = tenant_id
        self._logger = logging.getLogger(f"ai.agent.{agent_type}")

    def _extra(self, **kwargs: Any) -> dict[str, Any]:
        """Build extra dict for structured logging."""
        extra = {
            "agent_type": self.agent_type,
        }
        if self.run_id:
            extra["run_id"] = str(self.run_id)
        if self.tenant_id:
            extra["tenant_id"] = self.tenant_id
        extra.update(kwargs)
        return extra

    def info(self, message: str, **kwargs: Any) -> None:
        """Log info message."""
        self._logger.info(message, extra=self._extra(**kwargs))

    def warning(self, message: str, **kwargs: Any) -> None:
        """Log warning message."""
        self._logger.warning(message, extra=self._extra(**kwargs))

    def error(self, message: str, **kwargs: Any) -> None:
        """Log error message."""
        self._logger.error(message, extra=self._extra(**kwargs))

    def debug(self, message: str, **kwargs: Any) -> None:
        """Log debug message."""
        self._logger.debug(message, extra=self._extra(**kwargs))

    def run_started(self, input_data: Any) -> None:
        """Log run started."""
        self.info(
            "Agent run started",
            event="run_started",
            input_summary=str(input_data)[:200],
        )

    def run_completed(self, result: AgentResult[Any]) -> None:
        """Log run completed."""
        self.info(
            "Agent run completed",
            event="run_completed",
            success=result.success,
            iterations=result.iterations,
            cost_usd=float(result.total_cost_usd),
            duration_seconds=result.duration_seconds,
        )

    def run_failed(self, error: str, error_code: str | None = None) -> None:
        """Log run failed."""
        self.error(
            "Agent run failed",
            event="run_failed",
            error=error,
            error_code=error_code,
        )

    def iteration_started(self, iteration: int) -> None:
        """Log iteration started."""
        self.debug(
            f"Iteration {iteration} started",
            event="iteration_started",
            iteration=iteration,
        )

    def tool_called(
        self,
        tool_name: str,
        success: bool,
        duration_ms: float | None = None,
    ) -> None:
        """Log tool call."""
        self.debug(
            f"Tool {tool_name} called",
            event="tool_called",
            tool_name=tool_name,
            success=success,
            duration_ms=duration_ms,
        )

    def checkpoint_created(self, checkpoint_name: str, step_number: int) -> None:
        """Log checkpoint created."""
        self.info(
            f"Checkpoint created: {checkpoint_name}",
            event="checkpoint_created",
            checkpoint_name=checkpoint_name,
            step_number=step_number,
        )

        AGENT_CHECKPOINTS.labels(
            agent_type=self.agent_type,
            tenant_id=self.tenant_id or "",
        ).inc()
