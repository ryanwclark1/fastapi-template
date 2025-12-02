"""RabbitMQ messaging settings for FastStream.

Supports both URI-based configuration and individual component fields.
If a full AMQP URI is provided, it's parsed to populate the component fields.
Conversely, if components are provided, an AMQP URI is generated.
"""

from __future__ import annotations

from typing import Any, Literal
from urllib.parse import quote, unquote, urlparse

from pydantic import Field, SecretStr, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .yaml_sources import create_rabbit_yaml_source

# Exchange type options for RabbitMQ
ExchangeType = Literal["headers", "topic", "direct", "fanout"]


class RabbitSettings(BaseSettings):
    """RabbitMQ connection and queue settings.

    Environment variables use RABBIT_ prefix.

    Supports two configuration modes:
    1. Full URI: RABBIT_AMQP_URI="amqp://user:pass@host:5672/vhost"
    2. Components: RABBIT_HOST, RABBIT_PORT, RABBIT_USERNAME, etc.

    If AMQP_URI is set, it's parsed to populate individual fields.
    Individual field overrides still take precedence if set explicitly.

    Used by FastStream for event-driven messaging and Taskiq for background tasks.
    """

    # ─────────────────────────────────────────────────────
    # Enable/disable toggle
    # ─────────────────────────────────────────────────────
    enabled: bool = Field(
        default=True,
        description="Enable RabbitMQ integration for this service.",
    )

    # ─────────────────────────────────────────────────────
    # URI override (parsed into component fields)
    # ─────────────────────────────────────────────────────
    amqp_uri: str | None = Field(
        default=None,
        alias="AMQP_URI",
        description="Optional full AMQP URI; overrides host/port/user/pass/vhost.",
    )

    # ─────────────────────────────────────────────────────
    # Connection parameters (components)
    # ─────────────────────────────────────────────────────
    host: str = Field(
        default="localhost",
        min_length=1,
        max_length=255,
        description="RabbitMQ hostname or IP address.",
    )
    port: int = Field(
        default=5672,
        ge=1,
        le=65535,
        description="RabbitMQ port (5672, or 5671 when using TLS).",
    )
    username: str = Field(
        default="guest",
        min_length=1,
        max_length=100,
        description="RabbitMQ username.",
    )
    password: SecretStr = Field(
        default=SecretStr("guest"),
        description="RabbitMQ password.",
    )
    vhost: str = Field(
        default="/",
        description="RabbitMQ virtual host (with or without leading slash).",
    )

    # ─────────────────────────────────────────────────────
    # Connection management
    # ─────────────────────────────────────────────────────
    connection_name: str = Field(
        default="example-service",
        min_length=1,
        max_length=100,
        description="Connection name shown in RabbitMQ management UI.",
    )
    pool_size: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Connection pool size.",
    )
    heartbeat: int = Field(
        default=60,
        ge=0,
        le=3600,
        description="Heartbeat interval in seconds (0 disables heartbeats).",
    )

    # ─────────────────────────────────────────────────────
    # Retry / resilience
    # ─────────────────────────────────────────────────────
    retry_attempts: int = Field(
        default=5,
        ge=0,
        le=20,
        description="Number of connection retry attempts before failing.",
    )
    retry_backoff: float = Field(
        default=1.0,
        gt=0,
        le=60.0,
        description="Seconds to wait between connection retries.",
    )

    # ─────────────────────────────────────────────────────
    # Connection timeout
    # ─────────────────────────────────────────────────────
    connection_timeout: float = Field(
        default=10.0,
        ge=1.0,
        le=300.0,
        description="Connection timeout in seconds for initial RabbitMQ connection.",
    )

    # ─────────────────────────────────────────────────────
    # Startup behavior
    # ─────────────────────────────────────────────────────
    startup_require_rabbit: bool = Field(
        default=False,
        description=(
            "If True, application startup fails if RabbitMQ is unavailable. "
            "If False, application starts in degraded mode without messaging."
        ),
    )

    # ─────────────────────────────────────────────────────
    # Exchange configuration
    # ─────────────────────────────────────────────────────
    exchange_name: str = Field(
        default="example-service",
        min_length=1,
        max_length=100,
        pattern=r"^[a-zA-Z0-9_.-]+$",
        description="Default exchange name (alphanumeric, hyphens, underscores, dots).",
    )
    exchange_type: ExchangeType = Field(
        default="topic",
        description="Exchange type (headers, topic, direct, fanout).",
    )

    # ─────────────────────────────────────────────────────
    # Queue configuration
    # ─────────────────────────────────────────────────────
    queue_prefix: str = Field(
        default="example-service",
        min_length=1,
        max_length=100,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Prefix for queue names (alphanumeric, hyphens, underscores only).",
    )
    default_queue: str = Field(
        default="tasks",
        min_length=1,
        max_length=100,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Default queue name (alphanumeric, hyphens, underscores only).",
    )

    # ─────────────────────────────────────────────────────
    # Consumer configuration
    # ─────────────────────────────────────────────────────
    prefetch_count: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="QoS prefetch count for consumers.",
    )
    max_consumers: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum number of consumer workers.",
    )

    # ─────────────────────────────────────────────────────
    # Reliability
    # ─────────────────────────────────────────────────────
    publisher_confirms: bool = Field(
        default=True,
        description="Enable publisher confirms for reliable delivery.",
    )

    # ─────────────────────────────────────────────────────
    # Graceful shutdown
    # ─────────────────────────────────────────────────────
    graceful_timeout: float = Field(
        default=15.0,
        ge=0.1,
        le=300.0,
        description="Graceful shutdown timeout in seconds.",
    )

    # ─────────────────────────────────────────────────────
    # TLS / SSL
    # ─────────────────────────────────────────────────────
    ssl_enabled: bool = Field(
        default=False,
        description="Enable TLS/SSL for AMQP connections.",
    )
    ssl_ca_file: str | None = Field(
        default=None,
        description="Path to CA certificate when TLS is enabled.",
    )
    ssl_cert_file: str | None = Field(
        default=None,
        description="Path to client certificate when TLS is enabled.",
    )
    ssl_key_file: str | None = Field(
        default=None,
        description="Path to client private key when TLS is enabled.",
    )

    model_config = SettingsConfigDict(
        env_prefix="RABBIT_",
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
            create_rabbit_yaml_source(settings_cls),
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )

    # ─────────────────────────────────────────────────────
    # URI parsing validator
    # ─────────────────────────────────────────────────────
    @model_validator(mode="after")
    def _apply_uri(self) -> RabbitSettings:
        """Populate connection components from AMQP URI if provided.

        Parses the URI and sets host, port, username, password, and vhost.
        Uses object.__setattr__ because the model is frozen.
        """
        if not self.amqp_uri:
            return self

        parsed = urlparse(self.amqp_uri)

        if parsed.hostname:
            object.__setattr__(self, "host", parsed.hostname)
        if parsed.port:
            object.__setattr__(self, "port", parsed.port)

        if parsed.username:
            object.__setattr__(self, "username", unquote(parsed.username))
        if parsed.password:
            object.__setattr__(
                self,
                "password",
                SecretStr(unquote(parsed.password)),
            )

        if parsed.path and parsed.path != "/":
            vhost = parsed.path.lstrip("/")
            object.__setattr__(self, "vhost", vhost)

        # If scheme is amqps, enable SSL unless explicitly disabled
        if parsed.scheme == "amqps":
            object.__setattr__(self, "ssl_enabled", True)

        return self

    # ─────────────────────────────────────────────────────
    # Computed properties
    # ─────────────────────────────────────────────────────
    @computed_field  # type: ignore[prop-decorator]
    @property
    def url(self) -> str:
        """Return the effective AMQP URI, derived from component settings.

        This computed field builds a properly escaped AMQP URI from the
        individual connection parameters. Useful when you configure via
        components but need a URI string for a library.
        """
        user = quote(self.username, safe="") if self.username else ""
        pwd_raw = self.password.get_secret_value()
        pwd = quote(pwd_raw, safe="") if pwd_raw else ""

        auth = ""
        if user:
            auth = user
            if pwd:
                auth += f":{pwd}"
            auth += "@"

        # Handle vhost encoding
        vhost = self.vhost.lstrip("/")
        vhost_part = f"/{quote(vhost, safe='')}" if vhost else "/"

        scheme = "amqps" if self.ssl_enabled else "amqp"
        return f"{scheme}://{auth}{self.host}:{self.port}{vhost_part}"

    @property
    def is_configured(self) -> bool:
        """Check if RabbitMQ is enabled and has valid connection info."""
        return self.enabled and bool(self.host)

    # ─────────────────────────────────────────────────────
    # Helper methods
    # ─────────────────────────────────────────────────────
    def get_url(self) -> str:
        """Get RabbitMQ URL string.

        Returns:
            The computed AMQP URI.

        Raises:
            ValueError: If RabbitMQ is not enabled.
        """
        if not self.enabled:
            raise ValueError("RabbitMQ is not enabled")
        return self.url

    def get_prefixed_queue(self, queue_name: str) -> str:
        """Get queue name with prefix.

        Args:
            queue_name: The base queue name.

        Returns:
            The queue name prefixed with queue_prefix.
        """
        return f"{self.queue_prefix}.{queue_name}"

    def get_full_queue_name(self) -> str:
        """Get the full default queue name with prefix."""
        return self.get_prefixed_queue(self.default_queue)

    def to_connection_config(self) -> dict[str, Any]:
        """Convert to a connection configuration dictionary.

        Useful for passing to RabbitMQ client libraries.

        Returns:
            Dictionary with connection parameters.
        """
        config: dict[str, Any] = {
            "host": self.host,
            "port": self.port,
            "login": self.username,
            "password": self.password.get_secret_value(),
            "virtualhost": self.vhost,
            "heartbeat": self.heartbeat,
            "connection_name": self.connection_name,
        }

        if self.ssl_enabled:
            config["ssl"] = True
            if self.ssl_ca_file:
                config["ssl_ca_file"] = self.ssl_ca_file
            if self.ssl_cert_file:
                config["ssl_cert_file"] = self.ssl_cert_file
            if self.ssl_key_file:
                config["ssl_key_file"] = self.ssl_key_file

        return config
