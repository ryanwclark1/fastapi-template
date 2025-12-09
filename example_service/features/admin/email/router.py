"""Admin endpoints for email system management.

This module provides administrative endpoints for:
- System-wide email usage statistics
- Provider health monitoring across all tenants
- Email configuration management
- Encryption key rotation (future)
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import logging
import time
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Query

from example_service.core.dependencies.database import get_async_session
from example_service.core.models.email_config import EmailConfig, EmailUsageLog
from example_service.features.admin.email.schemas import (
    CacheInvalidationResponse,
    ConfigListResponse,
    EmailConfigSummary,
    HealthCheckResult,
    MetricsSummaryResponse,
    ProviderDistributionItem,
    ProviderDistributionResponse,
    SystemHealthResponse,
    SystemUsageResponse,
)
from example_service.infra.email import get_enhanced_email_service

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from example_service.infra.email.enhanced_service import EnhancedEmailService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/email", tags=["admin-email"])


# =============================================================================
# System-Wide Statistics
# =============================================================================


@router.get(
    "/usage",
    summary="Get system-wide email usage",
    description="Get aggregate email usage statistics across all tenants.",
    response_model=SystemUsageResponse,
)
async def get_system_usage(
    session: Annotated[AsyncSession, Depends(get_async_session)],
    days: Annotated[
        int, Query(default=30, ge=1, le=365, description="Number of days to query")
    ],
) -> SystemUsageResponse:
    """Get system-wide email usage statistics."""
    start_date = datetime.now(UTC) - timedelta(days=days)

    # Count active configs
    config_count_stmt = (
        select(func.count()).select_from(EmailConfig).where(EmailConfig.is_active)
    )
    config_count_result = await session.execute(config_count_stmt)
    active_configs = config_count_result.scalar_one()

    # Query usage logs
    usage_stmt = select(EmailUsageLog).where(EmailUsageLog.created_at >= start_date)
    usage_result = await session.execute(usage_stmt)
    logs = usage_result.scalars().all()

    # Calculate statistics
    total_emails = len(logs)
    total_cost = sum(log.cost_usd for log in logs if log.cost_usd)

    # Group by provider
    emails_by_provider: dict[str, int] = {}
    cost_by_provider: dict[str, float] = {}

    for log in logs:
        provider = log.provider
        emails_by_provider[provider] = emails_by_provider.get(provider, 0) + 1

        if log.cost_usd:
            cost_by_provider[provider] = (
                cost_by_provider.get(provider, 0.0) + log.cost_usd
            )

    # Get top tenants by usage
    tenant_usage_stmt = (
        select(
            EmailUsageLog.tenant_id,
            func.count(EmailUsageLog.id).label("email_count"),
            func.sum(EmailUsageLog.cost_usd).label("total_cost"),
        )
        .where(
            EmailUsageLog.created_at >= start_date, EmailUsageLog.tenant_id.isnot(None)
        )
        .group_by(EmailUsageLog.tenant_id)
        .order_by(func.count(EmailUsageLog.id).desc())
        .limit(10)
    )
    tenant_usage_result = await session.execute(tenant_usage_stmt)
    top_tenants_raw = tenant_usage_result.all()

    top_tenants = [
        {
            "tenant_id": row.tenant_id,
            "email_count": row.email_count,
            "total_cost_usd": round(float(row.total_cost or 0), 4),
        }
        for row in top_tenants_raw
    ]

    # Get unique tenant count
    tenant_count_stmt = (
        select(func.count(func.distinct(EmailUsageLog.tenant_id)))
        .select_from(EmailUsageLog)
        .where(
            EmailUsageLog.created_at >= start_date, EmailUsageLog.tenant_id.isnot(None)
        )
    )
    tenant_count_result = await session.execute(tenant_count_stmt)
    total_tenants = tenant_count_result.scalar_one()

    return SystemUsageResponse(
        period_days=days,
        period_start=start_date.isoformat(),
        period_end=datetime.now(UTC).isoformat(),
        total_tenants_active=total_tenants,
        total_tenants_configured=active_configs,
        total_emails_sent=total_emails,
        total_cost_usd=round(total_cost, 4),
        emails_by_provider=emails_by_provider,
        cost_by_provider={k: round(v, 4) for k, v in cost_by_provider.items()},
        top_tenants=top_tenants,
        average_cost_per_email=round(total_cost / total_emails, 6)
        if total_emails > 0
        else 0,
    )


@router.get(
    "/health",
    summary="Check email system health",
    description="Check health of all configured email providers across the system.",
    response_model=SystemHealthResponse,
)
async def check_system_health(
    session: Annotated[AsyncSession, Depends(get_async_session)],
    email_service: Annotated[EnhancedEmailService, Depends(get_enhanced_email_service)],
) -> SystemHealthResponse:
    """Check health of all email providers."""
    # Get all active configs
    stmt = select(EmailConfig).where(EmailConfig.is_active == True)  # noqa: E712
    result = await session.execute(stmt)
    configs = result.scalars().all()

    # Also check system default
    health_checks = []

    # Check system default
    try:
        start = time.perf_counter()
        system_healthy = await email_service.health_check(None)
        duration_ms = int((time.perf_counter() - start) * 1000)

        health_checks.append(
            HealthCheckResult(
                tenant_id=None,
                provider="system_default",
                healthy=system_healthy,
                response_time_ms=duration_ms,
                error=None,
            )
        )
    except Exception as e:
        health_checks.append(
            HealthCheckResult(
                tenant_id=None,
                provider="system_default",
                healthy=False,
                response_time_ms=None,
                error=str(e),
            )
        )

    # Check tenant configs (sample up to 10 for performance)
    sample_configs = configs[:10] if len(configs) > 10 else configs

    async def check_tenant(config: EmailConfig) -> HealthCheckResult:
        try:
            start = time.perf_counter()
            is_healthy = await email_service.health_check(config.tenant_id)
            duration_ms = int((time.perf_counter() - start) * 1000)
        except Exception as e:
            return HealthCheckResult(
                tenant_id=config.tenant_id,
                provider=str(config.provider_type),
                healthy=False,
                response_time_ms=None,
                error=str(e),
            )
        else:
            return HealthCheckResult(
                tenant_id=config.tenant_id,
                provider=str(config.provider_type),
                healthy=is_healthy,
                response_time_ms=duration_ms,
                error=None,
            )

    # Run health checks concurrently
    tenant_checks = await asyncio.gather(*[
        check_tenant(config) for config in sample_configs
    ])
    health_checks.extend(tenant_checks)

    # Calculate overall health
    healthy_count = sum(1 for check in health_checks if check.healthy)
    total_checks = len(health_checks)
    overall_healthy = healthy_count == total_checks

    return SystemHealthResponse(
        overall_healthy=overall_healthy,
        healthy_count=healthy_count,
        total_checks=total_checks,
        health_percentage=round((healthy_count / total_checks * 100), 2)
        if total_checks > 0
        else 0,
        checks=health_checks,
        sampled=len(configs) > 10,
        total_configs=len(configs),
        timestamp=datetime.now(UTC).isoformat(),
    )


# =============================================================================
# Configuration Management
# =============================================================================


@router.get(
    "/configs",
    summary="List all email configurations",
    description="Get a list of all tenant email configurations (admin view).",
    response_model=ConfigListResponse,
)
async def list_all_configs(
    session: Annotated[AsyncSession, Depends(get_async_session)],
    active_only: Annotated[
        bool, Query(default=False, description="Show only active configurations")
    ],
    provider: Annotated[
        str | None, Query(default=None, description="Filter by provider type")
    ],
) -> ConfigListResponse:
    """List all email configurations."""
    stmt = select(EmailConfig)

    if active_only:
        stmt = stmt.where(EmailConfig.is_active == True)  # noqa: E712

    if provider:
        stmt = stmt.where(EmailConfig.provider_type == provider)

    stmt = stmt.order_by(EmailConfig.created_at.desc())

    result = await session.execute(stmt)
    configs = result.scalars().all()

    return ConfigListResponse(
        total=len(configs),
        configs=[
            EmailConfigSummary(
                id=str(config.id),
                tenant_id=config.tenant_id,
                provider_type=str(config.provider_type),
                is_active=config.is_active,
                from_email=config.from_email,
                rate_limit_per_minute=config.rate_limit_per_minute,
                created_at=config.created_at.isoformat(),
                updated_at=config.updated_at.isoformat(),
            )
            for config in configs
        ],
    )


@router.post(
    "/configs/invalidate-cache",
    summary="Invalidate configuration cache",
    description="Clear the configuration cache for all tenants or a specific tenant.",
    response_model=CacheInvalidationResponse,
)
async def invalidate_cache(
    email_service: Annotated[EnhancedEmailService, Depends(get_enhanced_email_service)],
    tenant_id: Annotated[
        str | None, Query(default=None, description="Tenant ID (None = all)")
    ],
) -> CacheInvalidationResponse:
    """Invalidate configuration cache."""
    count = email_service.invalidate_config_cache(tenant_id)

    return CacheInvalidationResponse(
        success=True,
        invalidated_count=count,
        tenant_id=tenant_id,
        timestamp=datetime.now(UTC).isoformat(),
    )


# =============================================================================
# Metrics & Monitoring
# =============================================================================


@router.get(
    "/metrics",
    summary="Get email metrics summary",
    description="Get current Prometheus metrics values for email system.",
    response_model=MetricsSummaryResponse,
)
async def get_metrics_summary() -> MetricsSummaryResponse:
    """Get summary of current email metrics.

    Note: This returns snapshot values. For time-series data,
    query Prometheus directly.
    """
    # Note: Prometheus client doesn't provide easy access to current values
    # In production, you'd query Prometheus API directly
    # This is a simplified version showing available metrics

    return MetricsSummaryResponse(
        metrics_available=[
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
        note="Query Prometheus directly for time-series data",
        prometheus_query_examples={
            "total_deliveries_24h": "sum(increase(email_delivery_total[24h]))",
            "success_rate_24h": 'sum(rate(email_delivery_total{status="success"}[24h])) / sum(rate(email_delivery_total[24h])) * 100',
            "p99_latency": "histogram_quantile(0.99, rate(email_delivery_duration_seconds_bucket[5m]))",
            "cost_last_hour": "sum(increase(email_cost_usd_total[1h]))",
        },
    )


# =============================================================================
# Provider Management
# =============================================================================


@router.get(
    "/providers/distribution",
    summary="Get provider distribution",
    description="See which providers are most commonly used across tenants.",
    response_model=ProviderDistributionResponse,
)
async def get_provider_distribution(
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> ProviderDistributionResponse:
    """Get distribution of providers across tenants."""
    stmt = (
        select(
            EmailConfig.provider_type,
            func.count(EmailConfig.id).label("count"),
        )
        .where(EmailConfig.is_active == True)  # noqa: E712
        .group_by(EmailConfig.provider_type)
        .order_by(func.count(EmailConfig.id).desc())
    )

    result = await session.execute(stmt)
    distribution_raw = result.all()

    distribution = [
        ProviderDistributionItem(
            provider=row.provider_type.value, tenant_count=row.count
        )
        for row in distribution_raw
    ]

    total_configs = sum(item.tenant_count for item in distribution)

    return ProviderDistributionResponse(
        total_configured_tenants=total_configs,
        distribution=distribution,
        percentages={
            item.provider: round(item.tenant_count / total_configs * 100, 2)
            for item in distribution
        }
        if total_configs > 0
        else {},
    )
