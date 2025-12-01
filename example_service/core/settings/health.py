"""Health check configuration settings.

This module provides per-provider health check configuration allowing fine-grained
control over timeouts, thresholds, enabled/disabled state, and readiness criticality.

Environment variables use HEALTH_ prefix with double underscore for nested configs.
Example: HEALTH_DATABASE__TIMEOUT=2.0

Example:
    >>> from example_service.core.settings import get_health_settings
    >>>
    >>> settings = get_health_settings()
    >>> print(settings.database.timeout)  # 2.0
    >>> print(settings.database.critical_for_readiness)  # True
    >>> print(settings.cache.enabled)  # True
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderConfig(BaseSettings):
    """Configuration for an individual health check provider.

    Attributes:
        enabled: Whether this provider is enabled (False = skip registration)
        timeout: Health check timeout in seconds
        degraded_threshold_ms: Latency threshold for DEGRADED status (milliseconds)
        critical_for_readiness: If True, provider failure blocks readiness probe
    """

    enabled: bool = Field(
        default=True,
        description="Enable this health check provider",
    )

    timeout: float = Field(
        default=2.0,
        ge=0.1,
        le=30.0,
        description="Health check timeout in seconds",
    )

    degraded_threshold_ms: float = Field(
        default=1000.0,
        ge=1.0,
        le=60000.0,
        description="Latency threshold for DEGRADED status (milliseconds)",
    )

    critical_for_readiness: bool = Field(
        default=False,
        description="Whether this provider is critical for readiness probe",
    )

    model_config = SettingsConfigDict(
        frozen=True,
        extra="ignore",
    )


class HealthCheckSettings(BaseSettings):
    """Health check system configuration.

    Provides global settings and per-provider configuration for the health check
    aggregator and all registered providers.

    Environment Variables:
        HEALTH_CACHE_TTL_SECONDS: Result cache TTL (default: 10.0)
        HEALTH_HISTORY_SIZE: Max history entries (default: 100)
        HEALTH_GLOBAL_TIMEOUT: Overall check timeout (default: 30.0)

        Per-provider configs use double underscore notation:
        HEALTH_DATABASE__ENABLED=true
        HEALTH_DATABASE__TIMEOUT=2.0
        HEALTH_DATABASE__DEGRADED_THRESHOLD_MS=500.0
        HEALTH_DATABASE__CRITICAL_FOR_READINESS=true

    Example:
        >>> settings = HealthCheckSettings()
        >>> aggregator = HealthAggregator(
        ...     cache_ttl_seconds=settings.cache_ttl_seconds,
        ...     history_size=settings.history_size,
        ...     check_timeout_seconds=settings.global_timeout,
        ... )
        >>> if settings.database.enabled:
        ...     aggregator.add_provider(
        ...         DatabaseHealthProvider(
        ...             engine=engine,
        ...             timeout=settings.database.timeout,
        ...             latency_threshold_ms=settings.database.degraded_threshold_ms,
        ...         )
        ...     )
    """

    # ──────────────────────────────────────────────────────────────
    # Global settings
    # ──────────────────────────────────────────────────────────────

    cache_ttl_seconds: float = Field(
        default=10.0,
        ge=0.0,
        le=300.0,
        description="Result cache TTL in seconds (0 to disable caching)",
    )

    history_size: int = Field(
        default=100,
        ge=0,
        le=10000,
        description="Maximum number of health check results to keep in history",
    )

    global_timeout: float = Field(
        default=30.0,
        ge=1.0,
        le=300.0,
        description="Overall timeout for all health checks in seconds",
    )

    # ──────────────────────────────────────────────────────────────
    # Per-provider configuration
    # ──────────────────────────────────────────────────────────────

    database: ProviderConfig = Field(
        default_factory=lambda: ProviderConfig(
            enabled=True,
            timeout=2.0,
            degraded_threshold_ms=500.0,
            critical_for_readiness=True,
        ),
        description="Database health check configuration",
    )

    cache: ProviderConfig = Field(
        default_factory=lambda: ProviderConfig(
            enabled=True,
            timeout=1.0,
            degraded_threshold_ms=200.0,
            critical_for_readiness=False,
        ),
        description="Redis cache health check configuration",
    )

    rabbitmq: ProviderConfig = Field(
        default_factory=lambda: ProviderConfig(
            enabled=True,
            timeout=5.0,
            degraded_threshold_ms=1000.0,
            critical_for_readiness=False,
        ),
        description="RabbitMQ messaging health check configuration",
    )

    accent_auth: ProviderConfig = Field(
        default_factory=lambda: ProviderConfig(
            enabled=True,
            timeout=5.0,
            degraded_threshold_ms=1000.0,
            critical_for_readiness=False,
        ),
        description="Accent-Auth service health check configuration",
    )

    s3: ProviderConfig = Field(
        default_factory=lambda: ProviderConfig(
            enabled=True,
            timeout=5.0,
            degraded_threshold_ms=2000.0,
            critical_for_readiness=False,
        ),
        description="S3 storage health check configuration",
    )

    consul: ProviderConfig = Field(
        default_factory=lambda: ProviderConfig(
            enabled=True,
            timeout=3.0,
            degraded_threshold_ms=500.0,
            critical_for_readiness=False,
        ),
        description="Consul service discovery health check configuration",
    )

    # ──────────────────────────────────────────────────────────────
    # Helper methods
    # ──────────────────────────────────────────────────────────────

    def get_provider_config(self, provider_name: str) -> ProviderConfig | None:
        """Get configuration for a specific provider by name.

        Args:
            provider_name: Provider name (e.g., "database", "cache", "rabbitmq")

        Returns:
            ProviderConfig if found, None otherwise

        Example:
            >>> settings = HealthCheckSettings()
            >>> config = settings.get_provider_config("database")
            >>> if config and config.enabled:
            ...     print(f"Timeout: {config.timeout}s")
        """
        provider_map = {
            "database": self.database,
            "cache": self.cache,
            "messaging": self.rabbitmq,  # Alias for RabbitMQ provider
            "rabbitmq": self.rabbitmq,
            "auth_service": self.accent_auth,  # Alias for external auth service
            "accent_auth": self.accent_auth,
            "storage": self.s3,  # Alias for S3 provider
            "s3_storage": self.s3,
            "s3": self.s3,
            "consul": self.consul,
        }
        return provider_map.get(provider_name)

    def list_enabled_providers(self) -> list[str]:
        """Get list of enabled provider names.

        Returns:
            List of provider names that are currently enabled

        Example:
            >>> settings = HealthCheckSettings()
            >>> enabled = settings.list_enabled_providers()
            >>> print(enabled)  # ['database', 'cache', 'rabbitmq', ...]
        """
        providers = {
            "database": self.database,
            "cache": self.cache,
            "rabbitmq": self.rabbitmq,
            "accent_auth": self.accent_auth,
            "s3": self.s3,
            "consul": self.consul,
        }
        return [name for name, config in providers.items() if config.enabled]

    def list_critical_providers(self) -> list[str]:
        """Get list of providers critical for readiness.

        Returns:
            List of provider names marked as critical_for_readiness

        Example:
            >>> settings = HealthCheckSettings()
            >>> critical = settings.list_critical_providers()
            >>> print(critical)  # ['database']
        """
        providers = {
            "database": self.database,
            "cache": self.cache,
            "rabbitmq": self.rabbitmq,
            "accent_auth": self.accent_auth,
            "s3": self.s3,
            "consul": self.consul,
        }
        return [
            name
            for name, config in providers.items()
            if config.enabled and config.critical_for_readiness
        ]

    model_config = SettingsConfigDict(
        env_prefix="HEALTH_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        frozen=True,
        extra="ignore",
        env_nested_delimiter="__",  # Enable nested config via double underscore
        env_ignore_empty=True,
    )


__all__ = [
    "HealthCheckSettings",
    "ProviderConfig",
]
