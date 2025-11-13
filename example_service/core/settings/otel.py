"""OpenTelemetry tracing configuration."""

from __future__ import annotations

from pydantic import AnyUrl, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .sources import otel_source


class OtelSettings(BaseSettings):
    """OpenTelemetry distributed tracing settings.

    Environment variables use OTEL_ prefix.
    Example: OTEL_ENABLED=true, OTEL_ENDPOINT=http://tempo:4317
    """

    # Enable/disable tracing
    enabled: bool = Field(default=False, description="Enable OpenTelemetry tracing")

    # OTLP exporter endpoint
    endpoint: AnyUrl | None = Field(
        default=None,
        description="OTLP gRPC endpoint (e.g., http://tempo:4317, http://jaeger:4317)",
    )

    # Service identification
    service_name: str = Field(
        default="example-service",
        min_length=1,
        max_length=100,
        description="Service name for tracing"
    )
    service_version: str = Field(
        default="1.0.0",
        min_length=1,
        max_length=50,
        description="Service version for tracing"
    )

    # Connection settings
    insecure: bool = Field(
        default=True,
        description="Use insecure connection (no TLS) - for local development",
    )
    timeout: int = Field(
        default=10, ge=1, le=60, description="Export timeout in seconds"
    )

    # Sampling
    sample_rate: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Trace sampling rate (0.0-1.0, where 1.0 = 100%)",
    )

    # Instrumentation toggles
    instrument_fastapi: bool = Field(
        default=True, description="Instrument FastAPI endpoints"
    )
    instrument_httpx: bool = Field(
        default=True, description="Instrument HTTPX client"
    )
    instrument_sqlalchemy: bool = Field(
        default=True, description="Instrument SQLAlchemy"
    )
    instrument_asyncpg: bool = Field(
        default=True, description="Instrument asyncpg PostgreSQL driver"
    )

    @model_validator(mode="after")
    def validate_enabled_requires_endpoint(self) -> "OtelSettings":
        """Validate that if tracing is enabled, an endpoint must be provided."""
        if self.enabled and not self.endpoint:
            raise ValueError("OTEL endpoint must be provided when tracing is enabled")
        return self

    model_config = SettingsConfigDict(
        env_prefix="OTEL_",
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
            return otel_source()

        return (init_settings, files_source, env_settings, dotenv_settings, file_secret_settings)

    @property
    def is_configured(self) -> bool:
        """Check if tracing is enabled and configured."""
        return self.enabled and self.endpoint is not None
