"""Tests for AI observability components.

Tests cover:
- AIObservabilityLogger structured logging
- AIMetrics Prometheus metrics
- AITracer OpenTelemetry tracing
- BudgetService budget tracking
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch
import pytest


class TestAIObservabilityLogger:
    """Tests for AIObservabilityLogger."""

    def test_logger_initialization(self) -> None:
        """Test logger initializes correctly."""
        from example_service.infra.ai.observability.logging import AIObservabilityLogger

        ai_logger = AIObservabilityLogger(
            logger_name="test.ai",
            include_trace_context=False,
        )
        assert ai_logger is not None
        assert ai_logger._logger is not None

    def test_pipeline_started_logging(self) -> None:
        """Test pipeline started event is logged."""
        from example_service.infra.ai.observability.logging import AIObservabilityLogger

        ai_logger = AIObservabilityLogger(
            logger_name="test.ai",
            include_trace_context=False,
        )

        with patch.object(ai_logger._logger, "log") as mock_log:
            ai_logger.pipeline_started(
                pipeline_name="test_pipeline",
                execution_id="exec-123",
                tenant_id="tenant-456",
                step_count=5,
                estimated_cost_usd=Decimal("0.50"),
            )

            mock_log.assert_called_once()
            args, kwargs = mock_log.call_args
            assert args[1] == "Pipeline started: test_pipeline"
            assert kwargs["extra"]["execution_id"] == "exec-123"
            assert kwargs["extra"]["pipeline_name"] == "test_pipeline"
            assert kwargs["extra"]["tenant_id"] == "tenant-456"
            assert kwargs["extra"]["step_count"] == 5

    def test_pipeline_completed_logging(self) -> None:
        """Test pipeline completed event is logged."""
        from example_service.infra.ai.observability.logging import AIObservabilityLogger

        ai_logger = AIObservabilityLogger(
            logger_name="test.ai",
            include_trace_context=False,
        )

        with patch.object(ai_logger._logger, "log") as mock_log:
            ai_logger.pipeline_completed(
                pipeline_name="test_pipeline",
                execution_id="exec-123",
                tenant_id="tenant-456",
                success=True,
                duration_ms=1500.0,
                total_cost_usd=Decimal("0.45"),
                completed_steps=["step1", "step2", "step3"],
            )

            mock_log.assert_called_once()
            args, kwargs = mock_log.call_args
            assert "succeeded" in args[1]
            assert kwargs["extra"]["success"] is True
            assert kwargs["extra"]["duration_ms"] == 1500.0

    def test_pipeline_failed_logging(self) -> None:
        """Test pipeline failed event is logged."""
        from example_service.infra.ai.observability.logging import AIObservabilityLogger

        ai_logger = AIObservabilityLogger(
            logger_name="test.ai",
            include_trace_context=False,
        )

        with patch.object(ai_logger._logger, "log") as mock_log:
            ai_logger.pipeline_failed(
                pipeline_name="test_pipeline",
                execution_id="exec-123",
                error="Provider timeout",
                error_type="TimeoutError",
                failed_step="transcription",
                tenant_id="tenant-456",
                duration_ms=30000.0,
                completed_steps=["step1"],
                compensation_triggered=True,
            )

            mock_log.assert_called_once()
            args, kwargs = mock_log.call_args
            assert "Pipeline failed" in args[1]
            assert kwargs["extra"]["error"] == "Provider timeout"
            assert kwargs["extra"]["compensation_triggered"] is True

    def test_step_logging(self) -> None:
        """Test step events are logged correctly."""
        from example_service.infra.ai.observability.logging import AIObservabilityLogger

        ai_logger = AIObservabilityLogger(
            logger_name="test.ai",
            include_trace_context=False,
        )

        with patch.object(ai_logger._logger, "log") as mock_log:
            ai_logger.step_started(
                step_name="transcription",
                pipeline_name="test_pipeline",
                execution_id="exec-123",
                step_index=0,
                capability="transcription",
            )

            assert mock_log.call_count == 1
            args, kwargs = mock_log.call_args
            assert "Step started" in args[1]
            assert kwargs["extra"]["step_name"] == "transcription"

    def test_provider_logging(self) -> None:
        """Test provider events are logged correctly."""
        from example_service.infra.ai.observability.logging import AIObservabilityLogger

        ai_logger = AIObservabilityLogger(
            logger_name="test.ai",
            include_trace_context=False,
        )

        with patch.object(ai_logger._logger, "log") as mock_log:
            ai_logger.provider_request(
                provider="openai",
                capability="llm_generation",
                model="gpt-4o",
                timeout_seconds=30.0,
            )

            assert mock_log.call_count == 1
            args, kwargs = mock_log.call_args
            assert "Provider request" in args[1]
            assert kwargs["extra"]["provider"] == "openai"
            assert kwargs["extra"]["model"] == "gpt-4o"

    def test_budget_logging(self) -> None:
        """Test budget events are logged correctly."""
        from example_service.infra.ai.observability.logging import AIObservabilityLogger

        ai_logger = AIObservabilityLogger(
            logger_name="test.ai",
            include_trace_context=False,
        )

        with patch.object(ai_logger._logger, "log") as mock_log:
            ai_logger.budget_check(
                tenant_id="tenant-123",
                current_spend_usd=Decimal("45.00"),
                limit_usd=Decimal("100.00"),
                percent_used=45.0,
                action="allowed",
            )

            assert mock_log.call_count == 1
            args, kwargs = mock_log.call_args
            assert "Budget check" in args[1]
            assert kwargs["extra"]["percent_used"] == 45.0

    def test_timed_operation_context_manager(self) -> None:
        """Test timed operation context manager."""
        from example_service.infra.ai.observability.logging import AIObservabilityLogger

        ai_logger = AIObservabilityLogger(
            logger_name="test.ai",
            include_trace_context=False,
        )

        with patch.object(ai_logger._logger, "log") as mock_log:
            # Fast operation - should not log warning
            with ai_logger.timed_operation(
                "fast_operation",
                warn_threshold_ms=10000,
            ) as timing:
                pass  # Instant operation

            # Should not have logged (operation was fast)
            assert mock_log.call_count == 0
            assert "duration_ms" in timing

    def test_log_context_to_dict(self) -> None:
        """Test LogContext converts to dict correctly."""
        from example_service.infra.ai.observability.logging import LogContext

        context = LogContext(
            execution_id="exec-123",
            pipeline_name="test_pipeline",
            tenant_id="tenant-456",
            step_name="transcription",
            extra={"custom_field": "value"},
        )

        result = context.to_dict()
        assert result["execution_id"] == "exec-123"
        assert result["pipeline_name"] == "test_pipeline"
        assert result["tenant_id"] == "tenant-456"
        assert result["step_name"] == "transcription"
        assert result["custom_field"] == "value"


class TestAIMetrics:
    """Tests for AIMetrics."""

    def test_metrics_initialization(self) -> None:
        """Test metrics initializes correctly."""
        from example_service.infra.ai.observability.metrics import AIMetrics

        metrics = AIMetrics(prefix="test_ai", enabled=True)
        assert metrics is not None
        assert metrics.enabled is True

    def test_metrics_disabled(self) -> None:
        """Test metrics are disabled correctly."""
        from example_service.infra.ai.observability.metrics import AIMetrics

        metrics = AIMetrics(prefix="test_ai_disabled", enabled=False)
        # Should not raise errors when recording with disabled metrics
        metrics.record_pipeline_execution(
            pipeline_name="test",
            status="success",
            duration_seconds=1.0,
            total_cost_usd=Decimal("0.01"),
        )

    def test_record_pipeline_execution(self) -> None:
        """Test recording pipeline execution metrics."""
        from example_service.infra.ai.observability.metrics import AIMetrics

        metrics = AIMetrics(prefix="test_pipeline_exec", enabled=True)

        # Record a successful execution
        metrics.record_pipeline_execution(
            pipeline_name="call_analysis",
            status="success",
            duration_seconds=45.5,
            total_cost_usd=Decimal("0.085"),
            steps_completed=5,
            tenant_id="tenant-123",
        )

        # Verify metrics were recorded (no exception = success)
        assert metrics.pipeline_executions_total is not None

    def test_record_provider_request(self) -> None:
        """Test recording provider request metrics."""
        from example_service.infra.ai.observability.metrics import AIMetrics

        metrics = AIMetrics(prefix="test_provider_req", enabled=True)

        metrics.record_provider_request(
            provider="openai",
            capability="llm_generation",
            status="success",
            latency_seconds=0.5,
            cost_usd=Decimal("0.01"),
            tenant_id="tenant-123",
        )

        assert metrics.provider_requests_total is not None

    def test_record_provider_timeout(self) -> None:
        """Test recording provider timeout."""
        from example_service.infra.ai.observability.metrics import AIMetrics

        metrics = AIMetrics(prefix="test_timeout", enabled=True)

        metrics.record_provider_timeout(
            provider="anthropic",
            capability="llm_generation",
        )

        assert metrics.provider_timeout_total is not None

    def test_record_budget_metrics(self) -> None:
        """Test recording budget metrics."""
        from example_service.infra.ai.observability.metrics import AIMetrics

        metrics = AIMetrics(prefix="test_budget", enabled=True)

        metrics.record_budget_status(
            tenant_id="tenant-123",
            period="monthly",
            spend_usd=Decimal("45.00"),
            limit_usd=Decimal("100.00"),
        )

        metrics.record_budget_exceeded(
            tenant_id="tenant-123",
            action="warned",
        )

        assert metrics.budget_spend_usd is not None
        assert metrics.budget_exceeded_total is not None

    def test_record_sli_metrics(self) -> None:
        """Test recording SLI metrics."""
        from example_service.infra.ai.observability.metrics import AIMetrics

        metrics = AIMetrics(prefix="test_sli", enabled=True)

        metrics.record_sli_availability(
            service="ai_pipeline",
            availability=0.999,
        )

        metrics.record_sli_latency_target(
            service="ai_pipeline",
            target_ms=5000,
            percent_met=0.95,
        )

        metrics.record_sli_error_budget(
            service="ai_pipeline",
            period="monthly",
            remaining=0.75,
        )

        assert metrics.sli_availability is not None

    def test_record_fallback_metrics(self) -> None:
        """Test recording fallback metrics."""
        from example_service.infra.ai.observability.metrics import AIMetrics

        metrics = AIMetrics(prefix="test_fallback", enabled=True)

        metrics.record_step_fallback(
            pipeline_name="call_analysis",
            step_name="transcription",
            from_provider="deepgram",
            to_provider="openai",
        )

        metrics.record_fallback_success_rate(
            from_provider="deepgram",
            to_provider="openai",
            success_rate=0.85,
        )

        assert metrics.step_fallbacks_total is not None


class TestAITracer:
    """Tests for AITracer."""

    def test_tracer_initialization_disabled(self) -> None:
        """Test tracer initializes with disabled state."""
        from example_service.infra.ai.observability.tracing import AITracer

        tracer = AITracer(enabled=False)
        assert tracer.enabled is False

    @pytest.mark.asyncio
    async def test_noop_pipeline_span(self) -> None:
        """Test no-op pipeline span when tracing disabled."""
        from example_service.infra.ai.observability.tracing import AITracer, NoOpPipelineSpan

        tracer = AITracer(enabled=False)

        # Create mock pipeline and context
        mock_pipeline = MagicMock()
        mock_pipeline.name = "test_pipeline"
        mock_pipeline.version = "1.0.0"
        mock_pipeline.steps = []

        mock_context = MagicMock()
        mock_context.execution_id = "exec-123"
        mock_context.tenant_id = "tenant-456"

        async with tracer.pipeline_span(mock_pipeline, mock_context) as span:
            assert isinstance(span, NoOpPipelineSpan)
            # Should not raise errors
            span.set_attribute("test", "value")
            span.record_success(["step1"], Decimal("0.01"), 100.0)

    @pytest.mark.asyncio
    async def test_noop_step_span(self) -> None:
        """Test no-op step span when tracing disabled."""
        from example_service.infra.ai.observability.tracing import AITracer, NoOpStepSpan

        tracer = AITracer(enabled=False)

        mock_step = MagicMock()
        mock_step.name = "test_step"
        mock_step.capability = MagicMock()
        mock_step.capability.value = "llm_generation"
        mock_step.provider_preference = ["openai"]
        mock_step.timeout_seconds = 30.0

        mock_context = MagicMock()
        mock_context.execution_id = "exec-123"

        async with tracer.step_span(mock_step, mock_context) as span:
            assert isinstance(span, NoOpStepSpan)
            span.set_attribute("test", "value")
            span.record_skip("condition_not_met")

    @pytest.mark.asyncio
    async def test_noop_provider_span(self) -> None:
        """Test no-op provider span when tracing disabled."""
        from example_service.infra.ai.observability.tracing import AITracer, NoOpProviderSpan

        tracer = AITracer(enabled=False)

        mock_context = MagicMock()
        mock_context.execution_id = "exec-123"

        async with tracer.provider_span(
            "openai",
            "llm_generation",
            mock_context,
            attempt=1,
        ) as span:
            assert isinstance(span, NoOpProviderSpan)
            span.set_attribute("test", "value")
            span.set_request_attributes(model="gpt-4o")
            span.set_fallback_info(is_fallback=False)

    @pytest.mark.asyncio
    async def test_noop_compensation_span(self) -> None:
        """Test no-op compensation span when tracing disabled."""
        from example_service.infra.ai.observability.tracing import (
            AITracer,
            NoOpCompensationSpan,
        )

        tracer = AITracer(enabled=False)

        mock_context = MagicMock()
        mock_context.execution_id = "exec-123"

        async with tracer.compensation_span(
            "test_pipeline",
            mock_context,
            "Step failed",
            ["step1", "step2"],
        ) as span:
            assert isinstance(span, NoOpCompensationSpan)
            span.record_step_started("step1", 0)
            span.record_step_completed("step1", success=True)
            span.record_success(["step1", "step2"], 500.0)


class TestBudgetService:
    """Tests for BudgetService."""

    @pytest.mark.asyncio
    async def test_budget_service_initialization(self) -> None:
        """Test budget service initializes correctly."""
        from example_service.infra.ai.observability.budget import BudgetService

        service = BudgetService()
        assert service is not None

    @pytest.mark.asyncio
    async def test_set_and_check_budget(self) -> None:
        """Test setting and checking budget."""
        from example_service.infra.ai.observability.budget import BudgetService

        service = BudgetService()

        # Set budget
        config = await service.set_budget(
            tenant_id="tenant-123",
            daily_limit_usd=Decimal("10.00"),
            monthly_limit_usd=Decimal("100.00"),
        )

        assert config.tenant_id == "tenant-123"
        assert config.daily_limit_usd == Decimal("10.00")
        assert config.monthly_limit_usd == Decimal("100.00")

        # Check budget
        result = await service.check_budget("tenant-123")
        assert result.allowed is True
        assert result.current_spend_usd == Decimal(0)

    @pytest.mark.asyncio
    async def test_track_spend(self) -> None:
        """Test tracking spend."""
        from example_service.infra.ai.observability.budget import BudgetService

        service = BudgetService()

        # Set budget
        await service.set_budget(
            tenant_id="tenant-spend-test",
            daily_limit_usd=Decimal("10.00"),
        )

        # Track spend
        record = await service.track_spend(
            tenant_id="tenant-spend-test",
            cost_usd=Decimal("2.50"),
            pipeline_name="call_analysis",
            execution_id="exec-123",
        )

        assert record.cost_usd == Decimal("2.50")

        # Check budget reflects spend
        result = await service.check_budget("tenant-spend-test")
        assert result.current_spend_usd == Decimal("2.50")

    @pytest.mark.asyncio
    async def test_budget_exceeded(self) -> None:
        """Test budget exceeded detection."""
        from example_service.infra.ai.observability.budget import (
            BudgetAction,
            BudgetPolicy,
            BudgetService,
        )

        service = BudgetService()

        # Set strict budget
        await service.set_budget(
            tenant_id="tenant-exceed",
            daily_limit_usd=Decimal("5.00"),
            policy=BudgetPolicy.HARD_BLOCK,
        )

        # Track spend that exceeds budget
        await service.track_spend(
            tenant_id="tenant-exceed",
            cost_usd=Decimal("6.00"),
            pipeline_name="test",
        )

        # Check should show exceeded
        result = await service.check_budget("tenant-exceed")
        assert result.action == BudgetAction.BLOCKED
        assert result.allowed is False

    @pytest.mark.asyncio
    async def test_budget_warning_threshold(self) -> None:
        """Test budget warning threshold."""
        from example_service.infra.ai.observability.budget import (
            BudgetAction,
            BudgetService,
        )

        service = BudgetService()

        # Set budget with 80% warning threshold
        await service.set_budget(
            tenant_id="tenant-warn",
            daily_limit_usd=Decimal("10.00"),
            warn_threshold_percent=80.0,
        )

        # Track spend at 85%
        await service.track_spend(
            tenant_id="tenant-warn",
            cost_usd=Decimal("8.50"),
            pipeline_name="test",
        )

        # Check should show warning
        result = await service.check_budget("tenant-warn")
        assert result.action == BudgetAction.WARNED
        assert result.allowed is True  # Still allowed, just warned
        assert result.percent_used > 80.0

    @pytest.mark.asyncio
    async def test_spend_summary(self) -> None:
        """Test spend summary retrieval."""
        from example_service.infra.ai.observability.budget import (
            BudgetPeriod,
            BudgetService,
        )

        service = BudgetService()

        # Track multiple spends
        await service.track_spend(
            tenant_id="tenant-summary",
            cost_usd=Decimal("1.00"),
            pipeline_name="pipeline_a",
            provider="openai",
        )
        await service.track_spend(
            tenant_id="tenant-summary",
            cost_usd=Decimal("2.00"),
            pipeline_name="pipeline_b",
            provider="anthropic",
        )

        # Get summary
        summary = await service.get_spend_summary(
            "tenant-summary",
            BudgetPeriod.DAILY,
        )

        # Check total spend (format may vary)
        total = Decimal(summary["total_spend_usd"])
        assert total == Decimal("3.00")
        assert summary["record_count"] == 2
        assert "pipeline_a" in summary["by_pipeline"]
        assert "openai" in summary["by_provider"]


class TestObservabilityIntegration:
    """Integration tests for observability components."""

    def test_all_components_importable(self) -> None:
        """Test all observability components can be imported."""
        from example_service.infra.ai.observability import (
            AIMetrics,
            AIObservabilityLogger,
            AITracer,
            BudgetService,
            CompensationSpan,
            LogContext,
            PipelineLogContext,
            StepLogContext,
            configure_ai_logger,
            configure_ai_metrics,
            configure_ai_tracer,
            configure_budget_service,
            get_ai_logger,
            get_ai_metrics,
            get_ai_tracer,
            get_budget_service,
        )

        # All imports should succeed
        assert AIMetrics is not None
        assert AIObservabilityLogger is not None
        assert AITracer is not None
        assert BudgetService is not None
        assert CompensationSpan is not None
        assert LogContext is not None
        assert PipelineLogContext is not None
        assert StepLogContext is not None

    def test_singleton_getters(self) -> None:
        """Test singleton getters return same instances."""
        from example_service.infra.ai.observability import (
            get_ai_logger,
            get_ai_metrics,
            get_ai_tracer,
            get_budget_service,
        )

        # Get instances
        logger1 = get_ai_logger()
        logger2 = get_ai_logger()
        assert logger1 is logger2

        tracer1 = get_ai_tracer()
        tracer2 = get_ai_tracer()
        assert tracer1 is tracer2

        metrics1 = get_ai_metrics()
        metrics2 = get_ai_metrics()
        assert metrics1 is metrics2

        budget1 = get_budget_service()
        budget2 = get_budget_service()
        assert budget1 is budget2
