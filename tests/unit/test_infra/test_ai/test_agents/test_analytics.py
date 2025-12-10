"""Tests for the AI agent analytics module."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from example_service.infra.ai.agents.analytics import (
    AgentAnalytics,
    AgentMetrics,
    AggregationPeriod,
    BenchmarkResult,
    CostAnalysis,
    ErrorAnalysis,
    PerformanceBenchmark,
    UsageMetrics,
    UsageReport,
)


class TestAggregationPeriod:
    """Tests for AggregationPeriod enum."""

    def test_period_values(self) -> None:
        """Test aggregation period values."""
        assert AggregationPeriod.HOURLY.value == "hourly"
        assert AggregationPeriod.DAILY.value == "daily"
        assert AggregationPeriod.WEEKLY.value == "weekly"
        assert AggregationPeriod.MONTHLY.value == "monthly"


class TestUsageMetrics:
    """Tests for UsageMetrics dataclass."""

    def test_create_usage_metrics(self) -> None:
        """Test creating usage metrics."""
        now = datetime.now(UTC)
        metrics = UsageMetrics(
            period_start=now - timedelta(days=7),
            period_end=now,
            total_runs=100,
            successful_runs=90,
            failed_runs=10,
            total_input_tokens=50000,
            total_output_tokens=25000,
            total_cost_usd=Decimal("15.50"),
        )

        assert metrics.total_runs == 100
        assert metrics.successful_runs == 90
        assert metrics.total_cost_usd == Decimal("15.50")

    def test_usage_metrics_to_dict(self) -> None:
        """Test serialization to dict."""
        now = datetime.now(UTC)
        metrics = UsageMetrics(
            period_start=now - timedelta(days=1),
            period_end=now,
            total_runs=50,
            successful_runs=45,
            failed_runs=5,
            total_cost_usd=Decimal("10.00"),
            success_rate=90.0,
            error_rate=10.0,
        )

        d = metrics.to_dict()

        assert d["total_runs"] == 50
        assert d["successful_runs"] == 45
        assert d["total_cost_usd"] == 10.0
        assert d["success_rate"] == 90.0
        assert "period_start" in d
        assert "period_end" in d

    def test_default_values(self) -> None:
        """Test default values."""
        now = datetime.now(UTC)
        metrics = UsageMetrics(
            period_start=now,
            period_end=now,
        )

        assert metrics.total_runs == 0
        assert metrics.cancelled_runs == 0
        assert metrics.average_tokens_per_run == 0.0
        assert metrics.total_cost_usd == Decimal("0")


class TestAgentMetrics:
    """Tests for AgentMetrics dataclass."""

    def test_create_agent_metrics(self) -> None:
        """Test creating agent metrics."""
        metrics = AgentMetrics(
            agent_type="qa_agent",
            agent_version="1.0.0",
            total_runs=500,
            unique_tenants=10,
            unique_users=50,
            success_rate=95.0,
            total_cost_usd=Decimal("250.00"),
        )

        assert metrics.agent_type == "qa_agent"
        assert metrics.total_runs == 500
        assert metrics.success_rate == 95.0

    def test_default_values(self) -> None:
        """Test default values."""
        metrics = AgentMetrics(agent_type="test")

        assert metrics.total_runs == 0
        assert metrics.unique_tenants == 0
        assert metrics.top_errors == []


class TestCostAnalysis:
    """Tests for CostAnalysis dataclass."""

    def test_create_cost_analysis(self) -> None:
        """Test creating cost analysis."""
        now = datetime.now(UTC)
        analysis = CostAnalysis(
            tenant_id="tenant-123",
            period_start=now - timedelta(days=30),
            period_end=now,
            total_cost_usd=Decimal("500.00"),
            total_runs=1000,
            total_tokens=500000,
            cost_by_agent={"qa_agent": Decimal("300"), "code_agent": Decimal("200")},
            daily_average=Decimal("16.67"),
            projected_monthly=Decimal("500.00"),
            wasted_cost=Decimal("50.00"),
        )

        assert analysis.tenant_id == "tenant-123"
        assert analysis.total_cost_usd == Decimal("500.00")
        assert len(analysis.cost_by_agent) == 2

    def test_default_values(self) -> None:
        """Test default values."""
        now = datetime.now(UTC)
        analysis = CostAnalysis(
            tenant_id="test",
            period_start=now,
            period_end=now,
        )

        assert analysis.total_cost_usd == Decimal("0")
        assert analysis.cost_by_agent == {}
        assert analysis.cost_by_day == []


class TestErrorAnalysis:
    """Tests for ErrorAnalysis dataclass."""

    def test_create_error_analysis(self) -> None:
        """Test creating error analysis."""
        analysis = ErrorAnalysis(
            tenant_id="tenant-123",
            agent_type="qa_agent",
            total_errors=50,
            unique_error_types=5,
            errors_by_code={"ERR001": 20, "ERR002": 15, "ERR003": 15},
        )

        assert analysis.total_errors == 50
        assert len(analysis.errors_by_code) == 3


class TestUsageReport:
    """Tests for UsageReport dataclass."""

    def test_create_usage_report(self) -> None:
        """Test creating usage report."""
        now = datetime.now(UTC)
        summary = UsageMetrics(
            period_start=now - timedelta(days=30),
            period_end=now,
            total_runs=100,
            successful_runs=90,
            failed_runs=10,
        )

        report = UsageReport(
            tenant_id="tenant-123",
            report_period="2024-01 to 2024-01",
            summary=summary,
            recommendations=["Consider using a smaller model for simple queries"],
        )

        assert report.tenant_id == "tenant-123"
        assert report.summary is not None
        assert len(report.recommendations) == 1

    def test_usage_report_to_dict(self) -> None:
        """Test report serialization."""
        now = datetime.now(UTC)
        summary = UsageMetrics(
            period_start=now - timedelta(days=1),
            period_end=now,
            total_runs=50,
            successful_runs=45,
            failed_runs=5,
        )

        report = UsageReport(
            tenant_id="test",
            report_period="test period",
            summary=summary,
        )

        d = report.to_dict()

        assert d["tenant_id"] == "test"
        assert d["summary"]["total_runs"] == 50
        assert "generated_at" in d


class TestBenchmarkResult:
    """Tests for BenchmarkResult dataclass."""

    def test_create_benchmark_result(self) -> None:
        """Test creating benchmark result."""
        result = BenchmarkResult(
            test_name="simple_query",
            iterations=10,
            success_count=9,
            failure_count=1,
            min_duration_ms=100.0,
            max_duration_ms=500.0,
            avg_duration_ms=250.0,
            median_duration_ms=230.0,
            p95_duration_ms=450.0,
            p99_duration_ms=490.0,
            total_cost_usd=Decimal("0.50"),
            avg_cost_per_run=Decimal("0.05"),
            total_tokens=5000,
            avg_tokens_per_run=500.0,
        )

        assert result.test_name == "simple_query"
        assert result.iterations == 10
        assert result.success_count == 9
        assert result.avg_duration_ms == 250.0


class TestAgentAnalytics:
    """Tests for AgentAnalytics class."""

    @pytest.fixture
    def mock_session(self) -> AsyncMock:
        """Create mock database session."""
        return AsyncMock()

    @pytest.mark.anyio
    async def test_get_usage_metrics(self, mock_session: AsyncMock) -> None:
        """Test getting usage metrics."""
        # Mock query result
        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_row.total_runs = 100
        mock_row.successful = 90
        mock_row.failed = 8
        mock_row.cancelled = 1
        mock_row.timed_out = 1
        mock_row.input_tokens = 50000
        mock_row.output_tokens = 25000
        mock_row.total_cost = 15.50
        mock_row.avg_duration = 2.5
        mock_result.one.return_value = mock_row
        mock_session.execute.return_value = mock_result

        analytics = AgentAnalytics(mock_session)
        now = datetime.now(UTC)

        metrics = await analytics.get_usage_metrics(
            tenant_id="tenant-123",
            start_date=now - timedelta(days=7),
            end_date=now,
        )

        assert metrics.total_runs == 100
        assert metrics.successful_runs == 90
        assert metrics.failed_runs == 8
        mock_session.execute.assert_called_once()

    @pytest.mark.anyio
    async def test_get_usage_metrics_with_agent_filter(
        self, mock_session: AsyncMock
    ) -> None:
        """Test getting metrics filtered by agent type."""
        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_row.total_runs = 50
        mock_row.successful = 48
        mock_row.failed = 2
        mock_row.cancelled = 0
        mock_row.timed_out = 0
        mock_row.input_tokens = 20000
        mock_row.output_tokens = 10000
        mock_row.total_cost = 5.0
        mock_row.avg_duration = 1.5
        mock_result.one.return_value = mock_row
        mock_session.execute.return_value = mock_result

        analytics = AgentAnalytics(mock_session)
        now = datetime.now(UTC)

        metrics = await analytics.get_usage_metrics(
            tenant_id="tenant-123",
            start_date=now - timedelta(days=7),
            end_date=now,
            agent_type="qa_agent",
        )

        assert metrics.total_runs == 50

    @pytest.mark.anyio
    async def test_get_agent_metrics(self, mock_session: AsyncMock) -> None:
        """Test getting agent-specific metrics."""
        # Mock main aggregates
        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_row.total_runs = 200
        mock_row.unique_users = 25
        mock_row.total_cost = 100.0
        mock_row.avg_duration = 3.0
        mock_row.avg_iterations = 5.0
        mock_row.successful = 190
        mock_row.retried = 20
        mock_row.timed_out = 5
        mock_result.one.return_value = mock_row

        # Mock error results
        mock_error_result = MagicMock()
        mock_error_result.all.return_value = [
            MagicMock(error_code="ERR001", count=10),
            MagicMock(error_code="ERR002", count=5),
        ]

        mock_session.execute.side_effect = [mock_result, mock_error_result]

        analytics = AgentAnalytics(mock_session)

        metrics = await analytics.get_agent_metrics(
            tenant_id="tenant-123",
            agent_type="qa_agent",
        )

        assert metrics.agent_type == "qa_agent"
        assert metrics.total_runs == 200
        assert metrics.unique_users == 25
        assert len(metrics.top_errors) == 2

    @pytest.mark.anyio
    async def test_get_cost_analysis(self, mock_session: AsyncMock) -> None:
        """Test getting cost analysis."""
        # Mock total query
        mock_total_result = MagicMock()
        mock_total_row = MagicMock()
        mock_total_row.total_cost = 500.0
        mock_total_row.total_runs = 1000
        mock_total_row.total_tokens = 500000
        mock_total_result.one.return_value = mock_total_row

        # Mock agent breakdown
        mock_agent_result = MagicMock()
        mock_agent_result.all.return_value = [
            MagicMock(agent_type="qa_agent", cost=300.0),
            MagicMock(agent_type="code_agent", cost=200.0),
        ]

        # Mock daily breakdown
        mock_daily_result = MagicMock()
        mock_daily_result.all.return_value = []

        # Mock wasted cost
        mock_failed_result = MagicMock()
        mock_failed_result.scalar.return_value = 50.0

        mock_session.execute.side_effect = [
            mock_total_result,
            mock_agent_result,
            mock_daily_result,
            mock_failed_result,
        ]

        analytics = AgentAnalytics(mock_session)
        now = datetime.now(UTC)

        analysis = await analytics.get_cost_analysis(
            tenant_id="tenant-123",
            start_date=now - timedelta(days=30),
            end_date=now,
        )

        assert analysis.total_cost_usd == Decimal("500.0")
        assert analysis.total_runs == 1000
        assert len(analysis.cost_by_agent) == 2
        assert analysis.wasted_cost == Decimal("50.0")

    def test_generate_recommendations_high_error_rate(
        self, mock_session: AsyncMock
    ) -> None:
        """Test recommendations for high error rate."""
        now = datetime.now(UTC)
        summary = UsageMetrics(
            period_start=now - timedelta(days=7),
            period_end=now,
            total_runs=100,
            successful_runs=80,
            failed_runs=20,
            error_rate=20.0,
        )

        analytics = AgentAnalytics(mock_session)
        recommendations = analytics._generate_recommendations(
            summary,
            [],
            CostAnalysis(
                tenant_id="test",
                period_start=now,
                period_end=now,
                total_cost_usd=Decimal("100"),
                wasted_cost=Decimal("10"),
            ),
        )

        assert len(recommendations) >= 1
        assert any("error rate" in r.lower() for r in recommendations)

    def test_generate_recommendations_high_wasted_cost(
        self, mock_session: AsyncMock
    ) -> None:
        """Test recommendations for high wasted cost."""
        now = datetime.now(UTC)
        summary = UsageMetrics(
            period_start=now - timedelta(days=7),
            period_end=now,
            total_runs=100,
            successful_runs=95,
            failed_runs=5,
        )

        analytics = AgentAnalytics(mock_session)
        recommendations = analytics._generate_recommendations(
            summary,
            [],
            CostAnalysis(
                tenant_id="test",
                period_start=now,
                period_end=now,
                total_cost_usd=Decimal("100"),
                wasted_cost=Decimal("30"),  # 30% wasted
            ),
        )

        assert any("failed runs" in r.lower() for r in recommendations)


class TestPerformanceBenchmark:
    """Tests for PerformanceBenchmark class."""

    @pytest.fixture
    def mock_agent(self) -> MagicMock:
        """Create mock agent for benchmarking."""
        agent = MagicMock()

        # Create mock result
        result = MagicMock()
        result.success = True
        result.total_cost_usd = Decimal("0.01")
        result.total_input_tokens = 100
        result.total_output_tokens = 50
        result.error = None

        agent.execute = AsyncMock(return_value=result)
        return agent

    @pytest.mark.anyio
    async def test_run_benchmark(self, mock_agent: MagicMock) -> None:
        """Test running benchmark."""
        benchmark = PerformanceBenchmark(
            agent=mock_agent,
            warmup_runs=1,
            benchmark_runs=3,
        )

        test_cases = [
            {"name": "simple", "input": {"query": "test"}},
        ]

        results = await benchmark.run(test_cases)

        assert len(results) == 1
        result = results[0]
        assert result.test_name == "simple"
        assert result.iterations == 3
        # Warmup + benchmark runs
        assert mock_agent.execute.call_count == 4

    @pytest.mark.anyio
    async def test_benchmark_with_failures(self, mock_agent: MagicMock) -> None:
        """Test benchmark handles failures."""
        call_count = 0

        async def flaky_execute(input_data: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            result.success = call_count % 2 == 0  # Alternate success/failure
            result.total_cost_usd = Decimal("0.01")
            result.total_input_tokens = 100
            result.total_output_tokens = 50
            result.error = "Failed" if not result.success else None
            return result

        mock_agent.execute = flaky_execute

        benchmark = PerformanceBenchmark(
            agent=mock_agent,
            warmup_runs=0,
            benchmark_runs=4,
        )

        results = await benchmark.run([{"name": "test", "input": {}}])

        result = results[0]
        # 2 successes, 2 failures out of 4
        assert result.success_count == 2
        assert result.failure_count == 2

    def test_format_results(self, mock_agent: MagicMock) -> None:
        """Test formatting results."""
        benchmark = PerformanceBenchmark(
            agent=mock_agent,
            warmup_runs=0,
            benchmark_runs=5,
        )

        results = [
            BenchmarkResult(
                test_name="test1",
                iterations=5,
                success_count=5,
                failure_count=0,
                min_duration_ms=100,
                max_duration_ms=200,
                avg_duration_ms=150,
                median_duration_ms=145,
                p95_duration_ms=190,
                p99_duration_ms=198,
                total_cost_usd=Decimal("0.05"),
                avg_cost_per_run=Decimal("0.01"),
                total_tokens=500,
                avg_tokens_per_run=100,
            ),
        ]

        output = benchmark.format_results(results)

        assert "BENCHMARK RESULTS" in output
        assert "test1" in output
        assert "Min:" in output
        assert "Max:" in output
        assert "Avg:" in output
        assert "Cost:" in output


class TestAgentAnalyticsIntegration:
    """Integration tests for analytics (with mocked DB)."""

    @pytest.fixture
    def mock_session(self) -> AsyncMock:
        """Create mock database session."""
        return AsyncMock()

    @pytest.mark.anyio
    async def test_get_usage_report(self, mock_session: AsyncMock) -> None:
        """Test generating full usage report."""
        now = datetime.now(UTC)

        # Setup mocks for all queries
        mock_usage_result = MagicMock()
        mock_usage_row = MagicMock()
        mock_usage_row.total_runs = 100
        mock_usage_row.successful = 90
        mock_usage_row.failed = 10
        mock_usage_row.cancelled = 0
        mock_usage_row.timed_out = 0
        mock_usage_row.input_tokens = 50000
        mock_usage_row.output_tokens = 25000
        mock_usage_row.total_cost = 15.0
        mock_usage_row.avg_duration = 2.0
        mock_usage_result.one.return_value = mock_usage_row

        mock_agent_types_result = MagicMock()
        mock_agent_types_result.all.return_value = [("qa_agent",)]

        mock_agent_result = MagicMock()
        mock_agent_row = MagicMock()
        mock_agent_row.total_runs = 100
        mock_agent_row.unique_users = 10
        mock_agent_row.total_cost = 15.0
        mock_agent_row.avg_duration = 2.0
        mock_agent_row.avg_iterations = 3.0
        mock_agent_row.successful = 90
        mock_agent_row.retried = 5
        mock_agent_row.timed_out = 0
        mock_agent_result.one.return_value = mock_agent_row

        mock_error_result = MagicMock()
        mock_error_result.all.return_value = []

        mock_cost_total = MagicMock()
        mock_cost_row = MagicMock()
        mock_cost_row.total_cost = 15.0
        mock_cost_row.total_runs = 100
        mock_cost_row.total_tokens = 75000
        mock_cost_total.one.return_value = mock_cost_row

        mock_cost_agent = MagicMock()
        mock_cost_agent.all.return_value = []

        mock_cost_daily = MagicMock()
        mock_cost_daily.all.return_value = []

        mock_cost_failed = MagicMock()
        mock_cost_failed.scalar.return_value = 1.0

        mock_session.execute.side_effect = [
            mock_usage_result,  # get_usage_metrics
            mock_agent_types_result,  # get agent types
            mock_agent_result,  # get_agent_metrics
            mock_error_result,  # get_agent_metrics errors
            mock_cost_total,  # get_cost_analysis total
            mock_cost_agent,  # get_cost_analysis by agent
            mock_cost_daily,  # get_cost_analysis by day
            mock_cost_failed,  # get_cost_analysis failed
        ]

        analytics = AgentAnalytics(mock_session)

        report = await analytics.get_usage_report(
            tenant_id="tenant-123",
            start_date=now - timedelta(days=30),
            end_date=now,
        )

        assert report.tenant_id == "tenant-123"
        assert report.summary is not None
        assert report.summary.total_runs == 100
        assert len(report.metrics_by_agent) == 1
        assert report.cost_analysis is not None
