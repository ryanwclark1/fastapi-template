"""Business metrics and KPIs for monitoring application health and usage."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

from example_service.infra.metrics.prometheus import DEFAULT_LATENCY_BUCKETS, REGISTRY

# ============================================================================
# Error and Exception Metrics
# ============================================================================

errors_total = Counter(
    "errors_total",
    "Total number of errors by type and endpoint",
    ["error_type", "endpoint", "status_code"],
    registry=REGISTRY,
)

exceptions_unhandled_total = Counter(
    "exceptions_unhandled_total",
    "Total number of unhandled exceptions",
    ["exception_type", "endpoint"],
    registry=REGISTRY,
)

validation_errors_total = Counter(
    "validation_errors_total",
    "Total number of validation errors",
    ["endpoint", "field"],
    registry=REGISTRY,
)

# ============================================================================
# Rate Limiting Metrics
# ============================================================================

rate_limit_hits_total = Counter(
    "rate_limit_hits_total",
    "Total number of times rate limit was hit",
    ["endpoint", "limit_type"],  # limit_type: ip, user, api_key
    registry=REGISTRY,
)

rate_limit_remaining = Gauge(
    "rate_limit_remaining",
    "Current remaining rate limit tokens",
    ["key", "endpoint"],
    registry=REGISTRY,
)

rate_limit_checks_total = Counter(
    "rate_limit_checks_total",
    "Total number of rate limit checks performed",
    ["endpoint", "result"],  # result: allowed, denied
    registry=REGISTRY,
)

# Rate limiter protection status metrics
rate_limiter_protection_status = Gauge(
    "rate_limiter_protection_status",
    "Rate limiter protection status (1=active, 0.5=degraded, 0=disabled)",
    registry=REGISTRY,
)

rate_limiter_state_transitions_total = Counter(
    "rate_limiter_state_transitions_total",
    "Total number of rate limiter state transitions",
    ["from_state", "to_state"],
    registry=REGISTRY,
)

rate_limiter_redis_errors_total = Counter(
    "rate_limiter_redis_errors_total",
    "Total Redis errors during rate limit checks",
    ["error_type"],  # error_type: timeout, connection, auth, other
    registry=REGISTRY,
)

# ============================================================================
# Circuit Breaker Metrics
# ============================================================================

circuit_breaker_state = Gauge(
    "circuit_breaker_state",
    "Circuit breaker state (0=closed, 1=half_open, 2=open)",
    ["circuit_name"],
    registry=REGISTRY,
)

circuit_breaker_failures_total = Counter(
    "circuit_breaker_failures_total",
    "Total number of circuit breaker failures",
    ["circuit_name"],
    registry=REGISTRY,
)

circuit_breaker_successes_total = Counter(
    "circuit_breaker_successes_total",
    "Total number of circuit breaker successes",
    ["circuit_name"],
    registry=REGISTRY,
)

circuit_breaker_state_changes_total = Counter(
    "circuit_breaker_state_changes_total",
    "Total number of circuit breaker state changes",
    ["circuit_name", "from_state", "to_state"],
    registry=REGISTRY,
)

circuit_breaker_rejected_total = Counter(
    "circuit_breaker_rejected_total",
    "Total number of requests rejected by circuit breaker",
    ["circuit_name"],
    registry=REGISTRY,
)

# ============================================================================
# Retry Metrics
# ============================================================================

retry_attempts_total = Counter(
    "retry_attempts_total",
    "Total number of retry attempts",
    ["operation", "attempt_number"],
    registry=REGISTRY,
)

retry_exhausted_total = Counter(
    "retry_exhausted_total",
    "Total number of operations that exhausted all retries",
    ["operation"],
    registry=REGISTRY,
)

retry_success_after_failure_total = Counter(
    "retry_success_after_failure_total",
    "Total number of operations that succeeded after retry",
    ["operation", "attempts_needed"],
    registry=REGISTRY,
)

# ============================================================================
# API Usage Metrics
# ============================================================================

api_endpoint_calls_total = Counter(
    "api_endpoint_calls_total",
    "Total number of API endpoint calls",
    ["endpoint", "method", "user_type"],  # user_type: authenticated, anonymous
    registry=REGISTRY,
)

api_response_size_bytes = Histogram(
    "api_response_size_bytes",
    "API response size in bytes",
    ["endpoint", "method"],
    buckets=(100, 500, 1000, 5000, 10000, 50000, 100000, 500000, 1000000),
    registry=REGISTRY,
)

api_request_size_bytes = Histogram(
    "api_request_size_bytes",
    "API request size in bytes",
    ["endpoint", "method"],
    buckets=(100, 500, 1000, 5000, 10000, 50000, 100000, 500000, 1000000),
    registry=REGISTRY,
)

# ============================================================================
# Authentication & Authorization Metrics
# ============================================================================

auth_attempts_total = Counter(
    "auth_attempts_total",
    "Total number of authentication attempts",
    ["method", "result"],  # method: token, api_key, oauth; result: success, failure
    registry=REGISTRY,
)

auth_token_validations_total = Counter(
    "auth_token_validations_total",
    "Total number of token validations",
    ["result"],  # result: valid, invalid, expired
    registry=REGISTRY,
)

auth_token_cache_hits_total = Counter(
    "auth_token_cache_hits_total",
    "Total number of auth token cache hits",
    ["result"],  # result: hit, miss
    registry=REGISTRY,
)

permission_checks_total = Counter(
    "permission_checks_total",
    "Total number of permission checks",
    ["permission", "result"],  # result: allowed, denied
    registry=REGISTRY,
)

# ============================================================================
# External Service Metrics
# ============================================================================

external_service_calls_total = Counter(
    "external_service_calls_total",
    "Total number of external service calls",
    ["service_name", "endpoint", "status"],
    registry=REGISTRY,
)

external_service_duration_seconds = Histogram(
    "external_service_duration_seconds",
    "External service call duration in seconds",
    ["service_name", "endpoint"],
    buckets=DEFAULT_LATENCY_BUCKETS,
    registry=REGISTRY,
)

external_service_errors_total = Counter(
    "external_service_errors_total",
    "Total number of external service errors",
    ["service_name", "error_type"],
    registry=REGISTRY,
)

external_service_timeouts_total = Counter(
    "external_service_timeouts_total",
    "Total number of external service timeouts",
    ["service_name"],
    registry=REGISTRY,
)

# ============================================================================
# Business Domain Metrics (Examples - customize for your domain)
# ============================================================================

# User activity metrics
user_sessions_active = Gauge(
    "user_sessions_active",
    "Number of active user sessions",
    registry=REGISTRY,
)

user_actions_total = Counter(
    "user_actions_total",
    "Total number of user actions",
    ["action_type", "user_type"],  # action_type: create, update, delete, view
    registry=REGISTRY,
)

user_registrations_total = Counter(
    "user_registrations_total",
    "Total number of user registrations",
    ["source"],  # source: web, mobile, api
    registry=REGISTRY,
)

# Feature usage metrics
feature_usage_total = Counter(
    "feature_usage_total",
    "Total number of times each feature was used",
    ["feature_name", "user_type"],
    registry=REGISTRY,
)

feature_errors_total = Counter(
    "feature_errors_total",
    "Total number of feature-specific errors",
    ["feature_name", "error_type"],
    registry=REGISTRY,
)

# Data processing metrics
data_records_processed_total = Counter(
    "data_records_processed_total",
    "Total number of data records processed",
    ["operation", "status"],  # operation: import, export, transform
    registry=REGISTRY,
)

data_processing_duration_seconds = Histogram(
    "data_processing_duration_seconds",
    "Data processing duration in seconds",
    ["operation"],
    buckets=(0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 300.0, 600.0),
    registry=REGISTRY,
)

data_quality_issues_total = Counter(
    "data_quality_issues_total",
    "Total number of data quality issues detected",
    ["issue_type"],
    registry=REGISTRY,
)

# ============================================================================
# Performance Metrics
# ============================================================================

slow_queries_total = Counter(
    "slow_queries_total",
    "Total number of slow database queries (>1s)",
    ["operation"],
    registry=REGISTRY,
)

slow_requests_total = Counter(
    "slow_requests_total",
    "Total number of slow HTTP requests (>5s)",
    ["endpoint", "method"],
    registry=REGISTRY,
)

memory_usage_bytes = Gauge(
    "memory_usage_bytes",
    "Current memory usage in bytes",
    ["type"],  # categories: rss, vms, shared
    registry=REGISTRY,
)

cpu_usage_percent = Gauge(
    "cpu_usage_percent",
    "Current CPU usage percentage",
    registry=REGISTRY,
)

# ============================================================================
# SLO/SLI Metrics
# ============================================================================

slo_compliance_ratio = Gauge(
    "slo_compliance_ratio",
    "SLO compliance ratio (0-1)",
    ["slo_name"],
    registry=REGISTRY,
)

availability_ratio = Gauge(
    "availability_ratio",
    "Service availability ratio (0-1) over last hour",
    registry=REGISTRY,
)

error_budget_remaining = Gauge(
    "error_budget_remaining",
    "Error budget remaining for the current period (0-1)",
    ["period"],  # period: day, week, month
    registry=REGISTRY,
)

# ============================================================================
# Dependency Health Metrics
# ============================================================================

dependency_health = Gauge(
    "dependency_health",
    "Dependency health status (1=healthy, 0=unhealthy)",
    ["dependency_name", "dependency_type"],  # dependency_type values: database, cache, queue, api
    registry=REGISTRY,
)

dependency_check_duration_seconds = Histogram(
    "dependency_check_duration_seconds",
    "Dependency health check duration in seconds",
    ["dependency_name"],
    buckets=(0.001, 0.01, 0.1, 0.5, 1.0, 5.0),
    registry=REGISTRY,
)
