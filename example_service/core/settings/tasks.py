"""Task management configuration settings.

This module provides settings for task execution, result storage backends,
and task tracking capabilities.

Environment variables use TASK_ prefix.
Example: TASK_RESULT_BACKEND=postgres
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ._sanitizers import sanitize_inline_numeric

TaskResultBackend = Literal["redis", "postgres"]


class TaskSettings(BaseSettings):
    """Task management and result backend configuration.

    Environment variables use TASK_ prefix.
    Example: TASK_RESULT_BACKEND="postgres"

    Supports two result storage backends:
    1. Redis (default): Fast, ephemeral storage with configurable TTL
    2. Postgres: Persistent storage with JSONB for flexible querying

    The backend selection affects both:
    - Taskiq result backend (for task return values)
    - Task execution tracking (for history/statistics)
    """

    # ──────────────────────────────────────────────────────────────
    # Result backend selection
    # ──────────────────────────────────────────────────────────────

    result_backend: TaskResultBackend = Field(
        default="postgres",
        description="Task result storage backend: 'redis' (fast, ephemeral) or 'postgres' (persistent)",
    )

    # ──────────────────────────────────────────────────────────────
    # Execution tracking
    # ──────────────────────────────────────────────────────────────

    tracking_enabled: bool = Field(
        default=True,
        description="Enable task execution tracking (history, statistics)",
    )

    tracking_retention_hours: int = Field(
        default=24,
        ge=1,
        le=720,  # Max 30 days
        description="How long to retain task execution records (hours)",
    )

    # ──────────────────────────────────────────────────────────────
    # Redis-specific settings (when result_backend=redis)
    # ──────────────────────────────────────────────────────────────

    redis_result_ttl_seconds: int = Field(
        default=86400,  # 24 hours
        ge=60,
        le=604800,  # Max 7 days
        description="TTL for task results in Redis (seconds)",
    )

    redis_key_prefix: str = Field(
        default="taskiq",
        min_length=1,
        max_length=50,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Redis key prefix for task data",
    )

    redis_max_connections: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum Redis connections for task tracking",
    )

    # ──────────────────────────────────────────────────────────────
    # PostgreSQL-specific settings (when result_backend=postgres)
    # ──────────────────────────────────────────────────────────────

    postgres_table_name: str = Field(
        default="task_executions",
        pattern=r"^[a-z_][a-z0-9_]*$",
        description="PostgreSQL table name for task executions",
    )

    postgres_auto_cleanup: bool = Field(
        default=True,
        description="Automatically cleanup old task records based on retention",
    )

    postgres_cleanup_batch_size: int = Field(
        default=1000,
        ge=100,
        le=10000,
        description="Batch size for cleanup operations",
    )

    postgres_cleanup_interval_hours: int = Field(
        default=6,
        ge=1,
        le=24,
        description="Hours between automatic cleanup runs",
    )

    # ──────────────────────────────────────────────────────────────
    # Cancellation settings
    # ──────────────────────────────────────────────────────────────

    enable_task_cancellation: bool = Field(
        default=True,
        description="Enable task cancellation API",
    )

    cancellation_grace_period_seconds: int = Field(
        default=30,
        ge=5,
        le=300,
        description="Grace period before forceful cancellation (future use)",
    )

    # ──────────────────────────────────────────────────────────────
    # Timeout settings
    # ──────────────────────────────────────────────────────────────

    default_timeout_seconds: int = Field(
        default=300,
        ge=10,
        le=3600,
        description="Default task timeout in seconds (5 minutes default)",
    )

    timeout_enabled: bool = Field(
        default=True,
        description="Enable task timeout middleware",
    )

    # ──────────────────────────────────────────────────────────────
    # Deduplication settings
    # ──────────────────────────────────────────────────────────────

    deduplication_enabled: bool = Field(
        default=True,
        description="Enable task deduplication middleware",
    )

    deduplication_ttl_seconds: int = Field(
        default=300,
        ge=10,
        le=3600,
        description="TTL for deduplication keys (how long to prevent duplicates)",
    )

    # ──────────────────────────────────────────────────────────────
    # Dead Letter Queue settings
    # ──────────────────────────────────────────────────────────────

    dlq_enabled: bool = Field(
        default=True,
        description="Enable dead letter queue for failed tasks",
    )

    dlq_max_retries: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum retries before moving task to DLQ",
    )

    dlq_retention_hours: int = Field(
        default=168,
        ge=1,
        le=720,
        description="How long to retain DLQ entries (default: 7 days)",
    )

    # ──────────────────────────────────────────────────────────────
    # Progress tracking settings
    # ──────────────────────────────────────────────────────────────

    progress_tracking_enabled: bool = Field(
        default=True,
        description="Enable task progress tracking",
    )

    progress_update_throttle_ms: int = Field(
        default=500,
        ge=100,
        le=5000,
        description="Minimum interval between progress updates (ms)",
    )

    # ──────────────────────────────────────────────────────────────
    # API settings
    # ──────────────────────────────────────────────────────────────

    api_default_limit: int = Field(
        default=50,
        ge=1,
        le=200,
        description="Default page size for task listing endpoints",
    )

    api_max_limit: int = Field(
        default=200,
        ge=50,
        le=1000,
        description="Maximum page size for task listing endpoints",
    )

    # ──────────────────────────────────────────────────────────────
    # Computed fields
    # ──────────────────────────────────────────────────────────────

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_postgres_backend(self) -> bool:
        """Check if using PostgreSQL backend."""
        return self.result_backend == "postgres"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_redis_backend(self) -> bool:
        """Check if using Redis backend."""
        return self.result_backend == "redis"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def tracking_retention_seconds(self) -> int:
        """Get retention period in seconds."""
        return self.tracking_retention_hours * 3600

    @computed_field  # type: ignore[prop-decorator]
    @property
    def dlq_retention_seconds(self) -> int:
        """Get DLQ retention period in seconds."""
        return self.dlq_retention_hours * 3600

    # ──────────────────────────────────────────────────────────────
    # Validators
    # ──────────────────────────────────────────────────────────────

    @field_validator(
        "tracking_retention_hours",
        "redis_result_ttl_seconds",
        "postgres_cleanup_batch_size",
        "default_timeout_seconds",
        "deduplication_ttl_seconds",
        "dlq_max_retries",
        "dlq_retention_hours",
        "progress_update_throttle_ms",
        mode="before",
    )
    @classmethod
    def _normalize_numeric(cls, value: Any) -> Any:
        """Allow numeric env vars with inline comments."""
        return sanitize_inline_numeric(value)

    # ──────────────────────────────────────────────────────────────
    # Model configuration
    # ──────────────────────────────────────────────────────────────

    model_config = SettingsConfigDict(
        env_prefix="TASK_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        frozen=True,
        extra="ignore",
        env_ignore_empty=True,
    )
