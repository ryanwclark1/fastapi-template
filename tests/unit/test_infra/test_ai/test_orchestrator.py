"""Integration tests for InstrumentedOrchestrator.

Tests cover:
- Pipeline execution flow
- Budget enforcement integration
- Metrics recording
- Event streaming
- Error handling and compensation
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from example_service.infra.ai.capabilities.types import Capability, OperationResult
from example_service.infra.ai.instrumented_orchestrator import InstrumentedOrchestrator
from example_service.infra.ai.observability.budget import (
    BudgetAction,
    BudgetCheckResult,
    BudgetExceededException,
    BudgetPeriod,
    BudgetPolicy,
)
from example_service.infra.ai.pipelines.builder import Pipeline
from example_service.infra.ai.pipelines.types import (
    PipelineResult,
    StepResult,
    StepStatus,
)

# ──────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────


@pytest.fixture
def mock_registry():
    """Create mock capability registry."""
    registry = MagicMock()
    registry.get_providers_for_capability.return_value = []
    registry.build_fallback_chain.return_value = ["mock_provider"]
    return registry


@pytest.fixture
def mock_event_store():
    """Create mock event store."""
    store = MagicMock()
    store.append = AsyncMock()
    store.get_events = AsyncMock(return_value=[])
    store.get_workflow_state = AsyncMock(return_value={})

    async def mock_subscribe(execution_id, event_types=None):
        return
        yield  # Makes it an async generator

    store.subscribe = mock_subscribe
    return store


@pytest.fixture
def mock_tracer():
    """Create mock AI tracer."""
    tracer = MagicMock()

    # Create mock context manager for pipeline_span
    mock_span = MagicMock()
    mock_span.record_success = MagicMock()
    mock_span.record_failure = MagicMock()
    mock_span.__aenter__ = AsyncMock(return_value=mock_span)
    mock_span.__aexit__ = AsyncMock(return_value=False)

    tracer.pipeline_span.return_value = mock_span
    return tracer


@pytest.fixture
def mock_metrics():
    """Create mock AI metrics."""
    metrics = MagicMock()
    metrics.record_pipeline_started = MagicMock()
    metrics.record_pipeline_completed = MagicMock()
    metrics.record_pipeline_execution = MagicMock()
    metrics.record_step_execution = MagicMock()
    metrics.record_budget_exceeded = MagicMock()
    return metrics


@pytest.fixture
def mock_budget_service():
    """Create mock budget service."""
    service = MagicMock()
    service.check_budget = AsyncMock(
        return_value=BudgetCheckResult(
            allowed=True,
            action=BudgetAction.ALLOWED,
            current_spend_usd=Decimal("10.00"),
            limit_usd=Decimal("100.00"),
            percent_used=10.0,
            period=BudgetPeriod.MONTHLY,
            message="Budget OK",
        )
    )
    service.track_spend = AsyncMock()
    return service


@pytest.fixture
def simple_pipeline():
    """Create a simple test pipeline."""
    return (
        Pipeline("test_pipeline")
        .version("1.0.0")
        .description("Test pipeline")
        .estimated_cost("0.10")
        .step("step1")
            .capability(Capability.TRANSCRIPTION)
            .output_as("transcript")
            .done()
        .build()
    )


@pytest.fixture
def mock_saga_coordinator():
    """Create mock saga coordinator."""
    saga = MagicMock()
    saga.execute = AsyncMock(
        return_value=PipelineResult(
            execution_id="exec-123",
            pipeline_name="test_pipeline",
            pipeline_version="1.0.0",
            success=True,
            output={"transcript": {"text": "Hello world"}},
            completed_steps=["step1"],
            failed_step=None,
            step_results={
                "step1": StepResult(
                    step_name="step1",
                    status=StepStatus.COMPLETED,
                    operation_result=OperationResult(
                        success=True,
                        data={"text": "Hello world"},
                        provider_name="mock_provider",
                        capability=Capability.TRANSCRIPTION,
                        cost_usd=Decimal("0.05"),
                        latency_ms=1000.0,
                    ),
                    provider_used="mock_provider",
                    retries=0,
                )
            },
            total_duration_ms=1000.0,
            total_cost_usd=Decimal("0.05"),
            compensation_performed=False,
            compensated_steps=[],
            error=None,
        )
    )
    return saga


@pytest.fixture
def orchestrator(
    mock_registry,
    mock_event_store,
    mock_tracer,
    mock_metrics,
    mock_budget_service,
    mock_saga_coordinator,
):
    """Create orchestrator with all mocked dependencies."""
    orch = InstrumentedOrchestrator(
        registry=mock_registry,
        event_store=mock_event_store,
        tracer=mock_tracer,
        metrics=mock_metrics,
        budget_service=mock_budget_service,
        api_keys={"mock_provider": "test-key"},
    )
    # Replace saga coordinator with mock
    orch._saga = mock_saga_coordinator
    return orch


# ──────────────────────────────────────────────────────────────
# Test Basic Execution
# ──────────────────────────────────────────────────────────────


class TestBasicExecution:
    """Tests for basic pipeline execution."""

    @pytest.mark.asyncio
    async def test_execute_returns_result(self, orchestrator, simple_pipeline):
        """Execute should return PipelineResult."""
        result = await orchestrator.execute(
            pipeline=simple_pipeline,
            input_data={"audio": b"test"},
            tenant_id="tenant-123",
        )

        assert isinstance(result, PipelineResult)
        assert result.success is True
        assert result.pipeline_name == "test_pipeline"

    @pytest.mark.asyncio
    async def test_execute_calls_saga_coordinator(
        self, orchestrator, simple_pipeline, mock_saga_coordinator
    ):
        """Execute should delegate to saga coordinator."""
        await orchestrator.execute(
            pipeline=simple_pipeline,
            input_data={"audio": b"test"},
            tenant_id="tenant-123",
        )

        mock_saga_coordinator.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_without_tenant(self, orchestrator, simple_pipeline):
        """Execute should work without tenant ID."""
        result = await orchestrator.execute(
            pipeline=simple_pipeline,
            input_data={"audio": b"test"},
        )

        assert result.success is True


# ──────────────────────────────────────────────────────────────
# Test Budget Integration
# ──────────────────────────────────────────────────────────────


class TestBudgetIntegration:
    """Tests for budget enforcement integration."""

    @pytest.mark.asyncio
    async def test_execute_checks_budget(
        self, orchestrator, simple_pipeline, mock_budget_service
    ):
        """Execute should check budget before execution."""
        await orchestrator.execute(
            pipeline=simple_pipeline,
            input_data={"audio": b"test"},
            tenant_id="tenant-123",
        )

        mock_budget_service.check_budget.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_skips_budget_when_no_tenant(
        self, orchestrator, simple_pipeline, mock_budget_service
    ):
        """Execute should skip budget check without tenant."""
        await orchestrator.execute(
            pipeline=simple_pipeline,
            input_data={"audio": b"test"},
        )

        mock_budget_service.check_budget.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_skips_budget_when_requested(
        self, orchestrator, simple_pipeline, mock_budget_service
    ):
        """Execute should skip budget check when skip_budget_check=True."""
        await orchestrator.execute(
            pipeline=simple_pipeline,
            input_data={"audio": b"test"},
            tenant_id="tenant-123",
            skip_budget_check=True,
        )

        mock_budget_service.check_budget.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_raises_on_budget_exceeded(
        self, orchestrator, simple_pipeline, mock_budget_service
    ):
        """Execute should raise BudgetExceededException when budget exceeded."""
        mock_budget_service.check_budget.return_value = BudgetCheckResult(
            allowed=False,
            action=BudgetAction.BLOCKED,
            current_spend_usd=Decimal("100.00"),
            limit_usd=Decimal("100.00"),
            percent_used=100.0,
            period=BudgetPeriod.MONTHLY,
            message="Monthly budget exceeded",
        )

        with pytest.raises(BudgetExceededException) as exc_info:
            await orchestrator.execute(
                pipeline=simple_pipeline,
                input_data={"audio": b"test"},
                tenant_id="tenant-123",
            )

        assert "Monthly budget exceeded" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_execute_tracks_spend_after_success(
        self, orchestrator, simple_pipeline, mock_budget_service
    ):
        """Execute should track spend after successful execution."""
        await orchestrator.execute(
            pipeline=simple_pipeline,
            input_data={"audio": b"test"},
            tenant_id="tenant-123",
        )

        mock_budget_service.track_spend.assert_called_once()
        call_args = mock_budget_service.track_spend.call_args
        assert call_args.kwargs["tenant_id"] == "tenant-123"
        assert call_args.kwargs["pipeline_name"] == "test_pipeline"


# ──────────────────────────────────────────────────────────────
# Test Metrics Integration
# ──────────────────────────────────────────────────────────────


class TestMetricsIntegration:
    """Tests for Prometheus metrics integration."""

    @pytest.mark.asyncio
    async def test_execute_records_pipeline_started(
        self, orchestrator, simple_pipeline, mock_metrics
    ):
        """Execute should record pipeline started metric."""
        await orchestrator.execute(
            pipeline=simple_pipeline,
            input_data={"audio": b"test"},
            tenant_id="tenant-123",
        )

        mock_metrics.record_pipeline_started.assert_called_once_with(
            "test_pipeline", "tenant-123"
        )

    @pytest.mark.asyncio
    async def test_execute_records_pipeline_completed(
        self, orchestrator, simple_pipeline, mock_metrics
    ):
        """Execute should record pipeline completed metric."""
        await orchestrator.execute(
            pipeline=simple_pipeline,
            input_data={"audio": b"test"},
            tenant_id="tenant-123",
        )

        mock_metrics.record_pipeline_completed.assert_called_once_with(
            "test_pipeline", "tenant-123"
        )

    @pytest.mark.asyncio
    async def test_execute_records_pipeline_execution_metrics(
        self, orchestrator, simple_pipeline, mock_metrics
    ):
        """Execute should record detailed execution metrics."""
        await orchestrator.execute(
            pipeline=simple_pipeline,
            input_data={"audio": b"test"},
            tenant_id="tenant-123",
        )

        mock_metrics.record_pipeline_execution.assert_called_once()
        call_args = mock_metrics.record_pipeline_execution.call_args
        assert call_args.kwargs["pipeline_name"] == "test_pipeline"
        assert call_args.kwargs["status"] == "success"
        assert call_args.kwargs["tenant_id"] == "tenant-123"

    @pytest.mark.asyncio
    async def test_execute_records_budget_exceeded_metric(
        self, orchestrator, simple_pipeline, mock_budget_service, mock_metrics
    ):
        """Execute should record budget exceeded metric."""
        mock_budget_service.check_budget.return_value = BudgetCheckResult(
            allowed=False,
            action=BudgetAction.BLOCKED,
            current_spend_usd=Decimal("100.00"),
            limit_usd=Decimal("100.00"),
            percent_used=100.0,
            period=BudgetPeriod.MONTHLY,
            message="Budget exceeded",
        )

        with pytest.raises(BudgetExceededException):
            await orchestrator.execute(
                pipeline=simple_pipeline,
                input_data={"audio": b"test"},
                tenant_id="tenant-123",
            )

        mock_metrics.record_budget_exceeded.assert_called_once_with(
            "tenant-123", "blocked"
        )


# ──────────────────────────────────────────────────────────────
# Test Tracing Integration
# ──────────────────────────────────────────────────────────────


class TestTracingIntegration:
    """Tests for OpenTelemetry tracing integration."""

    @pytest.mark.asyncio
    async def test_execute_creates_pipeline_span(
        self, orchestrator, simple_pipeline, mock_tracer
    ):
        """Execute should create pipeline tracing span."""
        await orchestrator.execute(
            pipeline=simple_pipeline,
            input_data={"audio": b"test"},
            tenant_id="tenant-123",
        )

        mock_tracer.pipeline_span.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_records_success_on_span(
        self, orchestrator, simple_pipeline, mock_tracer
    ):
        """Execute should record success on tracing span."""
        await orchestrator.execute(
            pipeline=simple_pipeline,
            input_data={"audio": b"test"},
            tenant_id="tenant-123",
        )

        span = mock_tracer.pipeline_span.return_value
        span.record_success.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_records_failure_on_span(
        self, orchestrator, simple_pipeline, mock_tracer, mock_saga_coordinator
    ):
        """Execute should record failure on tracing span."""
        mock_saga_coordinator.execute.return_value = PipelineResult(
            execution_id="exec-123",
            pipeline_name="test_pipeline",
            pipeline_version="1.0.0",
            success=False,
            output={},
            completed_steps=[],
            failed_step="step1",
            step_results={},
            total_duration_ms=500.0,
            total_cost_usd=Decimal("0"),
            compensation_performed=False,
            compensated_steps=[],
            error="Step failed",
        )

        await orchestrator.execute(
            pipeline=simple_pipeline,
            input_data={"audio": b"test"},
            tenant_id="tenant-123",
        )

        span = mock_tracer.pipeline_span.return_value
        span.record_failure.assert_called_once()
        call_args = span.record_failure.call_args
        assert call_args.kwargs["failed_step"] == "step1"

    @pytest.mark.asyncio
    async def test_execute_works_without_tracer(
        self, mock_registry, mock_event_store, mock_budget_service, mock_saga_coordinator, simple_pipeline
    ):
        """Execute should work when tracing is disabled."""
        orch = InstrumentedOrchestrator(
            registry=mock_registry,
            event_store=mock_event_store,
            tracer=None,
            metrics=None,
            budget_service=mock_budget_service,
            enable_tracing=False,
            enable_metrics=False,
        )
        orch._saga = mock_saga_coordinator

        result = await orch.execute(
            pipeline=simple_pipeline,
            input_data={"audio": b"test"},
            tenant_id="tenant-123",
        )

        assert result.success is True


# ──────────────────────────────────────────────────────────────
# Test Error Handling
# ──────────────────────────────────────────────────────────────


class TestErrorHandling:
    """Tests for error handling in orchestrator."""

    @pytest.mark.asyncio
    async def test_failed_execution_returns_result(
        self, orchestrator, simple_pipeline, mock_saga_coordinator
    ):
        """Failed execution should return result with error details."""
        mock_saga_coordinator.execute.return_value = PipelineResult(
            execution_id="exec-123",
            pipeline_name="test_pipeline",
            pipeline_version="1.0.0",
            success=False,
            output={},
            completed_steps=[],
            failed_step="step1",
            step_results={
                "step1": StepResult(
                    step_name="step1",
                    status=StepStatus.FAILED,
                    operation_result=OperationResult(
                        success=False,
                        data=None,
                        provider_name="mock_provider",
                        capability=Capability.TRANSCRIPTION,
                        cost_usd=Decimal("0"),
                        latency_ms=500.0,
                        error="Provider error",
                    ),
                    provider_used="mock_provider",
                    retries=3,
                    error="Provider error",
                )
            },
            total_duration_ms=500.0,
            total_cost_usd=Decimal("0"),
            compensation_performed=True,
            compensated_steps=[],
            error="Step1 failed: Provider error",
        )

        result = await orchestrator.execute(
            pipeline=simple_pipeline,
            input_data={"audio": b"test"},
            tenant_id="tenant-123",
        )

        assert result.success is False
        assert result.failed_step == "step1"
        assert result.compensation_performed is True

    @pytest.mark.asyncio
    async def test_metrics_recorded_on_failure(
        self, orchestrator, simple_pipeline, mock_metrics, mock_saga_coordinator
    ):
        """Metrics should be recorded even on failure."""
        mock_saga_coordinator.execute.return_value = PipelineResult(
            execution_id="exec-123",
            pipeline_name="test_pipeline",
            pipeline_version="1.0.0",
            success=False,
            output={},
            completed_steps=[],
            failed_step="step1",
            step_results={},
            total_duration_ms=500.0,
            total_cost_usd=Decimal("0"),
            compensation_performed=False,
            compensated_steps=[],
            error="Failed",
        )

        await orchestrator.execute(
            pipeline=simple_pipeline,
            input_data={"audio": b"test"},
            tenant_id="tenant-123",
        )

        mock_metrics.record_pipeline_execution.assert_called_once()
        call_args = mock_metrics.record_pipeline_execution.call_args
        assert call_args.kwargs["status"] == "failure"

    @pytest.mark.asyncio
    async def test_pipeline_completed_always_recorded(
        self, orchestrator, simple_pipeline, mock_metrics, mock_saga_coordinator
    ):
        """Pipeline completed metric should always be recorded (for gauge)."""
        mock_saga_coordinator.execute.side_effect = RuntimeError("Unexpected error")

        with pytest.raises(RuntimeError):
            await orchestrator.execute(
                pipeline=simple_pipeline,
                input_data={"audio": b"test"},
                tenant_id="tenant-123",
            )

        # pipeline_completed should still be called in finally block
        mock_metrics.record_pipeline_completed.assert_called_once()


# ──────────────────────────────────────────────────────────────
# Test Configuration
# ──────────────────────────────────────────────────────────────


class TestConfiguration:
    """Tests for orchestrator configuration."""

    def test_default_configuration(self, mock_registry, mock_event_store):
        """Orchestrator should have sensible defaults."""
        orch = InstrumentedOrchestrator(
            registry=mock_registry,
            event_store=mock_event_store,
            enable_tracing=False,
            enable_metrics=False,
            enable_budget_enforcement=False,
        )

        assert orch.tracer is None
        assert orch.metrics is None
        assert orch.budget is None

    def test_api_keys_configuration(self, mock_registry, mock_event_store):
        """Orchestrator should store API keys."""
        orch = InstrumentedOrchestrator(
            registry=mock_registry,
            event_store=mock_event_store,
            api_keys={"openai": "sk-test", "anthropic": "sk-ant-test"},
            enable_tracing=False,
            enable_metrics=False,
            enable_budget_enforcement=False,
        )

        assert orch.api_keys["openai"] == "sk-test"
        assert orch.api_keys["anthropic"] == "sk-ant-test"

    def test_model_overrides_configuration(self, mock_registry, mock_event_store):
        """Orchestrator should store model overrides."""
        orch = InstrumentedOrchestrator(
            registry=mock_registry,
            event_store=mock_event_store,
            model_overrides={"openai": "gpt-4o-mini"},
            enable_tracing=False,
            enable_metrics=False,
            enable_budget_enforcement=False,
        )

        assert orch.model_overrides["openai"] == "gpt-4o-mini"


# ──────────────────────────────────────────────────────────────
# Test Event Streaming
# ──────────────────────────────────────────────────────────────


class TestEventStreaming:
    """Tests for event streaming functionality."""

    @pytest.mark.asyncio
    async def test_stream_events_returns_async_iterator(
        self, orchestrator, mock_event_store
    ):
        """stream_events should return async iterator."""
        events = []

        async for event in orchestrator.stream_events("exec-123"):
            events.append(event)
            break  # Just test iteration works

        # No events in mock, but iterator should work
        assert events == []

    @pytest.mark.asyncio
    async def test_stream_events_filters_by_type(
        self, orchestrator, mock_event_store
    ):
        """stream_events should support event type filtering."""
        from example_service.infra.ai.events import EventType

        # Test that filter parameter is passed (mock doesn't actually filter)
        async for _ in orchestrator.stream_events(
            "exec-123",
            event_types=[EventType.STEP_COMPLETED],
        ):
            break
