"""Database administration settings.

Provides settings for database administration features including
health checks, query timeouts, rate limiting, and audit retention.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AdminSettings(BaseSettings):
    """Database administration settings.

    Environment variables use ADMIN_ prefix.
    Example: ADMIN_ENABLED=true
    """

    # Feature toggle
    enabled: bool = Field(
        default=True,
        description="Enable database admin features",
    )

    # Rate limiting
    rate_limit_enabled: bool = Field(
        default=True,
        description="Enable rate limiting for admin operations",
    )
    rate_limit_max_ops: int = Field(
        default=5,
        ge=1,
        le=100,
        description="Maximum admin operations per window",
    )
    rate_limit_window_seconds: int = Field(
        default=60,
        ge=10,
        le=3600,
        description="Rate limit window duration in seconds",
    )

    # Query timeouts
    default_query_timeout_seconds: int = Field(
        default=30,
        ge=5,
        le=300,
        description="Default timeout for admin queries in seconds",
    )
    health_check_timeout_seconds: int = Field(
        default=10,
        ge=1,
        le=60,
        description="Health check query timeout in seconds",
    )

    # Health thresholds
    connection_pool_critical_threshold: float = Field(
        default=90.0,
        ge=0,
        le=100,
        description="Connection pool usage critical threshold percentage",
    )
    connection_pool_warning_threshold: float = Field(
        default=75.0,
        ge=0,
        le=100,
        description="Connection pool usage warning threshold percentage",
    )
    cache_hit_ratio_warning_threshold: float = Field(
        default=85.0,
        ge=0,
        le=100,
        description="Cache hit ratio warning threshold percentage",
    )

    # Audit retention
    audit_log_retention_days: int = Field(
        default=90,
        ge=1,
        le=730,
        description="Number of days to retain audit logs",
    )

    # Confirmation tokens
    confirmation_token_expiry_minutes: int = Field(
        default=2,
        ge=1,
        le=10,
        description="Expiry time for confirmation tokens in minutes",
    )

    model_config = SettingsConfigDict(
        env_prefix="ADMIN_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        frozen=True,
        extra="ignore",
    )


__all__ = ["AdminSettings"]
