"""Prometheus metrics for Consul service discovery.

These metrics provide observability into service discovery operations,
helping monitor registration health, TTL heartbeat reliability, and
operational errors.
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

from example_service.infra.metrics.prometheus import DEFAULT_LATENCY_BUCKETS, REGISTRY

# ──────────────────────────────────────────────────────────────
# Registration metrics
# ──────────────────────────────────────────────────────────────

service_discovery_registrations_total = Counter(
    "service_discovery_registrations_total",
    "Total service registration attempts with Consul. "
    "Tracks successful and failed registration operations. "
    "Usage: Increment after each registration attempt.",
    ["status"],  # success, failure
    registry=REGISTRY,
)

service_discovery_deregistrations_total = Counter(
    "service_discovery_deregistrations_total",
    "Total service deregistration attempts with Consul. "
    "Tracks successful and failed deregistration operations. "
    "Usage: Increment after each deregistration attempt.",
    ["status"],  # success, failure
    registry=REGISTRY,
)

# ──────────────────────────────────────────────────────────────
# TTL heartbeat metrics
# ──────────────────────────────────────────────────────────────

service_discovery_ttl_passes_total = Counter(
    "service_discovery_ttl_passes_total",
    "Total TTL health check heartbeats sent to Consul. "
    "Tracks successful and failed TTL pass/fail/warn operations. "
    "Usage: Increment after each TTL update attempt.",
    ["status", "check_status"],  # status: success/failure, check_status: pass/fail/warn
    registry=REGISTRY,
)

# ──────────────────────────────────────────────────────────────
# Error metrics
# ──────────────────────────────────────────────────────────────

service_discovery_errors_total = Counter(
    "service_discovery_errors_total",
    "Total errors during service discovery operations. "
    "Categorized by operation and error type for debugging. "
    "Usage: Increment when any Consul operation fails with an exception.",
    [
        "operation",
        "error_type",
    ],  # operation: register/deregister/ttl_pass, error_type: timeout/connection/http_error
    registry=REGISTRY,
)

# ──────────────────────────────────────────────────────────────
# Latency metrics
# ──────────────────────────────────────────────────────────────

service_discovery_operation_duration_seconds = Histogram(
    "service_discovery_operation_duration_seconds",
    "Duration of Consul API operations in seconds. "
    "Helps identify performance issues with Consul connectivity. "
    "Usage: Observe duration of each Consul API call.",
    ["operation"],  # register, deregister, ttl_pass, ttl_fail, ttl_warn
    buckets=DEFAULT_LATENCY_BUCKETS,
    registry=REGISTRY,
)

# ──────────────────────────────────────────────────────────────
# State metrics
# ──────────────────────────────────────────────────────────────

# Note: We intentionally don't use a Gauge for "is_registered" because:
# 1. It can lead to stale state if the process crashes
# 2. The registration status is better determined from heartbeat success rate
# 3. Counters are more reliable for aggregation across instances
