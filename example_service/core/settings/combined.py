"""Combined settings aggregator for backward compatibility.

This module provides a unified settings object that aggregates all modular settings.
Useful for files that need access to multiple settings domains.
"""

from __future__ import annotations

from functools import cached_property

from .app import AppSettings
from .auth import AuthSettings
from .logging_ import LoggingSettings
from .otel import OtelSettings
from .postgres import PostgresSettings
from .rabbit import RabbitSettings
from .redis import RedisSettings


class Settings:
    """Aggregated settings from all domains.

    Provides a single interface to access settings from all modules.
    Each settings domain is lazily loaded and cached.

    Example:
        ```python
        from example_service.core.settings import settings

        # Access app settings
        print(settings.debug)
        print(settings.service_name)

        # Access database settings
        print(settings.database_url)
        print(settings.pool_size)

        # Access OTel settings
        print(settings.enable_tracing)
        ```
    """

    @cached_property
    def _app(self) -> AppSettings:
        """Cached app settings."""
        return AppSettings()

    @cached_property
    def _db(self) -> PostgresSettings:
        """Cached database settings."""
        return PostgresSettings()

    @cached_property
    def _rabbit(self) -> RabbitSettings:
        """Cached RabbitMQ settings."""
        return RabbitSettings()

    @cached_property
    def _redis(self) -> RedisSettings:
        """Cached Redis settings."""
        return RedisSettings()

    @cached_property
    def _auth(self) -> AuthSettings:
        """Cached auth settings."""
        return AuthSettings()

    @cached_property
    def _logging(self) -> LoggingSettings:
        """Cached logging settings."""
        return LoggingSettings()

    @cached_property
    def _otel(self) -> OtelSettings:
        """Cached OpenTelemetry settings."""
        return OtelSettings()

    # App settings properties
    @property
    def service_name(self) -> str:
        """Service name."""
        return self._app.service_name

    @property
    def title(self) -> str:
        """API title."""
        return self._app.title

    @property
    def version(self) -> str:
        """API version."""
        return self._app.version

    @property
    def environment(self) -> str:
        """Environment name."""
        return self._app.environment

    @property
    def debug(self) -> bool:
        """Debug mode enabled."""
        return self._app.debug

    @property
    def docs_url(self) -> str | None:
        """Docs URL."""
        return self._app.docs_url

    @property
    def redoc_url(self) -> str | None:
        """ReDoc URL."""
        return self._app.redoc_url

    @property
    def openapi_url(self) -> str | None:
        """OpenAPI URL."""
        return self._app.openapi_url

    @property
    def disable_docs(self) -> bool:
        """Disable docs."""
        return self._app.disable_docs

    @property
    def root_path(self) -> str:
        """Root path."""
        return self._app.root_path

    @property
    def host(self) -> str:
        """Server host."""
        return self._app.host

    @property
    def port(self) -> int:
        """Server port."""
        return self._app.port

    @property
    def cors_origins(self) -> list[str]:
        """CORS origins."""
        return self._app.cors_origins

    @property
    def cors_allow_credentials(self) -> bool:
        """CORS allow credentials."""
        return self._app.cors_allow_credentials

    @property
    def cors_allow_methods(self) -> list[str]:
        """CORS allowed methods."""
        return self._app.cors_allow_methods

    @property
    def cors_allow_headers(self) -> list[str]:
        """CORS allowed headers."""
        return self._app.cors_allow_headers

    # Database settings properties (with database_ prefix for backward compat)
    @property
    def database_url(self) -> str | None:
        """Database URL."""
        return str(self._db.database_url) if self._db.database_url else None

    @property
    def database_pool_size(self) -> int:
        """Database pool size."""
        return self._db.pool_size

    @property
    def database_max_overflow(self) -> int:
        """Database max overflow."""
        return self._db.max_overflow

    @property
    def database_pool_timeout(self) -> int:
        """Database pool timeout."""
        return self._db.pool_timeout

    @property
    def database_pool_recycle(self) -> int:
        """Database pool recycle."""
        return self._db.pool_recycle

    @property
    def database_pool_pre_ping(self) -> bool:
        """Database pool pre-ping."""
        return self._db.pool_pre_ping

    @property
    def database_echo_sql(self) -> bool:
        """Echo SQL statements."""
        return self._db.echo_sql

    # OpenTelemetry settings properties
    @property
    def enable_tracing(self) -> bool:
        """Enable tracing."""
        return self._otel.enabled

    @property
    def otlp_endpoint(self) -> str | None:
        """OTLP endpoint."""
        return self._otel.endpoint

    @property
    def otlp_insecure(self) -> bool:
        """OTLP insecure connection."""
        return self._otel.insecure

    @property
    def otlp_timeout(self) -> int:
        """OTLP timeout."""
        return self._otel.timeout

    @property
    def sample_rate(self) -> float:
        """Trace sample rate."""
        return self._otel.sample_rate

    # Redis settings properties
    @property
    def redis_url(self) -> str | None:
        """Redis URL."""
        return str(self._redis.redis_url) if self._redis.redis_url else None

    @property
    def redis_default_ttl(self) -> int:
        """Redis default TTL."""
        return self._redis.default_ttl

    @property
    def redis_pool_size(self) -> int:
        """Redis pool size."""
        return self._redis.pool_size

    # RabbitMQ settings properties
    @property
    def rabbitmq_url(self) -> str | None:
        """RabbitMQ URL."""
        return str(self._rabbit.rabbitmq_url) if self._rabbit.rabbitmq_url else None

    @property
    def rabbit_queue(self) -> str:
        """RabbitMQ queue name."""
        return self._rabbit.queue

    # Auth settings properties
    @property
    def auth_service_url(self) -> str | None:
        """Auth service URL."""
        return str(self._auth.service_url) if self._auth.service_url else None

    @property
    def auth_token_cache_ttl(self) -> int:
        """Auth token cache TTL."""
        return self._auth.token_cache_ttl


# Global settings instance
settings = Settings()
