"""Data transfer configuration settings.

Environment variables use DATATRANSFER_ prefix.
Example: DATATRANSFER_EXPORT_DIR="/data/exports"
         DATATRANSFER_MAX_IMPORT_SIZE_MB=100
"""

from __future__ import annotations

from pathlib import Path
from tempfile import gettempdir

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_EXPORT_DIR = Path(gettempdir()) / "example_service_exports"


class DataTransferSettings(BaseSettings):
    """Data transfer (import/export) settings.

    Environment variables use DATATRANSFER_ prefix.
    Example: DATATRANSFER_EXPORT_DIR=/data/exports

    This module provides configuration for:
    - Export file storage location
    - Import file size limits
    - Compression settings
    - Batch processing configuration
    """

    # ──────────────────────────────────────────────────────────────
    # Export Configuration
    # ──────────────────────────────────────────────────────────────

    export_dir: str = Field(
        default=str(DEFAULT_EXPORT_DIR),
        description="Directory for storing export files (use proper directory in production)",
    )

    export_retention_hours: int = Field(
        default=24,
        ge=1,
        le=720,  # 30 days max
        description="Hours to retain export files before cleanup",
    )

    enable_compression: bool = Field(
        default=False,
        description="Enable gzip compression for exports",
    )

    compression_level: int = Field(
        default=6,
        ge=1,
        le=9,
        description="Gzip compression level (1=fastest, 9=best compression)",
    )

    # ──────────────────────────────────────────────────────────────
    # Async Execution Configuration (Option D Integration)
    # ──────────────────────────────────────────────────────────────

    default_execution_mode: str = Field(
        default="sync",
        description="Default execution mode: 'sync' (immediate), 'async' (background), 'auto' (threshold-based)",
    )

    async_threshold: int = Field(
        default=10000,
        ge=100,
        le=1000000,
        description="Record count threshold for 'auto' execution mode (above this = async)",
    )

    enable_export_acl: bool = Field(
        default=True,
        description="Require ACL permissions for export/import operations",
    )

    export_expiration_days: int = Field(
        default=7,
        ge=1,
        le=90,
        description="Days before completed export jobs are auto-deleted (via cleanup task)",
    )

    # ──────────────────────────────────────────────────────────────
    # Import Configuration
    # ──────────────────────────────────────────────────────────────

    max_import_size_mb: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Maximum import file size in MB",
    )

    default_batch_size: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Default number of records to process per batch",
    )

    max_validation_errors: int = Field(
        default=100,
        ge=10,
        le=1000,
        description="Maximum validation errors to report",
    )

    # ──────────────────────────────────────────────────────────────
    # Storage Integration
    # ──────────────────────────────────────────────────────────────

    upload_to_storage: bool = Field(
        default=False,
        description="Upload exports to object storage by default",
    )

    storage_export_prefix: str = Field(
        default="exports/",
        description="S3 key prefix for exported files",
    )

    # ──────────────────────────────────────────────────────────────
    # Tenant Configuration
    # ──────────────────────────────────────────────────────────────

    enable_tenant_isolation: bool = Field(
        default=False,
        description="Enable tenant isolation for data transfer operations",
    )

    # ──────────────────────────────────────────────────────────────
    # Computed Properties
    # ──────────────────────────────────────────────────────────────

    @computed_field  # type: ignore[prop-decorator]
    @property
    def export_path(self) -> Path:
        """Get export directory as Path object."""
        return Path(self.export_dir)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def max_import_size_bytes(self) -> int:
        """Get max import size in bytes."""
        return self.max_import_size_mb * 1024 * 1024

    # ──────────────────────────────────────────────────────────────
    # Helper Methods
    # ──────────────────────────────────────────────────────────────

    def ensure_export_dir(self) -> Path:
        """Ensure export directory exists and return it.

        Returns:
            Path to the export directory.
        """
        path = self.export_path
        path.mkdir(parents=True, exist_ok=True)
        return path

    # ──────────────────────────────────────────────────────────────
    # Model Configuration
    # ──────────────────────────────────────────────────────────────

    model_config = SettingsConfigDict(
        env_prefix="DATATRANSFER_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        frozen=True,
        populate_by_name=True,
        extra="ignore",
        env_ignore_empty=True,
    )
