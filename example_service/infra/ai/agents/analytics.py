"""Analytics and reporting for AI agents.

This module provides comprehensive analytics including:
- Run analytics and aggregations
- Cost analysis and forecasting
- Performance metrics and benchmarking
- Usage patterns and trends
- Error analysis and debugging

Example:
    from example_service.infra.ai.agents.analytics import (
        AgentAnalytics,
        PerformanceBenchmark,
    )

    analytics = AgentAnalytics(db_session)

    # Get usage report
    report = await analytics.get_usage_report(
        tenant_id="tenant-123",
        start_date=datetime(2024, 1, 1),
        end_date=datetime(2024, 1, 31),
    )

    # Run performance benchmark
    benchmark = PerformanceBenchmark(agent)
    results = await benchmark.run(test_cases)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any, Generic, TypeVar
import statistics
import logging

from sqlalchemy import and_, func, select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from example_service.infra.ai.agents.base import AgentResult, BaseAgent

logger = logging.getLogger(__name__)

T = TypeVar("T")


class AggregationPeriod(str, Enum):
    """Time period for aggregation."""

    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


@dataclass
class UsageMetrics:
    """Usage metrics for a time period."""

    period_start: datetime
    period_end: datetime

    # Run counts
    total_runs: int = 0
    successful_runs: int = 0
    failed_runs: int = 0
    cancelled_runs: int = 0
    timed_out_runs: int = 0

    # Token usage
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    average_tokens_per_run: float = 0.0

    # Cost
    total_cost_usd: Decimal = field(default_factory=lambda: Decimal("0"))
    average_cost_per_run: Decimal = field(default_factory=lambda: Decimal("0"))

    # Performance
    average_duration_seconds: float | None = None
    median_duration_seconds: float | None = None
    p95_duration_seconds: float | None = None
    p99_duration_seconds: float | None = None

    # Success metrics
    success_rate: float | None = None
    error_rate: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "total_runs": self.total_runs,
            "successful_runs": self.successful_runs,
            "failed_runs": self.failed_runs,
            "cancelled_runs": self.cancelled_runs,
            "timed_out_runs": self.timed_out_runs,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "average_tokens_per_run": self.average_tokens_per_run,
            "total_cost_usd": float(self.total_cost_usd),
            "average_cost_per_run": float(self.average_cost_per_run),
            "average_duration_seconds": self.average_duration_seconds,
            "median_duration_seconds": self.median_duration_seconds,
            "p95_duration_seconds": self.p95_duration_seconds,
            "p99_duration_seconds": self.p99_duration_seconds,
            "success_rate": self.success_rate,
            "error_rate": self.error_rate,
        }


@dataclass
class AgentMetrics:
    """Metrics for a specific agent type."""

    agent_type: str
    agent_version: str | None = None

    # Usage
    total_runs: int = 0
    unique_tenants: int = 0
    unique_users: int = 0

    # Performance
    average_duration_seconds: float | None = None
    average_iterations: float | None = None
    average_tool_calls: float | None = None

    # Cost
    total_cost_usd: Decimal = field(default_factory=lambda: Decimal("0"))
    cost_per_run: Decimal = field(default_factory=lambda: Decimal("0"))
    cost_per_1k_tokens: Decimal = field(default_factory=lambda: Decimal("0"))

    # Reliability
    success_rate: float | None = None
    retry_rate: float | None = None
    timeout_rate: float | None = None

    # Top errors
    top_errors: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class CostAnalysis:
    """Cost analysis for a tenant."""

    tenant_id: str
    period_start: datetime
    period_end: datetime

    # Totals
    total_cost_usd: Decimal = field(default_factory=lambda: Decimal("0"))
    total_runs: int = 0
    total_tokens: int = 0

    # Breakdown
    cost_by_agent: dict[str, Decimal] = field(default_factory=dict)
    cost_by_model: dict[str, Decimal] = field(default_factory=dict)
    cost_by_day: list[dict[str, Any]] = field(default_factory=list)

    # Trends
    daily_average: Decimal = field(default_factory=lambda: Decimal("0"))
    daily_trend: float | None = None  # % change
    projected_monthly: Decimal = field(default_factory=lambda: Decimal("0"))

    # Efficiency
    cost_per_successful_run: Decimal = field(default_factory=lambda: Decimal("0"))
    wasted_cost: Decimal = field(default_factory=lambda: Decimal("0"))  # Failed runs


@dataclass
class ErrorAnalysis:
    """Error analysis for debugging."""

    tenant_id: str | None = None
    agent_type: str | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None

    # Counts
    total_errors: int = 0
    unique_error_types: int = 0

    # Top errors
    errors_by_code: dict[str, int] = field(default_factory=dict)
    errors_by_agent: dict[str, int] = field(default_factory=dict)
    errors_by_step: dict[str, int] = field(default_factory=dict)

    # Error patterns
    error_rate_by_hour: list[dict[str, Any]] = field(default_factory=list)
    recent_errors: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class UsageReport:
    """Comprehensive usage report."""

    tenant_id: str
    report_period: str
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    # Summary
    summary: UsageMetrics | None = None

    # Breakdown
    metrics_by_agent: list[AgentMetrics] = field(default_factory=list)
    metrics_by_period: list[UsageMetrics] = field(default_factory=list)

    # Cost analysis
    cost_analysis: CostAnalysis | None = None

    # Error analysis
    error_analysis: ErrorAnalysis | None = None

    # Recommendations
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "tenant_id": self.tenant_id,
            "report_period": self.report_period,
            "generated_at": self.generated_at.isoformat(),
            "summary": self.summary.to_dict() if self.summary else None,
            "metrics_by_agent": [
                {
                    "agent_type": m.agent_type,
                    "total_runs": m.total_runs,
                    "success_rate": m.success_rate,
                    "total_cost_usd": float(m.total_cost_usd),
                }
                for m in self.metrics_by_agent
            ],
            "recommendations": self.recommendations,
        }


class AgentAnalytics:
    """Analytics engine for AI agents.

    Provides methods for analyzing agent usage, performance,
    and costs across tenants.
    """

    def __init__(self, db_session: AsyncSession) -> None:
        """Initialize analytics.

        Args:
            db_session: Database session
        """
        self.db_session = db_session

    async def get_usage_metrics(
        self,
        tenant_id: str,
        start_date: datetime,
        end_date: datetime,
        agent_type: str | None = None,
    ) -> UsageMetrics:
        """Get usage metrics for a time period.

        Args:
            tenant_id: Tenant ID
            start_date: Period start
            end_date: Period end
            agent_type: Optional agent type filter

        Returns:
            UsageMetrics for the period
        """
        from example_service.infra.ai.agents.models import AIAgentRun

        conditions = [
            AIAgentRun.tenant_id == tenant_id,
            AIAgentRun.created_at >= start_date,
            AIAgentRun.created_at <= end_date,
        ]

        if agent_type:
            conditions.append(AIAgentRun.agent_type == agent_type)

        # Aggregate query
        query = select(
            func.count(AIAgentRun.id).label("total_runs"),
            func.sum(
                func.case((AIAgentRun.status == "completed", 1), else_=0)
            ).label("successful"),
            func.sum(
                func.case((AIAgentRun.status == "failed", 1), else_=0)
            ).label("failed"),
            func.sum(
                func.case((AIAgentRun.status == "cancelled", 1), else_=0)
            ).label("cancelled"),
            func.sum(
                func.case((AIAgentRun.status == "timeout", 1), else_=0)
            ).label("timed_out"),
            func.sum(AIAgentRun.total_input_tokens).label("input_tokens"),
            func.sum(AIAgentRun.total_output_tokens).label("output_tokens"),
            func.sum(AIAgentRun.total_cost_usd).label("total_cost"),
            func.avg(
                func.extract(
                    "epoch",
                    AIAgentRun.completed_at - AIAgentRun.started_at
                )
            ).label("avg_duration"),
        ).where(and_(*conditions))

        result = await self.db_session.execute(query)
        row = result.one()

        total_runs = row.total_runs or 0
        successful = row.successful or 0
        total_cost = Decimal(str(row.total_cost or 0))
        total_tokens = (row.input_tokens or 0) + (row.output_tokens or 0)

        metrics = UsageMetrics(
            period_start=start_date,
            period_end=end_date,
            total_runs=total_runs,
            successful_runs=successful,
            failed_runs=row.failed or 0,
            cancelled_runs=row.cancelled or 0,
            timed_out_runs=row.timed_out or 0,
            total_input_tokens=row.input_tokens or 0,
            total_output_tokens=row.output_tokens or 0,
            average_tokens_per_run=total_tokens / total_runs if total_runs > 0 else 0,
            total_cost_usd=total_cost,
            average_cost_per_run=total_cost / total_runs if total_runs > 0 else Decimal("0"),
            average_duration_seconds=row.avg_duration,
            success_rate=successful / total_runs * 100 if total_runs > 0 else None,
            error_rate=(row.failed or 0) / total_runs * 100 if total_runs > 0 else None,
        )

        return metrics

    async def get_agent_metrics(
        self,
        tenant_id: str,
        agent_type: str,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> AgentMetrics:
        """Get metrics for a specific agent type.

        Args:
            tenant_id: Tenant ID
            agent_type: Agent type
            start_date: Optional start date
            end_date: Optional end date

        Returns:
            AgentMetrics for the agent
        """
        from example_service.infra.ai.agents.models import AIAgentRun

        conditions = [
            AIAgentRun.tenant_id == tenant_id,
            AIAgentRun.agent_type == agent_type,
        ]

        if start_date:
            conditions.append(AIAgentRun.created_at >= start_date)
        if end_date:
            conditions.append(AIAgentRun.created_at <= end_date)

        # Main aggregates
        query = select(
            func.count(AIAgentRun.id).label("total_runs"),
            func.count(func.distinct(AIAgentRun.created_by_id)).label("unique_users"),
            func.sum(AIAgentRun.total_cost_usd).label("total_cost"),
            func.avg(
                func.extract(
                    "epoch",
                    AIAgentRun.completed_at - AIAgentRun.started_at
                )
            ).label("avg_duration"),
            func.avg(AIAgentRun.current_step).label("avg_iterations"),
            func.sum(
                func.case((AIAgentRun.status == "completed", 1), else_=0)
            ).label("successful"),
            func.sum(
                func.case((AIAgentRun.retry_count > 0, 1), else_=0)
            ).label("retried"),
            func.sum(
                func.case((AIAgentRun.status == "timeout", 1), else_=0)
            ).label("timed_out"),
        ).where(and_(*conditions))

        result = await self.db_session.execute(query)
        row = result.one()

        total_runs = row.total_runs or 0
        successful = row.successful or 0

        metrics = AgentMetrics(
            agent_type=agent_type,
            total_runs=total_runs,
            unique_users=row.unique_users or 0,
            total_cost_usd=Decimal(str(row.total_cost or 0)),
            cost_per_run=(
                Decimal(str(row.total_cost or 0)) / total_runs
                if total_runs > 0
                else Decimal("0")
            ),
            average_duration_seconds=row.avg_duration,
            average_iterations=row.avg_iterations,
            success_rate=successful / total_runs * 100 if total_runs > 0 else None,
            retry_rate=(row.retried or 0) / total_runs * 100 if total_runs > 0 else None,
            timeout_rate=(row.timed_out or 0) / total_runs * 100 if total_runs > 0 else None,
        )

        # Get top errors
        error_query = (
            select(
                AIAgentRun.error_code,
                func.count(AIAgentRun.id).label("count"),
            )
            .where(
                and_(
                    *conditions,
                    AIAgentRun.error_code.isnot(None),
                )
            )
            .group_by(AIAgentRun.error_code)
            .order_by(func.count(AIAgentRun.id).desc())
            .limit(10)
        )
        error_result = await self.db_session.execute(error_query)
        metrics.top_errors = [
            {"error_code": r.error_code, "count": r.count}
            for r in error_result.all()
        ]

        return metrics

    async def get_cost_analysis(
        self,
        tenant_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> CostAnalysis:
        """Get detailed cost analysis.

        Args:
            tenant_id: Tenant ID
            start_date: Period start
            end_date: Period end

        Returns:
            CostAnalysis for the period
        """
        from example_service.infra.ai.agents.models import AIAgentRun

        conditions = [
            AIAgentRun.tenant_id == tenant_id,
            AIAgentRun.created_at >= start_date,
            AIAgentRun.created_at <= end_date,
        ]

        # Total cost
        total_query = select(
            func.sum(AIAgentRun.total_cost_usd).label("total_cost"),
            func.count(AIAgentRun.id).label("total_runs"),
            func.sum(
                AIAgentRun.total_input_tokens + AIAgentRun.total_output_tokens
            ).label("total_tokens"),
        ).where(and_(*conditions))

        total_result = await self.db_session.execute(total_query)
        total_row = total_result.one()

        # Cost by agent
        agent_query = (
            select(
                AIAgentRun.agent_type,
                func.sum(AIAgentRun.total_cost_usd).label("cost"),
            )
            .where(and_(*conditions))
            .group_by(AIAgentRun.agent_type)
        )
        agent_result = await self.db_session.execute(agent_query)
        cost_by_agent = {
            r.agent_type: Decimal(str(r.cost or 0))
            for r in agent_result.all()
        }

        # Cost by day
        daily_query = (
            select(
                func.date(AIAgentRun.created_at).label("date"),
                func.sum(AIAgentRun.total_cost_usd).label("cost"),
                func.count(AIAgentRun.id).label("runs"),
            )
            .where(and_(*conditions))
            .group_by(func.date(AIAgentRun.created_at))
            .order_by(func.date(AIAgentRun.created_at))
        )
        daily_result = await self.db_session.execute(daily_query)
        cost_by_day = [
            {
                "date": str(r.date),
                "cost_usd": float(r.cost or 0),
                "runs": r.runs,
            }
            for r in daily_result.all()
        ]

        # Calculate daily average and trend
        total_cost = Decimal(str(total_row.total_cost or 0))
        num_days = (end_date - start_date).days or 1
        daily_average = total_cost / num_days

        # Project monthly cost
        projected_monthly = daily_average * 30

        # Calculate wasted cost (failed runs)
        failed_query = select(
            func.sum(AIAgentRun.total_cost_usd).label("wasted"),
        ).where(
            and_(
                *conditions,
                AIAgentRun.status.in_(["failed", "timeout", "cancelled"]),
            )
        )
        failed_result = await self.db_session.execute(failed_query)
        wasted = Decimal(str(failed_result.scalar() or 0))

        return CostAnalysis(
            tenant_id=tenant_id,
            period_start=start_date,
            period_end=end_date,
            total_cost_usd=total_cost,
            total_runs=total_row.total_runs or 0,
            total_tokens=total_row.total_tokens or 0,
            cost_by_agent=cost_by_agent,
            cost_by_day=cost_by_day,
            daily_average=daily_average,
            projected_monthly=projected_monthly,
            wasted_cost=wasted,
        )

    async def get_usage_report(
        self,
        tenant_id: str,
        start_date: datetime,
        end_date: datetime,
        include_recommendations: bool = True,
    ) -> UsageReport:
        """Generate comprehensive usage report.

        Args:
            tenant_id: Tenant ID
            start_date: Report start date
            end_date: Report end date
            include_recommendations: Include optimization recommendations

        Returns:
            Complete UsageReport
        """
        # Get summary metrics
        summary = await self.get_usage_metrics(tenant_id, start_date, end_date)

        # Get metrics by agent
        from example_service.infra.ai.agents.models import AIAgentRun

        agent_types_query = (
            select(func.distinct(AIAgentRun.agent_type))
            .where(
                and_(
                    AIAgentRun.tenant_id == tenant_id,
                    AIAgentRun.created_at >= start_date,
                    AIAgentRun.created_at <= end_date,
                )
            )
        )
        agent_types_result = await self.db_session.execute(agent_types_query)
        agent_types = [r[0] for r in agent_types_result.all()]

        metrics_by_agent = []
        for agent_type in agent_types:
            agent_metrics = await self.get_agent_metrics(
                tenant_id, agent_type, start_date, end_date
            )
            metrics_by_agent.append(agent_metrics)

        # Get cost analysis
        cost_analysis = await self.get_cost_analysis(tenant_id, start_date, end_date)

        # Generate recommendations
        recommendations = []
        if include_recommendations:
            recommendations = self._generate_recommendations(
                summary, metrics_by_agent, cost_analysis
            )

        return UsageReport(
            tenant_id=tenant_id,
            report_period=f"{start_date.date()} to {end_date.date()}",
            summary=summary,
            metrics_by_agent=metrics_by_agent,
            cost_analysis=cost_analysis,
            recommendations=recommendations,
        )

    def _generate_recommendations(
        self,
        summary: UsageMetrics,
        agent_metrics: list[AgentMetrics],
        cost_analysis: CostAnalysis,
    ) -> list[str]:
        """Generate optimization recommendations."""
        recommendations = []

        # Check error rate
        if summary.error_rate and summary.error_rate > 10:
            recommendations.append(
                f"High error rate detected ({summary.error_rate:.1f}%). "
                "Review agent configurations and error logs."
            )

        # Check cost efficiency
        if cost_analysis.wasted_cost > cost_analysis.total_cost_usd * Decimal("0.2"):
            recommendations.append(
                f"${float(cost_analysis.wasted_cost):.2f} spent on failed runs. "
                "Consider improving retry logic or input validation."
            )

        # Check agent performance
        for agent in agent_metrics:
            if agent.timeout_rate and agent.timeout_rate > 5:
                recommendations.append(
                    f"Agent '{agent.agent_type}' has {agent.timeout_rate:.1f}% timeout rate. "
                    "Consider increasing timeout or optimizing prompts."
                )

            if agent.retry_rate and agent.retry_rate > 20:
                recommendations.append(
                    f"Agent '{agent.agent_type}' has {agent.retry_rate:.1f}% retry rate. "
                    "Review error handling and input validation."
                )

        return recommendations


@dataclass
class BenchmarkResult:
    """Result from a performance benchmark."""

    test_name: str
    iterations: int
    success_count: int
    failure_count: int

    # Timing
    min_duration_ms: float
    max_duration_ms: float
    avg_duration_ms: float
    median_duration_ms: float
    p95_duration_ms: float
    p99_duration_ms: float

    # Cost
    total_cost_usd: Decimal = field(default_factory=lambda: Decimal("0"))
    avg_cost_per_run: Decimal = field(default_factory=lambda: Decimal("0"))

    # Tokens
    total_tokens: int = 0
    avg_tokens_per_run: float = 0.0

    # Details
    individual_results: list[dict[str, Any]] = field(default_factory=list)


class PerformanceBenchmark(Generic[T]):
    """Performance benchmarking for agents.

    Run standardized tests to measure agent performance.

    Example:
        benchmark = PerformanceBenchmark(
            agent=my_agent,
            warmup_runs=2,
            benchmark_runs=10,
        )

        results = await benchmark.run([
            {"name": "simple_query", "input": {"query": "Hello"}},
            {"name": "complex_query", "input": {"query": "Explain..."}},
        ])
    """

    def __init__(
        self,
        agent: BaseAgent[Any, Any],
        warmup_runs: int = 2,
        benchmark_runs: int = 10,
    ) -> None:
        """Initialize benchmark.

        Args:
            agent: Agent to benchmark
            warmup_runs: Number of warmup runs (not counted)
            benchmark_runs: Number of benchmark runs
        """
        self.agent = agent
        self.warmup_runs = warmup_runs
        self.benchmark_runs = benchmark_runs

    async def run(
        self,
        test_cases: list[dict[str, Any]],
    ) -> list[BenchmarkResult]:
        """Run benchmarks for test cases.

        Args:
            test_cases: List of test cases with "name" and "input"

        Returns:
            List of BenchmarkResult for each test case
        """
        results = []

        for test_case in test_cases:
            result = await self._benchmark_case(test_case)
            results.append(result)

        return results

    async def _benchmark_case(
        self,
        test_case: dict[str, Any],
    ) -> BenchmarkResult:
        """Benchmark a single test case."""
        test_name = test_case.get("name", "unnamed")
        test_input = test_case.get("input", {})

        logger.info(f"Benchmarking: {test_name}")

        # Warmup runs
        for _ in range(self.warmup_runs):
            await self.agent.execute(test_input)

        # Benchmark runs
        durations: list[float] = []
        costs: list[Decimal] = []
        tokens: list[int] = []
        successes = 0
        failures = 0
        individual_results: list[dict[str, Any]] = []

        for i in range(self.benchmark_runs):
            start = datetime.now(UTC)
            result = await self.agent.execute(test_input)
            duration_ms = (datetime.now(UTC) - start).total_seconds() * 1000

            durations.append(duration_ms)
            costs.append(result.total_cost_usd)
            tokens.append(result.total_input_tokens + result.total_output_tokens)

            if result.success:
                successes += 1
            else:
                failures += 1

            individual_results.append({
                "iteration": i + 1,
                "success": result.success,
                "duration_ms": duration_ms,
                "cost_usd": float(result.total_cost_usd),
                "tokens": result.total_input_tokens + result.total_output_tokens,
                "error": result.error,
            })

        # Calculate statistics
        sorted_durations = sorted(durations)
        p95_idx = int(len(sorted_durations) * 0.95)
        p99_idx = int(len(sorted_durations) * 0.99)

        total_cost = sum(costs, Decimal("0"))
        total_tokens = sum(tokens)

        return BenchmarkResult(
            test_name=test_name,
            iterations=self.benchmark_runs,
            success_count=successes,
            failure_count=failures,
            min_duration_ms=min(durations),
            max_duration_ms=max(durations),
            avg_duration_ms=statistics.mean(durations),
            median_duration_ms=statistics.median(durations),
            p95_duration_ms=sorted_durations[p95_idx] if durations else 0,
            p99_duration_ms=sorted_durations[p99_idx] if durations else 0,
            total_cost_usd=total_cost,
            avg_cost_per_run=total_cost / self.benchmark_runs,
            total_tokens=total_tokens,
            avg_tokens_per_run=total_tokens / self.benchmark_runs,
            individual_results=individual_results,
        )

    def format_results(self, results: list[BenchmarkResult]) -> str:
        """Format benchmark results as a string."""
        lines = ["=" * 60, "BENCHMARK RESULTS", "=" * 60, ""]

        for result in results:
            lines.extend([
                f"Test: {result.test_name}",
                f"  Runs: {result.iterations} "
                f"(Success: {result.success_count}, Failed: {result.failure_count})",
                f"  Duration (ms):",
                f"    Min: {result.min_duration_ms:.2f}",
                f"    Max: {result.max_duration_ms:.2f}",
                f"    Avg: {result.avg_duration_ms:.2f}",
                f"    Median: {result.median_duration_ms:.2f}",
                f"    P95: {result.p95_duration_ms:.2f}",
                f"    P99: {result.p99_duration_ms:.2f}",
                f"  Cost: ${float(result.total_cost_usd):.4f} total, "
                f"${float(result.avg_cost_per_run):.4f}/run",
                f"  Tokens: {result.total_tokens} total, "
                f"{result.avg_tokens_per_run:.1f}/run",
                "",
            ])

        return "\n".join(lines)
