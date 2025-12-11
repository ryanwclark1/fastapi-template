"""DLQ configuration and retry policies.

This module provides configuration models for Dead Letter Queue behavior,
including retry policies with various backoff strategies.

The design follows the existing RabbitSettings pattern with:
- Pydantic BaseSettings for environment variable support
- Comprehensive validation with Field constraints
- Frozen models for thread safety
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RetryPolicy(StrEnum):
    """Retry policy for failed message processing.

    Each policy defines how delays between retry attempts are calculated:

    - IMMEDIATE: No delay between retries (use with caution - can cause storms)
    - LINEAR: Delay increases linearly (delay * attempt)
    - EXPONENTIAL: Delay doubles each attempt (delay * 2^attempt) - recommended
    - FIBONACCI: Delay follows Fibonacci sequence (smoother than exponential)

    Example:
        With initial_delay=1000ms:

        Attempt | IMMEDIATE | LINEAR | EXPONENTIAL | FIBONACCI
        --------|-----------|--------|-------------|----------
        1       | 0ms       | 1000ms | 1000ms      | 1000ms
        2       | 0ms       | 2000ms | 2000ms      | 1000ms
        3       | 0ms       | 3000ms | 4000ms      | 2000ms
        4       | 0ms       | 4000ms | 8000ms      | 3000ms
        5       | 0ms       | 5000ms | 16000ms     | 5000ms
    """

    IMMEDIATE = "immediate"
    LINEAR = "linear"
    EXPONENTIAL = "exponential"
    FIBONACCI = "fibonacci"


class DLQConfig(BaseSettings):
    """Configuration for Dead Letter Queue behavior.

    Environment variables use DLQ_ prefix (e.g., DLQ_MAX_RETRIES=5).

    The configuration supports:
    - Retry limits (count-based and duration-based)
    - Multiple retry policies with jitter
    - Exception filtering (retryable vs non-retryable)
    - Message TTL in DLQ

    Example:
        # Basic configuration with exponential backoff
        config = DLQConfig(
            enabled=True,
            max_retries=5,
            retry_policy=RetryPolicy.EXPONENTIAL,
            initial_delay_ms=1000,  # 1 second
            max_delay_ms=60000,     # 1 minute cap
        )

        # Production configuration with strict limits
        config = DLQConfig(
            enabled=True,
            max_retries=5,
            retry_policy=RetryPolicy.EXPONENTIAL,
            initial_delay_ms=5000,
            max_delay_ms=300000,          # 5 minutes
            max_retry_duration_ms=1800000, # 30 minutes total
            jitter=True,
        )

    Attributes:
        enabled: Whether DLQ functionality is enabled.
        max_retries: Maximum retry attempts before moving to DLQ.
        retry_policy: Retry delay calculation policy.
        initial_delay_ms: Initial retry delay in milliseconds.
        max_delay_ms: Maximum retry delay (caps growth).
        retry_multiplier: Multiplier for exponential backoff.
        jitter: Add random jitter to prevent thundering herd.
        jitter_range: Jitter multiplier range (min, max).
        max_retry_duration_ms: Maximum total retry time.
        message_ttl_ms: TTL for messages in DLQ.
        non_retryable_exceptions: Exception names that skip retry.
        retryable_exceptions: Only retry these exceptions (None = all).
        track_failures: Track failure details in headers.
    """

    # ─────────────────────────────────────────────────────
    # Enable/disable toggle
    # ─────────────────────────────────────────────────────
    enabled: bool = Field(
        default=True,
        description="Enable DLQ functionality.",
    )

    # ─────────────────────────────────────────────────────
    # Retry limits
    # ─────────────────────────────────────────────────────
    max_retries: int = Field(
        default=5,
        ge=0,
        le=20,
        description="Maximum retry attempts before routing to DLQ (0-20).",
    )
    max_retry_duration_ms: int | None = Field(
        default=None,
        ge=1000,
        description="Maximum total retry duration in ms (None = no limit).",
    )

    # ─────────────────────────────────────────────────────
    # Retry policy
    # ─────────────────────────────────────────────────────
    retry_policy: RetryPolicy = Field(
        default=RetryPolicy.EXPONENTIAL,
        description="Retry delay calculation policy.",
    )
    initial_delay_ms: int = Field(
        default=1000,
        ge=100,
        le=60000,
        description="Initial retry delay in milliseconds (100-60000).",
    )
    max_delay_ms: int = Field(
        default=60000,
        ge=1000,
        le=3600000,
        description="Maximum retry delay in milliseconds (1s-1h).",
    )
    retry_multiplier: float = Field(
        default=2.0,
        ge=1.0,
        le=10.0,
        description="Backoff multiplier for exponential policy.",
    )

    # ─────────────────────────────────────────────────────
    # Jitter (prevents thundering herd)
    # ─────────────────────────────────────────────────────
    jitter: bool = Field(
        default=True,
        description="Add random jitter to retry delays.",
    )
    jitter_range: tuple[float, float] = Field(
        default=(0.5, 1.5),
        description="Jitter multiplier range (min, max).",
    )

    # ─────────────────────────────────────────────────────
    # Message TTL
    # ─────────────────────────────────────────────────────
    message_ttl_ms: int | None = Field(
        default=86400000,  # 24 hours
        ge=60000,
        description="Message TTL in DLQ (ms, None = infinite).",
    )

    # ─────────────────────────────────────────────────────
    # Exception filtering
    # ─────────────────────────────────────────────────────
    non_retryable_exceptions: tuple[str, ...] = Field(
        default=(
            "ValueError",
            "TypeError",
            "KeyError",
            "AttributeError",
            "ValidationError",
            "JSONDecodeError",
        ),
        description="Exception class names that skip retry (permanent failures).",
    )
    retryable_exceptions: tuple[str, ...] | None = Field(
        default=None,
        description="Only retry these exception class names (None = retry all except non-retryable).",
    )

    # ─────────────────────────────────────────────────────
    # Failure tracking
    # ─────────────────────────────────────────────────────
    track_failures: bool = Field(
        default=True,
        description="Track failure details in message headers.",
    )

    model_config = SettingsConfigDict(
        env_prefix="DLQ_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        frozen=True,
        extra="ignore",
    )

    # ─────────────────────────────────────────────────────
    # Validation
    # ─────────────────────────────────────────────────────
    @model_validator(mode="after")
    def _validate_delays(self) -> DLQConfig:
        """Ensure max_delay >= initial_delay."""
        if self.max_delay_ms < self.initial_delay_ms:
            msg = (
                f"max_delay_ms ({self.max_delay_ms}) must be >= "
                f"initial_delay_ms ({self.initial_delay_ms})"
            )
            raise ValueError(
                msg,
            )
        return self

    @model_validator(mode="after")
    def _validate_jitter_range(self) -> DLQConfig:
        """Ensure jitter range is valid (min < max, both positive)."""
        min_jitter, max_jitter = self.jitter_range
        if min_jitter < 0 or max_jitter < 0:
            msg = "Jitter range values must be positive"
            raise ValueError(msg)
        if min_jitter >= max_jitter:
            msg = f"Jitter range min ({min_jitter}) must be < max ({max_jitter})"
            raise ValueError(
                msg,
            )
        return self

    # ─────────────────────────────────────────────────────
    # Helper methods
    # ─────────────────────────────────────────────────────
    def should_retry_exception(self, exception: Exception) -> bool:
        """Check if an exception should trigger a retry.

        Exceptions are NOT retried if:
        1. Exception class name is in non_retryable_exceptions
        2. retryable_exceptions is set and exception is not in the list

        Args:
            exception: The exception that was raised.

        Returns:
            True if the exception should be retried, False otherwise.

        Example:
            config = DLQConfig(
                non_retryable_exceptions=("ValueError", "TypeError")
            )

            # ValueError -> don't retry (permanent failure)
            assert not config.should_retry_exception(ValueError("bad input"))

            # TimeoutError -> retry (transient failure)
            assert config.should_retry_exception(TimeoutError("timeout"))
        """
        exc_name = type(exception).__name__

        # Check non-retryable first (permanent failures)
        if exc_name in self.non_retryable_exceptions:
            return False

        # If retryable whitelist is specified, only retry those
        if self.retryable_exceptions is not None:
            return exc_name in self.retryable_exceptions

        # Default: retry all exceptions not explicitly excluded
        return True

    def to_dict(self) -> dict[str, Any]:
        """Convert config to dictionary for logging/debugging.

        Returns:
            Dictionary with all configuration values.
        """
        return {
            "enabled": self.enabled,
            "max_retries": self.max_retries,
            "max_retry_duration_ms": self.max_retry_duration_ms,
            "retry_policy": self.retry_policy.value,
            "initial_delay_ms": self.initial_delay_ms,
            "max_delay_ms": self.max_delay_ms,
            "retry_multiplier": self.retry_multiplier,
            "jitter": self.jitter,
            "jitter_range": self.jitter_range,
            "message_ttl_ms": self.message_ttl_ms,
            "non_retryable_exceptions": self.non_retryable_exceptions,
            "retryable_exceptions": self.retryable_exceptions,
            "track_failures": self.track_failures,
        }


__all__ = ["DLQConfig", "RetryPolicy"]
