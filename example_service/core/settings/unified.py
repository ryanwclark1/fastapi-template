"""Unified settings composition for convenient access.

This module provides an optional unified settings class that composes
all domain-specific settings into a single object. This is purely additive
and does not replace the modular get_*_settings() functions.

Usage:
    from example_service.core.settings import get_settings

    settings = get_settings()
    print(settings.app.host)       # Access app settings
    print(settings.db.pool_size)   # Access database settings
    print(settings.redis.default_ttl)  # Access Redis settings

Benefits:
- Single import for all settings access
- IDE autocompletion across all settings domains
- Useful for dependency injection patterns
- Each nested settings class still respects its own env prefix

Note:
    For production code that only needs specific settings,
    prefer the individual get_*_settings() functions to avoid
    loading unnecessary configuration.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from .app import AppSettings
    from .auth import AuthSettings
    from .backup import BackupSettings
    from .consul import ConsulSettings
    from .logs import LoggingSettings
    from .otel import OtelSettings
    from .postgres import PostgresSettings
    from .rabbit import RabbitSettings
    from .redis import RedisSettings
    from .storage import StorageSettings


def _get_app_settings() -> AppSettings:
    """Lazy import to avoid circular dependencies."""
    from .app import AppSettings
    return AppSettings()


def _get_db_settings() -> PostgresSettings:
    """Lazy import to avoid circular dependencies."""
    from .postgres import PostgresSettings
    return PostgresSettings()


def _get_redis_settings() -> RedisSettings:
    """Lazy import to avoid circular dependencies."""
    from .redis import RedisSettings
    return RedisSettings()


def _get_rabbit_settings() -> RabbitSettings:
    """Lazy import to avoid circular dependencies."""
    from .rabbit import RabbitSettings
    return RabbitSettings()


def _get_logging_settings() -> LoggingSettings:
    """Lazy import to avoid circular dependencies."""
    from .logs import LoggingSettings
    return LoggingSettings()


def _get_otel_settings() -> OtelSettings:
    """Lazy import to avoid circular dependencies."""
    from .otel import OtelSettings
    return OtelSettings()


def _get_auth_settings() -> AuthSettings:
    """Lazy import to avoid circular dependencies."""
    from .auth import AuthSettings
    return AuthSettings()


def _get_backup_settings() -> BackupSettings:
    """Lazy import to avoid circular dependencies."""
    from .backup import BackupSettings
    return BackupSettings()


def _get_consul_settings() -> ConsulSettings:
    """Lazy import to avoid circular dependencies."""
    from .consul import ConsulSettings
    return ConsulSettings()


def _get_storage_settings() -> StorageSettings:
    """Lazy import to avoid circular dependencies."""
    from .storage import StorageSettings
    return StorageSettings()


class Settings(BaseSettings):
    """Unified settings composing all domain settings.

    This class creates instances of each domain settings class,
    allowing convenient access via a single object.

    Note: Each nested settings class still loads from its own
    environment prefix (APP_, DB_, REDIS_, etc.), not from a unified prefix.

    Example:
        settings = Settings()
        assert settings.app.debug == False
        assert settings.db.pool_size == 10
    """

    model_config = SettingsConfigDict(
        frozen=True,
        extra="ignore",
    )

    # Domain settings - each uses default_factory to create fresh instances
    app: AppSettings = Field(default_factory=_get_app_settings)
    db: PostgresSettings = Field(default_factory=_get_db_settings)
    redis: RedisSettings = Field(default_factory=_get_redis_settings)
    rabbit: RabbitSettings = Field(default_factory=_get_rabbit_settings)
    logging: LoggingSettings = Field(default_factory=_get_logging_settings)
    otel: OtelSettings = Field(default_factory=_get_otel_settings)
    auth: AuthSettings = Field(default_factory=_get_auth_settings)
    backup: BackupSettings = Field(default_factory=_get_backup_settings)
    consul: ConsulSettings = Field(default_factory=_get_consul_settings)
    storage: StorageSettings = Field(default_factory=_get_storage_settings)


def _rebuild_model() -> None:
    """Rebuild the Settings model with actual type references.

    This is needed because we use TYPE_CHECKING imports for the
    nested settings classes. Before instantiating Settings, we
    must rebuild the model with the actual types available.
    """
    from .app import AppSettings
    from .auth import AuthSettings
    from .backup import BackupSettings
    from .consul import ConsulSettings
    from .logs import LoggingSettings
    from .otel import OtelSettings
    from .postgres import PostgresSettings
    from .rabbit import RabbitSettings
    from .redis import RedisSettings
    from .storage import StorageSettings

    Settings.model_rebuild(
        _types_namespace={
            "AppSettings": AppSettings,
            "PostgresSettings": PostgresSettings,
            "RedisSettings": RedisSettings,
            "RabbitSettings": RabbitSettings,
            "LoggingSettings": LoggingSettings,
            "OtelSettings": OtelSettings,
            "AuthSettings": AuthSettings,
            "BackupSettings": BackupSettings,
            "ConsulSettings": ConsulSettings,
            "StorageSettings": StorageSettings,
        }
    )


_model_rebuilt = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get unified settings instance (cached).

    Returns a cached instance of the unified Settings class,
    providing access to all domain settings.

    Returns:
        Settings: Unified settings with all domain configurations.

    Example:
        from example_service.core.settings import get_settings

        settings = get_settings()
        if settings.app.debug:
            print("Debug mode enabled")
        if settings.db.is_configured:
            print(f"Database pool size: {settings.db.pool_size}")
    """
    global _model_rebuilt
    if not _model_rebuilt:
        _rebuild_model()
        _model_rebuilt = True
    return Settings()
