"""PostgreSQL database settings with psycopg3 support.

Supports both DSN-based configuration and individual component fields.
If a full DSN is provided, it's parsed to populate the component fields.
Conversely, if components are provided, a DSN is generated.

Supports both:
- SQLAlchemy 2.x + psycopg3 (async ORM path) with postgresql+psycopg://
- psycopg3 native pool (driver-only path) with postgresql://
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus, unquote, urlparse

from pydantic import Field, SecretStr, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .yaml_sources import create_db_yaml_source


class PostgresSettings(BaseSettings):
    """PostgreSQL connection and pool settings.

    Environment variables use DB_ prefix.

    Supports two configuration modes:
    1. Full DSN: DB_DSN="postgresql+psycopg://user:pass@host:5432/dbname"
    2. Components: DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME, etc.

    If DSN is set, it's parsed to populate individual fields.
    Individual field overrides still take precedence if set explicitly.

    For Unix sockets: postgresql+psycopg://user:pass@/dbname?host=/var/run/postgresql
    For SSL: Add ?sslmode=require to the URL
    """

    # ─────────────────────────────────────────────────────
    # Enable/disable toggle
    # ─────────────────────────────────────────────────────
    enabled: bool = Field(
        default=True,
        description="Enable database integration. Set to False for tests or stateless APIs.",
    )

    # ─────────────────────────────────────────────────────
    # Optional DSN Override
    # ─────────────────────────────────────────────────────
    dsn: str | None = Field(
        default=None,
        alias="DATABASE_URL",
        description=(
            "Optional complete SQLAlchemy database URL. "
            "If set, it's parsed to populate component fields."
        ),
    )

    # ─────────────────────────────────────────────────────
    # Connection Parameters (components)
    # ─────────────────────────────────────────────────────
    host: str = Field(
        default="localhost",
        min_length=1,
        max_length=255,
        description="PostgreSQL server hostname or IP address.",
    )
    port: int = Field(
        default=5432,
        ge=1,
        le=65535,
        description="PostgreSQL server port.",
    )
    user: str = Field(
        default="postgres",
        min_length=1,
        max_length=100,
        description="Database username.",
    )
    password: SecretStr = Field(
        default=SecretStr("postgres"),
        description="Database password.",
    )
    name: str = Field(
        default="example_service",
        min_length=1,
        max_length=100,
        description="Database name.",
    )
    driver: str = Field(
        default="psycopg",
        description="SQLAlchemy driver (e.g., 'psycopg' for async PostgreSQL, 'psycopg2' for sync).",
    )
    application_name: str = Field(
        default="example-service",
        min_length=1,
        max_length=100,
        description="Application name reported to PostgreSQL (visible in pg_stat_activity).",
    )

    # ─────────────────────────────────────────────────────
    # SQLAlchemy Connection Pool Configuration
    # ─────────────────────────────────────────────────────
    pool_size: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum number of database connections in the pool.",
    )
    max_overflow: int = Field(
        default=10,
        ge=0,
        le=100,
        description="Maximum number of connections above pool_size (temporary burst).",
    )
    pool_pre_ping: bool = Field(
        default=True,
        description="Enable connection health checks before use.",
    )
    pool_timeout: float = Field(
        default=30.0,
        ge=0.1,
        le=300.0,
        description="Timeout (seconds) when acquiring a connection from the pool.",
    )
    pool_recycle: int = Field(
        default=1800,
        ge=0,
        le=86400,
        description="Recycle connections after N seconds (prevents stale connections).",
    )
    connect_timeout: float = Field(
        default=5.0,
        ge=0.1,
        le=60.0,
        description="Database connection timeout in seconds.",
    )
    echo: bool = Field(
        default=False,
        description="Echo SQL statements to logs (debug only).",
    )

    # ─────────────────────────────────────────────────────
    # psycopg3 Native Pool Settings (driver-only path)
    # ─────────────────────────────────────────────────────
    pg_min_size: int = Field(
        default=1,
        ge=0,
        le=100,
        description="psycopg_pool minimum pool size.",
    )
    pg_max_size: int = Field(
        default=10,
        ge=1,
        le=100,
        description="psycopg_pool maximum pool size.",
    )
    pg_max_idle: int | None = Field(
        default=None,
        description="psycopg_pool max idle seconds (None = no limit).",
    )
    pg_timeout: float = Field(
        default=30.0,
        ge=0.1,
        le=300.0,
        description="psycopg_pool acquire timeout in seconds.",
    )

    # ─────────────────────────────────────────────────────
    # Health Check / Startup Behaviour
    # ─────────────────────────────────────────────────────
    health_checks_enabled: bool = Field(
        default=False,
        description=(
            "Enable database connectivity checks in health endpoints. "
            "Disable in development/tests to avoid touching real databases."
        ),
    )
    health_check_timeout: float = Field(
        default=2.0,
        ge=0.1,
        le=30.0,
        description="Timeout (seconds) used for database health checks.",
    )
    startup_retry_attempts: int = Field(
        default=3,
        ge=1,
        le=20,
        description="Number of retry attempts during service startup.",
    )
    startup_retry_delay: float = Field(
        default=2.0,
        ge=0.1,
        le=60.0,
        description="Delay (seconds) between startup retry attempts.",
    )
    startup_retry_timeout: float = Field(
        default=60.0,
        ge=5.0,
        le=300.0,
        description="Maximum total time (seconds) for startup retry attempts (stop_after_delay).",
    )
    startup_require_db: bool = Field(
        default=True,
        description=(
            "If True, service fails fast when database is unavailable at startup. "
            "If False, service starts but reports unhealthy until DB is available."
        ),
    )

    model_config = SettingsConfigDict(
        env_prefix="DB_",
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
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        """Customize settings source precedence: init > yaml > env > dotenv > secrets."""
        return (
            init_settings,
            create_db_yaml_source(settings_cls),
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )

    # ─────────────────────────────────────────────────────
    # Validators
    # ─────────────────────────────────────────────────────
    @field_validator("pg_max_idle", mode="before")
    @classmethod
    def _normalize_pg_max_idle(cls, value: Any) -> Any:
        """Allow 'null' or empty env values to disable idle timeout."""
        if isinstance(value, str) and value.strip().lower() in {"null", ""}:
            return None
        return value

    @model_validator(mode="after")
    def _apply_dsn(self) -> PostgresSettings:
        """Populate connection components from DSN if provided.

        Parses the DSN and sets host, port, user, password, and name.
        Uses object.__setattr__ because the model is frozen.
        """
        if not self.dsn:
            return self

        parsed = urlparse(self.dsn)

        if parsed.hostname:
            object.__setattr__(self, "host", parsed.hostname)
        if parsed.port:
            object.__setattr__(self, "port", parsed.port)

        if parsed.username:
            object.__setattr__(self, "user", unquote(parsed.username))
        if parsed.password:
            object.__setattr__(
                self,
                "password",
                SecretStr(unquote(parsed.password)),
            )

        # Database name is the path without leading slash
        if parsed.path and parsed.path != "/":
            db_name = parsed.path.lstrip("/")
            object.__setattr__(self, "name", db_name)

        # Extract driver from scheme if present (e.g., postgresql+psycopg)
        if parsed.scheme and "+" in parsed.scheme:
            driver = parsed.scheme.split("+")[1]
            object.__setattr__(self, "driver", driver)

        return self

    # ─────────────────────────────────────────────────────
    # Computed Properties
    # ─────────────────────────────────────────────────────
    @computed_field  # type: ignore[misc]
    @property
    def url(self) -> str:
        """SQLAlchemy database URL (async by default for psycopg).

        Returns:
            SQLAlchemy-compatible database URL built from component fields.
            Includes application_name and async flag for psycopg driver.
        """
        safe_password = quote_plus(self.password.get_secret_value())
        safe_app_name = quote_plus(self.application_name)

        base = (
            f"postgresql+{self.driver}://{self.user}:{safe_password}"
            f"@{self.host}:{self.port}/{self.name}"
        )

        params: list[str] = [f"application_name={safe_app_name}"]

        # Note: psycopg3 async mode is determined by the driver scheme (postgresql+psycopg://),
        # NOT by an async_=1 query parameter. The async_=1 parameter was used by asyncpg.
        # For psycopg3, the async behavior is automatic when using create_async_engine.

        return base + "?" + "&".join(params)

    @computed_field  # type: ignore[misc]
    @property
    def sync_url(self) -> str:
        """SQLAlchemy database URL for synchronous operations.

        Returns:
            SQLAlchemy-compatible database URL without async flag.
        """
        safe_password = quote_plus(self.password.get_secret_value())
        safe_app_name = quote_plus(self.application_name)

        base = (
            f"postgresql+{self.driver}://{self.user}:{safe_password}"
            f"@{self.host}:{self.port}/{self.name}"
        )

        return base + f"?application_name={safe_app_name}"

    @property
    def psycopg_url(self) -> str:
        """psycopg-native URL (without SQLAlchemy driver specifier).

        Returns:
            PostgreSQL URL suitable for psycopg3 native pool.
        """
        safe_password = quote_plus(self.password.get_secret_value())
        return f"postgresql://{self.user}:{safe_password}@{self.host}:{self.port}/{self.name}"

    @property
    def is_configured(self) -> bool:
        """Check if database is configured with valid connection info."""
        return self.enabled and bool(self.host and self.name)

    # ─────────────────────────────────────────────────────
    # DSN Builder with Overrides
    # ─────────────────────────────────────────────────────
    def build_dsn(
        self,
        *,
        app_name: str | None = None,
        async_enabled: bool | None = None,
        include_driver: bool = True,
    ) -> str:
        """Build a SQLAlchemy DSN with optional overrides.

        Args:
            app_name: Optional application name override.
            async_enabled: Override whether the connection should be async.
                If None, inferred from driver (True for psycopg, False for psycopg2).
            include_driver: Include driver in scheme (True for SQLAlchemy, False for native).

        Returns:
            SQLAlchemy-compatible database URL.
        """
        safe_password = quote_plus(self.password.get_secret_value())
        safe_app = quote_plus(app_name or self.application_name)

        driver = self.driver
        if include_driver and async_enabled is not None:
            driver = "psycopg" if async_enabled else "psycopg2"

        if include_driver:
            scheme = f"postgresql+{driver}"
        else:
            scheme = "postgresql"

        base = f"{scheme}://{self.user}:{safe_password}@{self.host}:{self.port}/{self.name}"

        # Note: For psycopg3, async mode is determined by using create_async_engine,
        # not by a query parameter. The async_=1 parameter was used by asyncpg.
        # We keep the async_enabled parameter for API compatibility but don't use it
        # as a query parameter with psycopg3.

        params: list[str] = [f"application_name={safe_app}"]

        return base + "?" + "&".join(params)

    # ─────────────────────────────────────────────────────
    # Engine/Pool Configuration Helpers
    # ─────────────────────────────────────────────────────
    def sqlalchemy_engine_kwargs(self) -> dict[str, Any]:
        """Keyword arguments for create_async_engine / create_engine.

        Returns:
            Dict of engine keyword arguments (pool, echo, connect_args).

        Example:
            engine = create_async_engine(
                db_settings.url,
                **db_settings.sqlalchemy_engine_kwargs(),
            )
        """
        return {
            "pool_size": self.pool_size,
            "max_overflow": self.max_overflow,
            "pool_pre_ping": self.pool_pre_ping,
            "pool_timeout": self.pool_timeout,
            "pool_recycle": self.pool_recycle,
            "connect_args": {
                "connect_timeout": int(self.connect_timeout),
            },
            "echo": self.echo,
        }

    def pool_kwargs(self) -> dict[str, Any]:
        """Pool-related kwargs only (if you want to separate concerns).

        Returns:
            Dict with pool configuration only.
        """
        return {
            "pool_size": self.pool_size,
            "max_overflow": self.max_overflow,
            "pool_pre_ping": self.pool_pre_ping,
            "pool_timeout": self.pool_timeout,
            "pool_recycle": self.pool_recycle,
        }

    def psycopg_pool_kwargs(self) -> dict[str, Any]:
        """Keyword arguments for psycopg_pool.AsyncConnectionPool.

        Returns:
            Dict suitable for psycopg3 native pool configuration.

        Example:
            pool = AsyncConnectionPool(
                db_settings.psycopg_url,
                **db_settings.psycopg_pool_kwargs(),
            )
        """
        kwargs: dict[str, Any] = {
            "min_size": self.pg_min_size,
            "max_size": self.pg_max_size,
            "timeout": self.pg_timeout,
        }
        if self.pg_max_idle is not None:
            kwargs["max_idle"] = self.pg_max_idle
        return kwargs

    # ─────────────────────────────────────────────────────
    # Legacy Compatibility Methods
    # ─────────────────────────────────────────────────────
    def get_sqlalchemy_url(self) -> str:
        """Get SQLAlchemy-compatible URL string.

        Returns:
            The computed async SQLAlchemy URL.

        Note:
            Prefer using the `url` computed field directly.
        """
        return self.url

    def get_psycopg_url(self) -> str:
        """Get psycopg-native URL.

        Returns:
            PostgreSQL URL without SQLAlchemy driver specifier.

        Note:
            Prefer using the `psycopg_url` property directly.
        """
        return self.psycopg_url
