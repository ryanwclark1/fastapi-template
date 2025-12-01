"""Prometheus metrics for monitoring with exemplar support."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

# Create custom registry for better control and exemplar support
REGISTRY = CollectorRegistry()

# Define histogram buckets for better granularity
# Covers response times from 1ms to 10s
DEFAULT_LATENCY_BUCKETS = (
    0.001,
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)

# Middleware-specific latency buckets (optimized for fast middleware operations)
# Covers execution times from 100μs to 1s
MIDDLEWARE_LATENCY_BUCKETS = (
    0.001,  # 1ms
    0.005,  # 5ms
    0.01,  # 10ms
    0.025,  # 25ms
    0.05,  # 50ms
    0.1,  # 100ms
    0.25,  # 250ms
    0.5,  # 500ms
    1.0,  # 1s
)

# Request size buckets (1KB to 10MB)
REQUEST_SIZE_BUCKETS = (
    1024,  # 1KB
    10240,  # 10KB
    102400,  # 100KB
    1048576,  # 1MB
    10485760,  # 10MB
)

# HTTP metrics
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
    registry=REGISTRY,
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
    buckets=DEFAULT_LATENCY_BUCKETS,
    registry=REGISTRY,
)

http_requests_in_progress = Gauge(
    "http_requests_in_progress",
    "Number of HTTP requests in progress",
    ["method", "endpoint"],
    registry=REGISTRY,
)

# Middleware metrics
middleware_execution_seconds = Histogram(
    "middleware_execution_seconds",
    "Individual middleware execution time in seconds. "
    "Tracks the performance of each middleware component separately. "
    "Usage: Instrument at the start and end of each middleware's process_request/process_response.",
    ["middleware_name"],
    buckets=MIDDLEWARE_LATENCY_BUCKETS,
    registry=REGISTRY,
)

request_size_bytes = Histogram(
    "request_size_bytes",
    "Distribution of HTTP request body sizes in bytes. "
    "Helps identify payload patterns and optimize size limits. "
    "Usage: Record after reading request body in middleware, before processing.",
    ["endpoint", "method"],
    buckets=REQUEST_SIZE_BUCKETS,
    registry=REGISTRY,
)

request_size_limit_rejections_total = Counter(
    "request_size_limit_rejections_total",
    "Total number of requests rejected due to exceeding size limits. "
    "Indicates clients sending oversized payloads. "
    "Usage: Increment when rejecting requests in size validation middleware.",
    ["endpoint", "method"],
    registry=REGISTRY,
)

rate_limit_rejections_total = Counter(
    "rate_limit_rejections_total",
    "Total number of requests rejected due to rate limiting. "
    "Tracks rate limit enforcement by key type (IP, user, API key, etc.). "
    "Usage: Increment when rate limiter rejects a request with 429 status.",
    ["endpoint", "limit_key_type"],
    registry=REGISTRY,
)

middleware_errors_total = Counter(
    "middleware_errors_total",
    "Total number of errors occurring in middleware processing. "
    "Categorized by middleware name and error type for debugging. "
    "Usage: Increment in middleware exception handlers with error classification.",
    ["middleware_name", "error_type"],
    registry=REGISTRY,
)

# Database metrics
database_connections_active = Gauge(
    "database_connections_active",
    "Number of active database connections",
    registry=REGISTRY,
)

database_query_duration_seconds = Histogram(
    "database_query_duration_seconds",
    "Database query duration in seconds",
    ["operation"],
    buckets=DEFAULT_LATENCY_BUCKETS,
    registry=REGISTRY,
)

# Database Pool metrics
# These metrics provide deep visibility into SQLAlchemy connection pool health
database_pool_size = Gauge(
    "database_pool_size",
    "Configured maximum pool size. "
    "Set at startup from DB_POOL_SIZE setting. "
    "Use with database_pool_checkedout for utilization calculation.",
    registry=REGISTRY,
)

database_pool_max_overflow = Gauge(
    "database_pool_max_overflow",
    "Configured maximum overflow connections beyond pool_size. "
    "Set at startup from DB_MAX_OVERFLOW setting. "
    "Overflow connections are created when pool is exhausted.",
    registry=REGISTRY,
)

database_pool_checkedout = Gauge(
    "database_pool_checkedout",
    "Number of connections currently checked out from the pool. "
    "Incremented on checkout, decremented on checkin. "
    "Alert when approaching pool_size + max_overflow.",
    registry=REGISTRY,
)

database_pool_overflow = Gauge(
    "database_pool_overflow",
    "Current number of overflow connections in use. "
    "Non-zero indicates pool exhaustion requiring temporary connections. "
    "Sustained overflow suggests pool_size needs increase.",
    registry=REGISTRY,
)

database_pool_checkout_time_seconds = Histogram(
    "database_pool_checkout_time_seconds",
    "Time spent waiting to acquire a connection from the pool. "
    "High values indicate pool contention or exhaustion. "
    "Excludes actual query time - measures only pool wait.",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    registry=REGISTRY,
)

database_pool_checkout_timeout_total = Counter(
    "database_pool_checkout_timeout_total",
    "Total connection checkout timeouts. "
    "Occurs when pool_timeout exceeded waiting for connection. "
    "Critical alert - indicates capacity issues.",
    registry=REGISTRY,
)

database_pool_invalidations_total = Counter(
    "database_pool_invalidations_total",
    "Total connections invalidated and removed from pool. "
    "Tracked by reason: stale (age exceeded), error (connection failed), soft (recyclable).",
    ["reason"],
    registry=REGISTRY,
)

database_pool_recycles_total = Counter(
    "database_pool_recycles_total",
    "Total connections recycled due to exceeding pool_recycle age. "
    "Normal maintenance - prevents stale connections. "
    "High rate may indicate pool_recycle set too low.",
    registry=REGISTRY,
)

# Cache metrics
cache_hits_total = Counter(
    "cache_hits_total",
    "Total number of cache hits",
    ["cache_name"],
    registry=REGISTRY,
)

cache_misses_total = Counter(
    "cache_misses_total",
    "Total number of cache misses",
    ["cache_name"],
    registry=REGISTRY,
)

cache_operation_duration_seconds = Histogram(
    "cache_operation_duration_seconds",
    "Cache operation duration in seconds",
    ["operation", "cache_name"],
    buckets=DEFAULT_LATENCY_BUCKETS,
    registry=REGISTRY,
)

# Cache Infrastructure Metrics
# These metrics track Redis server health and resource usage
cache_memory_bytes = Gauge(
    "cache_memory_bytes",
    "Redis memory usage in bytes. "
    "Collected from Redis INFO command (used_memory field). "
    "Monitor for memory pressure and capacity planning.",
    ["cache_name"],
    registry=REGISTRY,
)

cache_memory_max_bytes = Gauge(
    "cache_memory_max_bytes",
    "Redis maximum memory limit in bytes. "
    "0 means no limit configured. "
    "Use with cache_memory_bytes for utilization calculation.",
    ["cache_name"],
    registry=REGISTRY,
)

cache_keys_total = Gauge(
    "cache_keys_total",
    "Total number of keys in Redis database. "
    "Collected from Redis INFO command (db0.keys). "
    "Useful for capacity monitoring.",
    ["cache_name"],
    registry=REGISTRY,
)

cache_evictions_total = Counter(
    "cache_evictions_total",
    "Total number of keys evicted from cache. "
    "High eviction rate indicates memory pressure. "
    "Tracked from Redis INFO evicted_keys delta.",
    ["cache_name"],
    registry=REGISTRY,
)

cache_expired_keys_total = Counter(
    "cache_expired_keys_total",
    "Total number of keys expired due to TTL. "
    "Normal cache behavior - indicates TTL is working. "
    "Tracked from Redis INFO expired_keys delta.",
    ["cache_name"],
    registry=REGISTRY,
)

cache_connections_active = Gauge(
    "cache_connections_active",
    "Number of active Redis client connections. "
    "From Redis INFO connected_clients. "
    "Spike may indicate connection leak.",
    ["cache_name"],
    registry=REGISTRY,
)

cache_commands_total = Counter(
    "cache_commands_total",
    "Total commands processed by Redis. "
    "From Redis INFO total_commands_processed delta. "
    "Useful for throughput monitoring.",
    ["cache_name"],
    registry=REGISTRY,
)

cache_keyspace_hits_total = Counter(
    "cache_keyspace_hits_total",
    "Total keyspace hits from Redis server perspective. "
    "From Redis INFO keyspace_hits. "
    "Compare with cache_hits_total for validation.",
    ["cache_name"],
    registry=REGISTRY,
)

cache_keyspace_misses_total = Counter(
    "cache_keyspace_misses_total",
    "Total keyspace misses from Redis server perspective. "
    "From Redis INFO keyspace_misses. "
    "Compare with cache_misses_total for validation.",
    ["cache_name"],
    registry=REGISTRY,
)

# RabbitMQ metrics
rabbitmq_messages_published_total = Counter(
    "rabbitmq_messages_published_total",
    "Total number of messages published to RabbitMQ",
    ["exchange"],
    registry=REGISTRY,
)

rabbitmq_messages_consumed_total = Counter(
    "rabbitmq_messages_consumed_total",
    "Total number of messages consumed from RabbitMQ",
    ["queue"],
    registry=REGISTRY,
)

# WebSocket metrics
websocket_connections_total = Gauge(
    "websocket_connections_total",
    "Current number of active WebSocket connections",
    registry=REGISTRY,
)

websocket_messages_received_total = Counter(
    "websocket_messages_received_total",
    "Total number of WebSocket messages received from clients",
    ["message_type"],
    registry=REGISTRY,
)

websocket_messages_sent_total = Counter(
    "websocket_messages_sent_total",
    "Total number of WebSocket messages sent to clients",
    ["message_type"],
    registry=REGISTRY,
)

websocket_connection_duration_seconds = Histogram(
    "websocket_connection_duration_seconds",
    "Duration of WebSocket connections in seconds",
    buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600),
    registry=REGISTRY,
)

websocket_broadcast_recipients = Histogram(
    "websocket_broadcast_recipients",
    "Number of recipients per broadcast message",
    buckets=(1, 5, 10, 25, 50, 100, 250, 500, 1000),
    registry=REGISTRY,
)

# Taskiq metrics
taskiq_tasks_total = Counter(
    "taskiq_tasks_total",
    "Total number of Taskiq tasks executed",
    ["task_name", "status"],
    registry=REGISTRY,
)

taskiq_task_duration_seconds = Histogram(
    "taskiq_task_duration_seconds",
    "Taskiq task duration in seconds",
    ["task_name"],
    buckets=DEFAULT_LATENCY_BUCKETS,
    registry=REGISTRY,
)

# Application metrics
application_info = Gauge(
    "application_info",
    "Application information",
    ["version", "service", "environment"],
    registry=REGISTRY,
)

# ──────────────────────────────────────────────────────────────────────────────
# OpenTelemetry Exporter Metrics
# ──────────────────────────────────────────────────────────────────────────────
# These metrics provide visibility into the health and performance of OTLP span export

otel_spans_exported_total = Counter(
    "otel_spans_exported_total",
    "Total number of spans exported via OTLP. "
    "Tracks successful span delivery to collector. "
    "Usage: Incremented after each successful batch export.",
    ["exporter_type"],
    registry=REGISTRY,
)

otel_spans_failed_total = Counter(
    "otel_spans_failed_total",
    "Total number of spans that failed to export. "
    "Indicates connectivity or collector issues. "
    "Usage: Incremented when export returns non-success result.",
    ["exporter_type", "error_type"],
    registry=REGISTRY,
)

otel_spans_dropped_total = Counter(
    "otel_spans_dropped_total",
    "Total number of spans dropped due to queue overflow. "
    "Indicates BatchSpanProcessor queue exhaustion. "
    "Critical - spans are permanently lost when this increments.",
    ["exporter_type"],
    registry=REGISTRY,
)

otel_export_duration_seconds = Histogram(
    "otel_export_duration_seconds",
    "Duration of OTLP export operations in seconds. "
    "Measures time from export call to completion. "
    "High latency may indicate network or collector issues.",
    ["exporter_type"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=REGISTRY,
)

otel_export_batch_size = Histogram(
    "otel_export_batch_size",
    "Number of spans per export batch. "
    "Tracks how full batches are before export. "
    "Consistently small batches may indicate low traffic or aggressive scheduling.",
    ["exporter_type"],
    buckets=(1, 5, 10, 25, 50, 100, 250, 500, 1000, 2000),
    registry=REGISTRY,
)

otel_exporter_state = Gauge(
    "otel_exporter_state",
    "Current state of the OTLP exporter. "
    "Values: 0=unknown, 1=healthy, 2=degraded, 3=failing. "
    "Based on recent export success rate.",
    ["exporter_type"],
    registry=REGISTRY,
)

otel_export_retries_total = Counter(
    "otel_export_retries_total",
    "Total number of export retry attempts. "
    "Non-zero indicates transient collector connectivity issues. "
    "Usage: Incremented on each retry attempt before success or final failure.",
    ["exporter_type"],
    registry=REGISTRY,
)

otel_last_successful_export_timestamp = Gauge(
    "otel_last_successful_export_timestamp",
    "Unix timestamp of the last successful export. "
    "Use for alerting on export staleness. "
    "Compare with current time to detect export failures.",
    ["exporter_type"],
    registry=REGISTRY,
)
