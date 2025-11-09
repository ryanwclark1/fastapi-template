"""OpenTelemetry tracing configuration."""

from __future__ import annotations

from pydantic import Field
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
    endpoint: str | None = Field(
        default=None,
        description="OTLP gRPC endpoint (e.g., http://tempo:4317, http://jaeger:4317)",
    )

    # Service identification
    service_name: str = Field(
        default="example-service", description="Service name for tracing"
    )
    service_version: str = Field(
        default="1.0.0", description="Service version for tracing"
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

    model_config = SettingsConfigDict(
        env_prefix="OTEL_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        frozen=True,
    )

    @property
    def is_configured(self) -> bool:
        """Check if tracing is enabled and configured."""
        return self.enabled and self.endpoint is not None
