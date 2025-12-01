"""Prometheus metrics for health check monitoring.

These metrics provide comprehensive observability into health check operations,
tracking check frequency, duration, status transitions, and provider-level
health trends. Essential for monitoring system reliability and dependency health.

Metrics Categories:
- Check counters: Track total checks by provider and status
- Duration histograms: Measure check execution time
- Status gauges: Current health status per provider
- Transition counters: Status change tracking for alerting
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

from example_service.infra.metrics.prometheus import REGISTRY

# ──────────────────────────────────────────────────────────────
# Health Check Counters
# ──────────────────────────────────────────────────────────────

health_check_total = Counter(
    "health_check_total",
    "Total number of health checks performed. "
    "Tracks all health check executions by provider and result status. "
    "Usage: Increment after each health check completes.",
    ["provider", "status"],  # status: healthy, degraded, unhealthy
    registry=REGISTRY,
)

# ──────────────────────────────────────────────────────────────
# Health Check Duration
# ──────────────────────────────────────────────────────────────

health_check_duration_seconds = Histogram(
    "health_check_duration_seconds",
    "Health check execution duration in seconds. "
    "Measures time taken to complete each provider's health check. "
    "Usage: Observe duration at the start and end of check_health().",
    ["provider"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    registry=REGISTRY,
)

# ──────────────────────────────────────────────────────────────
# Current Health Status
# ──────────────────────────────────────────────────────────────

health_check_status_gauge = Gauge(
    "health_check_status",
    "Current health status of provider. "
    "1.0 = healthy, 0.5 = degraded, 0.0 = unhealthy. "
    "Usage: Set after each health check based on result.",
    ["provider"],
    registry=REGISTRY,
)

# ──────────────────────────────────────────────────────────────
# Status Transitions
# ──────────────────────────────────────────────────────────────

health_check_status_transitions_total = Counter(
    "health_check_status_transitions_total",
    "Total health status transitions. "
    "Tracks when provider status changes (e.g., healthy -> degraded). "
    "Usage: Increment when status differs from previous check. "
    "Alert: Rate(transitions) > threshold indicates instability.",
    ["provider", "from_status", "to_status"],
    registry=REGISTRY,
)

# ──────────────────────────────────────────────────────────────
# Check Errors
# ──────────────────────────────────────────────────────────────

health_check_errors_total = Counter(
    "health_check_errors_total",
    "Total health check errors (exceptions during check execution). "
    "Distinguishes between provider failures vs check execution errors. "
    "Usage: Increment when check_health() raises unexpected exception.",
    ["provider", "error_type"],
    registry=REGISTRY,
)
