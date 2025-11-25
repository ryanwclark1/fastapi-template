"""OpenTelemetry tracing configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import AliasChoices, AnyUrl, Field, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .yaml_sources import create_otel_yaml_source


class OtelSettings(BaseSettings):
    """OpenTelemetry distributed tracing settings.

    Environment variables use OTEL_ prefix.
    Example: OTEL_ENABLED=true, OTEL_ENDPOINT=http://tempo:4317

    Supports production features:
    - Batch processor configuration for performance
    - Compression for bandwidth optimization
    - TLS/mTLS for secure production deployments
    - Authentication headers for managed collectors
    - Resource detection for automatic metadata
    """

    # ──────────────────────────────────────────────────────────────
    # Basic configuration
    # ──────────────────────────────────────────────────────────────

    enabled: bool = Field(
        default=False,
        description="Enable OpenTelemetry tracing",
    )

    endpoint: AnyUrl | None = Field(
        default=None,
        description="OTLP gRPC endpoint (e.g., http://tempo:4317, http://jaeger:4317)",
    )

    # ──────────────────────────────────────────────────────────────
    # Service identification
    # ──────────────────────────────────────────────────────────────

    service_name: str = Field(
        default="example-service",
        min_length=1,
        max_length=100,
        description="Service name for tracing",
    )

    service_version: str = Field(
        default="1.0.0",
        min_length=1,
        max_length=50,
        description="Service version for tracing",
    )

    # ──────────────────────────────────────────────────────────────
    # Connection and transport settings
    # ──────────────────────────────────────────────────────────────

    insecure: bool = Field(
        default=True,
        description="Use insecure gRPC connection (no TLS) - for local development",
    )

    export_timeout: int = Field(
        default=30,
        ge=1,
        le=120,
        description="Maximum time (seconds) to wait for export to complete",
    )

    compression: Literal["none", "gzip"] = Field(
        default="gzip",
        description="Compression algorithm for OTLP export (gzip recommended for production)",
    )

    headers: dict[str, str] = Field(
        default_factory=dict,
        description="Additional headers for OTLP exporter (e.g., authentication tokens)",
    )

    # ──────────────────────────────────────────────────────────────
    # TLS/mTLS settings (production security)
    # ──────────────────────────────────────────────────────────────

    tls_enabled: bool = Field(
        default=False,
        description="Enable TLS for OTLP connection (mutually exclusive with insecure)",
    )

    tls_cert_file: Path | None = Field(
        default=None,
        description="Path to client certificate file for mTLS",
    )

    tls_key_file: Path | None = Field(
        default=None,
        description="Path to client private key file for mTLS",
    )

    tls_ca_file: Path | None = Field(
        default=None,
        description="Path to CA certificate file for server verification",
    )

    # ──────────────────────────────────────────────────────────────
    # Batch processor settings (performance optimization)
    # ──────────────────────────────────────────────────────────────

    batch_schedule_delay: int = Field(
        default=5000,
        ge=100,
        le=60000,
        description="Maximum time (ms) to wait before exporting a batch of spans",
    )

    batch_max_export_batch_size: int = Field(
        default=512,
        ge=1,
        le=2048,
        description="Maximum number of spans to export in a single batch",
    )

    batch_max_queue_size: int = Field(
        default=2048,
        ge=1,
        le=8192,
        description="Maximum queue size for pending spans before dropping",
    )

    # ──────────────────────────────────────────────────────────────
    # Sampling configuration
    # ──────────────────────────────────────────────────────────────

    sample_rate: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Trace sampling rate (0.0-1.0, where 1.0 = 100%)",
    )

    sampler_type: Literal["always_on", "always_off", "trace_id_ratio", "parent_based"] = Field(
        default="parent_based",
        description="Sampling strategy type (parent_based recommended for production)",
    )

    parent_sampler_root: Literal["always_on", "always_off", "trace_id_ratio"] = Field(
        default="trace_id_ratio",
        description="Sampler to use for root spans when parent_based sampling is enabled",
    )

    # ──────────────────────────────────────────────────────────────
    # Resource detection and metadata
    # ──────────────────────────────────────────────────────────────

    enable_resource_detector: bool = Field(
        default=True,
        description="Automatically detect environment attributes (host, process, container, k8s)",
    )

    # ──────────────────────────────────────────────────────────────
    # Instrumentation toggles
    # ──────────────────────────────────────────────────────────────

    instrument_fastapi: bool = Field(
        default=True,
        description="Instrument FastAPI endpoints for automatic tracing",
    )

    instrument_httpx: bool = Field(
        default=True,
        description="Instrument HTTPX client for outgoing HTTP request tracing",
    )

    instrument_sqlalchemy: bool = Field(
        default=True,
        description="Instrument SQLAlchemy for database query tracing",
    )

    instrument_psycopg: bool = Field(
        default=True,
        description="Instrument psycopg PostgreSQL driver for database operation tracing",
        validation_alias=AliasChoices("instrument_psycopg", "instrument_asyncpg"),
    )

    # ──────────────────────────────────────────────────────────────
    # Validators and computed fields
    # ──────────────────────────────────────────────────────────────

    @model_validator(mode="after")
    def validate_enabled_requires_endpoint(self) -> "OtelSettings":
        """Validate that if tracing is enabled, an endpoint must be provided."""
        if self.enabled and not self.endpoint:
            raise ValueError("OTEL endpoint must be provided when tracing is enabled")
        return self

    @model_validator(mode="after")
    def validate_tls_or_insecure(self) -> "OtelSettings":
        """Validate that tls_enabled and insecure are mutually exclusive."""
        if self.tls_enabled and self.insecure:
            raise ValueError("Cannot use both tls_enabled=True and insecure=True - they are mutually exclusive")
        return self

    @computed_field
    @property
    def is_configured(self) -> bool:
        """Check if tracing is enabled and configured.

        Returns True if both enabled and endpoint are set.
        """
        return self.enabled and self.endpoint is not None

    # ──────────────────────────────────────────────────────────────
    # Helper methods
    # ──────────────────────────────────────────────────────────────

    def exporter_kwargs(self) -> dict[str, Any]:
        """Return kwargs for OTLPSpanExporter initialization.

        Returns all configured settings for the OTLP exporter including
        endpoint, timeout, compression, headers, and TLS credentials.

        Returns:
            Dictionary suitable for unpacking into OTLPSpanExporter(**kwargs).
        """
        kwargs: dict[str, Any] = {
            "endpoint": str(self.endpoint),
            "insecure": self.insecure,
            "timeout": self.export_timeout,
        }

        # Add compression if enabled
        if self.compression != "none":
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import Compression
            kwargs["compression"] = Compression.Gzip if self.compression == "gzip" else Compression.NoCompression

        # Add authentication headers if provided
        if self.headers:
            kwargs["headers"] = tuple(self.headers.items())

        # Add TLS credentials if enabled
        if self.tls_enabled:
            credentials = self._build_tls_credentials()
            if credentials:
                kwargs["credentials"] = credentials
                kwargs["insecure"] = False  # Override insecure when using TLS

        return kwargs

    def batch_processor_kwargs(self) -> dict[str, Any]:
        """Return kwargs for BatchSpanProcessor initialization.

        Returns configured batch processing parameters for optimal performance
        and memory usage.

        Returns:
            Dictionary suitable for unpacking into BatchSpanProcessor(**kwargs).
        """
        return {
            "schedule_delay_millis": self.batch_schedule_delay,
            "max_export_batch_size": self.batch_max_export_batch_size,
            "max_queue_size": self.batch_max_queue_size,
            "export_timeout_millis": self.export_timeout * 1000,
        }

    def resource_attributes(self) -> dict[str, str]:
        """Build resource attributes dict for service identification.

        Includes service name, version, and environment. Additional attributes
        like host, process, and container info are added automatically if
        enable_resource_detector is True.

        Returns:
            Dictionary of resource attributes.
        """
        from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION

        attrs: dict[str, str] = {
            SERVICE_NAME: self.service_name,
            SERVICE_VERSION: self.service_version,
        }

        # Add environment attribute from app settings
        try:
            from example_service.core.settings import get_app_settings
            app = get_app_settings()
            attrs["deployment.environment"] = app.environment
            attrs["service.namespace"] = app.service_name
        except Exception:
            # Fallback if app settings not available
            attrs["deployment.environment"] = "unknown"

        return attrs

    def get_sampler(self) -> Any:
        """Get configured sampler instance based on settings.

        Returns appropriate sampler based on sampler_type and sample_rate.

        Returns:
            OpenTelemetry Sampler instance.
        """
        from opentelemetry.sdk.trace.sampling import (
            ALWAYS_OFF,
            ALWAYS_ON,
            ParentBased,
            TraceIdRatioBased,
        )

        if self.sampler_type == "always_on":
            return ALWAYS_ON
        elif self.sampler_type == "always_off":
            return ALWAYS_OFF
        elif self.sampler_type == "trace_id_ratio":
            return TraceIdRatioBased(self.sample_rate)
        else:  # parent_based
            # Choose root sampler
            if self.parent_sampler_root == "always_on":
                root_sampler = ALWAYS_ON
            elif self.parent_sampler_root == "always_off":
                root_sampler = ALWAYS_OFF
            else:  # trace_id_ratio
                root_sampler = TraceIdRatioBased(self.sample_rate)

            return ParentBased(root=root_sampler)

    def _build_tls_credentials(self) -> Any | None:
        """Build gRPC SSL credentials from TLS settings.

        Returns:
            gRPC ChannelCredentials or None if TLS files not provided.
        """
        if not self.tls_enabled:
            return None

        try:
            import grpc

            # Load certificate files
            root_certs = None
            private_key = None
            certificate_chain = None

            if self.tls_ca_file and self.tls_ca_file.exists():
                root_certs = self.tls_ca_file.read_bytes()

            if self.tls_key_file and self.tls_key_file.exists():
                private_key = self.tls_key_file.read_bytes()

            if self.tls_cert_file and self.tls_cert_file.exists():
                certificate_chain = self.tls_cert_file.read_bytes()

            # Create SSL credentials
            if root_certs or private_key or certificate_chain:
                return grpc.ssl_channel_credentials(
                    root_certificates=root_certs,
                    private_key=private_key,
                    certificate_chain=certificate_chain,
                )

            # Fallback to default SSL credentials
            return grpc.ssl_channel_credentials()

        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                f"Failed to build TLS credentials: {e}. Falling back to insecure connection."
            )
            return None

    model_config = SettingsConfigDict(
        env_prefix="OTEL_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        frozen=True,
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
            create_otel_yaml_source(settings_cls),
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )
