"""RabbitMQ messaging settings for FastStream."""

from __future__ import annotations

from pydantic import AnyUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from .sources import rabbit_source


class RabbitSettings(BaseSettings):
    """RabbitMQ connection and queue settings.

    Environment variables use RABBIT_ prefix.
    Example: RABBIT_RABBITMQ_URL="amqp://guest:guest@localhost:5672/"

    Used by FastStream for event-driven messaging and Taskiq for background tasks.
    """

    # RabbitMQ connection
    rabbitmq_url: AnyUrl | None = Field(
        default=None,
        alias="RABBITMQ_URL",
        description="RabbitMQ AMQP URL (amqp://user:pass@host:port/vhost)",
    )

    # Queue configuration
    queue_prefix: str = Field(
        default="example-service",
        description="Prefix for queue names (enables multi-environment setup)",
    )
    exchange: str = Field(
        default="example-service", description="Default exchange name"
    )
    queue: str = Field(default="tasks_queue", description="Default queue name")

    # Consumer configuration
    prefetch_count: int = Field(
        default=100, ge=1, le=1000, description="Number of messages to prefetch"
    )
    max_consumers: int = Field(
        default=10, ge=1, le=100, description="Maximum number of consumer workers"
    )

    # Connection pool settings
    pool_size: int = Field(
        default=10, ge=1, le=100, description="Connection pool size"
    )

    # Graceful shutdown
    graceful_timeout: float = Field(
        default=15.0, ge=0.1, description="Graceful shutdown timeout in seconds"
    )

    # Optional separate credentials
    password: SecretStr | None = Field(
        default=None, description="RabbitMQ password (if not in URL)"
    )

    model_config = SettingsConfigDict(
        env_prefix="RABBIT_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        frozen=True,
        populate_by_name=True,
    )

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        """Customize settings source precedence."""

        def files_source(_):
            return rabbit_source()

        return (init_settings, files_source, env_settings, dotenv_settings, file_secret_settings)

    @property
    def is_configured(self) -> bool:
        """Check if RabbitMQ is configured."""
        return self.rabbitmq_url is not None

    def get_url(self) -> str:
        """Get RabbitMQ URL string."""
        if not self.rabbitmq_url:
            raise ValueError("RabbitMQ URL not configured")
        return str(self.rabbitmq_url)

    def get_prefixed_queue(self, queue_name: str) -> str:
        """Get queue name with prefix."""
        return f"{self.queue_prefix}.{queue_name}"
