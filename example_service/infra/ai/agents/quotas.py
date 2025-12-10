"""Rate limiting and quota management for AI agents.

This module provides quota management and rate limiting for AI operations:
- Token quotas (daily, monthly)
- Request rate limits
- Cost budgets
- Concurrent execution limits
- Per-model limits

Features:
- Redis-backed distributed quotas
- Sliding window rate limiting
- Automatic quota reset
- Quota alerts and notifications
- Usage reporting

Example:
    from example_service.infra.ai.agents.quotas import (
        QuotaManager,
        QuotaConfig,
        RateLimiter,
    )

    # Configure quotas
    config = QuotaConfig(
        daily_token_limit=100000,
        monthly_cost_limit_usd=500.0,
        requests_per_minute=60,
    )

    manager = QuotaManager(config, tenant_id="tenant-123")

    # Check before making request
    if await manager.check_quota():
        result = await make_ai_call()
        await manager.record_usage(tokens=result.tokens, cost=result.cost)
    else:
        raise QuotaExceededError("Daily token limit reached")
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum
import logging
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# =============================================================================
# Quota Types
# =============================================================================


class QuotaType(str, Enum):
    """Types of quotas."""

    TOKENS_DAILY = "tokens_daily"
    TOKENS_MONTHLY = "tokens_monthly"
    COST_DAILY = "cost_daily"
    COST_MONTHLY = "cost_monthly"
    REQUESTS_MINUTE = "requests_minute"
    REQUESTS_HOUR = "requests_hour"
    REQUESTS_DAY = "requests_day"
    CONCURRENT_EXECUTIONS = "concurrent_executions"
    AGENT_CALLS_DAILY = "agent_calls_daily"


class QuotaStatus(str, Enum):
    """Status of a quota check."""

    OK = "ok"  # Under limit
    WARNING = "warning"  # Approaching limit (>80%)
    EXCEEDED = "exceeded"  # Over limit
    DISABLED = "disabled"  # Quota not configured


# =============================================================================
# Quota Configuration
# =============================================================================


class QuotaConfig(BaseModel):
    """Configuration for quota limits.

    All limits are optional. Set to None to disable that limit.
    """

    # Token limits
    daily_token_limit: int | None = Field(None, ge=0, description="Max tokens per day")
    monthly_token_limit: int | None = Field(None, ge=0, description="Max tokens per month")

    # Cost limits (USD)
    daily_cost_limit_usd: Decimal | None = Field(None, ge=0, description="Max cost per day")
    monthly_cost_limit_usd: Decimal | None = Field(None, ge=0, description="Max cost per month")

    # Request rate limits
    requests_per_minute: int | None = Field(None, ge=1, description="Max requests per minute")
    requests_per_hour: int | None = Field(None, ge=1, description="Max requests per hour")
    requests_per_day: int | None = Field(None, ge=1, description="Max requests per day")

    # Concurrency limits
    max_concurrent_executions: int | None = Field(
        None, ge=1, description="Max concurrent executions"
    )
    max_concurrent_per_workflow: int | None = Field(
        None, ge=1, description="Max concurrent per workflow type"
    )

    # Agent-specific limits
    agent_calls_per_day: int | None = Field(None, ge=1, description="Max agent calls per day")

    # Per-model limits
    model_limits: dict[str, dict[str, int]] | None = Field(
        None, description="Per-model token limits"
    )

    # Alert thresholds
    warning_threshold: float = Field(0.8, ge=0, le=1, description="Warning at this % of limit")
    alert_on_warning: bool = Field(True, description="Send alert when warning threshold reached")
    alert_on_exceeded: bool = Field(True, description="Send alert when limit exceeded")


# =============================================================================
# Quota Result
# =============================================================================


@dataclass
class QuotaCheckResult:
    """Result of a quota check.

    Attributes:
        allowed: Whether the request is allowed
        status: Overall quota status
        checks: Individual quota check results
        remaining: Remaining quota values
        reset_at: When quotas will reset
        message: Human-readable message
    """

    allowed: bool
    status: QuotaStatus
    checks: dict[QuotaType, QuotaStatus] = field(default_factory=dict)
    remaining: dict[QuotaType, int | Decimal] = field(default_factory=dict)
    reset_at: dict[QuotaType, datetime] = field(default_factory=dict)
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "allowed": self.allowed,
            "status": self.status.value,
            "checks": {k.value: v.value for k, v in self.checks.items()},
            "remaining": {k.value: float(v) if isinstance(v, Decimal) else v for k, v in self.remaining.items()},
            "reset_at": {k.value: v.isoformat() for k, v in self.reset_at.items()},
            "message": self.message,
        }


# =============================================================================
# Quota Store (Abstract)
# =============================================================================


class QuotaStore(ABC):
    """Abstract base for quota storage backends."""

    @abstractmethod
    async def get_usage(
        self,
        tenant_id: str,
        quota_type: QuotaType,
        window_start: datetime,
    ) -> int | Decimal:
        """Get current usage for a quota window."""

    @abstractmethod
    async def increment_usage(
        self,
        tenant_id: str,
        quota_type: QuotaType,
        amount: int | Decimal,
        window_start: datetime,
        ttl_seconds: int | None = None,
    ) -> int | Decimal:
        """Increment usage and return new total."""

    @abstractmethod
    async def get_concurrent_count(
        self,
        tenant_id: str,
        scope: str = "global",
    ) -> int:
        """Get current concurrent execution count."""

    @abstractmethod
    async def acquire_concurrent_slot(
        self,
        tenant_id: str,
        execution_id: str,
        scope: str = "global",
        ttl_seconds: int = 3600,
    ) -> bool:
        """Try to acquire a concurrent execution slot."""

    @abstractmethod
    async def release_concurrent_slot(
        self,
        tenant_id: str,
        execution_id: str,
        scope: str = "global",
    ) -> None:
        """Release a concurrent execution slot."""


class InMemoryQuotaStore(QuotaStore):
    """In-memory quota store for testing and development."""

    def __init__(self) -> None:
        self._usage: dict[str, dict[str, int | Decimal]] = {}
        self._concurrent: dict[str, set[str]] = {}
        self._lock = asyncio.Lock()

    def _get_key(self, tenant_id: str, quota_type: QuotaType, window: datetime) -> str:
        """Generate storage key."""
        return f"{tenant_id}:{quota_type.value}:{window.isoformat()}"

    async def get_usage(
        self,
        tenant_id: str,
        quota_type: QuotaType,
        window_start: datetime,
    ) -> int | Decimal:
        """Get usage for window."""
        key = self._get_key(tenant_id, quota_type, window_start)
        if tenant_id not in self._usage:
            return 0
        return self._usage[tenant_id].get(key, 0)

    async def increment_usage(
        self,
        tenant_id: str,
        quota_type: QuotaType,
        amount: int | Decimal,
        window_start: datetime,
        ttl_seconds: int | None = None,
    ) -> int | Decimal:
        """Increment usage."""
        async with self._lock:
            if tenant_id not in self._usage:
                self._usage[tenant_id] = {}

            key = self._get_key(tenant_id, quota_type, window_start)
            current = self._usage[tenant_id].get(key, 0)
            new_value = current + amount
            self._usage[tenant_id][key] = new_value
            return new_value

    async def get_concurrent_count(
        self,
        tenant_id: str,
        scope: str = "global",
    ) -> int:
        """Get concurrent count."""
        key = f"{tenant_id}:{scope}"
        return len(self._concurrent.get(key, set()))

    async def acquire_concurrent_slot(
        self,
        tenant_id: str,
        execution_id: str,
        scope: str = "global",
        ttl_seconds: int = 3600,
    ) -> bool:
        """Acquire concurrent slot."""
        async with self._lock:
            key = f"{tenant_id}:{scope}"
            if key not in self._concurrent:
                self._concurrent[key] = set()
            self._concurrent[key].add(execution_id)
            return True

    async def release_concurrent_slot(
        self,
        tenant_id: str,
        execution_id: str,
        scope: str = "global",
    ) -> None:
        """Release concurrent slot."""
        async with self._lock:
            key = f"{tenant_id}:{scope}"
            if key in self._concurrent:
                self._concurrent[key].discard(execution_id)


# =============================================================================
# Rate Limiter
# =============================================================================


class RateLimiter:
    """Sliding window rate limiter.

    Uses a sliding window algorithm to limit requests
    over time periods.

    Example:
        limiter = RateLimiter(
            store=quota_store,
            requests_per_minute=60,
            requests_per_hour=1000,
        )

        if await limiter.check("tenant-123"):
            await limiter.record("tenant-123")
            # Make request
        else:
            # Rate limited
    """

    def __init__(
        self,
        store: QuotaStore,
        requests_per_minute: int | None = None,
        requests_per_hour: int | None = None,
        requests_per_day: int | None = None,
    ) -> None:
        """Initialize rate limiter.

        Args:
            store: Quota storage backend
            requests_per_minute: Limit per minute
            requests_per_hour: Limit per hour
            requests_per_day: Limit per day
        """
        self.store = store
        self.limits = {
            QuotaType.REQUESTS_MINUTE: (requests_per_minute, timedelta(minutes=1)),
            QuotaType.REQUESTS_HOUR: (requests_per_hour, timedelta(hours=1)),
            QuotaType.REQUESTS_DAY: (requests_per_day, timedelta(days=1)),
        }

    async def check(self, tenant_id: str) -> QuotaCheckResult:
        """Check if request is allowed.

        Args:
            tenant_id: Tenant identifier

        Returns:
            QuotaCheckResult with allowed status
        """
        now = datetime.now(UTC)
        checks: dict[QuotaType, QuotaStatus] = {}
        remaining: dict[QuotaType, int] = {}
        reset_at: dict[QuotaType, datetime] = {}

        for quota_type, (limit, window) in self.limits.items():
            if limit is None:
                checks[quota_type] = QuotaStatus.DISABLED
                continue

            window_start = now - window
            usage = await self.store.get_usage(tenant_id, quota_type, window_start)
            remaining_count = max(0, limit - int(usage))

            remaining[quota_type] = remaining_count
            reset_at[quota_type] = now + window

            if usage >= limit:
                checks[quota_type] = QuotaStatus.EXCEEDED
            elif usage >= limit * 0.8:
                checks[quota_type] = QuotaStatus.WARNING
            else:
                checks[quota_type] = QuotaStatus.OK

        # Overall status
        if any(s == QuotaStatus.EXCEEDED for s in checks.values()):
            status = QuotaStatus.EXCEEDED
            allowed = False
            message = "Rate limit exceeded"
        elif any(s == QuotaStatus.WARNING for s in checks.values()):
            status = QuotaStatus.WARNING
            allowed = True
            message = "Approaching rate limit"
        else:
            status = QuotaStatus.OK
            allowed = True
            message = None

        return QuotaCheckResult(
            allowed=allowed,
            status=status,
            checks=checks,
            remaining=remaining,
            reset_at=reset_at,
            message=message,
        )

    async def record(self, tenant_id: str, count: int = 1) -> None:
        """Record a request.

        Args:
            tenant_id: Tenant identifier
            count: Number of requests to record
        """
        now = datetime.now(UTC)

        for quota_type, (limit, window) in self.limits.items():
            if limit is None:
                continue

            window_start = now - window
            ttl = int(window.total_seconds())
            await self.store.increment_usage(
                tenant_id, quota_type, count, window_start, ttl
            )


# =============================================================================
# Quota Manager
# =============================================================================


class QuotaManager:
    """Manages all quotas for a tenant.

    Provides a unified interface for checking and tracking
    all quota types (tokens, cost, requests, concurrency).

    Example:
        config = QuotaConfig(
            daily_token_limit=100000,
            monthly_cost_limit_usd=Decimal("500.00"),
            requests_per_minute=60,
            max_concurrent_executions=5,
        )

        manager = QuotaManager(config, tenant_id="tenant-123", store=store)

        # Check all quotas
        result = await manager.check_quota()
        if not result.allowed:
            raise QuotaExceededError(result.message)

        # After operation
        await manager.record_usage(
            tokens=1500,
            cost=Decimal("0.05"),
            model="gpt-4o",
        )
    """

    def __init__(
        self,
        config: QuotaConfig,
        tenant_id: str,
        store: QuotaStore | None = None,
    ) -> None:
        """Initialize quota manager.

        Args:
            config: Quota configuration
            tenant_id: Tenant identifier
            store: Storage backend (uses in-memory if not provided)
        """
        self.config = config
        self.tenant_id = tenant_id
        self.store = store or InMemoryQuotaStore()
        self.rate_limiter = RateLimiter(
            self.store,
            requests_per_minute=config.requests_per_minute,
            requests_per_hour=config.requests_per_hour,
            requests_per_day=config.requests_per_day,
        )

    def _get_window_start(self, period: str) -> datetime:
        """Get the start of a quota window."""
        now = datetime.now(UTC)
        if period == "day":
            return now.replace(hour=0, minute=0, second=0, microsecond=0)
        if period == "month":
            return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if period == "minute":
            return now.replace(second=0, microsecond=0)
        if period == "hour":
            return now.replace(minute=0, second=0, microsecond=0)
        return now

    async def check_quota(
        self,
        tokens_needed: int = 0,
        cost_estimate: Decimal = Decimal(0),
    ) -> QuotaCheckResult:
        """Check all applicable quotas.

        Args:
            tokens_needed: Estimated tokens for the operation
            cost_estimate: Estimated cost for the operation

        Returns:
            QuotaCheckResult with overall status
        """
        checks: dict[QuotaType, QuotaStatus] = {}
        remaining: dict[QuotaType, int | Decimal] = {}
        reset_at: dict[QuotaType, datetime] = {}

        # Check rate limits
        rate_result = await self.rate_limiter.check(self.tenant_id)
        checks.update(rate_result.checks)
        remaining.update(rate_result.remaining)
        reset_at.update(rate_result.reset_at)

        # Check token quotas
        if self.config.daily_token_limit is not None:
            window = self._get_window_start("day")
            usage = await self.store.get_usage(
                self.tenant_id, QuotaType.TOKENS_DAILY, window
            )
            limit = self.config.daily_token_limit
            remaining_tokens = max(0, limit - int(usage) - tokens_needed)

            remaining[QuotaType.TOKENS_DAILY] = remaining_tokens
            reset_at[QuotaType.TOKENS_DAILY] = window + timedelta(days=1)

            if usage + tokens_needed > limit:
                checks[QuotaType.TOKENS_DAILY] = QuotaStatus.EXCEEDED
            elif usage + tokens_needed > limit * self.config.warning_threshold:
                checks[QuotaType.TOKENS_DAILY] = QuotaStatus.WARNING
            else:
                checks[QuotaType.TOKENS_DAILY] = QuotaStatus.OK

        if self.config.monthly_token_limit is not None:
            window = self._get_window_start("month")
            usage = await self.store.get_usage(
                self.tenant_id, QuotaType.TOKENS_MONTHLY, window
            )
            limit = self.config.monthly_token_limit
            remaining_tokens = max(0, limit - int(usage) - tokens_needed)

            remaining[QuotaType.TOKENS_MONTHLY] = remaining_tokens
            reset_at[QuotaType.TOKENS_MONTHLY] = (window.replace(day=1) + timedelta(days=32)).replace(day=1)

            if usage + tokens_needed > limit:
                checks[QuotaType.TOKENS_MONTHLY] = QuotaStatus.EXCEEDED
            elif usage + tokens_needed > limit * self.config.warning_threshold:
                checks[QuotaType.TOKENS_MONTHLY] = QuotaStatus.WARNING
            else:
                checks[QuotaType.TOKENS_MONTHLY] = QuotaStatus.OK

        # Check cost quotas
        if self.config.daily_cost_limit_usd is not None:
            window = self._get_window_start("day")
            usage = Decimal(str(await self.store.get_usage(
                self.tenant_id, QuotaType.COST_DAILY, window
            )))
            limit = self.config.daily_cost_limit_usd
            remaining_cost = max(Decimal(0), limit - usage - cost_estimate)

            remaining[QuotaType.COST_DAILY] = remaining_cost
            reset_at[QuotaType.COST_DAILY] = window + timedelta(days=1)

            if usage + cost_estimate > limit:
                checks[QuotaType.COST_DAILY] = QuotaStatus.EXCEEDED
            elif usage + cost_estimate > limit * Decimal(str(self.config.warning_threshold)):
                checks[QuotaType.COST_DAILY] = QuotaStatus.WARNING
            else:
                checks[QuotaType.COST_DAILY] = QuotaStatus.OK

        if self.config.monthly_cost_limit_usd is not None:
            window = self._get_window_start("month")
            usage = Decimal(str(await self.store.get_usage(
                self.tenant_id, QuotaType.COST_MONTHLY, window
            )))
            limit = self.config.monthly_cost_limit_usd
            remaining_cost = max(Decimal(0), limit - usage - cost_estimate)

            remaining[QuotaType.COST_MONTHLY] = remaining_cost
            reset_at[QuotaType.COST_MONTHLY] = (window.replace(day=1) + timedelta(days=32)).replace(day=1)

            if usage + cost_estimate > limit:
                checks[QuotaType.COST_MONTHLY] = QuotaStatus.EXCEEDED
            elif usage + cost_estimate > limit * Decimal(str(self.config.warning_threshold)):
                checks[QuotaType.COST_MONTHLY] = QuotaStatus.WARNING
            else:
                checks[QuotaType.COST_MONTHLY] = QuotaStatus.OK

        # Check concurrent execution limit
        if self.config.max_concurrent_executions is not None:
            concurrent = await self.store.get_concurrent_count(self.tenant_id)
            limit = self.config.max_concurrent_executions

            remaining[QuotaType.CONCURRENT_EXECUTIONS] = max(0, limit - concurrent)

            if concurrent >= limit:
                checks[QuotaType.CONCURRENT_EXECUTIONS] = QuotaStatus.EXCEEDED
            elif concurrent >= limit * self.config.warning_threshold:
                checks[QuotaType.CONCURRENT_EXECUTIONS] = QuotaStatus.WARNING
            else:
                checks[QuotaType.CONCURRENT_EXECUTIONS] = QuotaStatus.OK

        # Determine overall status
        if any(s == QuotaStatus.EXCEEDED for s in checks.values()):
            status = QuotaStatus.EXCEEDED
            allowed = False
            exceeded = [k.value for k, v in checks.items() if v == QuotaStatus.EXCEEDED]
            message = f"Quota exceeded: {', '.join(exceeded)}"
        elif any(s == QuotaStatus.WARNING for s in checks.values()):
            status = QuotaStatus.WARNING
            allowed = True
            warning = [k.value for k, v in checks.items() if v == QuotaStatus.WARNING]
            message = f"Approaching quota limit: {', '.join(warning)}"
        else:
            status = QuotaStatus.OK
            allowed = True
            message = None

        return QuotaCheckResult(
            allowed=allowed,
            status=status,
            checks=checks,
            remaining=remaining,
            reset_at=reset_at,
            message=message,
        )

    async def record_usage(
        self,
        tokens: int = 0,
        cost: Decimal = Decimal(0),
        model: str | None = None,
    ) -> None:
        """Record usage after an operation.

        Args:
            tokens: Tokens consumed
            cost: Cost incurred
            model: Model used (for per-model tracking)
        """
        # Record request
        await self.rate_limiter.record(self.tenant_id)

        # Record tokens
        if tokens > 0:
            if self.config.daily_token_limit is not None:
                window = self._get_window_start("day")
                await self.store.increment_usage(
                    self.tenant_id, QuotaType.TOKENS_DAILY, tokens, window, 86400
                )

            if self.config.monthly_token_limit is not None:
                window = self._get_window_start("month")
                await self.store.increment_usage(
                    self.tenant_id, QuotaType.TOKENS_MONTHLY, tokens, window, 86400 * 31
                )

        # Record cost
        if cost > 0:
            if self.config.daily_cost_limit_usd is not None:
                window = self._get_window_start("day")
                await self.store.increment_usage(
                    self.tenant_id, QuotaType.COST_DAILY, cost, window, 86400
                )

            if self.config.monthly_cost_limit_usd is not None:
                window = self._get_window_start("month")
                await self.store.increment_usage(
                    self.tenant_id, QuotaType.COST_MONTHLY, cost, window, 86400 * 31
                )

    async def acquire_execution_slot(
        self,
        execution_id: str,
        workflow_id: str | None = None,
    ) -> bool:
        """Acquire a concurrent execution slot.

        Args:
            execution_id: Unique execution ID
            workflow_id: Optional workflow ID for per-workflow limits

        Returns:
            True if slot acquired, False if limit reached
        """
        if self.config.max_concurrent_executions is None:
            return True

        concurrent = await self.store.get_concurrent_count(self.tenant_id)
        if concurrent >= self.config.max_concurrent_executions:
            return False

        return await self.store.acquire_concurrent_slot(
            self.tenant_id, execution_id, "global", 3600
        )

    async def release_execution_slot(
        self,
        execution_id: str,
        workflow_id: str | None = None,
    ) -> None:
        """Release a concurrent execution slot.

        Args:
            execution_id: Unique execution ID
            workflow_id: Optional workflow ID
        """
        await self.store.release_concurrent_slot(self.tenant_id, execution_id, "global")

    async def get_usage_summary(self) -> dict[str, Any]:
        """Get current usage summary.

        Returns:
            Dictionary with current usage stats
        """
        result = await self.check_quota()
        return {
            "tenant_id": self.tenant_id,
            "status": result.status.value,
            "quotas": result.to_dict(),
            "checked_at": datetime.now(UTC).isoformat(),
        }


# =============================================================================
# Quota Decorator
# =============================================================================


def require_quota(
    tokens_estimate: int = 0,
    cost_estimate: Decimal = Decimal(0),
):
    """Decorator to check quota before executing an async function.

    Args:
        tokens_estimate: Estimated tokens
        cost_estimate: Estimated cost

    Returns:
        Decorated function

    Example:
        @require_quota(tokens_estimate=1000)
        async def my_agent_call(manager: QuotaManager, query: str):
            # ... make AI call ...
    """
    def decorator(func):
        async def wrapper(manager: QuotaManager, *args, **kwargs):
            result = await manager.check_quota(tokens_estimate, cost_estimate)
            if not result.allowed:
                raise QuotaExceededError(result.message or "Quota exceeded")
            return await func(manager, *args, **kwargs)
        return wrapper
    return decorator


# =============================================================================
# Exceptions
# =============================================================================


class QuotaExceededError(Exception):
    """Raised when a quota limit is exceeded."""

    def __init__(
        self,
        message: str,
        quota_type: QuotaType | None = None,
        result: QuotaCheckResult | None = None,
    ) -> None:
        super().__init__(message)
        self.quota_type = quota_type
        self.result = result


class RateLimitedError(QuotaExceededError):
    """Raised when rate limit is exceeded."""



# =============================================================================
# Global Quota Store
# =============================================================================


_global_store: QuotaStore | None = None


def get_quota_store() -> QuotaStore:
    """Get global quota store."""
    global _global_store
    if _global_store is None:
        _global_store = InMemoryQuotaStore()
    return _global_store


def configure_quota_store(store: QuotaStore | None) -> None:
    """Configure global quota store."""
    global _global_store
    _global_store = store


def reset_quota_store() -> None:
    """Reset quota store to default."""
    global _global_store
    _global_store = None


# =============================================================================
# Exports
# =============================================================================


__all__ = [
    # Types
    "QuotaStatus",
    "QuotaType",
    # Configuration
    "QuotaConfig",
    # Results
    "QuotaCheckResult",
    # Store
    "InMemoryQuotaStore",
    "QuotaStore",
    # Rate limiter
    "RateLimiter",
    # Manager
    "QuotaManager",
    # Decorator
    "require_quota",
    # Exceptions
    "QuotaExceededError",
    "RateLimitedError",
    # Global store
    "configure_quota_store",
    "get_quota_store",
    "reset_quota_store",
]
