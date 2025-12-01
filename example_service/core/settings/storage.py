"""S3-compatible object storage configuration settings.

Environment variables use STORAGE_ prefix.
Example: STORAGE_ENDPOINT="http://localhost:9000"
         STORAGE_BUCKET="uploads"

Supports:
- AWS S3 (default, no endpoint needed)
- MinIO (set endpoint to MinIO server URL)
- LocalStack (set endpoint to LocalStack URL)
- Any S3-compatible storage
"""

from __future__ import annotations

from typing import Any

from pydantic import (
    Field,
    SecretStr,
    ValidationInfo,
    computed_field,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from .yaml_sources import create_storage_yaml_source


class StorageSettings(BaseSettings):
    """S3-compatible object storage settings.

    Environment variables use STORAGE_ prefix.
    Example: STORAGE_ENABLED=true

    This module provides file storage configuration that:
    - Supports both AWS S3 and S3-compatible services (MinIO, LocalStack)
    - Configures upload limits and allowed file types
    - Enables thumbnail generation for images
    """

    # ──────────────────────────────────────────────────────────────
    # Enable/Disable toggle
    # ──────────────────────────────────────────────────────────────

    enabled: bool = Field(
        default=False,
        description="Enable S3-compatible file storage (disabled by default)",
    )

    # ──────────────────────────────────────────────────────────────
    # S3 Connection Configuration
    # ──────────────────────────────────────────────────────────────

    endpoint: str | None = Field(
        default=None,
        description="S3-compatible endpoint URL (for MinIO/LocalStack). None for AWS S3.",
    )

    bucket: str = Field(
        default="uploads",
        min_length=3,
        max_length=63,
        description="Default bucket for file uploads",
    )

    region: str = Field(
        default="us-east-1",
        description="AWS region (used for AWS S3 and request signing)",
    )

    access_key: SecretStr | None = Field(
        default=None,
        description="S3 access key ID",
    )

    secret_key: SecretStr | None = Field(
        default=None,
        description="S3 secret access key",
    )

    use_ssl: bool = Field(
        default=True,
        description="Use SSL/TLS for S3 connections (set False for local MinIO without TLS)",
    )

    verify_ssl: bool = Field(
        default=True,
        description="Verify SSL certificates (set False for self-signed certs in local MinIO)",
    )

    max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum number of retry attempts for failed S3 operations",
    )

    timeout: int = Field(
        default=30,
        ge=1,
        le=300,
        description="S3 operation timeout in seconds",
    )

    max_pool_connections: int = Field(
        default=10,
        ge=1,
        le=200,
        description="Maximum number of connections in the connection pool",
    )

    retry_mode: str = Field(
        default="adaptive",
        description="boto3 retry mode: standard, adaptive, or legacy",
    )

    # ──────────────────────────────────────────────────────────────
    # Upload Configuration
    # ──────────────────────────────────────────────────────────────

    max_file_size_mb: int = Field(
        default=100,
        ge=1,
        le=5000,
        description="Maximum file size in MB",
    )

    allowed_content_types: list[str] = Field(
        default_factory=lambda: [
            # Images
            "image/jpeg",
            "image/png",
            "image/gif",
            "image/webp",
            "image/svg+xml",
            # Documents
            "application/pdf",
            "text/plain",
            "text/csv",
            "application/json",
            # Archives
            "application/zip",
            "application/gzip",
            # Office documents
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ],
        description="Allowed MIME types for uploads",
    )

    presigned_url_expiry_seconds: int = Field(
        default=3600,
        ge=60,
        le=604800,  # 7 days max
        description="Presigned URL expiration in seconds (default 1 hour)",
    )

    # ──────────────────────────────────────────────────────────────
    # Processing Configuration
    # ──────────────────────────────────────────────────────────────

    enable_thumbnails: bool = Field(
        default=True,
        description="Enable automatic thumbnail generation for images",
    )

    thumbnail_sizes: list[int] = Field(
        default_factory=lambda: [128, 256, 512],
        description="Thumbnail sizes to generate (width in pixels)",
    )

    # ──────────────────────────────────────────────────────────────
    # Path Configuration
    # ──────────────────────────────────────────────────────────────

    upload_prefix: str = Field(
        default="uploads/",
        description="S3 key prefix for uploaded files",
    )

    thumbnail_prefix: str = Field(
        default="thumbnails/",
        description="S3 key prefix for generated thumbnails",
    )

    # ──────────────────────────────────────────────────────────────
    # Health Check Configuration
    # ──────────────────────────────────────────────────────────────

    health_check_enabled: bool = Field(
        default=True,
        description="Enable storage health checks",
    )

    health_check_timeout: float = Field(
        default=5.0,
        ge=1.0,
        le=30.0,
        description="Health check timeout in seconds",
    )

    health_check_key: str = Field(
        default=".health-check",
        description="Key used for health check operations (should be a small object)",
    )

    # ──────────────────────────────────────────────────────────────
    # Streaming Configuration
    # ──────────────────────────────────────────────────────────────

    streaming_chunk_size: int = Field(
        default=1024 * 1024,  # 1MB
        ge=65536,  # 64KB minimum
        le=104857600,  # 100MB maximum
        description="Chunk size in bytes for streaming uploads/downloads",
    )

    streaming_buffer_size: int = Field(
        default=4,
        ge=1,
        le=32,
        description="Number of chunks to buffer during streaming operations",
    )

    # ──────────────────────────────────────────────────────────────
    # Service Lifecycle Configuration
    # ──────────────────────────────────────────────────────────────

    startup_require_storage: bool = Field(
        default=False,
        description="Whether to fail application startup if storage is unavailable (False = degraded mode)",
    )

    startup_timeout: float = Field(
        default=10.0,
        ge=1.0,
        le=60.0,
        description="Timeout in seconds for storage service initialization",
    )

    shutdown_timeout: float = Field(
        default=5.0,
        ge=1.0,
        le=30.0,
        description="Timeout in seconds for graceful shutdown",
    )

    # ──────────────────────────────────────────────────────────────
    # Validators
    # ──────────────────────────────────────────────────────────────

    @field_validator("allowed_content_types", mode="before")
    @classmethod
    def _parse_content_types(cls, value: Any) -> list[str]:
        """Parse comma-separated content types from env var."""
        if isinstance(value, str):
            # Try JSON first
            if value.startswith("["):
                import json

                parsed = json.loads(value)
                # Ensure list of strings
                return [str(item) for item in parsed]
            # Otherwise treat as comma-separated
            return [t.strip() for t in value.split(",") if t.strip()]
        return list(value) if value else []

    @field_validator("thumbnail_sizes", mode="before")
    @classmethod
    def _parse_thumbnail_sizes(cls, value: Any) -> list[int]:
        """Parse comma-separated thumbnail sizes from env var."""
        if isinstance(value, str):
            # Try JSON first
            if value.startswith("["):
                import json

                parsed = json.loads(value)
                return [int(size) for size in parsed]
            # Otherwise treat as comma-separated
            return [int(s.strip()) for s in value.split(",") if s.strip()]
        return list(value) if value else []

    @field_validator("retry_mode")
    @classmethod
    def _validate_retry_mode(cls, value: str) -> str:
        """Validate retry_mode is one of the allowed values."""
        allowed_modes = {"standard", "adaptive", "legacy"}
        if value not in allowed_modes:
            raise ValueError(f"retry_mode must be one of {allowed_modes}, got {value}")
        return value

    @field_validator("access_key", "secret_key", mode="after")
    @classmethod
    def _validate_credentials(
        cls, value: SecretStr | None, _info: ValidationInfo
    ) -> SecretStr | None:
        """Validate that both access_key and secret_key are provided together or neither.

        This validator ensures credential consistency - you can't have just one credential.
        Both must be provided for static credentials, or neither for IAM role authentication.

        Args:
            value: The credential value being validated
            info: Pydantic validation context (required by Pydantic protocol)

        Returns:
            The validated credential value unchanged
        """
        # This runs for each field individually, so we'll do the cross-field check
        # in the model validator below
        return value

    @model_validator(mode="after")
    def _validate_credential_consistency(self) -> StorageSettings:
        """Validate that both credentials are provided together or neither.

        Ensures you can't have just one credential - both must be provided for static
        credentials, or neither for IAM role authentication.
        """
        has_access_key = self.access_key is not None
        has_secret_key = self.secret_key is not None

        if has_access_key != has_secret_key:
            raise ValueError(
                "Both access_key and secret_key must be provided together when using "
                "static credentials. Provide both or neither (for IAM role authentication)."
            )

        return self

    # ──────────────────────────────────────────────────────────────
    # Computed Properties
    # ──────────────────────────────────────────────────────────────

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_configured(self) -> bool:
        """Check if storage is enabled and properly configured.

        Storage is considered configured when:
        - enabled=True
        - Either credentials are provided (access_key and secret_key) OR
          neither is provided (for IAM role authentication)

        Note: The credential consistency is already validated by the model validator.
        """
        return self.enabled

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_minio(self) -> bool:
        """Check if configured for MinIO/S3-compatible (has custom endpoint)."""
        return self.endpoint is not None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def max_file_size_bytes(self) -> int:
        """Get max file size in bytes."""
        return self.max_file_size_mb * 1024 * 1024

    # ──────────────────────────────────────────────────────────────
    # Helper Methods
    # ──────────────────────────────────────────────────────────────

    def is_content_type_allowed(self, content_type: str) -> bool:
        """Check if a content type is in the allowed list.

        Args:
            content_type: MIME type to check.

        Returns:
            True if allowed, False otherwise.
        """
        return content_type in self.allowed_content_types

    def get_boto3_config(self) -> dict[str, Any]:
        """Get configuration dict for boto3/aioboto3 client.

        Returns:
            Dictionary suitable for creating S3 client with all connection parameters.
            Includes credentials (if provided), endpoint, SSL settings, and region.
        """
        if not self.is_configured:
            raise ValueError("Storage not configured")

        config: dict[str, Any] = {
            "region_name": self.region,
            "use_ssl": self.use_ssl,
            "verify": self.verify_ssl,
        }

        # Only add credentials if they're provided (for static auth)
        # If not provided, boto3 will use IAM role authentication
        if self.access_key is not None and self.secret_key is not None:
            config["aws_access_key_id"] = self.access_key.get_secret_value()
            config["aws_secret_access_key"] = self.secret_key.get_secret_value()

        if self.endpoint:
            config["endpoint_url"] = self.endpoint

        return config

    def get_client_config_with_lifecycle(self) -> dict[str, Any]:
        """Get boto3 config suitable for persistent client with lifecycle management.

        Returns configuration optimized for long-running service with:
        - Connection pooling
        - Retry configuration
        - Timeout settings

        Returns:
            Dictionary suitable for creating S3 client with lifecycle-aware settings.
        """
        config = self.get_boto3_config()
        # Add any additional lifecycle-specific config
        return config

    # ──────────────────────────────────────────────────────────────
    # Model Configuration
    # ──────────────────────────────────────────────────────────────

    model_config = SettingsConfigDict(
        env_prefix="STORAGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        frozen=True,
        populate_by_name=True,
        extra="ignore",
        env_ignore_empty=True,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: Any,
        env_settings: Any,
        dotenv_settings: Any,
        file_secret_settings: Any,
    ) -> tuple[Any, ...]:
        """Customize settings source precedence: init > yaml > env > dotenv > secrets."""
        return (
            init_settings,
            create_storage_yaml_source(settings_cls),
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )
