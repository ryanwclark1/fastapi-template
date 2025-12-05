"""Prometheus metrics for service availability monitoring.

These metrics provide comprehensive observability into external service
availability, health check operations, and endpoint gating based on
service dependencies.

Metrics Categories:
- Availability gauges: Current service availability status
- Health check counters: Track check frequency and results
- Health check duration: Measure check execution time
- Service unavailable responses: Track 503 responses due to service unavailability
- Override gauges: Track admin override states

Usage:
    from example_service.infra.metrics.availability import (
        service_availability_gauge,
        service_health_check_total,
        service_unavailable_responses_total,
    )

    # Update service availability
    service_availability_gauge.labels(service_name="database").set(1)

    # Track health check result
    service_health_check_total.labels(
        service_name="database",
        result="healthy"
    ).inc()

    # Track 503 response
    service_unavailable_responses_total.labels(
        service_name="database",
        endpoint="/api/v1/items"
    ).inc()
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

from example_service.infra.metrics.prometheus import REGISTRY

# ──────────────────────────────────────────────────────────────
# Service Availability Status
# ──────────────────────────────────────────────────────────────

service_availability_gauge = Gauge(
    "service_availability",
    "External service availability status. "
    "1 = available, 0 = unavailable. "
    "This is the effective availability considering admin overrides. "
    "Usage: Set after each health check or override change.",
    ["service_name"],
    registry=REGISTRY,
)

service_health_available_gauge = Gauge(
    "service_health_available",
    "Raw health check availability (ignoring admin overrides). "
    "1 = health check passed, 0 = health check failed. "
    "Compare with service_availability to identify overrides.",
    ["service_name"],
    registry=REGISTRY,
)

service_override_mode_gauge = Gauge(
    "service_override_mode",
    "Current admin override mode for service. "
    "0 = none (normal), 1 = force_enable, -1 = force_disable. "
    "Non-zero indicates manual admin intervention.",
    ["service_name"],
    registry=REGISTRY,
)

# ──────────────────────────────────────────────────────────────
# Health Check Counters
# ──────────────────────────────────────────────────────────────

service_health_check_total = Counter(
    "service_health_check_total",
    "Total health checks performed per service. "
    "Tracks all health check executions by result. "
    "Usage: Increment after each health check completes.",
    ["service_name", "result"],  # result: healthy, unhealthy, timeout
    registry=REGISTRY,
)

# ──────────────────────────────────────────────────────────────
# Health Check Duration
# ──────────────────────────────────────────────────────────────

service_health_check_duration_seconds = Histogram(
    "service_health_check_duration_seconds",
    "Health check execution duration per service in seconds. "
    "Measures time taken to complete each service's health check. "
    "High latency may indicate network issues or service degradation.",
    ["service_name"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    registry=REGISTRY,
)

# ──────────────────────────────────────────────────────────────
# Service Unavailable Responses
# ──────────────────────────────────────────────────────────────

service_unavailable_responses_total = Counter(
    "service_unavailable_responses_total",
    "Total 503 responses due to service unavailability. "
    "Tracks requests rejected because a required service was unavailable. "
    "Usage: Increment when RequireX dependency raises ServiceUnavailableException.",
    ["service_name", "endpoint"],
    registry=REGISTRY,
)

# ──────────────────────────────────────────────────────────────
# Failure/Recovery Tracking
# ──────────────────────────────────────────────────────────────

service_consecutive_failures_gauge = Gauge(
    "service_consecutive_failures",
    "Current consecutive health check failures per service. "
    "Resets to 0 on successful health check. "
    "Used for availability determination with failure_threshold.",
    ["service_name"],
    registry=REGISTRY,
)

service_consecutive_successes_gauge = Gauge(
    "service_consecutive_successes",
    "Current consecutive health check successes per service. "
    "Resets to 0 on failed health check. "
    "Used for recovery determination with recovery_threshold.",
    ["service_name"],
    registry=REGISTRY,
)

service_status_transitions_total = Counter(
    "service_status_transitions_total",
    "Total availability status transitions per service. "
    "Tracks when service availability changes (available -> unavailable or vice versa). "
    "High rate indicates service instability or flapping.",
    ["service_name", "from_status", "to_status"],
    registry=REGISTRY,
)

# ──────────────────────────────────────────────────────────────
# Health Monitor Status
# ──────────────────────────────────────────────────────────────

health_monitor_running_gauge = Gauge(
    "health_monitor_running",
    "Whether the background health monitor is running. "
    "1 = running, 0 = stopped. "
    "Should always be 1 when service availability is enabled.",
    registry=REGISTRY,
)

health_monitor_check_cycle_total = Counter(
    "health_monitor_check_cycle_total",
    "Total health check cycles completed. "
    "Each cycle checks all registered services. "
    "Used to verify health monitor is actively running.",
    registry=REGISTRY,
)

health_monitor_check_cycle_duration_seconds = Histogram(
    "health_monitor_check_cycle_duration_seconds",
    "Duration of complete health check cycle in seconds. "
    "Measures time to check all services in one cycle. "
    "Should be less than check_interval setting.",
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
    registry=REGISTRY,
)


def update_service_metrics(
    service_name: str,
    is_available: bool,
    health_available: bool,
    override_mode: str,
    consecutive_failures: int,
    consecutive_successes: int,
) -> None:
    """Convenience function to update all metrics for a service.

    Args:
        service_name: The service name (e.g., "database", "cache")
        is_available: Effective availability (considering overrides)
        health_available: Raw health check result
        override_mode: Override mode ("none", "force_enable", "force_disable")
        consecutive_failures: Current failure count
        consecutive_successes: Current success count
    """
    service_availability_gauge.labels(service_name=service_name).set(
        1 if is_available else 0
    )
    service_health_available_gauge.labels(service_name=service_name).set(
        1 if health_available else 0
    )

    # Convert override mode to numeric value
    override_value = {"none": 0, "force_enable": 1, "force_disable": -1}.get(
        override_mode, 0
    )
    service_override_mode_gauge.labels(service_name=service_name).set(override_value)

    service_consecutive_failures_gauge.labels(service_name=service_name).set(
        consecutive_failures
    )
    service_consecutive_successes_gauge.labels(service_name=service_name).set(
        consecutive_successes
    )


__all__ = [
    "health_monitor_check_cycle_duration_seconds",
    "health_monitor_check_cycle_total",
    "health_monitor_running_gauge",
    "service_availability_gauge",
    "service_consecutive_failures_gauge",
    "service_consecutive_successes_gauge",
    "service_health_available_gauge",
    "service_health_check_duration_seconds",
    "service_health_check_total",
    "service_override_mode_gauge",
    "service_status_transitions_total",
    "service_unavailable_responses_total",
    "update_service_metrics",
]
