"""Admin service for email system management.

Provides system-wide email operations:
- Aggregate usage statistics across all tenants
- Provider health monitoring
- Configuration management
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
from typing import TYPE_CHECKING

from example_service.core.services.base import BaseService
from example_service.features.email.repository import (
    EmailConfigRepository,
    EmailUsageLogRepository,
    get_email_config_repository,
    get_email_usage_log_repository,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from example_service.features.email.models import EmailConfig
    from example_service.infra.email.enhanced_service import EnhancedEmailService


logger = logging.getLogger(__name__)


class EmailAdminService(BaseService):
    """Admin service for system-wide email management.

    Provides:
    - Aggregate usage statistics
    - Health monitoring across tenants
    - Configuration listing and management
    """

    def __init__(
        self,
        session: AsyncSession,
        email_service: EnhancedEmailService,
        *,
        config_repository: EmailConfigRepository | None = None,
        usage_repository: EmailUsageLogRepository | None = None,
    ) -> None:
        """Initialize admin service with dependencies.

        Args:
            session: Database session
            email_service: Infrastructure email service
            config_repository: Optional config repository
            usage_repository: Optional usage log repository
        """
        super().__init__()
        self._session = session
        self._email_service = email_service
        self._config_repo = config_repository or get_email_config_repository()
        self._usage_repo = usage_repository or get_email_usage_log_repository()

    async def get_system_usage(
        self,
        *,
        days: int = 30,
    ) -> dict:
        """Get system-wide email usage statistics.

        Args:
            days: Number of days to query (default: 30)

        Returns:
            Dictionary with aggregate usage statistics
        """
        start_date = datetime.now(UTC) - timedelta(days=days)

        # Get all active configs
        active_configs = await self._config_repo.list_active_configs(
            self._session, limit=10000,
        )

        # Get all usage logs for the period
        # Note: For large-scale, this should be aggregated in the repository
        usage_logs = await self._usage_repo.get_all_usage_logs(
            self._session,
            start_date=start_date,
        )

        # Calculate statistics
        total_emails = len(usage_logs)
        total_cost = sum(log.cost_usd for log in usage_logs if log.cost_usd)

        # Group by provider
        emails_by_provider: dict[str, int] = {}
        cost_by_provider: dict[str, float] = {}

        for log in usage_logs:
            provider = log.provider
            emails_by_provider[provider] = emails_by_provider.get(provider, 0) + 1
            if log.cost_usd:
                cost_by_provider[provider] = cost_by_provider.get(provider, 0.0) + log.cost_usd

        # Get tenant statistics
        tenant_ids = {log.tenant_id for log in usage_logs if log.tenant_id}

        # Calculate top tenants
        tenant_usage: dict[str, dict] = {}
        for log in usage_logs:
            if log.tenant_id:
                if log.tenant_id not in tenant_usage:
                    tenant_usage[log.tenant_id] = {"count": 0, "cost": 0.0}
                tenant_usage[log.tenant_id]["count"] += 1
                if log.cost_usd:
                    tenant_usage[log.tenant_id]["cost"] += log.cost_usd

        top_tenants = sorted(
            [
                {
                    "tenant_id": tid,
                    "email_count": data["count"],
                    "total_cost_usd": round(data["cost"], 4),
                }
                for tid, data in tenant_usage.items()
            ],
            key=lambda x: x["email_count"],
            reverse=True,
        )[:10]

        return {
            "period_days": days,
            "period_start": start_date.isoformat(),
            "period_end": datetime.now(UTC).isoformat(),
            "total_tenants_active": len(tenant_ids),
            "total_tenants_configured": len(active_configs),
            "total_emails_sent": total_emails,
            "total_cost_usd": round(total_cost, 4),
            "emails_by_provider": emails_by_provider,
            "cost_by_provider": {k: round(v, 4) for k, v in cost_by_provider.items()},
            "top_tenants": top_tenants,
            "average_cost_per_email": round(total_cost / total_emails, 6) if total_emails > 0 else 0,
        }

    async def check_system_health(self) -> dict:
        """Check health of all email providers across the system.

        Returns:
            Dictionary with health check results
        """
        import asyncio
        import time

        # Get all active configs
        configs = await self._config_repo.list_active_configs(
            self._session, limit=1000,
        )

        health_checks = []

        # Check system default
        try:
            start = time.perf_counter()
            system_healthy = await self._email_service.health_check(None)
            duration_ms = int((time.perf_counter() - start) * 1000)

            health_checks.append({
                "tenant_id": None,
                "provider": "system_default",
                "healthy": system_healthy,
                "response_time_ms": duration_ms,
                "error": None,
            })
        except Exception as e:
            health_checks.append({
                "tenant_id": None,
                "provider": "system_default",
                "healthy": False,
                "response_time_ms": None,
                "error": str(e),
            })

        # Check tenant configs (sample up to 10 for performance)
        sample_configs = list(configs)[:10] if len(configs) > 10 else list(configs)

        async def check_tenant(config: EmailConfig) -> dict:
            try:
                start = time.perf_counter()
                is_healthy = await self._email_service.health_check(config.tenant_id)
                duration_ms = int((time.perf_counter() - start) * 1000)

                return {
                    "tenant_id": config.tenant_id,
                    "provider": config.provider_type.value if hasattr(config.provider_type, "value") else config.provider_type,
                    "healthy": is_healthy,
                    "response_time_ms": duration_ms,
                    "error": None,
                }
            except Exception as e:
                return {
                    "tenant_id": config.tenant_id,
                    "provider": config.provider_type.value if hasattr(config.provider_type, "value") else config.provider_type,
                    "healthy": False,
                    "response_time_ms": None,
                    "error": str(e),
                }

        # Run health checks concurrently
        tenant_checks = await asyncio.gather(*[check_tenant(config) for config in sample_configs])
        health_checks.extend(tenant_checks)

        # Calculate overall health
        healthy_count = sum(1 for check in health_checks if check["healthy"])
        total_checks = len(health_checks)
        overall_healthy = healthy_count == total_checks

        return {
            "overall_healthy": overall_healthy,
            "healthy_count": healthy_count,
            "total_checks": total_checks,
            "health_percentage": round((healthy_count / total_checks * 100), 2) if total_checks > 0 else 0,
            "checks": health_checks,
            "sampled": len(configs) > 10,
            "total_configs": len(configs),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    async def list_all_configs(
        self,
        *,
        active_only: bool = False,
        provider: str | None = None,
    ) -> dict:
        """List all email configurations.

        Args:
            active_only: Filter to only active configs
            provider: Filter by provider type

        Returns:
            Dictionary with config list
        """
        if provider:
            configs = await self._config_repo.list_by_provider_type(
                self._session, provider,
            )
            if active_only:
                configs = [c for c in configs if c.is_active]
        elif active_only:
            configs = await self._config_repo.list_active_configs(self._session)
        else:
            configs = await self._config_repo.list(self._session, limit=1000)

        return {
            "total": len(configs),
            "configs": [
                {
                    "id": str(config.id),
                    "tenant_id": config.tenant_id,
                    "provider_type": config.provider_type.value if hasattr(config.provider_type, "value") else config.provider_type,
                    "is_active": config.is_active,
                    "from_email": config.from_email,
                    "rate_limit_per_minute": config.rate_limit_per_minute,
                    "created_at": config.created_at.isoformat(),
                    "updated_at": config.updated_at.isoformat(),
                }
                for config in configs
            ],
        }

    def invalidate_cache(self, tenant_id: str | None = None) -> dict:
        """Invalidate configuration cache.

        Args:
            tenant_id: Specific tenant (None = all tenants)

        Returns:
            Dictionary with invalidation result
        """
        count = self._email_service.invalidate_config_cache(tenant_id)

        return {
            "success": True,
            "invalidated_count": count,
            "tenant_id": tenant_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    async def get_provider_distribution(self) -> dict:
        """Get distribution of providers across tenants.

        Returns:
            Dictionary with provider distribution
        """
        configs = await self._config_repo.list_active_configs(self._session)

        # Count by provider
        provider_counts: dict[str, int] = {}
        for config in configs:
            provider = config.provider_type.value if hasattr(config.provider_type, "value") else config.provider_type
            provider_counts[provider] = provider_counts.get(provider, 0) + 1

        distribution = [
            {"provider": provider, "tenant_count": count}
            for provider, count in sorted(
                provider_counts.items(), key=lambda x: x[1], reverse=True,
            )
        ]

        total_configs = sum(item["tenant_count"] for item in distribution)

        return {
            "total_configured_tenants": total_configs,
            "distribution": distribution,
            "percentages": {
                item["provider"]: round(item["tenant_count"] / total_configs * 100, 2)
                for item in distribution
            } if total_configs > 0 else {},
        }


__all__ = ["EmailAdminService"]
