"""PostgreSQL database settings with psycopg3 support."""

from __future__ import annotations

from pydantic import Field, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from .sources import db_source


class PostgresSettings(BaseSettings):
    """PostgreSQL connection and pool settings.

    Environment variables use DB_ prefix.
    Example: DB_DATABASE_URL="postgresql+psycopg://user:pass@localhost/db"

    Supports both:
    - SQLAlchemy 2.x + psycopg3 (async ORM path) with postgresql+psycopg://
    - psycopg3 native pool (driver-only path) with postgresql://

    For Unix sockets: postgresql+psycopg://user:pass@/dbname?host=/var/run/postgresql
    For SSL: Add ?sslmode=require to the URL
    """

    # Database connection
    database_url: PostgresDsn | None = Field(
        default=None,
        alias="DATABASE_URL",
        description="PostgreSQL connection URL (postgresql+psycopg://...)",
    )

    # SQLAlchemy connection pool settings (when using ORM)
    pool_size: int = Field(
        default=10, ge=1, le=100, description="Base connection pool size"
    )
    pool_min: int = Field(
        default=1, ge=0, le=100, description="Minimum pool size (kept for symmetry)"
    )
    max_overflow: int = Field(
        default=10,
        ge=0,
        le=100,
        description="Additional connections beyond pool_size",
    )
    pool_timeout: int = Field(
        default=30, ge=1, le=300, description="Seconds to wait for a connection"
    )
    pool_recycle: int = Field(
        default=1800,
        ge=0,
        description="Recycle connections after N seconds (prevents stale connections)",
    )
    pool_pre_ping: bool = Field(
        default=True, description="Test connections before using them"
    )
    echo_sql: bool = Field(default=False, description="Log all SQL statements")

    # psycopg3 native pool settings (when using driver-only path)
    pg_min_size: int = Field(default=1, ge=0, description="psycopg_pool min size")
    pg_max_size: int = Field(default=10, ge=1, description="psycopg_pool max size")
    pg_max_idle: int | None = Field(
        default=None, description="psycopg_pool max idle seconds"
    )
    pg_timeout: float = Field(
        default=30.0, ge=0.1, description="psycopg_pool acquire timeout"
    )

    # Optional separate credentials (if constructing DSN manually)
    password: SecretStr | None = Field(
        default=None, description="Database password (if not in URL)"
    )

    model_config = SettingsConfigDict(
        env_prefix="DB_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        frozen=True,
        populate_by_name=True,  # Allow both DATABASE_URL and database_url
    )

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        """Customize settings source precedence."""

        def files_source(_):
            return db_source()

        return (init_settings, files_source, env_settings, dotenv_settings, file_secret_settings)

    @property
    def is_configured(self) -> bool:
        """Check if database is configured."""
        return self.database_url is not None

    def get_sqlalchemy_url(self) -> str:
        """Get SQLAlchemy-compatible URL string."""
        if not self.database_url:
            raise ValueError("Database URL not configured")
        return str(self.database_url)

    def get_psycopg_url(self) -> str:
        """Get psycopg-native URL (without +psycopg driver specifier)."""
        if not self.database_url:
            raise ValueError("Database URL not configured")
        return str(self.database_url).replace("+psycopg", "")
