"""Prometheus metrics for email delivery monitoring.

This module provides comprehensive metrics for tracking email delivery:
- Success/failure rates by provider and tenant
- Delivery duration histograms
- Rate limiting rejections
- Provider health status
- Cost tracking

Usage:
    from example_service.infra.email.metrics import (
        email_delivery_total,
        email_delivery_duration_seconds,
    )

    # Record delivery attempt
    email_delivery_total.labels(
        provider="smtp",
        tenant_id="tenant-123",
        status="success",
    ).inc()

    # Record delivery duration
    email_delivery_duration_seconds.labels(provider="smtp").observe(0.45)
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# =============================================================================
# Delivery Metrics
# =============================================================================

email_delivery_total = Counter(
    "email_delivery_total",
    "Total number of email delivery attempts",
    labelnames=["provider", "tenant_id", "status"],
)
"""
Counter for tracking all email delivery attempts.

Labels:
    provider: Email provider used (smtp, sendgrid, ses, etc.)
    tenant_id: Tenant identifier (or 'system' for system emails)
    status: Delivery status (success, failed, rate_limited)

Example:
    email_delivery_total.labels(
        provider="sendgrid",
        tenant_id="tenant-123",
        status="success"
    ).inc()
"""

email_delivery_duration_seconds = Histogram(
    "email_delivery_duration_seconds",
    "Email delivery duration in seconds",
    labelnames=["provider"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)
"""
Histogram tracking email delivery duration distribution.

Labels:
    provider: Email provider used

Buckets optimized for email delivery latency:
    - 0.05s-0.25s: Fast local SMTP
    - 0.5s-2.5s: Normal API providers
    - 5s-30s: Slow/retried deliveries

Example:
    email_delivery_duration_seconds.labels(provider="smtp").observe(0.45)
"""

email_recipients_total = Counter(
    "email_recipients_total",
    "Total number of email recipients (for bulk emails)",
    labelnames=["provider", "tenant_id"],
)
"""
Counter for tracking total recipient count across all emails.

Useful for billing and quota management in multi-recipient scenarios.

Labels:
    provider: Email provider used
    tenant_id: Tenant identifier

Example:
    email_recipients_total.labels(
        provider="sendgrid",
        tenant_id="tenant-123"
    ).inc(5)  # Email sent to 5 recipients
"""

# =============================================================================
# Rate Limiting Metrics
# =============================================================================

email_rate_limit_hits_total = Counter(
    "email_rate_limit_hits_total",
    "Total number of rate limit rejections",
    labelnames=["tenant_id", "limit_type"],
)
"""
Counter for rate limiting events.

Labels:
    tenant_id: Tenant hitting rate limit
    limit_type: Type of limit (per_minute, per_hour, daily_quota)

Example:
    email_rate_limit_hits_total.labels(
        tenant_id="tenant-123",
        limit_type="per_minute"
    ).inc()
"""

email_quota_utilization = Gauge(
    "email_quota_utilization",
    "Current quota utilization percentage",
    labelnames=["tenant_id", "quota_type"],
)
"""
Gauge showing current quota usage percentage.

Labels:
    tenant_id: Tenant identifier
    quota_type: Quota type (daily, monthly)

Example:
    email_quota_utilization.labels(
        tenant_id="tenant-123",
        quota_type="daily"
    ).set(75.5)  # 75.5% of daily quota used
"""

# =============================================================================
# Provider Health Metrics
# =============================================================================

email_provider_health = Gauge(
    "email_provider_health",
    "Provider health status (1=healthy, 0=unhealthy)",
    labelnames=["provider", "tenant_id"],
)
"""
Gauge indicating provider health for each tenant.

Values:
    1.0: Provider is healthy
    0.0: Provider is unhealthy

Labels:
    provider: Email provider name
    tenant_id: Tenant identifier (or 'system' for system provider)

Example:
    email_provider_health.labels(
        provider="smtp",
        tenant_id="tenant-123"
    ).set(1)  # Healthy
"""

email_provider_errors_total = Counter(
    "email_provider_errors_total",
    "Total provider errors by category",
    labelnames=["provider", "tenant_id", "error_category"],
)
"""
Counter for provider-specific errors.

Labels:
    provider: Email provider name
    tenant_id: Tenant identifier
    error_category: Error type (auth, network, quota, invalid_recipient, etc.)

Example:
    email_provider_errors_total.labels(
        provider="sendgrid",
        tenant_id="tenant-123",
        error_category="auth"
    ).inc()
"""

# =============================================================================
# Cost Tracking Metrics
# =============================================================================

email_cost_usd_total = Counter(
    "email_cost_usd_total",
    "Total email delivery cost in USD",
    labelnames=["provider", "tenant_id"],
)
"""
Counter tracking cumulative email costs.

Labels:
    provider: Email provider name
    tenant_id: Tenant identifier

Example:
    # SendGrid charges $0.0001 per email
    email_cost_usd_total.labels(
        provider="sendgrid",
        tenant_id="tenant-123"
    ).inc(0.0001)
"""

email_monthly_spend_usd = Gauge(
    "email_monthly_spend_usd",
    "Current month's email spending in USD",
    labelnames=["tenant_id"],
)
"""
Gauge showing current month-to-date spending per tenant.

Updated from EmailUsageLog aggregations.

Labels:
    tenant_id: Tenant identifier

Example:
    email_monthly_spend_usd.labels(tenant_id="tenant-123").set(45.67)
"""

# =============================================================================
# Queue Metrics
# =============================================================================

email_queue_size = Gauge(
    "email_queue_size",
    "Current number of emails in background queue",
    labelnames=["queue_name"],
)
"""
Gauge showing current email queue depth.

Labels:
    queue_name: Queue identifier (notifications, marketing, transactional)

Example:
    email_queue_size.labels(queue_name="notifications").set(127)
"""

email_queue_processing_duration_seconds = Histogram(
    "email_queue_processing_duration_seconds",
    "Time taken to process queued emails",
    labelnames=["queue_name"],
    buckets=[0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0],
)
"""
Histogram tracking queue processing time.

Labels:
    queue_name: Queue identifier

Example:
    email_queue_processing_duration_seconds.labels(
        queue_name="notifications"
    ).observe(2.3)
"""

# =============================================================================
# Configuration Metrics
# =============================================================================

email_config_cache_hits_total = Counter(
    "email_config_cache_hits_total",
    "Total configuration cache hits",
)
"""
Counter for config cache hits (TTL cache performance).

Example:
    email_config_cache_hits_total.inc()
"""

email_config_cache_misses_total = Counter(
    "email_config_cache_misses_total",
    "Total configuration cache misses",
)
"""
Counter for config cache misses (requires DB query).

Example:
    email_config_cache_misses_total.inc()
"""

email_active_tenants = Gauge(
    "email_active_tenants",
    "Number of tenants with custom email configs",
)
"""
Gauge showing total tenants with custom email configurations.

Updated periodically from database counts.

Example:
    email_active_tenants.set(42)
"""
