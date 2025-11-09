"""Application settings using Pydantic Settings."""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with environment variable support.

    Settings are loaded from environment variables with EXAMPLE_SERVICE_ prefix.
    For local development, create a .env file in the project root.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_prefix="EXAMPLE_SERVICE_",
    )

    # Service configuration
    service_name: str = Field(default="example-service", description="Service name")
    service_port: int = Field(default=8000, description="Service HTTP port")
    debug: bool = Field(default=False, description="Debug mode")
    log_level: str = Field(default="INFO", description="Logging level")

    # Database configuration (optional)
    database_url: str | None = Field(
        default=None, description="Database connection URL"
    )
    database_pool_size: int = Field(default=20, description="Database pool size")
    database_max_overflow: int = Field(
        default=10, description="Database max overflow"
    )

    # Cache configuration (optional)
    redis_url: str | None = Field(default=None, description="Redis connection URL")
    cache_ttl: int = Field(default=3600, description="Default cache TTL in seconds")

    # External services (optional)
    auth_service_url: str | None = Field(
        default=None, description="Authentication service URL"
    )
    confd_service_url: str | None = Field(
        default=None, description="Configuration service URL"
    )

    # Observability
    enable_metrics: bool = Field(default=True, description="Enable Prometheus metrics")
    enable_tracing: bool = Field(default=False, description="Enable OpenTelemetry tracing")
    otlp_endpoint: str | None = Field(
        default=None, description="OpenTelemetry OTLP endpoint (e.g., http://tempo:4317)"
    )
    otlp_insecure: bool = Field(
        default=True, description="Use insecure connection for OTLP"
    )

    # Message Broker (RabbitMQ)
    rabbitmq_url: str | None = Field(
        default=None, description="RabbitMQ connection URL (amqp://user:pass@host:port)"
    )
    rabbitmq_exchange: str = Field(
        default="example_exchange", description="RabbitMQ exchange name"
    )
    rabbitmq_queue_prefix: str = Field(
        default="example", description="RabbitMQ queue name prefix"
    )

    # Task Queue (Taskiq)
    taskiq_broker_url: str | None = Field(
        default=None, description="Taskiq broker URL (redis://host:port or amqp://...)"
    )
    taskiq_result_backend: str | None = Field(
        default=None, description="Taskiq result backend URL"
    )

    # External Auth
    auth_token_url: str | None = Field(
        default=None, description="External auth token validation URL"
    )
    auth_token_cache_ttl: int = Field(
        default=300, description="Auth token cache TTL in seconds"
    )


# Global settings instance
settings = Settings()
