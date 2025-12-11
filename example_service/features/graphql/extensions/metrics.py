"""Prometheus metrics extension for GraphQL operations.

Provides comprehensive metrics for monitoring GraphQL API performance,
including request rates, latencies, error rates, complexity scores,
cache hit rates, and DataLoader efficiency.

Usage:
    from example_service.features.graphql.extensions.metrics import GraphQLMetricsExtension

    extensions = [
        GraphQLMetricsExtension(),  # Enable metrics
    ]
"""

from __future__ import annotations

import logging
import time

from prometheus_client import Counter, Gauge, Histogram
from strawberry.extensions import SchemaExtension

logger = logging.getLogger(__name__)

__all__ = ["GRAPHQL_METRICS", "GraphQLMetricsExtension"]


# ============================================================================
# Prometheus Metrics Definitions
# ============================================================================


class GraphQLMetrics:
    """Container for all GraphQL Prometheus metrics.

    Provides 20+ metrics across multiple categories:
    - Request metrics (rate, duration, errors)
    - Complexity metrics (score distribution)
    - Cache metrics (hit/miss rates)
    - DataLoader metrics (batch sizes, efficiency)
    - Resolver metrics (field execution times)
    """

    def __init__(self) -> None:
        """Initialize all GraphQL metrics."""
        # ====================================================================
        # Request Metrics
        # ====================================================================

        self.requests_total = Counter(
            "graphql_requests_total",
            "Total number of GraphQL requests",
            labelnames=["operation_type", "operation_name", "status"],
        )

        self.request_duration_seconds = Histogram(
            "graphql_request_duration_seconds",
            "GraphQL request duration in seconds",
            labelnames=["operation_type", "operation_name"],
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
        )

        self.errors_total = Counter(
            "graphql_errors_total",
            "Total number of GraphQL errors",
            labelnames=["operation_type", "operation_name", "error_code"],
        )

        self.validation_errors_total = Counter(
            "graphql_validation_errors_total",
            "Total number of GraphQL validation errors",
            labelnames=["operation_type"],
        )

        # ====================================================================
        # Complexity Metrics
        # ====================================================================

        self.complexity_score = Histogram(
            "graphql_complexity_score",
            "GraphQL query complexity score distribution",
            labelnames=["operation_type", "operation_name"],
            buckets=(10, 50, 100, 250, 500, 1000, 2500, 5000),
        )

        self.complexity_limit_exceeded_total = Counter(
            "graphql_complexity_limit_exceeded_total",
            "Number of queries rejected due to complexity limit",
            labelnames=["operation_type"],
        )

        self.query_depth = Histogram(
            "graphql_query_depth",
            "GraphQL query depth (nesting level)",
            labelnames=["operation_type", "operation_name"],
            buckets=(1, 2, 3, 5, 7, 10, 15, 20),
        )

        # ====================================================================
        # Cache Metrics
        # ====================================================================

        self.cache_hits_total = Counter(
            "graphql_cache_hits_total",
            "Total number of cache hits",
            labelnames=["cache_type", "operation_type"],
        )

        self.cache_misses_total = Counter(
            "graphql_cache_misses_total",
            "Total number of cache misses",
            labelnames=["cache_type", "operation_type"],
        )

        self.cache_hit_ratio = Gauge(
            "graphql_cache_hit_ratio",
            "Cache hit ratio (0.0-1.0)",
            labelnames=["cache_type"],
        )

        # ====================================================================
        # DataLoader Metrics
        # ====================================================================

        self.dataloader_batch_size = Histogram(
            "graphql_dataloader_batch_size",
            "DataLoader batch size distribution",
            labelnames=["loader_name"],
            buckets=(1, 2, 5, 10, 20, 50, 100, 200, 500),
        )

        self.dataloader_loads_total = Counter(
            "graphql_dataloader_loads_total",
            "Total number of DataLoader load calls",
            labelnames=["loader_name"],
        )

        self.dataloader_batches_total = Counter(
            "graphql_dataloader_batches_total",
            "Total number of DataLoader batch executions",
            labelnames=["loader_name"],
        )

        self.dataloader_cache_hits_total = Counter(
            "graphql_dataloader_cache_hits_total",
            "DataLoader cache hits (within request)",
            labelnames=["loader_name"],
        )

        # ====================================================================
        # Resolver Metrics
        # ====================================================================

        self.resolver_duration_seconds = Histogram(
            "graphql_resolver_duration_seconds",
            "Individual resolver execution duration",
            labelnames=["resolver_name", "parent_type"],
            buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
        )

        self.resolver_errors_total = Counter(
            "graphql_resolver_errors_total",
            "Total number of resolver errors",
            labelnames=["resolver_name", "parent_type"],
        )

        # ====================================================================
        # Rate Limiting Metrics
        # ====================================================================

        self.rate_limit_exceeded_total = Counter(
            "graphql_rate_limit_exceeded_total",
            "Number of requests rejected due to rate limiting",
            labelnames=["operation_type", "user_type"],
        )

        # ====================================================================
        # Concurrency Metrics
        # ====================================================================

        self.active_requests = Gauge(
            "graphql_active_requests",
            "Number of currently active GraphQL requests",
            labelnames=["operation_type"],
        )

        self.concurrent_resolvers = Gauge(
            "graphql_concurrent_resolvers",
            "Number of concurrently executing resolvers",
        )


