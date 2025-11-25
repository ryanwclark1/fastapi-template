"""Logging configuration settings."""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .yaml_sources import create_logging_yaml_source

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class LoggingSettings(BaseSettings):
    """Structured logging configuration.

    Environment variables use LOG_ prefix.
    Example: LOG_LEVEL=INFO, LOG_JSON=true, LOG_FILE_ENABLED=false

    Combines best practices from accent-ai services with FastAPI-specific features.
    """

    # ──────────────────────────────────────────────────────────────
    # Basic configuration
    # ──────────────────────────────────────────────────────────────

    service_name: str = Field(
        default="example-service",
        description="Service name to include in log records (static field in JSON)",
    )

    level: LogLevel = Field(
        default="INFO",
        description="Root logger level (DEBUG|INFO|WARNING|ERROR|CRITICAL)",
    )

    json_logs: bool = Field(
        default=True,
        alias="json",
        description="Enable JSON Lines (JSONL) formatted structured logs",
    )

    # ──────────────────────────────────────────────────────────────
    # Per-handler log levels
    # ──────────────────────────────────────────────────────────────

    console_level: LogLevel | None = Field(
        default=None,
        description="Console handler log level. If None, uses root level.",
    )

    file_level: LogLevel | None = Field(
        default=None,
        description="File handler log level. If None, uses root level.",
    )

    # ──────────────────────────────────────────────────────────────
    # File logging / rotation
    # ──────────────────────────────────────────────────────────────

    file_enabled: bool = Field(
        default=True,
        description="Enable file logging. When False, file_path is ignored.",
    )

    file_path: Path | None = Field(
        default=Path("logs/example-service.log.jsonl"),
        description="Path to log file. When None or file_enabled is False, file logging is disabled.",
    )

    file_max_bytes: int = Field(
        default=10_485_760,  # 10 MiB
        ge=1024,
        le=1_073_741_824,
        description="Maximum log file size in bytes before rotation (10MB default, max 1GB).",
    )

    file_backup_count: int = Field(
        default=5,
        ge=0,
        le=100,
        description="Number of rotated log files to keep.",
    )

    # ──────────────────────────────────────────────────────────────
    # Console / stdout logging
    # ──────────────────────────────────────────────────────────────

    console_enabled: bool = Field(
        default=True,
        description="Enable console/stdout logging",
    )

    colorize: bool | None = Field(
        default=None,
        description="Enable console colors. If None, auto-detect (respects NO_COLOR/FORCE_COLOR env vars).",
    )

    colorize_message: bool = Field(
        default=False,
        description="Colorize entire log message (not just level name). Only applies when colorize is enabled.",
    )

    level_colors: dict[str, str | tuple[int, int, int]] | None = Field(
        default=None,
        description=(
            "Custom color mapping for log levels. Values can be:\n"
            "  - ANSI color strings (e.g., '\\033[31m')\n"
            "  - RGB tuples (e.g., (255, 0, 0) for red)\n"
            "  - Hex strings (e.g., '#FF0000' or 'FF0000')\n"
            "If None, uses default color scheme."
        ),
    )

    @field_validator("level_colors", mode="before")
    @classmethod
    def _coerce_invalid_level_colors(cls, v: Any) -> dict[str, Any] | None:
        """Coerce invalid level_colors values to None with a warning.

        This prevents startup failures from config typos (e.g., `level_colors: true`
        when the user meant `colorize: true`).
        """
        if v is None:
            return None
        if isinstance(v, dict):
            return v
        # Invalid type - warn and fall back to default
        warnings.warn(
            f"Invalid level_colors value: {v!r} (expected dict or null). "
            f"Using default color scheme. Did you mean 'colorize: true'?",
            UserWarning,
            stacklevel=2,
        )
        return None

    # ──────────────────────────────────────────────────────────────
    # Context injection
    # ──────────────────────────────────────────────────────────────

    include_context: bool = Field(
        default=True,
        description="Enable automatic context injection into log records via ContextInjectingFilter",
    )

    context_fields: list[str] = Field(
        default_factory=lambda: [
            "request_id",
            "user_id",
            "trace_id",
            "span_id",
        ],
        description="Expected context field names (for documentation/schema purposes)",
    )

    # ──────────────────────────────────────────────────────────────
    # Advanced / integration flags
    # ──────────────────────────────────────────────────────────────

    # config_path removed - use YAML or environment variables only

    capture_warnings: bool = Field(
        default=True,
        description="Forward Python `warnings` module output to the logging system.",
    )

    include_function_name: bool = Field(
        default=False,
        description="Include function name in log records (adds overhead)",
    )

    include_process_info: bool = Field(
        default=False,
        description="Include process ID and name in log records",
    )

    include_thread_info: bool = Field(
        default=False,
        description="Include thread ID and name in log records",
    )

    # ──────────────────────────────────────────────────────────────
    # FastAPI-specific features
    # ──────────────────────────────────────────────────────────────

    include_uvicorn: bool = Field(
        default=True,
        description="Include Uvicorn access logs in output",
    )

    include_request_id: bool = Field(
        default=True,
        description="Include request ID in structured logs for tracing",
    )

    log_slow_requests: bool = Field(
        default=True,
        description="Log requests that exceed slow_request_threshold",
    )

    slow_request_threshold: float = Field(
        default=1.0,
        ge=0.1,
        le=60.0,
        description="Threshold in seconds for logging slow requests",
    )

    # ──────────────────────────────────────────────────────────────
    # Log sampling (production feature)
    # ──────────────────────────────────────────────────────────────

    enable_sampling: bool = Field(
        default=False,
        description="Enable log sampling for high-volume endpoints (health checks, metrics, etc.)",
    )

    sampling_rate_health: float = Field(
        default=0.001,
        ge=0.0,
        le=1.0,
        description="Sample rate for health check logs (0.001 = 0.1%)",
    )

    sampling_rate_metrics: float = Field(
        default=0.01,
        ge=0.0,
        le=1.0,
        description="Sample rate for metrics endpoint logs (0.01 = 1%)",
    )

    sampling_rate_default: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Default sample rate for other loggers (1.0 = 100%)",
    )

    enable_rate_limit: bool = Field(
        default=False,
        description="Enable rate limiting to prevent log storms",
    )

    rate_limit_max_per_second: int = Field(
        default=100,
        ge=1,
        le=10000,
        description="Maximum logs per second per logger when rate limiting enabled",
    )

    rate_limit_window_seconds: float = Field(
        default=1.0,
        ge=0.1,
        le=60.0,
        description="Time window in seconds for rate limiting (default: 1 second)",
    )

    # Advanced sampling configuration
    sampling_rates_custom: dict[str, float] = Field(
        default_factory=dict,
        description="Custom sample rates per logger name. Example: {'app.noisy_endpoint': 0.01}",
    )

    # ──────────────────────────────────────────────────────────────
    # Computed / helper fields
    # ──────────────────────────────────────────────────────────────

    @computed_field
    @property
    def effective_file_path(self) -> Path | None:
        """Return the file path only when file logging is enabled.

        This computed field makes the effective file path part of the model's
        serialization and schema, and clearly separates the "should we log to file?"
        decision from "where should we log?".
        """
        if not self.file_enabled:
            return None
        return self.file_path

    @computed_field
    @property
    def level_int(self) -> int:
        """Get numeric log level for use with logging module."""
        import logging

        return getattr(logging, self.level.upper(), logging.INFO)

    @computed_field
    @property
    def effective_console_level(self) -> LogLevel:
        """Get effective console handler level (falls back to root level)."""
        return self.console_level or self.level

    @computed_field
    @property
    def effective_file_level(self) -> LogLevel:
        """Get effective file handler level (falls back to root level)."""
        return self.file_level or self.level

    @computed_field
    @property
    def console_level_int(self) -> int:
        """Get numeric console log level."""
        import logging

        return getattr(logging, self.effective_console_level.upper(), logging.INFO)

    @computed_field
    @property
    def file_level_int(self) -> int:
        """Get numeric file log level."""
        import logging

        return getattr(logging, self.effective_file_level.upper(), logging.INFO)

    @field_validator("level", "console_level", "file_level", mode="before")
    @classmethod
    def normalize_level(cls, v: str | None) -> str | None:
        """Normalize log level to uppercase."""
        if isinstance(v, str):
            return v.upper()
        return v

    @computed_field
    @property
    def effective_sampling_rates(self) -> dict[str, float]:
        """Build complete sampling rates dict merging defaults with custom.

        Returns:
            Dict mapping logger names to sample rates.
        """
        rates = {
            # Default noisy endpoints
            "example_service.app.api.health": self.sampling_rate_health,
            "example_service.api.health": self.sampling_rate_health,
            "example_service.app.api.metrics": self.sampling_rate_metrics,
            "example_service.api.metrics": self.sampling_rate_metrics,
            "uvicorn.access": self.sampling_rate_metrics,
        }
        # Override with custom rates
        rates.update(self.sampling_rates_custom)
        return rates

    def to_logging_kwargs(self) -> dict[str, Any]:
        """Return kwargs suitable for configure_logging(...).

        This helper bridges the settings model to the actual logging configuration
        function, making the integration explicit and type-safe.

        Returns:
            Dictionary with all logging configuration parameters.
        """
        return {
            # Core settings
            "service_name": self.service_name,
            "log_level": self.level,
            "json_logs": self.json_logs,
            # Handler levels
            "console_level": self.effective_console_level,
            "file_level": self.effective_file_level,
            # File logging
            "file_path": str(self.effective_file_path) if self.effective_file_path else None,
            "file_max_bytes": self.file_max_bytes,
            "file_backup_count": self.file_backup_count,
            # Console logging
            "console_enabled": self.console_enabled,
            "colorize": self.colorize,
            "colorize_message": self.colorize_message,
            "level_colors": self.level_colors,
            # Context
            "include_context": self.include_context,
            # Advanced
            "capture_warnings": self.capture_warnings,
            "include_function_name": self.include_function_name,
            "include_process_info": self.include_process_info,
            "include_thread_info": self.include_thread_info,
            # FastAPI-specific
            "include_uvicorn": self.include_uvicorn,
            # Sampling
            "enable_sampling": self.enable_sampling,
            "sampling_rates": self.effective_sampling_rates,
            "sampling_rate_default": self.sampling_rate_default,
            "enable_rate_limit": self.enable_rate_limit,
            "rate_limit_max_per_second": self.rate_limit_max_per_second,
            "rate_limit_window_seconds": self.rate_limit_window_seconds,
        }

    model_config = SettingsConfigDict(
        env_prefix="LOG_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        frozen=True,
        extra="ignore",
        populate_by_name=True,
        env_ignore_empty=True,  # Ignore empty string env vars
    )

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        """Customize settings source precedence: init > yaml > env > dotenv > secrets."""
        return (
            init_settings,
            create_logging_yaml_source(settings_cls),
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )
