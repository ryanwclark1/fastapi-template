"""Logging configuration settings."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .sources import logging_source

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class LoggingSettings(BaseSettings):
    """Structured logging configuration.

    Environment variables use LOG_ prefix.
    Example: LOG_LEVEL=INFO, LOG_JSON=true
    """

    # Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
    level: LogLevel = Field(
        default="INFO",
        description="Logging level (DEBUG|INFO|WARNING|ERROR|CRITICAL)",
    )

    # JSON structured logging
    json: bool = Field(
        default=True, description="Enable JSON-formatted structured logs"
    )

    # Include uvicorn access logs
    include_uvicorn: bool = Field(
        default=True, description="Include Uvicorn access logs"
    )

    # Log file configuration
    log_file: str | None = Field(
        default="logs/example-service.log.jsonl",
        max_length=500,
        description="Log file path (None to disable file logging)",
    )
    max_bytes: int = Field(
        default=10_485_760, ge=1024, le=1_073_741_824, description="Max log file size in bytes (10MB, max 1GB)"
    )
    backup_count: int = Field(
        default=5, ge=0, le=100, description="Number of backup log files to keep"
    )

    # Console logging
    console_enabled: bool = Field(
        default=True, description="Enable console/stdout logging"
    )

    # Request ID tracking
    include_request_id: bool = Field(
        default=True, description="Include request ID in logs"
    )

    # Performance logging
    log_slow_requests: bool = Field(
        default=True, description="Log slow requests (> threshold)"
    )
    slow_request_threshold: float = Field(
        default=1.0, ge=0.1, le=60.0, description="Slow request threshold in seconds"
    )

    @field_validator("level", mode="before")
    @classmethod
    def normalize_level(cls, v: str) -> str:
        """Normalize log level to uppercase."""
        if isinstance(v, str):
            return v.upper()
        return v

    model_config = SettingsConfigDict(
        env_prefix="LOG_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        frozen=True,
    )

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        """Customize settings source precedence."""

        def files_source(_):
            return logging_source()

        return (init_settings, files_source, env_settings, dotenv_settings, file_secret_settings)

    @property
    def level_int(self) -> int:
        """Get numeric log level."""
        import logging

        return getattr(logging, self.level.upper(), logging.INFO)
