"""Webhook delivery configuration settings.

Provides settings for webhook HTTP delivery, retry logic, and timeout configuration.
These settings apply to webhook systems across the application (jobs, events, etc.).
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class WebhookSettings(BaseSettings):
    """Configuration for webhook delivery system.

    Controls HTTP timeouts, retry behavior, and delivery guarantees
    for outbound webhook notifications.
    """

    # HTTP delivery settings
    timeout_seconds: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Timeout for webhook HTTP requests (seconds)",
    )
    connect_timeout_seconds: int = Field(
        default=10,
        ge=1,
        le=60,
        description="Connection timeout for webhook HTTP requests (seconds)",
    )

    # Retry configuration
    max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum retry attempts for failed webhook delivery",
    )
    retry_delay_seconds: float = Field(
        default=60.0,
        ge=0.0,
        description="Base delay between webhook retry attempts (seconds)",
    )
    retry_backoff_multiplier: float = Field(
        default=2.0,
        ge=1.0,
        le=10.0,
        description="Exponential backoff multiplier for retries",
    )
    retry_max_delay_seconds: float = Field(
        default=3600.0,
        ge=1.0,
        description="Maximum delay between retries (1 hour default)",
    )

    # Delivery guarantees
    enable_signature: bool = Field(
        default=True,
        description="Include HMAC signature in webhook requests",
    )
    max_payload_size_bytes: int = Field(
        default=1048576,  # 1MB
        ge=1024,
        le=10485760,  # 10MB max
        description="Maximum webhook payload size in bytes",
    )

    # Rate limiting
    rate_limit_per_endpoint: int = Field(
        default=100,
        ge=1,
        description="Maximum webhook deliveries per endpoint per minute",
    )

    # Circuit breaker
    circuit_breaker_threshold: int = Field(
        default=5,
        ge=1,
        description="Failed deliveries before circuit opens",
    )
    circuit_breaker_timeout_seconds: int = Field(
        default=300,
        ge=1,
        description="Seconds before attempting to close circuit (5 min default)",
    )

    model_config = SettingsConfigDict(
        env_prefix="WEBHOOK_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        frozen=True,
        extra="ignore",
    )


__all__ = ["WebhookSettings"]