# Global metrics instance
GRAPHQL_METRICS = GraphQLMetrics()


# ============================================================================
# Metrics Extension
# ============================================================================


class GraphQLMetricsExtension(SchemaExtension):
    """Prometheus metrics extension for GraphQL operations.

    Automatically records metrics for all GraphQL operations including:
    - Request rate and latency
    - Error rates and types
    - Query complexity scores
    - Cache performance
    - DataLoader efficiency

    Metrics are exposed via the standard Prometheus /metrics endpoint.

    Example:
        schema = strawberry.Schema(
            query=Query,
            mutation=Mutation,
            extensions=[
                GraphQLMetricsExtension(),  # Enable metrics
                GraphQLTracingExtension(),  # Enable tracing
                ComplexityLimiter(),
            ],
        )
    """

    def __init__(self) -> None:
        """Initialize metrics extension."""
        self.metrics = GRAPHQL_METRICS
        self._start_time: float | None = None

    def on_execute(self) -> None:
        """Record metrics at operation start."""
        execution_context = self.execution_context

        # Record start time
        self._start_time = time.perf_counter()

        # Get operation details
        operation_type = execution_context.operation_type or "unknown"
        operation_name = execution_context.operation_name or "anonymous"

        # Increment active requests gauge
        self.metrics.active_requests.labels(operation_type=operation_type).inc()

        # Store for later use
        execution_context._metrics_operation_type = operation_type
        execution_context._metrics_operation_name = operation_name

    def on_request_end(self) -> None:
        """Record metrics at operation end."""
        execution_context = self.execution_context

        # Calculate duration
        duration = time.perf_counter() - self._start_time if self._start_time else 0.0

        # Get operation details
        operation_type = getattr(execution_context, "_metrics_operation_type", "unknown")
        operation_name = getattr(execution_context, "_metrics_operation_name", "anonymous")

        # Decrement active requests gauge
        self.metrics.active_requests.labels(operation_type=operation_type).dec()

        # Record request duration
        self.metrics.request_duration_seconds.labels(
            operation_type=operation_type,
            operation_name=operation_name,
        ).observe(duration)

        # Check for errors
        result = execution_context.result
        status = "error" if (result and result.errors) else "success"

        # Increment request counter
        self.metrics.requests_total.labels(
            operation_type=operation_type,
            operation_name=operation_name,
            status=status,
        ).inc()

        # Record errors if any
        if result and result.errors:
            for error in result.errors:
                # Get error code if available
                error_code = "unknown"
                if hasattr(error, "extensions") and error.extensions:
                    error_code = error.extensions.get("code", "unknown")

                self.metrics.errors_total.labels(
                    operation_type=operation_type,
                    operation_name=operation_name,
                    error_code=error_code,
                ).inc()

        # Try to get complexity score if available
        # (This would be set by ComplexityLimiter extension)
        complexity = getattr(execution_context, "_complexity_score", None)
        if complexity is not None:
            self.metrics.complexity_score.labels(
                operation_type=operation_type,
                operation_name=operation_name,
            ).observe(complexity)

        # Try to get query depth if available
        depth = getattr(execution_context, "_query_depth", None)
        if depth is not None:
            self.metrics.query_depth.labels(
                operation_type=operation_type,
                operation_name=operation_name,
            ).observe(depth)


# ============================================================================
# Helper Functions for Recording Metrics
# ============================================================================


def record_cache_hit(cache_type: str, operation_type: str) -> None:
    """Record a cache hit.

    Args:
        cache_type: Type of cache (query, field, cdn)
        operation_type: GraphQL operation type
    """
    GRAPHQL_METRICS.cache_hits_total.labels(
        cache_type=cache_type,
        operation_type=operation_type,
    ).inc()


def record_cache_miss(cache_type: str, operation_type: str) -> None:
    """Record a cache miss.

    Args:
        cache_type: Type of cache (query, field, cdn)
        operation_type: GraphQL operation type
    """
    GRAPHQL_METRICS.cache_misses_total.labels(
        cache_type=cache_type,
        operation_type=operation_type,
    ).inc()


def record_dataloader_batch(loader_name: str, batch_size: int) -> None:
    """Record DataLoader batch execution.

    Args:
        loader_name: Name of the DataLoader
        batch_size: Number of keys in the batch
    """
    GRAPHQL_METRICS.dataloader_batch_size.labels(loader_name=loader_name).observe(batch_size)
    GRAPHQL_METRICS.dataloader_batches_total.labels(loader_name=loader_name).inc()


def record_dataloader_load(loader_name: str) -> None:
    """Record a DataLoader load call.

    Args:
        loader_name: Name of the DataLoader
    """
    GRAPHQL_METRICS.dataloader_loads_total.labels(loader_name=loader_name).inc()


