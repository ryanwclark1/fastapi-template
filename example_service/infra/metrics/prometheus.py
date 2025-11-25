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
