"""Budget tracking and enforcement for AI workflows.

Provides:
- Cost calculation from usage metrics
- Budget tracking per tenant and time period
- Budget enforcement (warn, block)
- Spend reporting and analytics

Architecture:
    BudgetService
        ├── track_spend() - Record cost incurred
        ├── check_budget() - Pre-execution budget check
        ├── get_spend() - Query current spend
        └── BudgetStore - Persistence backend

Budget Policies:
    - WARN: Log warning but allow execution
    - SOFT_BLOCK: Block new requests, allow in-progress
    - HARD_BLOCK: Block all requests immediately

Example:
    from example_service.infra.ai.observability.budget import BudgetService

    budget = BudgetService()

    # Set tenant budget
    await budget.set_budget(
        tenant_id="tenant-123",
        daily_limit_usd=Decimal("10.00"),
        monthly_limit_usd=Decimal("100.00"),
    )

    # Check before execution
    check = await budget.check_budget(
        tenant_id="tenant-123",
        estimated_cost_usd=Decimal("0.50"),
    )

    if check.allowed:
        # Execute workflow
        result = await executor.execute(...)

        # Track spend
        await budget.track_spend(
            tenant_id="tenant-123",
            cost_usd=result.total_cost_usd,
            pipeline_name="call_analysis",
        )
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
import logging
from typing import Any

logger = logging.getLogger(__name__)


class BudgetPeriod(str, Enum):
    """Budget period types."""

    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class BudgetPolicy(str, Enum):
    """Budget enforcement policy."""

    WARN = "warn"  # Log warning but allow
    SOFT_BLOCK = "soft_block"  # Block new, allow in-progress
    HARD_BLOCK = "hard_block"  # Block all


class BudgetAction(str, Enum):
    """Action taken when budget is checked."""

    ALLOWED = "allowed"
    WARNED = "warned"
    BLOCKED = "blocked"


@dataclass
class BudgetConfig:
    """Budget configuration for a tenant.

    Defines spending limits and enforcement policy.
    """

    tenant_id: str
    daily_limit_usd: Decimal | None = None
    weekly_limit_usd: Decimal | None = None
    monthly_limit_usd: Decimal | None = None
    warn_threshold_percent: float = 80.0  # Warn at 80% of limit
    policy: BudgetPolicy = BudgetPolicy.WARN
    enabled: bool = True

    def get_limit(self, period: BudgetPeriod) -> Decimal | None:
        """Get limit for a specific period."""
        if period == BudgetPeriod.DAILY:
            return self.daily_limit_usd
        if period == BudgetPeriod.WEEKLY:
            return self.weekly_limit_usd
        if period == BudgetPeriod.MONTHLY:
            return self.monthly_limit_usd
        return None


@dataclass
class BudgetCheckResult:
    """Result of a budget check."""

    allowed: bool
    action: BudgetAction
    current_spend_usd: Decimal
    limit_usd: Decimal | None
    percent_used: float
    period: BudgetPeriod
    message: str = ""
    exceeded_periods: list[BudgetPeriod] = field(default_factory=list)

    @property
    def remaining_usd(self) -> Decimal | None:
        """Get remaining budget."""
        if self.limit_usd is None:
            return None
        return max(Decimal(0), self.limit_usd - self.current_spend_usd)


@dataclass
class SpendRecord:
    """Record of spend for a tenant."""

    tenant_id: str
    cost_usd: Decimal
    pipeline_name: str | None = None
    execution_id: str | None = None
    provider: str | None = None
    capability: str | None = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)


class InMemoryBudgetStore:
    """In-memory budget store for development/testing.

    Stores budget configurations and spend records in memory.
    Not suitable for production - use Redis or database backend.
    """

    def __init__(self) -> None:
        self._configs: dict[str, BudgetConfig] = {}
        self._records: list[SpendRecord] = []
        self._lock = asyncio.Lock()

    async def set_config(self, config: BudgetConfig) -> None:
        """Store budget configuration."""
        async with self._lock:
            self._configs[config.tenant_id] = config

    async def get_config(self, tenant_id: str) -> BudgetConfig | None:
        """Get budget configuration."""
        return self._configs.get(tenant_id)

    async def add_spend(self, record: SpendRecord) -> None:
        """Record spend."""
        async with self._lock:
            self._records.append(record)

    async def get_spend(
        self,
        tenant_id: str,
        since: datetime,
        until: datetime | None = None,
    ) -> Decimal:
        """Get total spend for a tenant in a time period."""
        until = until or datetime.utcnow()

        total = Decimal(0)
        for record in self._records:
            if (
                record.tenant_id == tenant_id
                and record.timestamp >= since
                and record.timestamp <= until
            ):
                total += record.cost_usd

        return total

    async def get_spend_records(
        self,
        tenant_id: str,
        since: datetime,
        until: datetime | None = None,
        limit: int = 1000,
    ) -> list[SpendRecord]:
        """Get spend records for a tenant."""
        until = until or datetime.utcnow()

        records = [
            r for r in self._records
            if (
                r.tenant_id == tenant_id
                and r.timestamp >= since
                and r.timestamp <= until
            )
        ]

        return records[:limit]

    async def cleanup_old_records(self, older_than: datetime) -> int:
        """Remove records older than specified time."""
        async with self._lock:
            old_count = len(self._records)
            self._records = [r for r in self._records if r.timestamp >= older_than]
            return old_count - len(self._records)


class BudgetService:
    """Service for budget tracking and enforcement.

    Provides methods for:
    - Configuring tenant budgets
    - Pre-execution budget checks
    - Post-execution spend tracking
    - Spend reporting

    Example:
        service = BudgetService()

        # Configure budget
        await service.set_budget(
            tenant_id="tenant-123",
            daily_limit_usd=Decimal("10.00"),
            monthly_limit_usd=Decimal("100.00"),
            policy=BudgetPolicy.SOFT_BLOCK,
        )

        # Check before execution
        check = await service.check_budget("tenant-123")
        if not check.allowed:
            raise BudgetExceededException(check.message)

        # Track after execution
        await service.track_spend(
            tenant_id="tenant-123",
            cost_usd=Decimal("0.05"),
            pipeline_name="call_analysis",
        )
    """

    def __init__(
        self,
        store: InMemoryBudgetStore | None = None,
        default_daily_limit: Decimal | None = None,
        default_monthly_limit: Decimal | None = None,
        metrics: Any = None,  # AIMetrics instance
    ) -> None:
        """Initialize budget service.

        Args:
            store: Budget store backend
            default_daily_limit: Default daily limit for unconfigured tenants
            default_monthly_limit: Default monthly limit for unconfigured tenants
            metrics: Optional AIMetrics for recording budget metrics
        """
        self.store = store or InMemoryBudgetStore()
        self.default_daily_limit = default_daily_limit
        self.default_monthly_limit = default_monthly_limit
        self.metrics = metrics

    async def set_budget(
        self,
        tenant_id: str,
        daily_limit_usd: Decimal | None = None,
        weekly_limit_usd: Decimal | None = None,
        monthly_limit_usd: Decimal | None = None,
        warn_threshold_percent: float = 80.0,
        policy: BudgetPolicy = BudgetPolicy.WARN,
        enabled: bool = True,
    ) -> BudgetConfig:
        """Set budget configuration for a tenant.

        Args:
            tenant_id: Tenant identifier
            daily_limit_usd: Daily spending limit
            weekly_limit_usd: Weekly spending limit
            monthly_limit_usd: Monthly spending limit
            warn_threshold_percent: Percentage at which to warn
            policy: Enforcement policy
            enabled: Whether budget enforcement is enabled

        Returns:
            Created BudgetConfig
        """
        config = BudgetConfig(
            tenant_id=tenant_id,
            daily_limit_usd=daily_limit_usd,
            weekly_limit_usd=weekly_limit_usd,
            monthly_limit_usd=monthly_limit_usd,
            warn_threshold_percent=warn_threshold_percent,
            policy=policy,
            enabled=enabled,
        )

        await self.store.set_config(config)

        logger.info(
            f"Budget configured for tenant: {tenant_id}",
            extra={
                "tenant_id": tenant_id,
                "daily_limit": str(daily_limit_usd) if daily_limit_usd else None,
                "monthly_limit": str(monthly_limit_usd) if monthly_limit_usd else None,
                "policy": policy.value,
            },
        )

        return config

    async def check_budget(
        self,
        tenant_id: str,
        estimated_cost_usd: Decimal | None = None,
    ) -> BudgetCheckResult:
        """Check if tenant has budget for execution.

        Args:
            tenant_id: Tenant identifier
            estimated_cost_usd: Estimated cost of upcoming operation

        Returns:
            BudgetCheckResult with allowed status and details
        """
        config = await self.store.get_config(tenant_id)

        # Use defaults if no config
        if not config:
            config = BudgetConfig(
                tenant_id=tenant_id,
                daily_limit_usd=self.default_daily_limit,
                monthly_limit_usd=self.default_monthly_limit,
            )

        if not config.enabled:
            return BudgetCheckResult(
                allowed=True,
                action=BudgetAction.ALLOWED,
                current_spend_usd=Decimal(0),
                limit_usd=None,
                percent_used=0.0,
                period=BudgetPeriod.DAILY,
                message="Budget enforcement disabled",
            )

        # Check all configured periods
        exceeded_periods: list[BudgetPeriod] = []
        worst_result: BudgetCheckResult | None = None

        for period in [BudgetPeriod.DAILY, BudgetPeriod.WEEKLY, BudgetPeriod.MONTHLY]:
            limit = config.get_limit(period)
            if limit is None:
                continue

            since = self._get_period_start(period)
            current_spend = await self.store.get_spend(tenant_id, since)

            # Include estimated cost
            projected_spend = current_spend
            if estimated_cost_usd:
                projected_spend += estimated_cost_usd

            percent_used = float(projected_spend / limit * 100) if limit > 0 else 0

            # Check if exceeded
            if projected_spend > limit:
                exceeded_periods.append(period)

                result = BudgetCheckResult(
                    allowed=config.policy == BudgetPolicy.WARN,
                    action=(
                        BudgetAction.WARNED
                        if config.policy == BudgetPolicy.WARN
                        else BudgetAction.BLOCKED
                    ),
                    current_spend_usd=current_spend,
                    limit_usd=limit,
                    percent_used=percent_used,
                    period=period,
                    message=f"{period.value.capitalize()} budget exceeded: ${projected_spend:.4f} / ${limit:.2f}",
                    exceeded_periods=exceeded_periods,
                )

                if worst_result is None or not result.allowed:
                    worst_result = result

            # Check if near limit (warn threshold)
            elif percent_used >= config.warn_threshold_percent:
                result = BudgetCheckResult(
                    allowed=True,
                    action=BudgetAction.WARNED,
                    current_spend_usd=current_spend,
                    limit_usd=limit,
                    percent_used=percent_used,
                    period=period,
                    message=f"{period.value.capitalize()} budget at {percent_used:.1f}%",
                )

                if worst_result is None:
                    worst_result = result

        # No issues found
        if worst_result is None:
            # Get daily spend for reporting
            daily_since = self._get_period_start(BudgetPeriod.DAILY)
            daily_spend = await self.store.get_spend(tenant_id, daily_since)
            daily_limit = config.daily_limit_usd or self.default_daily_limit

            return BudgetCheckResult(
                allowed=True,
                action=BudgetAction.ALLOWED,
                current_spend_usd=daily_spend,
                limit_usd=daily_limit,
                percent_used=float(daily_spend / daily_limit * 100) if daily_limit else 0,
                period=BudgetPeriod.DAILY,
                message="Within budget",
            )

        # Update metrics
        if self.metrics and not worst_result.allowed:
            self.metrics.record_budget_exceeded(
                tenant_id=tenant_id,
                action=worst_result.action.value,
            )

        return worst_result

    async def track_spend(
        self,
        tenant_id: str,
        cost_usd: Decimal,
        pipeline_name: str | None = None,
        execution_id: str | None = None,
        provider: str | None = None,
        capability: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SpendRecord:
        """Track spend for a tenant.

        Args:
            tenant_id: Tenant identifier
            cost_usd: Cost incurred
            pipeline_name: Name of pipeline executed
            execution_id: Execution identifier
            provider: Provider used
            capability: Capability executed
            metadata: Additional metadata

        Returns:
            Created SpendRecord
        """
        record = SpendRecord(
            tenant_id=tenant_id,
            cost_usd=cost_usd,
            pipeline_name=pipeline_name,
            execution_id=execution_id,
            provider=provider,
            capability=capability,
            metadata=metadata or {},
        )

        await self.store.add_spend(record)

        logger.debug(
            f"Spend tracked: ${cost_usd:.6f}",
            extra={
                "tenant_id": tenant_id,
                "cost_usd": str(cost_usd),
                "pipeline": pipeline_name,
                "provider": provider,
            },
        )

        # Update metrics
        if self.metrics:
            config = await self.store.get_config(tenant_id)
            if config:
                for period in [BudgetPeriod.DAILY, BudgetPeriod.MONTHLY]:
                    limit = config.get_limit(period)
                    if limit:
                        since = self._get_period_start(period)
                        spend = await self.store.get_spend(tenant_id, since)
                        self.metrics.record_budget_status(
                            tenant_id=tenant_id,
                            period=period.value,
                            spend_usd=spend,
                            limit_usd=limit,
                        )

        return record

    async def get_spend_summary(
        self,
        tenant_id: str,
        period: BudgetPeriod = BudgetPeriod.DAILY,
    ) -> dict[str, Any]:
        """Get spend summary for a tenant.

        Args:
            tenant_id: Tenant identifier
            period: Time period for summary

        Returns:
            Summary dict with spend, limit, and breakdowns
        """
        config = await self.store.get_config(tenant_id)
        since = self._get_period_start(period)
        total_spend = await self.store.get_spend(tenant_id, since)
        records = await self.store.get_spend_records(tenant_id, since)

        # Calculate breakdowns
        by_pipeline: dict[str, Decimal] = {}
        by_provider: dict[str, Decimal] = {}
        by_capability: dict[str, Decimal] = {}

        for record in records:
            if record.pipeline_name:
                by_pipeline[record.pipeline_name] = (
                    by_pipeline.get(record.pipeline_name, Decimal(0)) + record.cost_usd
                )
            if record.provider:
                by_provider[record.provider] = (
                    by_provider.get(record.provider, Decimal(0)) + record.cost_usd
                )
            if record.capability:
                by_capability[record.capability] = (
                    by_capability.get(record.capability, Decimal(0)) + record.cost_usd
                )

        limit = config.get_limit(period) if config else None

        return {
            "tenant_id": tenant_id,
            "period": period.value,
            "since": since.isoformat(),
            "until": datetime.utcnow().isoformat(),
            "total_spend_usd": str(total_spend),
            "limit_usd": str(limit) if limit else None,
            "remaining_usd": str(limit - total_spend) if limit else None,
            "percent_used": float(total_spend / limit * 100) if limit else None,
            "record_count": len(records),
            "by_pipeline": {k: str(v) for k, v in by_pipeline.items()},
            "by_provider": {k: str(v) for k, v in by_provider.items()},
            "by_capability": {k: str(v) for k, v in by_capability.items()},
        }

    def _get_period_start(self, period: BudgetPeriod) -> datetime:
        """Get the start time for a budget period."""
        now = datetime.utcnow()

        if period == BudgetPeriod.HOURLY:
            return now.replace(minute=0, second=0, microsecond=0)
        if period == BudgetPeriod.DAILY:
            return now.replace(hour=0, minute=0, second=0, microsecond=0)
        if period == BudgetPeriod.WEEKLY:
            # Start of week (Monday)
            days_since_monday = now.weekday()
            start = now - timedelta(days=days_since_monday)
            return start.replace(hour=0, minute=0, second=0, microsecond=0)
        if period == BudgetPeriod.MONTHLY:
            return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        return now


class BudgetExceededException(Exception):
    """Raised when budget is exceeded and policy blocks execution."""

    def __init__(
        self,
        message: str,
        check_result: BudgetCheckResult | None = None,
    ) -> None:
        super().__init__(message)
        self.check_result = check_result


# Singleton instance
_budget_service: BudgetService | None = None


def get_budget_service() -> BudgetService:
    """Get the global budget service singleton.

    Returns:
        The singleton BudgetService instance
    """
    global _budget_service
    if _budget_service is None:
        _budget_service = BudgetService()
    return _budget_service


def configure_budget_service(
    default_daily_limit: Decimal | None = None,
    default_monthly_limit: Decimal | None = None,
    metrics: Any = None,
) -> BudgetService:
    """Configure and return the global budget service.

    Args:
        default_daily_limit: Default daily limit for unconfigured tenants
        default_monthly_limit: Default monthly limit for unconfigured tenants
        metrics: Optional AIMetrics instance

    Returns:
        Configured BudgetService instance
    """
    global _budget_service
    _budget_service = BudgetService(
        default_daily_limit=default_daily_limit,
        default_monthly_limit=default_monthly_limit,
        metrics=metrics,
    )
    return _budget_service
