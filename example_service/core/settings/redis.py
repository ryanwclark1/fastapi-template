"""Redis cache configuration settings."""

from __future__ import annotations

from pydantic import Field, RedisDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from .sources import db_source  # Redis settings can share db_source or have their own


class RedisSettings(BaseSettings):
    """Redis cache and session storage settings.

    Environment variables use REDIS_ prefix.
    Example: REDIS_URL="redis://localhost:6379/0"
    """

    # Redis connection
    redis_url: RedisDsn | None = Field(
        default=None,
        alias="REDIS_URL",
        description="Redis connection URL (redis://host:port/db)",
    )

    # Cache TTL settings
    default_ttl: int = Field(
        default=3600, ge=0, description="Default cache TTL in seconds (1 hour)"
    )
    auth_token_ttl: int = Field(
        default=300, ge=0, description="Auth token cache TTL in seconds (5 minutes)"
    )

    # Connection pool settings
    pool_size: int = Field(
        default=10, ge=1, le=100, description="Connection pool size"
    )
    pool_timeout: int = Field(
        default=10, ge=1, le=60, description="Connection timeout in seconds"
    )

    # Retry settings
    max_retries: int = Field(
        default=3, ge=0, le=10, description="Maximum retry attempts"
    )
    retry_delay: float = Field(
        default=0.5, ge=0.1, le=5.0, description="Initial retry delay in seconds"
    )

    # Key prefix for namespacing
    key_prefix: str = Field(
        default="example-service:", description="Prefix for all cache keys"
    )

    # Optional separate password
    password: SecretStr | None = Field(
        default=None, description="Redis password (if not in URL)"
    )

    model_config = SettingsConfigDict(
        env_prefix="REDIS_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        frozen=True,
        populate_by_name=True,
    )

    @property
    def is_configured(self) -> bool:
        """Check if Redis is configured."""
        return self.redis_url is not None

    def get_url(self) -> str:
        """Get Redis URL string."""
        if not self.redis_url:
            raise ValueError("Redis URL not configured")
        return str(self.redis_url)

    def get_prefixed_key(self, key: str) -> str:
        """Get cache key with prefix."""
        return f"{self.key_prefix}{key}"
