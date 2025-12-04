"""Prometheus metrics for DLQ monitoring.

This module provides Prometheus metrics for observing DLQ behavior:
- Retry attempts by queue and policy
- Retry delay distribution
- DLQ routing counts by reason
- Poison message detection
- Message age at DLQ routing

All metrics use the shared REGISTRY from infra/metrics/prometheus.py
for consistent metric collection.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

from example_service.infra.metrics.prometheus import REGISTRY

# ============================================================================
# Retry Metrics
# ============================================================================

dlq_retry_attempts_total = Counter(
    "messaging_dlq_retry_attempts_total",
    "Total number of message retry attempts. "
    "Tracks retry activity by queue, policy, and attempt number. "
    "Usage: Increment when scheduling a retry (before delay).",
    ["queue", "policy", "attempt_number"],
    registry=REGISTRY,
)

dlq_retry_delay_seconds = Histogram(
    "messaging_dlq_retry_delay_seconds",
    "Distribution of retry delays in seconds. "
    "Shows how long messages wait before retry. "
    "Usage: Observe the calculated delay before sleeping.",
    ["queue", "policy"],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
    registry=REGISTRY,
)

# ============================================================================
# DLQ Routing Metrics
# ============================================================================

dlq_routed_total = Counter(
    "messaging_dlq_routed_total",
    "Total number of messages routed to Dead Letter Queue. "
    "Tracks final failures that exhaust retry attempts or hit permanent errors. "
    "Labeled by queue and reason for routing.",
    ["queue", "reason"],
    registry=REGISTRY,
)

dlq_reason_breakdown_total = Counter(
    "messaging_dlq_reason_breakdown_total",
    "Detailed breakdown of DLQ routing reasons. "
    "Reasons: max_retries_exceeded, max_duration_exceeded, "
    "non_retryable, poison_message, message_expired. "
    "Usage: Increment when routing to DLQ with specific reason.",
    ["reason"],
    registry=REGISTRY,
)

# ============================================================================
# Poison Message Metrics
# ============================================================================

dlq_poison_detected_total = Counter(
    "messaging_dlq_poison_detected_total",
    "Total number of poison messages detected. "
    "Indicates messages that repeatedly fail with same error. "
    "Usage: Increment when poison detector returns True.",
    ["queue"],
    registry=REGISTRY,
)

dlq_poison_cache_size = Gauge(
    "messaging_dlq_poison_cache_size",
    "Current size of the poison message detection cache. "
    "Monitors memory usage of poison detector. "
    "Usage: Update periodically from detector.get_stats().",
    registry=REGISTRY,
)

# ============================================================================
# Message Age Metrics
# ============================================================================

dlq_message_age_at_routing_seconds = Histogram(
    "messaging_dlq_message_age_at_routing_seconds",
    "Age of messages when routed to DLQ. "
    "Shows how long messages were retried before giving up. "
    "Usage: Observe message age when routing to DLQ.",
    ["queue"],
    buckets=(1.0, 5.0, 10.0, 30.0, 60.0, 300.0, 600.0, 1800.0, 3600.0, 86400.0),
    registry=REGISTRY,
)

dlq_message_ttl_exceeded_total = Counter(
    "messaging_dlq_ttl_exceeded_total",
    "Total messages routed to DLQ due to TTL expiration. "
    "Indicates messages that exceeded their maximum lifetime. "
    "Usage: Increment when routing expired messages.",
    ["queue"],
    registry=REGISTRY,
)

# ============================================================================
# Exception Metrics
# ============================================================================

dlq_exception_types_total = Counter(
    "messaging_dlq_exception_types_total",
    "Exception types encountered during message processing. "
    "Tracks which exceptions cause failures. "
    "Usage: Increment with exception class name on each failure.",
    ["queue", "exception_type", "retryable"],
    registry=REGISTRY,
)

# ============================================================================
# Middleware Performance Metrics
# ============================================================================

dlq_middleware_duration_seconds = Histogram(
    "messaging_dlq_middleware_duration_seconds",
    "Time spent in DLQ middleware processing. "
    "Includes retry delay calculation and republishing. "
    "Usage: Time the full middleware execution.",
    ["queue", "outcome"],  # outcome: success, retry, dlq
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    registry=REGISTRY,
)

dlq_republish_failures_total = Counter(
    "messaging_dlq_republish_failures_total",
    "Total number of failed message republish attempts. "
    "Indicates broker connectivity issues during retry. "
    "Usage: Increment when republish raises exception.",
    ["queue"],
    registry=REGISTRY,
)


# ============================================================================
# Helper Functions
# ============================================================================


def record_retry_attempt(
    queue: str,
    policy: str,
    attempt_number: int,
    delay_seconds: float,
) -> None:
    """Record a retry attempt with its delay.

    Convenience function to update multiple metrics at once.

    Args:
        queue: Queue name.
        policy: Retry policy name (exponential, fibonacci, etc.).
        attempt_number: Current attempt number (1-based).
        delay_seconds: Calculated delay in seconds.
    """
    dlq_retry_attempts_total.labels(
        queue=queue,
        policy=policy,
        attempt_number=str(attempt_number),
    ).inc()

    dlq_retry_delay_seconds.labels(
        queue=queue,
        policy=policy,
    ).observe(delay_seconds)


def record_dlq_routing(
    queue: str,
    reason: str,
    message_age_seconds: float | None = None,
) -> None:
    """Record a message being routed to DLQ.

    Convenience function to update multiple metrics at once.

    Args:
        queue: Queue name.
        reason: Reason for DLQ routing.
        message_age_seconds: Optional age of message in seconds.
    """
    dlq_routed_total.labels(queue=queue, reason=reason).inc()
    dlq_reason_breakdown_total.labels(reason=reason).inc()

    if message_age_seconds is not None:
        dlq_message_age_at_routing_seconds.labels(queue=queue).observe(
            message_age_seconds
        )


def record_exception(
    queue: str,
    exception: Exception,
    retryable: bool,
) -> None:
    """Record an exception during message processing.

    Args:
        queue: Queue name.
        exception: The exception that was raised.
        retryable: Whether the exception is retryable.
    """
    dlq_exception_types_total.labels(
        queue=queue,
        exception_type=type(exception).__name__,
        retryable=str(retryable).lower(),
    ).inc()


__all__ = [
    # Exception metrics
    "dlq_exception_types_total",
    # Age metrics
    "dlq_message_age_at_routing_seconds",
    "dlq_message_ttl_exceeded_total",
    # Performance metrics
    "dlq_middleware_duration_seconds",
    # Poison metrics
    "dlq_poison_cache_size",
    "dlq_poison_detected_total",
    # DLQ routing metrics
    "dlq_reason_breakdown_total",
    "dlq_republish_failures_total",
    # Retry metrics
    "dlq_retry_attempts_total",
    "dlq_retry_delay_seconds",
    "dlq_routed_total",
    # Helper functions
    "record_dlq_routing",
    "record_exception",
    "record_retry_attempt",
]
