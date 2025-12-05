"""Schemas for email administration endpoints.

This module provides response schemas for:
- System-wide email usage statistics
- Provider health monitoring
- Configuration management
- Metrics summaries
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SystemEmailStats(BaseModel):
    """System-wide email statistics."""

    total_tenants: int = Field(description="Number of tenants with email activity")
    active_configs: int = Field(description="Number of active email configurations")
    total_emails_sent: int = Field(description="Total emails sent in period")
    total_cost_usd: float = Field(description="Total cost across all tenants")
    emails_by_provider: dict[str, int] = Field(description="Email count by provider")
    cost_by_provider: dict[str, float] = Field(description="Cost breakdown by provider")
    top_tenants: list[dict[str, Any]] = Field(description="Top tenants by usage")


class SystemUsageResponse(BaseModel):
    """Response schema for system-wide usage statistics."""

    period_days: int
    period_start: str
    period_end: str
    total_tenants_active: int
    total_tenants_configured: int
    total_emails_sent: int
    total_cost_usd: float
    emails_by_provider: dict[str, int]
    cost_by_provider: dict[str, float]
    top_tenants: list[dict[str, Any]]
    average_cost_per_email: float


class HealthCheckResult(BaseModel):
    """Individual health check result."""

    tenant_id: str | None
    provider: str
    healthy: bool
    response_time_ms: int | None
    error: str | None


class SystemHealthResponse(BaseModel):
    """Response schema for system health check."""

    overall_healthy: bool
    healthy_count: int
    total_checks: int
    health_percentage: float
    checks: list[HealthCheckResult]
    sampled: bool
    total_configs: int
    timestamp: str


class EmailConfigSummary(BaseModel):
    """Summary of an email configuration for admin view."""

    id: str
    tenant_id: str
    provider_type: str
    is_active: bool
    from_email: str | None
    rate_limit_per_minute: int | None
    created_at: str
    updated_at: str


class ConfigListResponse(BaseModel):
    """Response schema for listing all configurations."""

    total: int
    configs: list[EmailConfigSummary]


class CacheInvalidationResponse(BaseModel):
    """Response schema for cache invalidation."""

    success: bool
    invalidated_count: int
    tenant_id: str | None
    timestamp: str


class MetricsSummaryResponse(BaseModel):
    """Response schema for metrics summary."""

    metrics_available: list[str]
    note: str
    prometheus_query_examples: dict[str, str]


class ProviderDistributionItem(BaseModel):
    """Distribution item for a single provider."""

    provider: str
    tenant_count: int


class ProviderDistributionResponse(BaseModel):
    """Response schema for provider distribution."""

    total_configured_tenants: int
    distribution: list[ProviderDistributionItem]
    percentages: dict[str, float]
