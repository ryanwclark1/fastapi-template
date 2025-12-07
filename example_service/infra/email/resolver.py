"""Email configuration resolver with TTL-based caching.

Provides tenant-specific email configuration resolution with:
- TTL-based caching to prevent stale configs
- Fallback to system settings when no tenant config exists
- Thread-safe cache operations
- Manual cache invalidation API

Usage:
    resolver = EmailConfigResolver(session_factory, settings)

    # Get config for tenant (cached)
    config = await resolver.get_config("tenant-123")

    # Invalidate on config update
    resolver.invalidate("tenant-123")
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import time
from typing import TYPE_CHECKING, Any

from example_service.core.models.email_config import EmailConfig, EmailProviderType

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession

    from example_service.core.settings.email import EmailSettings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolvedEmailConfig:
    """Resolved email configuration combining tenant and system settings.

    This is an immutable snapshot of the resolved configuration,
    suitable for passing to providers.

    Attributes:
        tenant_id: Tenant ID or None for system default
        provider_type: Email provider to use
        source: Where config came from ("tenant", "system", "default")
        All provider-specific fields from EmailConfig or EmailSettings
    """

    tenant_id: str | None
    provider_type: EmailProviderType
    source: str  # "tenant", "system", "default"

    # SMTP
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool | None = None
    smtp_use_ssl: bool | None = None

    # AWS SES
    aws_region: str | None = None
    aws_access_key: str | None = None
    aws_secret_key: str | None = None
    aws_configuration_set: str | None = None

    # API-based providers (SendGrid, Mailgun)
    api_key: str | None = None
    api_endpoint: str | None = None

    # Sender defaults
    from_email: str | None = None
    from_name: str | None = None
    reply_to: str | None = None

    # Rate limits
    rate_limit_per_minute: int | None = None
    rate_limit_per_hour: int | None = None
    daily_quota: int | None = None

    # Cost tracking
    cost_per_email_usd: float | None = None
    monthly_budget_usd: float | None = None

    # Extra config
    config_json: dict[str, Any] | None = None


@dataclass
class _CacheEntry:
    """Cache entry with timestamp for TTL checking."""

    config: ResolvedEmailConfig | None
    cached_at: float


class EmailConfigResolver:
    """Resolves email configuration for tenants with caching.

    Implements a TTL-based cache to balance performance with freshness.
    When a tenant config is not found, falls back to system settings.

    Example:
        resolver = EmailConfigResolver(
            session_factory=get_session,
            settings=email_settings,
            cache_ttl=300  # 5 minutes
        )

        # Get tenant config (may be cached)
        config = await resolver.get_config("tenant-123")

        # Force refresh after config update
        resolver.invalidate("tenant-123")

        # Clear entire cache (e.g., on settings change)
        resolver.invalidate_all()
    """

    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
        settings: EmailSettings,
        cache_ttl: int = 300,  # 5 minutes default
    ) -> None:
        """Initialize resolver.

        Args:
            session_factory: Factory function to create database sessions
            settings: System-level email settings (fallback)
            cache_ttl: Cache time-to-live in seconds (default: 300)
        """
        self._session_factory = session_factory
        self._settings = settings
        self._cache_ttl = cache_ttl
        self._cache: dict[str, _CacheEntry] = {}

        logger.info(
            "Email config resolver initialized",
            extra={"cache_ttl": cache_ttl},
        )

    async def get_config(self, tenant_id: str | None = None) -> ResolvedEmailConfig:
        """Get resolved email configuration for a tenant.

        Resolution order:
        1. Check cache (if not expired)
        2. Query database for tenant config
        3. Fall back to system settings

        Args:
            tenant_id: Tenant ID, or None for system default

        Returns:
            ResolvedEmailConfig with all provider settings
        """
        if tenant_id is None:
            return self._resolve_from_settings()

        # Check cache
        cache_key = tenant_id
        if cache_key in self._cache:
            entry = self._cache[cache_key]
            age = time.time() - entry.cached_at
            if age < self._cache_ttl:
                logger.debug(
                    "Email config cache hit",
                    extra={"tenant_id": tenant_id, "age_seconds": int(age)},
                )
                # Return cached config or system fallback
                return entry.config or self._resolve_from_settings()

            # Cache expired, remove entry
            logger.debug(
                "Email config cache expired",
                extra={"tenant_id": tenant_id, "age_seconds": int(age)},
            )
            del self._cache[cache_key]

        # Query database
        config = await self._fetch_tenant_config(tenant_id)

        # Cache result (even if None, to avoid repeated queries)
        resolved = self._resolve_from_db_config(config, tenant_id) if config else None
        self._cache[cache_key] = _CacheEntry(
            config=resolved,
            cached_at=time.time(),
        )

        if resolved:
            logger.debug(
                "Email config loaded from database",
                extra={
                    "tenant_id": tenant_id,
                    "provider": resolved.provider_type.value,
                },
            )
            return resolved

        # Fall back to system settings
        logger.debug(
            "No tenant email config, using system settings",
            extra={"tenant_id": tenant_id},
        )
        return self._resolve_from_settings()

    async def _fetch_tenant_config(self, tenant_id: str) -> EmailConfig | None:
        """Fetch tenant config from database.

        Args:
            tenant_id: Tenant ID to look up

        Returns:
            EmailConfig if found and active, None otherwise
        """
        from sqlalchemy import select

        async with self._session_factory() as session:
            stmt = select(EmailConfig).where(
                EmailConfig.tenant_id == tenant_id,
                EmailConfig.is_active.is_(True),
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    def _resolve_from_db_config(self, config: EmailConfig, tenant_id: str) -> ResolvedEmailConfig:
        """Create resolved config from database model.

        Args:
            config: Database EmailConfig model
            tenant_id: Tenant ID

        Returns:
            ResolvedEmailConfig with tenant settings
        """
        return ResolvedEmailConfig(
            tenant_id=tenant_id,
            provider_type=EmailProviderType(config.provider_type),
            source="tenant",
            # SMTP
            smtp_host=config.smtp_host,
            smtp_port=config.smtp_port,
            smtp_username=config.smtp_username,
            smtp_password=config.smtp_password,
            smtp_use_tls=config.smtp_use_tls,
            smtp_use_ssl=config.smtp_use_ssl,
            # AWS SES
            aws_region=config.aws_region,
            aws_access_key=config.aws_access_key,
            aws_secret_key=config.aws_secret_key,
            aws_configuration_set=config.aws_configuration_set,
            # API providers
            api_key=config.api_key,
            api_endpoint=config.api_endpoint,
            # Sender
            from_email=config.from_email or self._settings.default_from_email,
            from_name=config.from_name or self._settings.default_from_name,
            reply_to=config.reply_to,
            # Rate limits (use tenant override or system default)
            rate_limit_per_minute=(
                config.rate_limit_per_minute or self._settings.rate_limit_per_minute
            ),
            rate_limit_per_hour=config.rate_limit_per_hour,
            daily_quota=config.daily_quota,
            # Cost
            cost_per_email_usd=config.cost_per_email_usd,
            monthly_budget_usd=config.monthly_budget_usd,
            # Extra
            config_json=config.config_json,
        )

    def _resolve_from_settings(self) -> ResolvedEmailConfig:
        """Create resolved config from system settings.

        Returns:
            ResolvedEmailConfig with system default settings
        """
        # Map backend string to provider type
        backend_to_provider = {
            "smtp": EmailProviderType.SMTP,
            "console": EmailProviderType.CONSOLE,
            "file": EmailProviderType.FILE,
        }
        provider_type = backend_to_provider.get(self._settings.backend, EmailProviderType.SMTP)

        return ResolvedEmailConfig(
            tenant_id=None,
            provider_type=provider_type,
            source="system",
            # SMTP from settings
            smtp_host=self._settings.smtp_host,
            smtp_port=self._settings.smtp_port,
            smtp_username=self._settings.smtp_username,
            smtp_password=(
                self._settings.smtp_password.get_secret_value()
                if self._settings.smtp_password
                else None
            ),
            smtp_use_tls=self._settings.use_tls,
            smtp_use_ssl=self._settings.use_ssl,
            # Sender
            from_email=self._settings.default_from_email,
            from_name=self._settings.default_from_name,
            # Rate limits
            rate_limit_per_minute=self._settings.rate_limit_per_minute,
        )

    def invalidate(self, tenant_id: str) -> bool:
        """Invalidate cache for a specific tenant.

        Call this after updating a tenant's email configuration.

        Args:
            tenant_id: Tenant ID to invalidate

        Returns:
            True if entry was in cache and removed
        """
        if tenant_id in self._cache:
            del self._cache[tenant_id]
            logger.info(
                "Email config cache invalidated",
                extra={"tenant_id": tenant_id},
            )
            return True
        return False

    def invalidate_all(self) -> int:
        """Clear entire cache.

        Call this after system-wide configuration changes.

        Returns:
            Number of entries cleared
        """
        count = len(self._cache)
        self._cache.clear()
        if count > 0:
            logger.info(
                "Email config cache cleared",
                extra={"entries_cleared": count},
            )
        return count

    def get_cache_stats(self) -> dict[str, int]:
        """Get cache statistics.

        Returns:
            Dict with cache size and other stats
        """
        now = time.time()
        valid_count = sum(
            1 for entry in self._cache.values() if now - entry.cached_at < self._cache_ttl
        )
        return {
            "total_entries": len(self._cache),
            "valid_entries": valid_count,
            "expired_entries": len(self._cache) - valid_count,
            "ttl_seconds": self._cache_ttl,
        }


# Module-level singleton (initialized on first use)
_resolver: EmailConfigResolver | None = None


def get_email_config_resolver() -> EmailConfigResolver:
    """Get the singleton email config resolver.

    This initializes the resolver on first use with default settings.
    For custom configuration, use initialize_email_config_resolver().

    Returns:
        EmailConfigResolver instance
    """
    global _resolver
    if _resolver is None:
        msg = (
            "Email config resolver not initialized. "
            "Call initialize_email_config_resolver() during app startup."
        )
        raise RuntimeError(
            msg
        )
    return _resolver


def initialize_email_config_resolver(
    session_factory: Callable[[], AsyncSession],
    settings: EmailSettings,
    cache_ttl: int = 300,
) -> EmailConfigResolver:
    """Initialize the singleton email config resolver.

    Call this during application startup.

    Args:
        session_factory: Factory function to create database sessions
        settings: System-level email settings
        cache_ttl: Cache TTL in seconds

    Returns:
        Initialized EmailConfigResolver
    """
    global _resolver
    _resolver = EmailConfigResolver(
        session_factory=session_factory,
        settings=settings,
        cache_ttl=cache_ttl,
    )
    return _resolver


__all__ = [
    "EmailConfigResolver",
    "ResolvedEmailConfig",
    "get_email_config_resolver",
    "initialize_email_config_resolver",
]