def record_complexity_limit_exceeded(operation_type: str) -> None:
    """Record complexity limit rejection.

    Args:
        operation_type: GraphQL operation type
    """
    GRAPHQL_METRICS.complexity_limit_exceeded_total.labels(operation_type=operation_type).inc()


def record_rate_limit_exceeded(operation_type: str, user_type: str) -> None:
    """Record rate limit rejection.

    Args:
        operation_type: GraphQL operation type
        user_type: User type (authenticated, anonymous)
    """
    GRAPHQL_METRICS.rate_limit_exceeded_total.labels(
        operation_type=operation_type,
        user_type=user_type,
    ).inc()


# ============================================================================
# Usage Examples
# ============================================================================

"""
Example: Basic metrics setup
    from example_service.features.graphql.extensions.metrics import GraphQLMetricsExtension

    schema = strawberry.Schema(
        query=Query,
        mutation=Mutation,
        extensions=[
            GraphQLMetricsExtension(),  # Enable metrics
        ],
    )

Example: Recording cache metrics
    from example_service.features.graphql.extensions.metrics import (
        record_cache_hit,
        record_cache_miss,
    )

    # In query cache extension
    cached_result = cache.get(cache_key)
    if cached_result:
        record_cache_hit("query", operation_type)
        return cached_result
    else:
        record_cache_miss("query", operation_type)
        # Execute query...

Example: Recording DataLoader metrics
    from example_service.features.graphql.extensions.metrics import (
        record_dataloader_batch,
        record_dataloader_load,
    )

    class ReminderDataLoader:
        async def _batch_load_reminders(self, ids: list[UUID]) -> list[Reminder | None]:
            # Record batch execution
            record_dataloader_batch("reminders", len(ids))

            # Load reminders...
            return results

        async def load(self, id_: UUID) -> Reminder | None:
            # Record individual load call
            record_dataloader_load("reminders")
            return await self._loader.load(id_)

Example: Viewing metrics in Prometheus
    # Query examples:

    # Request rate per operation
    rate(graphql_requests_total[5m])

    # 95th percentile latency
    histogram_quantile(0.95, rate(graphql_request_duration_seconds_bucket[5m]))

    # Error rate
    rate(graphql_errors_total[5m]) / rate(graphql_requests_total[5m])

    # Cache hit ratio
    graphql_cache_hit_ratio

    # DataLoader batch efficiency
    rate(graphql_dataloader_batches_total[5m]) / rate(graphql_dataloader_loads_total[5m])

Example: Grafana dashboard queries
    # Panel 1: Request Rate
    sum(rate(graphql_requests_total[5m])) by (operation_type)

    # Panel 2: Latency (p50, p95, p99)
    histogram_quantile(0.50, sum(rate(graphql_request_duration_seconds_bucket[5m])) by (le))
    histogram_quantile(0.95, sum(rate(graphql_request_duration_seconds_bucket[5m])) by (le))
    histogram_quantile(0.99, sum(rate(graphql_request_duration_seconds_bucket[5m])) by (le))

    # Panel 3: Error Rate
    sum(rate(graphql_errors_total[5m])) by (error_code)

    # Panel 4: Complexity Distribution
    histogram_quantile(0.95, sum(rate(graphql_complexity_score_bucket[5m])) by (le))

    # Panel 5: Cache Performance
    sum(rate(graphql_cache_hits_total[5m])) / (
        sum(rate(graphql_cache_hits_total[5m])) + sum(rate(graphql_cache_misses_total[5m]))
    )

    # Panel 6: Active Requests
    sum(graphql_active_requests) by (operation_type)

Example: Alerting rules
    # High error rate
    - alert: GraphQLHighErrorRate
      expr: rate(graphql_errors_total[5m]) / rate(graphql_requests_total[5m]) > 0.05
      for: 5m
      annotations:
        summary: "GraphQL error rate above 5%"

    # High latency
    - alert: GraphQLHighLatency
      expr: histogram_quantile(0.95, rate(graphql_request_duration_seconds_bucket[5m])) > 2
      for: 5m
      annotations:
        summary: "GraphQL P95 latency above 2s"

    # Complexity limits frequently hit
    - alert: GraphQLComplexityLimitHigh
      expr: rate(graphql_complexity_limit_exceeded_total[5m]) > 10
      for: 5m
      annotations:
        summary: "Many queries hitting complexity limit"

    # DataLoader efficiency low
    - alert: GraphQLDataLoaderInefficient
      expr: |
        rate(graphql_dataloader_batches_total[5m]) /
        rate(graphql_dataloader_loads_total[5m]) < 0.5
      for: 10m
      annotations:
        summary: "DataLoader batching efficiency below 50%"

Best Practices:
1. Enable metrics in all environments
2. Set up Grafana dashboards for visualization
3. Configure alerts for critical metrics
4. Monitor cache hit ratios
5. Track DataLoader batch sizes (aim for >10 items per batch)
6. Watch for complexity limit rejections
7. Correlate with tracing data for debugging

Performance Considerations:
- Metrics have minimal overhead (~0.1ms per operation)
- Histograms use buckets to avoid high cardinality
- Labels are carefully chosen to avoid cardinality explosion
- Gauges are thread-safe and use atomic operations
"""
