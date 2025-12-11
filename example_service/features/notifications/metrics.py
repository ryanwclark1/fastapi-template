"""Prometheus metrics for notification system monitoring.

This module provides comprehensive metrics for tracking notifications:
- Creation and dispatch counters
- Delivery success/failure by channel
- Delivery duration histograms
- Retry attempts tracking
- Unread notification gauge

Usage:
    from example_service.features.notifications.metrics import (
        notification_created_total,
        notification_delivered_total,
    )

    # Record notification creation
    notification_created_total.labels(
        notification_type="reminder_due",
        priority="high",
    ).inc()

    # Record delivery
    notification_delivered_total.labels(
        channel="email",
        status="delivered",
    ).inc()
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# =============================================================================
# Notification Lifecycle Metrics
# =============================================================================

notification_created_total = Counter(
    "notification_created_total",
    "Total number of notifications created",
    labelnames=["notification_type", "priority"],
)
"""
Counter for tracking notification creation.

Labels:
    notification_type: Type of notification (reminder_due, task_assigned, etc.)
    priority: Priority level (low, normal, high, urgent)

Example:
    notification_created_total.labels(
        notification_type="reminder_due",
        priority="high"
    ).inc()
"""

notification_dispatched_total = Counter(
    "notification_dispatched_total",
    "Total number of notifications dispatched to channels",
    labelnames=["notification_type"],
)
"""
Counter for tracking notification dispatch.

Labels:
    notification_type: Type of notification

Example:
    notification_dispatched_total.labels(
        notification_type="reminder_due"
    ).inc()
"""

notification_delivered_total = Counter(
    "notification_delivered_total",
    "Total number of notification deliveries by channel and status",
    labelnames=["channel", "status"],
)
"""
Counter for tracking delivery attempts and results.

Labels:
    channel: Delivery channel (email, websocket, webhook, in_app)
    status: Delivery status (delivered, failed, pending)

Example:
    notification_delivered_total.labels(
        channel="email",
        status="delivered"
    ).inc()
"""

# =============================================================================
# Delivery Performance Metrics
# =============================================================================

notification_delivery_duration_seconds = Histogram(
    "notification_delivery_duration_seconds",
    "Notification delivery duration in seconds",
    labelnames=["channel"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)
"""
Histogram tracking notification delivery duration distribution.

Labels:
    channel: Delivery channel

Buckets optimized for notification delivery latency:
    - 0.05s-0.25s: Fast in-app/websocket
    - 0.5s-2.5s: Normal email/webhook API calls
    - 5s-30s: Slow/retried deliveries

Example:
    notification_delivery_duration_seconds.labels(
        channel="email"
    ).observe(1.5)
"""

# =============================================================================
# Retry Metrics
# =============================================================================

notification_retry_total = Counter(
    "notification_retry_total",
    "Total number of notification delivery retries",
    labelnames=["channel"],
)
"""
Counter for tracking notification retry attempts.

Labels:
    channel: Delivery channel being retried

Example:
    notification_retry_total.labels(
        channel="email"
    ).inc()
"""

notification_retry_exhausted_total = Counter(
    "notification_retry_exhausted_total",
    "Total number of notifications that exhausted all retry attempts",
    labelnames=["channel"],
)
"""
Counter for tracking notifications that failed after all retries.

Labels:
    channel: Delivery channel that exhausted retries

Example:
    notification_retry_exhausted_total.labels(
        channel="webhook"
    ).inc()
"""

# =============================================================================
# User Engagement Metrics
# =============================================================================

notification_unread_gauge = Gauge(
    "notification_unread_gauge",
    "Current number of unread notifications per user",
    labelnames=["user_id"],
)
"""
Gauge showing current unread notification count per user.

Updated periodically or after read/unread operations.

Labels:
    user_id: User identifier

Example:
    notification_unread_gauge.labels(
        user_id="user-123"
    ).set(42)
"""

notification_read_total = Counter(
    "notification_read_total",
    "Total number of notifications marked as read",
    labelnames=["notification_type"],
)
"""
Counter for tracking when notifications are read.

Labels:
    notification_type: Type of notification

Example:
    notification_read_total.labels(
        notification_type="reminder_due"
    ).inc()
"""

notification_dismissed_total = Counter(
    "notification_dismissed_total",
    "Total number of notifications dismissed by users",
    labelnames=["notification_type", "auto_dismiss"],
)
"""
Counter for tracking notification dismissals.

Labels:
    notification_type: Type of notification
    auto_dismiss: Whether it was auto-dismissed (true/false)

Example:
    notification_dismissed_total.labels(
        notification_type="reminder_due",
        auto_dismiss="false"
    ).inc()
"""

# =============================================================================
# Channel-Specific Metrics
# =============================================================================

notification_channel_enabled_total = Counter(
    "notification_channel_enabled_total",
    "Total number of times a channel was enabled in user preferences",
    labelnames=["channel"],
)
"""
Counter for tracking channel preference changes.

Labels:
    channel: Channel name

Example:
    notification_channel_enabled_total.labels(
        channel="email"
    ).inc()
"""

notification_quiet_hours_delayed_total = Counter(
    "notification_quiet_hours_delayed_total",
    "Total number of notifications delayed due to quiet hours",
    labelnames=["notification_type"],
)
"""
Counter for notifications delayed by quiet hours.

Labels:
    notification_type: Type of notification

Example:
    notification_quiet_hours_delayed_total.labels(
        notification_type="reminder_due"
    ).inc()
"""

# =============================================================================
# Error Tracking Metrics
# =============================================================================

notification_errors_total = Counter(
    "notification_errors_total",
    "Total notification errors by channel and error category",
    labelnames=["channel", "error_category"],
)
"""
Counter for notification delivery errors.

Labels:
    channel: Delivery channel
    error_category: Error type (network, auth, validation, exception, etc.)

Example:
    notification_errors_total.labels(
        channel="webhook",
        error_category="network"
    ).inc()
"""

# =============================================================================
# Template Metrics
# =============================================================================

notification_template_rendered_total = Counter(
    "notification_template_rendered_total",
    "Total number of notification templates rendered",
    labelnames=["template_name", "channel"],
)
"""
Counter for tracking template rendering.

Labels:
    template_name: Name of the template
    channel: Channel being rendered for

Example:
    notification_template_rendered_total.labels(
        template_name="reminder_due",
        channel="email"
    ).inc()
"""

notification_template_errors_total = Counter(
    "notification_template_errors_total",
    "Total number of template rendering errors",
    labelnames=["template_name"],
)
"""
Counter for template rendering errors.

Labels:
    template_name: Name of the template that failed

Example:
    notification_template_errors_total.labels(
        template_name="reminder_due"
    ).inc()
"""

# =============================================================================
# System Health Metrics
# =============================================================================

notification_queue_size = Gauge(
    "notification_queue_size",
    "Current number of notifications pending dispatch",
    labelnames=["status"],
)
"""
Gauge showing pending notification queue depth.

Labels:
    status: Queue status (scheduled, pending_retry)

Example:
    notification_queue_size.labels(
        status="scheduled"
    ).set(127)
"""

notification_active_subscriptions = Gauge(
    "notification_active_subscriptions",
    "Number of active WebSocket subscriptions for real-time notifications",
)
"""
Gauge showing active WebSocket connections for notifications.

Example:
    notification_active_subscriptions.set(45)
"""
