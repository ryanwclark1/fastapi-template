"""GraphQL extensions for security, performance, and observability.

This package contains Strawberry extensions that enhance the GraphQL API with:
- Rate limiting (per-operation throttling)
- Query complexity limiting (depth and cost scoring)
- OpenTelemetry tracing (distributed tracing)
- Prometheus metrics (request rates, latencies, caching, DataLoaders)
- Caching (query and field-level)
"""

from __future__ import annotations

from example_service.features.graphql.extensions.complexity_limiter import (
    ComplexityConfig,
    ComplexityLimiter,
)
from example_service.features.graphql.extensions.metrics import (
    GRAPHQL_METRICS,
    GraphQLMetricsExtension,
    record_cache_hit,
    record_cache_miss,
    record_complexity_limit_exceeded,
    record_dataloader_batch,
    record_dataloader_load,
    record_rate_limit_exceeded,
)
from example_service.features.graphql.extensions.rate_limiter import GraphQLRateLimiter
from example_service.features.graphql.extensions.tracing import (
    GraphQLTracingExtension,
    get_graphql_tracer,
    trace_dataloader_batch,
    trace_resolver,
)

__all__ = [
    "GRAPHQL_METRICS",
    "ComplexityConfig",
    "ComplexityLimiter",
    # Metrics
    "GraphQLMetricsExtension",
    # Security
    "GraphQLRateLimiter",
    # Observability
    "GraphQLTracingExtension",
    "get_graphql_tracer",
    "record_cache_hit",
    "record_cache_miss",
    "record_complexity_limit_exceeded",
    "record_dataloader_batch",
    "record_dataloader_load",
    "record_rate_limit_exceeded",
    "trace_dataloader_batch",
    "trace_resolver",
]
