"""Redis cache configuration settings."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote, urlparse

from pydantic import Field, SecretStr, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ._sanitizers import sanitize_inline_numeric
from .yaml_sources import create_redis_yaml_source


class RedisSettings(BaseSettings):
    """Redis cache and session storage settings.

    Environment variables use REDIS_ prefix.
    Example: REDIS_URL="redis://localhost:6379/0"

    Supports bidirectional configuration:
    1. Provide REDIS_URL → components are parsed automatically
    2. Provide components (host, port, etc.) → URL is built automatically
    """

    # ──────────────────────────────────────────────────────────────
    # Connection configuration (bidirectional)
    # ──────────────────────────────────────────────────────────────

    redis_url: str | None = Field(
        default=None,
        alias="REDIS_URL",
        description="Redis connection URL (redis://[username:password@]host:port/db). If provided, overrides component fields.",
    )

    # Component fields (populated from URL or used to build URL)
    host: str = Field(
        default="localhost",
        description="Redis server hostname or IP address",
    )

    port: int = Field(
        default=6379,
        ge=1,
        le=65535,
        description="Redis server port",
    )

    db: int = Field(
        default=0,
        ge=0,
        le=15,
        description="Redis database number (0-15)",
    )

    username: str | None = Field(
        default=None,
        description="Redis username (Redis 6+ ACL)",
    )

    password: SecretStr | None = Field(
        default=None,
        description="Redis password for authentication",
    )

    # ──────────────────────────────────────────────────────────────
    # Connection pool settings
    # ──────────────────────────────────────────────────────────────

    max_connections: int = Field(
        default=50,
        ge=1,
        le=1000,
        description="Maximum Redis connection pool size",
    )

    socket_timeout: float = Field(
        default=5.0,
        ge=0.1,
        le=30.0,
        description="Redis socket timeout in seconds (for operations)",
    )

    socket_connect_timeout: float = Field(
        default=5.0,
        ge=0.1,
        le=30.0,
        description="Redis socket connection timeout in seconds (initial connection)",
    )

    socket_keepalive: bool = Field(
        default=True,
        description="Enable TCP keepalive on Redis connections",
    )

    # ──────────────────────────────────────────────────────────────
    # SSL/TLS settings
    # ──────────────────────────────────────────────────────────────

    ssl_enabled: bool = Field(
        default=False,
        description="Enable SSL/TLS for Redis connection (use rediss:// scheme)",
    )

    ssl_cert_reqs: Literal["none", "optional", "required"] = Field(
        default="required",
        description="SSL certificate verification requirement",
    )

    ssl_ca_certs: Path | None = Field(
        default=None,
        description="Path to CA certificate bundle for SSL verification",
    )

    # ──────────────────────────────────────────────────────────────
    # Cache TTL settings
    # ──────────────────────────────────────────────────────────────

    default_ttl: int = Field(
        default=3600,
        ge=0,
        description="Default cache TTL in seconds (1 hour)",
    )

    auth_token_ttl: int = Field(
        default=300,
        ge=0,
        description="Auth token cache TTL in seconds (5 minutes)",
    )

    # ──────────────────────────────────────────────────────────────
    # Retry and resilience settings
    # ──────────────────────────────────────────────────────────────

    max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum retry attempts for failed operations",
    )

    retry_delay: float = Field(
        default=0.5,
        ge=0.1,
        le=5.0,
        description="Initial retry delay in seconds (with exponential backoff)",
    )

    # ──────────────────────────────────────────────────────────────
    # Health check and startup settings
    # ──────────────────────────────────────────────────────────────

    health_check_timeout: float = Field(
        default=2.0,
        ge=0.1,
        le=10.0,
        description="Health check timeout in seconds",
    )

    health_check_interval: int = Field(
        default=30,
        ge=0,
        le=300,
        description="Health check interval in seconds (0 to disable)",
    )

    startup_retry_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Number of connection retry attempts during startup",
    )

    startup_retry_delay: float = Field(
        default=1.0,
        ge=0.1,
        le=10.0,
        description="Initial delay between startup retry attempts in seconds",
    )

    startup_require_cache: bool = Field(
        default=False,
        description="Whether to fail application startup if Redis is unavailable (False = degraded mode)",
    )

    # ──────────────────────────────────────────────────────────────
    # Application-specific settings
    # ──────────────────────────────────────────────────────────────

    key_prefix: str = Field(
        default="example-service:",
        min_length=1,
        max_length=100,
        pattern=r"^[a-zA-Z0-9_-]+:?$",
        description="Prefix for all cache keys (alphanumeric, hyphens, underscores, optional trailing colon)",
    )

    # ──────────────────────────────────────────────────────────────
    # Validators and computed fields
    # ──────────────────────────────────────────────────────────────

    @model_validator(mode="after")
    def _apply_url(self) -> "RedisSettings":
        """Parse redis_url into component fields if provided.

        This enables bidirectional configuration: you can provide a URL and the
        components (host, port, etc.) are automatically populated.
        """
        if self.redis_url:
            parsed = urlparse(self.redis_url)

            # Parse components from URL
            if parsed.hostname:
                object.__setattr__(self, "host", parsed.hostname)
            if parsed.port:
                object.__setattr__(self, "port", parsed.port)
            if parsed.path and len(parsed.path) > 1:
                # Extract DB number from path (e.g., "/0" -> 0)
                try:
                    db_num = int(parsed.path.lstrip("/"))
                    object.__setattr__(self, "db", db_num)
                except (ValueError, AttributeError):
                    pass
            if parsed.username:
                object.__setattr__(self, "username", parsed.username)
            if parsed.password:
                object.__setattr__(self, "password", SecretStr(parsed.password))

            # Detect SSL from scheme
            if parsed.scheme == "rediss":
                object.__setattr__(self, "ssl_enabled", True)

        return self

    @computed_field
    @property
    def url(self) -> str:
        """Build Redis URL from component fields.

        Returns URL in format: redis[s]://[username:password@]host:port/db
        """
        scheme = "rediss" if self.ssl_enabled else "redis"

        # Build auth portion if credentials exist
        auth = ""
        if self.username or self.password:
            username_part = quote(self.username) if self.username else ""
            password_part = quote(self.password.get_secret_value()) if self.password else ""

            if username_part and password_part:
                auth = f"{username_part}:{password_part}@"
            elif password_part:
                auth = f":{password_part}@"

        return f"{scheme}://{auth}{self.host}:{self.port}/{self.db}"

    @computed_field
    @property
    def is_configured(self) -> bool:
        """Check if Redis is configured.

        Redis is considered configured if either redis_url is provided
        or host is non-default.
        """
        return self.redis_url is not None or self.host != "localhost"

    @field_validator("default_ttl", "auth_token_ttl", mode="before")
    @classmethod
    def _normalize_ttl(cls, value: Any) -> Any:
        """Allow numeric env vars with inline comments (e.g., "3600  # 1 hour")."""
        return sanitize_inline_numeric(value)

    # ──────────────────────────────────────────────────────────────
    # Helper methods
    # ──────────────────────────────────────────────────────────────

    def build_url(
        self,
        *,
        with_db: bool = True,
        with_auth: bool = True,
    ) -> str:
        """Build Redis URL with optional components.

        Args:
            with_db: Include database number in URL.
            with_auth: Include authentication in URL.

        Returns:
            Redis URL string.
        """
        scheme = "rediss" if self.ssl_enabled else "redis"

        # Build auth portion
        auth = ""
        if with_auth and (self.username or self.password):
            username_part = quote(self.username) if self.username else ""
            password_part = quote(self.password.get_secret_value()) if self.password else ""

            if username_part and password_part:
                auth = f"{username_part}:{password_part}@"
            elif password_part:
                auth = f":{password_part}@"

        # Build DB portion
        db_part = f"/{self.db}" if with_db else ""

        return f"{scheme}://{auth}{self.host}:{self.port}{db_part}"

    def connection_pool_kwargs(self) -> dict[str, Any]:
        """Return kwargs for redis.asyncio.ConnectionPool.from_url().

        Returns:
            Dictionary suitable for unpacking into ConnectionPool.from_url(**kwargs).
        """
        kwargs: dict[str, Any] = {
            "max_connections": self.max_connections,
            "socket_timeout": self.socket_timeout,
            "socket_connect_timeout": self.socket_connect_timeout,
            "socket_keepalive": self.socket_keepalive,
            "decode_responses": True,
            "encoding": "utf-8",
        }

        # Add health check interval if configured
        if self.health_check_interval > 0:
            kwargs["health_check_interval"] = self.health_check_interval

        # Add SSL settings if enabled
        if self.ssl_enabled:
            import ssl

            ssl_context = ssl.create_default_context()

            # Configure certificate verification
            if self.ssl_cert_reqs == "none":
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
            elif self.ssl_cert_reqs == "optional":
                ssl_context.verify_mode = ssl.CERT_OPTIONAL
            else:  # required
                ssl_context.verify_mode = ssl.CERT_REQUIRED

            # Load custom CA certs if provided
            if self.ssl_ca_certs and self.ssl_ca_certs.exists():
                ssl_context.load_verify_locations(cafile=str(self.ssl_ca_certs))

            kwargs["ssl"] = ssl_context

        return kwargs

    def get_url(self) -> str:
        """Get Redis URL string (legacy compatibility method).

        Use the .url computed field instead for new code.

        Returns:
            Redis URL string.

        Raises:
            ValueError: If Redis is not configured.
        """
        if not self.is_configured:
            raise ValueError("Redis URL not configured")
        return self.url

    def get_prefixed_key(self, key: str) -> str:
        """Get cache key with configured prefix.

        Args:
            key: Base cache key.

        Returns:
            Prefixed cache key.
        """
        return f"{self.key_prefix}{key}"

    model_config = SettingsConfigDict(
        env_prefix="REDIS_",
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
            create_redis_yaml_source(settings_cls),
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )
