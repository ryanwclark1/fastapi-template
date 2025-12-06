"""Prometheus metrics for AI workflow observability.

Provides metrics for:
- Pipeline execution (count, duration, success rate)
- Step execution (count, duration, provider usage)
- Provider performance (latency, error rate, cost)
- Resource usage (tokens, audio duration)
- Budget tracking (spend, remaining)

Metric Naming Convention:
    ai_<component>_<metric>_<unit>

Examples:
    - ai_pipeline_executions_total
    - ai_step_duration_seconds
    - ai_provider_cost_usd_total
    - ai_tokens_total

Labels:
    - pipeline: Pipeline name
    - step: Step name
    - provider: Provider name (openai, anthropic, deepgram)
    - capability: Capability type (transcription, llm_generation)
    - status: Execution status (success, failure, skipped)
    - tenant_id: Tenant identifier (if multi-tenant)

Example:
    from example_service.infra.ai.observability.metrics import AIMetrics

    metrics = AIMetrics()

    # Record pipeline execution
    metrics.record_pipeline_execution(
        pipeline_name="call_analysis",
        status="success",
        duration_seconds=45.2,
        total_cost_usd=Decimal("0.085"),
    )

    # Record step execution
    metrics.record_step_execution(
        pipeline_name="call_analysis",
        step_name="transcribe",
        provider="deepgram",
        capability="transcription_diarization",
        status="success",
        duration_seconds=12.5,
        cost_usd=Decimal("0.043"),
    )
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from decimal import Decimal

try:
    from prometheus_client import Counter, Gauge, Histogram, Summary

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    Counter = None  # type: ignore[assignment, misc]
    Gauge = None  # type: ignore[assignment, misc]
    Histogram = None  # type: ignore[assignment, misc]
    Summary = None  # type: ignore[assignment, misc]

logger = logging.getLogger(__name__)


class AIMetrics:
    """Prometheus metrics collector for AI workflows.

    Provides methods for recording metrics at different levels:
    - Pipeline level: Overall execution metrics
    - Step level: Individual step metrics
    - Provider level: API call metrics

    Thread Safety:
        Prometheus client metrics are thread-safe.
        This class is safe for concurrent use.

    Example:
        metrics = AIMetrics()

        # In pipeline executor
        with metrics.pipeline_timer("call_analysis"):
            result = await execute_pipeline()

        metrics.record_pipeline_execution(
            pipeline_name="call_analysis",
            status="success" if result.success else "failure",
            duration_seconds=result.total_duration_ms / 1000,
            total_cost_usd=result.total_cost_usd,
        )
    """

    # Histogram buckets for different metric types
    DURATION_BUCKETS = (0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0)
    LATENCY_BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)
    COST_BUCKETS = (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 5.0)
    TOKEN_BUCKETS = (10, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 50000)

    def __init__(self, prefix: str = "ai", enabled: bool = True) -> None:
        """Initialize AI metrics collector.

        Args:
            prefix: Metric name prefix
            enabled: Whether metrics collection is enabled
        """
        self.prefix = prefix
        self.enabled = enabled and PROMETHEUS_AVAILABLE

        if not PROMETHEUS_AVAILABLE and enabled:
            logger.warning(
                "Prometheus client not available. Install with: pip install prometheus-client"
            )

        if self.enabled:
            self._init_metrics()

    def _get_or_create_metric(
        self,
        metric_class: type[Counter | Gauge | Histogram | Summary] | None,
        name: str,
        description: str,
        labels: list[str],
        **kwargs: Any,
    ) -> Any:
        """Get existing metric or create new one.

        Handles Prometheus duplicate registration by returning existing metrics.
        """
        from prometheus_client import REGISTRY

        if metric_class is None:
            raise RuntimeError("Prometheus client not available")

        # Check if metric already exists in registry
        for collector in list(REGISTRY._names_to_collectors.values()):
            if hasattr(collector, "_name") and collector._name == name:
                return collector

        # Create new metric
        return metric_class(name, description, labels, **kwargs)

    def _load_existing_metrics(self) -> None:
        """Load references to existing metrics from Prometheus registry.

        Called when metrics were already registered (e.g., in tests or repeated startups).
        """
        from prometheus_client import REGISTRY

        def get_metric(name: str) -> Any:
            """Get metric from registry by name."""
            return REGISTRY._names_to_collectors.get(name)

        # Pipeline metrics
        self.pipeline_executions_total = get_metric(f"{self.prefix}_pipeline_executions_total")
        self.pipeline_duration_seconds = get_metric(f"{self.prefix}_pipeline_duration_seconds")
        self.pipeline_cost_usd_total = get_metric(f"{self.prefix}_pipeline_cost_usd_total")
        self.pipeline_steps_completed = get_metric(f"{self.prefix}_pipeline_steps_completed")
        self.pipelines_active = get_metric(f"{self.prefix}_pipelines_active")

        # Step metrics
        self.step_executions_total = get_metric(f"{self.prefix}_step_executions_total")
        self.step_duration_seconds = get_metric(f"{self.prefix}_step_duration_seconds")
        self.step_retries_total = get_metric(f"{self.prefix}_step_retries_total")
        self.step_fallbacks_total = get_metric(f"{self.prefix}_step_fallbacks_total")
        self.step_skipped_total = get_metric(f"{self.prefix}_step_skipped_total")

        # Provider metrics
        self.provider_requests_total = get_metric(f"{self.prefix}_provider_requests_total")
        self.provider_latency_seconds = get_metric(f"{self.prefix}_provider_latency_seconds")
        self.provider_errors_total = get_metric(f"{self.prefix}_provider_errors_total")
        self.provider_cost_usd_total = get_metric(f"{self.prefix}_provider_cost_usd_total")
        self.provider_cost_per_call_usd = get_metric(f"{self.prefix}_provider_cost_per_call_usd")

        # Resource usage metrics
        self.tokens_processed_total = get_metric(f"{self.prefix}_tokens_processed_total")
        self.tokens_per_request = get_metric(f"{self.prefix}_tokens_per_request")
        self.audio_seconds_processed = get_metric(f"{self.prefix}_audio_seconds_processed")

        # Budget metrics
        self.budget_checks_total = get_metric(f"{self.prefix}_budget_checks_total")
        self.budget_exceeded_total = get_metric(f"{self.prefix}_budget_exceeded_total")
        self.budget_utilization_percent = get_metric(f"{self.prefix}_budget_utilization_percent")

        # Saga metrics
        self.compensations_total = get_metric(f"{self.prefix}_compensations_total")
        self.compensation_duration_seconds = get_metric(
            f"{self.prefix}_compensation_duration_seconds"
        )

        # Event metrics
        self.events_published_total = get_metric(f"{self.prefix}_events_published_total")
        self.event_subscribers_active = get_metric(f"{self.prefix}_event_subscribers_active")

    def _init_metrics(self) -> None:
        """Initialize all Prometheus metrics.

        Uses _get_or_create_metric to handle cases where metrics were
        already registered (e.g., in tests or repeated startups).
        """
        from prometheus_client import REGISTRY

        # Check if metrics already exist (from previous init)
        first_metric_name = f"{self.prefix}_pipeline_executions_total"
        if first_metric_name in REGISTRY._names_to_collectors:
            logger.debug("AI metrics already registered, reusing existing metrics")
            # Get references to existing metrics
            self._load_existing_metrics()
            return

        # ============================================================
        # Pipeline Metrics
        # ============================================================

        self.pipeline_executions_total = Counter(
            f"{self.prefix}_pipeline_executions_total",
            "Total number of pipeline executions",
            ["pipeline", "status", "tenant_id"],
        )

        self.pipeline_duration_seconds = Histogram(
            f"{self.prefix}_pipeline_duration_seconds",
            "Pipeline execution duration in seconds",
            ["pipeline", "status"],
            buckets=self.DURATION_BUCKETS,
        )

        self.pipeline_cost_usd_total = Counter(
            f"{self.prefix}_pipeline_cost_usd_total",
            "Total cost of pipeline executions in USD",
            ["pipeline", "tenant_id"],
        )

        self.pipeline_steps_completed = Histogram(
            f"{self.prefix}_pipeline_steps_completed",
            "Number of steps completed per pipeline execution",
            ["pipeline"],
            buckets=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10),
        )

        self.pipelines_active = Gauge(
            f"{self.prefix}_pipelines_active",
            "Number of currently executing pipelines",
            ["pipeline"],
        )

        # ============================================================
        # Step Metrics
        # ============================================================

        self.step_executions_total = Counter(
            f"{self.prefix}_step_executions_total",
            "Total number of step executions",
            ["pipeline", "step", "capability", "status"],
        )

        self.step_duration_seconds = Histogram(
            f"{self.prefix}_step_duration_seconds",
            "Step execution duration in seconds",
            ["pipeline", "step", "capability"],
            buckets=self.DURATION_BUCKETS,
        )

        self.step_retries_total = Counter(
            f"{self.prefix}_step_retries_total",
            "Total number of step retries",
            ["pipeline", "step", "capability"],
        )

        self.step_fallbacks_total = Counter(
            f"{self.prefix}_step_fallbacks_total",
            "Total number of fallback attempts",
            ["pipeline", "step", "from_provider", "to_provider"],
        )

        self.step_skipped_total = Counter(
            f"{self.prefix}_step_skipped_total",
            "Total number of skipped steps",
            ["pipeline", "step", "reason"],
        )

        # ============================================================
        # Provider Metrics
        # ============================================================

        self.provider_requests_total = Counter(
            f"{self.prefix}_provider_requests_total",
            "Total number of provider API requests",
            ["provider", "capability", "status"],
        )

        self.provider_latency_seconds = Histogram(
            f"{self.prefix}_provider_latency_seconds",
            "Provider API latency in seconds",
            ["provider", "capability"],
            buckets=self.LATENCY_BUCKETS,
        )

        self.provider_errors_total = Counter(
            f"{self.prefix}_provider_errors_total",
            "Total number of provider errors",
            ["provider", "capability", "error_code"],
        )

        self.provider_cost_usd_total = Counter(
            f"{self.prefix}_provider_cost_usd_total",
            "Total cost by provider in USD",
            ["provider", "capability", "tenant_id"],
        )

        self.provider_cost_per_call_usd = Histogram(
            f"{self.prefix}_provider_cost_per_call_usd",
            "Cost distribution per provider call",
            ["provider", "capability"],
            buckets=self.COST_BUCKETS,
        )

        # ============================================================
        # Resource Usage Metrics
        # ============================================================

        self.tokens_total = Counter(
            f"{self.prefix}_tokens_total",
            "Total tokens processed",
            ["provider", "capability", "direction"],  # direction: input/output
        )

        self.tokens_per_request = Histogram(
            f"{self.prefix}_tokens_per_request",
            "Tokens per request distribution",
            ["provider", "capability", "direction"],
            buckets=self.TOKEN_BUCKETS,
        )

        self.audio_seconds_total = Counter(
            f"{self.prefix}_audio_seconds_total",
            "Total audio seconds processed",
            ["provider", "capability"],
        )

        self.characters_total = Counter(
            f"{self.prefix}_characters_total",
            "Total characters processed (PII, etc.)",
            ["provider", "capability"],
        )

        # ============================================================
        # Budget Metrics
        # ============================================================

        self.budget_spend_usd = Gauge(
            f"{self.prefix}_budget_spend_usd",
            "Current budget spend in USD",
            ["tenant_id", "period"],  # period: daily, monthly
        )

        self.budget_limit_usd = Gauge(
            f"{self.prefix}_budget_limit_usd",
            "Budget limit in USD",
            ["tenant_id", "period"],
        )

        self.budget_utilization_ratio = Gauge(
            f"{self.prefix}_budget_utilization_ratio",
            "Budget utilization ratio (0-1)",
            ["tenant_id", "period"],
        )

        self.budget_exceeded_total = Counter(
            f"{self.prefix}_budget_exceeded_total",
            "Number of times budget was exceeded",
            ["tenant_id", "action"],  # action: blocked, warned
        )

        # ============================================================
        # Compensation Metrics
        # ============================================================

        self.compensation_executions_total = Counter(
            f"{self.prefix}_compensation_executions_total",
            "Total number of compensation executions",
            ["pipeline", "status"],  # status: success, partial, failed
        )

        self.compensation_steps_total = Counter(
            f"{self.prefix}_compensation_steps_total",
            "Total number of compensation steps executed",
            ["pipeline", "step", "status"],
        )

    # ================================================================
    # Pipeline Recording Methods
    # ================================================================

    def record_pipeline_started(
        self,
        pipeline_name: str,
        _tenant_id: str | None = None,
    ) -> None:
        """Record pipeline execution started."""
        if not self.enabled:
            return

        self.pipelines_active.labels(
            pipeline=pipeline_name,
        ).inc()

    def record_pipeline_completed(
        self,
        pipeline_name: str,
        _tenant_id: str | None = None,
    ) -> None:
        """Record pipeline execution completed (success or failure)."""
        if not self.enabled:
            return

        self.pipelines_active.labels(
            pipeline=pipeline_name,
        ).dec()

    def record_pipeline_execution(
        self,
        pipeline_name: str,
        status: str,
        duration_seconds: float,
        total_cost_usd: Decimal | float,
        steps_completed: int = 0,
        tenant_id: str | None = None,
    ) -> None:
        """Record complete pipeline execution metrics."""
        if not self.enabled:
            return

        tenant = tenant_id or "default"

        self.pipeline_executions_total.labels(
            pipeline=pipeline_name,
            status=status,
            tenant_id=tenant,
        ).inc()

        self.pipeline_duration_seconds.labels(
            pipeline=pipeline_name,
            status=status,
        ).observe(duration_seconds)

        self.pipeline_cost_usd_total.labels(
            pipeline=pipeline_name,
            tenant_id=tenant,
        ).inc(float(total_cost_usd))

        self.pipeline_steps_completed.labels(
            pipeline=pipeline_name,
        ).observe(steps_completed)

    # ================================================================
    # Step Recording Methods
    # ================================================================

    def record_step_execution(
        self,
        pipeline_name: str,
        step_name: str,
        capability: str,
        status: str,
        duration_seconds: float,
        _cost_usd: Decimal | float = 0,
        retries: int = 0,
        _provider_used: str | None = None,
    ) -> None:
        """Record step execution metrics."""
        if not self.enabled:
            return

        self.step_executions_total.labels(
            pipeline=pipeline_name,
            step=step_name,
            capability=capability,
            status=status,
        ).inc()

        self.step_duration_seconds.labels(
            pipeline=pipeline_name,
            step=step_name,
            capability=capability,
        ).observe(duration_seconds)

        if retries > 0:
            self.step_retries_total.labels(
                pipeline=pipeline_name,
                step=step_name,
                capability=capability,
            ).inc(retries)

    def record_step_fallback(
        self,
        pipeline_name: str,
        step_name: str,
        from_provider: str,
        to_provider: str,
    ) -> None:
        """Record a fallback from one provider to another."""
        if not self.enabled:
            return

        self.step_fallbacks_total.labels(
            pipeline=pipeline_name,
            step=step_name,
            from_provider=from_provider,
            to_provider=to_provider,
        ).inc()

    def record_step_skipped(
        self,
        pipeline_name: str,
        step_name: str,
        reason: str,
    ) -> None:
        """Record a skipped step."""
        if not self.enabled:
            return

        self.step_skipped_total.labels(
            pipeline=pipeline_name,
            step=step_name,
            reason=reason,
        ).inc()

    # ================================================================
    # Provider Recording Methods
    # ================================================================

    def record_provider_request(
        self,
        provider: str,
        capability: str,
        status: str,
        latency_seconds: float,
        cost_usd: Decimal | float = 0,
        error_code: str | None = None,
        tenant_id: str | None = None,
    ) -> None:
        """Record provider API request metrics."""
        if not self.enabled:
            return

        tenant = tenant_id or "default"

        self.provider_requests_total.labels(
            provider=provider,
            capability=capability,
            status=status,
        ).inc()

        self.provider_latency_seconds.labels(
            provider=provider,
            capability=capability,
        ).observe(latency_seconds)

        if status == "failure" and error_code:
            self.provider_errors_total.labels(
                provider=provider,
                capability=capability,
                error_code=error_code,
            ).inc()

        if cost_usd:
            cost = float(cost_usd)
            self.provider_cost_usd_total.labels(
                provider=provider,
                capability=capability,
                tenant_id=tenant,
            ).inc(cost)

            self.provider_cost_per_call_usd.labels(
                provider=provider,
                capability=capability,
            ).observe(cost)

    def record_token_usage(
        self,
        provider: str,
        capability: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        """Record token usage metrics."""
        if not self.enabled:
            return

        if input_tokens > 0:
            self.tokens_total.labels(
                provider=provider,
                capability=capability,
                direction="input",
            ).inc(input_tokens)

            self.tokens_per_request.labels(
                provider=provider,
                capability=capability,
                direction="input",
            ).observe(input_tokens)

        if output_tokens > 0:
            self.tokens_total.labels(
                provider=provider,
                capability=capability,
                direction="output",
            ).inc(output_tokens)

            self.tokens_per_request.labels(
                provider=provider,
                capability=capability,
                direction="output",
            ).observe(output_tokens)

    def record_audio_duration(
        self,
        provider: str,
        capability: str,
        duration_seconds: float,
    ) -> None:
        """Record audio duration processed."""
        if not self.enabled:
            return

        self.audio_seconds_total.labels(
            provider=provider,
            capability=capability,
        ).inc(duration_seconds)

    def record_character_count(
        self,
        provider: str,
        capability: str,
        character_count: int,
    ) -> None:
        """Record character count processed."""
        if not self.enabled:
            return

        self.characters_total.labels(
            provider=provider,
            capability=capability,
        ).inc(character_count)

    # ================================================================
    # Budget Recording Methods
    # ================================================================

    def record_budget_status(
        self,
        tenant_id: str,
        period: str,
        spend_usd: Decimal | float,
        limit_usd: Decimal | float,
    ) -> None:
        """Record current budget status."""
        if not self.enabled:
            return

        spend = float(spend_usd)
        limit = float(limit_usd)

        self.budget_spend_usd.labels(
            tenant_id=tenant_id,
            period=period,
        ).set(spend)

        self.budget_limit_usd.labels(
            tenant_id=tenant_id,
            period=period,
        ).set(limit)

        if limit > 0:
            self.budget_utilization_ratio.labels(
                tenant_id=tenant_id,
                period=period,
            ).set(spend / limit)

    def record_budget_exceeded(
        self,
        tenant_id: str,
        action: str,
    ) -> None:
        """Record budget exceeded event."""
        if not self.enabled:
            return

        self.budget_exceeded_total.labels(
            tenant_id=tenant_id,
            action=action,
        ).inc()

    # ================================================================
    # Compensation Recording Methods
    # ================================================================

    def record_compensation_execution(
        self,
        pipeline_name: str,
        status: str,
        _steps_compensated: int = 0,
        _steps_failed: int = 0,
    ) -> None:
        """Record compensation execution metrics."""
        if not self.enabled:
            return

        self.compensation_executions_total.labels(
            pipeline=pipeline_name,
            status=status,
        ).inc()

    def record_compensation_step(
        self,
        pipeline_name: str,
        step_name: str,
        status: str,
    ) -> None:
        """Record individual compensation step."""
        if not self.enabled:
            return

        self.compensation_steps_total.labels(
            pipeline=pipeline_name,
            step=step_name,
            status=status,
        ).inc()


# Singleton instance
_metrics: AIMetrics | None = None


def get_ai_metrics() -> AIMetrics:
    """Get the global AI metrics singleton.

    Returns:
        The singleton AIMetrics instance
    """
    global _metrics
    if _metrics is None:
        _metrics = AIMetrics()
    return _metrics


def configure_ai_metrics(
    prefix: str = "ai",
    enabled: bool = True,
) -> AIMetrics:
    """Configure and return the global AI metrics.

    Args:
        prefix: Metric name prefix
        enabled: Whether metrics collection is enabled

    Returns:
        Configured AIMetrics instance
    """
    global _metrics
    # Reuse existing metrics if already configured to avoid Prometheus duplicate registration
    if _metrics is not None:
        return _metrics
    _metrics = AIMetrics(prefix=prefix, enabled=enabled)
    return _metrics
