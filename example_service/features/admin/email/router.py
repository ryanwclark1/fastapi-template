"""Admin endpoints for email system management.

This module provides administrative endpoints for:
- System-wide email usage statistics
- Provider health monitoring across all tenants
- Email configuration management
- Encryption key rotation (future)
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Query

from example_service.features.admin.email.dependencies import (
    EmailAdminServiceDep,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/email", tags=["admin-email"])


# =============================================================================
# System-Wide Statistics
# =============================================================================


@router.get(
    "/usage",
    summary="Get system-wide email usage",
    description="Get aggregate email usage statistics across all tenants.",
)
async def get_system_usage(
    service: EmailAdminServiceDep,
    days: Annotated[int, Query(ge=1, le=365, description="Number of days to query")] = 30,
) -> dict:
    """Get system-wide email usage statistics."""
    return await service.get_system_usage(days=days)


@router.get(
    "/health",
    summary="Check email system health",
    description="Check health of all configured email providers across the system.",
)
async def check_system_health(
    service: EmailAdminServiceDep,
) -> dict:
    """Check health of all email providers."""
    return await service.check_system_health()


# =============================================================================
# Configuration Management
# =============================================================================


@router.get(
    "/configs",
    summary="List all email configurations",
    description="Get a list of all tenant email configurations (admin view).",
)
async def list_all_configs(
    service: EmailAdminServiceDep,
    active_only: Annotated[bool, Query(description="Show only active configurations")] = False,
    provider: Annotated[str | None, Query(description="Filter by provider type")] = None,
) -> dict:
    """List all email configurations."""
    return await service.list_all_configs(active_only=active_only, provider=provider)


@router.post(
    "/configs/invalidate-cache",
    summary="Invalidate configuration cache",
    description="Clear the configuration cache for all tenants or a specific tenant.",
)
async def invalidate_cache(
    service: EmailAdminServiceDep,
    tenant_id: Annotated[str | None, Query(description="Tenant ID (None = all)")] = None,
) -> dict:
    """Invalidate configuration cache."""
    return service.invalidate_cache(tenant_id)


# =============================================================================
# Metrics & Monitoring
# =============================================================================


@router.get(
    "/metrics",
    summary="Get email metrics summary",
    description="Get current Prometheus metrics values for email system.",
)
async def get_metrics_summary() -> dict:
    """Get summary of current email metrics.

    Note: This returns snapshot values. For time-series data,
    query Prometheus directly.
    """
    return {
        "metrics_available": [
            "email_delivery_total",
            "email_delivery_duration_seconds",
            "email_recipients_total",
            "email_rate_limit_hits_total",
            "email_quota_utilization",
            "email_provider_health",
            "email_provider_errors_total",
            "email_cost_usd_total",
            "email_monthly_spend_usd",
            "email_config_cache_hits_total",
            "email_config_cache_misses_total",
        ],
        "note": "Query Prometheus directly for time-series data",
        "prometheus_query_examples": {
            "total_deliveries_24h": "sum(increase(email_delivery_total[24h]))",
            "success_rate_24h": 'sum(rate(email_delivery_total{status="success"}[24h])) / sum(rate(email_delivery_total[24h])) * 100',
            "p99_latency": "histogram_quantile(0.99, rate(email_delivery_duration_seconds_bucket[5m]))",
            "cost_last_hour": "sum(increase(email_cost_usd_total[1h]))",
        },
    }


# =============================================================================
# Provider Management
# =============================================================================


@router.get(
    "/providers/distribution",
    summary="Get provider distribution",
    description="See which providers are most commonly used across tenants.",
)
async def get_provider_distribution(
    service: EmailAdminServiceDep,
) -> dict:
    """Get distribution of providers across tenants."""
    return await service.get_provider_distribution()
