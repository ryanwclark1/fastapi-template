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
