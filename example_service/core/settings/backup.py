"""Database backup configuration settings."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ._sanitizers import sanitize_inline_numeric
from .yaml_sources import create_backup_yaml_source


class BackupSettings(BaseSettings):
    """Database backup and storage settings.

    Environment variables use BACKUP_ prefix.
    Example: BACKUP_LOCAL_DIR="/var/backups/database"
             BACKUP_S3_BUCKET="my-backups"

    Supports:
    - Local filesystem backups with rotation
    - S3-compatible storage (AWS S3, MinIO, etc.)
    - pg_dump configuration
    """

    # Local storage
    local_dir: Path = Field(
        default=Path("/var/backups/database"),
        description="Local directory for backup files",
    )
    retention_days: int = Field(
        default=7,
        ge=1,
        le=365,
        description="Keep local backups for N days",
    )

    # S3 storage
    s3_bucket: str | None = Field(
        default=None,
        description="S3 bucket name for backup storage",
    )
    s3_prefix: str = Field(
        default="backups/database",
        description="S3 key prefix for backup files",
    )
    s3_endpoint_url: str | None = Field(
        default=None,
        description="Custom S3 endpoint URL (for MinIO, LocalStack, etc.)",
    )
    s3_access_key: SecretStr | None = Field(
        default=None,
        description="S3 access key ID",
    )
    s3_secret_key: SecretStr | None = Field(
        default=None,
        description="S3 secret access key",
    )
    s3_region: str = Field(
        default="us-east-1",
        description="AWS region for S3",
    )
    s3_retention_days: int = Field(
        default=30,
        ge=1,
        le=3650,
        description="Keep S3 backups for N days",
    )

    # pg_dump options
    pg_dump_path: str = Field(
        default="pg_dump",
        description="Path to pg_dump binary",
    )
    compression: bool = Field(
        default=True,
        description="Use gzip compression for backups",
    )
    include_blobs: bool = Field(
        default=True,
        description="Include large objects in backup",
    )
    exclude_tables: list[str] = Field(
        default_factory=list,
        description="Tables to exclude from backup (e.g., audit logs)",
    )

    # Scheduling
    enabled: bool = Field(
        default=True,
        description="Enable scheduled backups",
    )
    schedule_hour: int = Field(
        default=2,
        ge=0,
        le=23,
        description="Hour (UTC) to run daily backup",
    )
    schedule_minute: int = Field(
        default=0,
        ge=0,
        le=59,
        description="Minute to run daily backup",
    )

    model_config = SettingsConfigDict(
        env_prefix="BACKUP_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        frozen=True,
        populate_by_name=True,
        extra="ignore",
        env_ignore_empty=True,  # Ignore empty string env vars
    )

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        """Customize settings source precedence: init > yaml > env > dotenv > secrets."""
        return (
            init_settings,
            create_backup_yaml_source(settings_cls),
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )

    @field_validator(
        "retention_days", "s3_retention_days", "schedule_hour", "schedule_minute", mode="before"
    )
    @classmethod
    def _normalize_numeric(cls, value: Any) -> Any:
        """Allow numeric env vars with inline comments."""
        return sanitize_inline_numeric(value)

    @field_validator("exclude_tables", mode="before")
    @classmethod
    def _normalize_exclude_tables(cls, value: Any) -> Any:
        """Parse comma-separated list from env var."""
        if isinstance(value, str):
            return [t.strip() for t in value.split(",") if t.strip()]
        return value

    @property
    def is_configured(self) -> bool:
        """Check if backup is configured (at minimum local storage)."""
        return self.enabled and self.local_dir is not None

    @property
    def is_s3_configured(self) -> bool:
        """Check if S3 storage is configured."""
        return (
            self.s3_bucket is not None
            and self.s3_access_key is not None
            and self.s3_secret_key is not None
        )

    def get_backup_filename(self, timestamp: str) -> str:
        """Generate backup filename with timestamp.

        Args:
            timestamp: Timestamp string (e.g., "20240101_020000")

        Returns:
            Filename like "backup_20240101_020000.sql.gz"
        """
        ext = ".sql.gz" if self.compression else ".sql"
        return f"backup_{timestamp}{ext}"

    def get_local_path(self, filename: str) -> Path:
        """Get full local path for a backup file."""
        return self.local_dir / filename

    def get_s3_key(self, filename: str) -> str:
        """Get S3 key for a backup file."""
        prefix = self.s3_prefix.rstrip("/")
        return f"{prefix}/{filename}"
