"""LRU-cached settings loaders for optimal performance.

Settings are loaded and validated once, then cached for the lifetime of the process.
This ensures:
- Single source of truth
- Fast O(1) access after first load
- No repeated file/env parsing
- Immutable configuration

Usage:
    from example_service.core.settings.loader import get_app_settings

    settings = get_app_settings()  # First call: loads and validates
    settings = get_app_settings()  # Subsequent calls: returns cached instance

Testing:
    In tests, clear the cache to force reload:
    get_app_settings.cache_clear()

    Or override with custom values:
    settings = AppSettings(debug=True, ...)
"""

from __future__ import annotations

from functools import lru_cache

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


@lru_cache(maxsize=1)
def get_app_settings() -> AppSettings:
    """Get cached application settings.

    Returns:
        Validated and frozen AppSettings instance.
    """
    return AppSettings()


@lru_cache(maxsize=1)
def get_db_settings() -> PostgresSettings:
    """Get cached database settings.

    Returns:
        Validated and frozen PostgresSettings instance.
    """
    return PostgresSettings()


@lru_cache(maxsize=1)
def get_rabbit_settings() -> RabbitSettings:
    """Get cached RabbitMQ settings.

    Returns:
        Validated and frozen RabbitSettings instance.
    """
    return RabbitSettings()


@lru_cache(maxsize=1)
def get_logging_settings() -> LoggingSettings:
    """Get cached logging settings.

    Returns:
        Validated and frozen LoggingSettings instance.
    """
    return LoggingSettings()


@lru_cache(maxsize=1)
def get_otel_settings() -> OtelSettings:
    """Get cached OpenTelemetry settings.

    Returns:
        Validated and frozen OtelSettings instance.
    """
    return OtelSettings()


@lru_cache(maxsize=1)
def get_redis_settings() -> RedisSettings:
    """Get cached Redis settings.

    Returns:
        Validated and frozen RedisSettings instance.
    """
    return RedisSettings()


@lru_cache(maxsize=1)
def get_auth_settings() -> AuthSettings:
    """Get cached authentication settings.

    Returns:
        Validated and frozen AuthSettings instance.
    """
    return AuthSettings()


@lru_cache(maxsize=1)
def get_backup_settings() -> BackupSettings:
    """Get cached backup settings.

    Returns:
        Validated and frozen BackupSettings instance.
    """
    return BackupSettings()


@lru_cache(maxsize=1)
def get_consul_settings() -> ConsulSettings:
    """Get cached Consul service discovery settings.

    Returns:
        Validated and frozen ConsulSettings instance.
    """
    return ConsulSettings()


@lru_cache(maxsize=1)
def get_storage_settings() -> StorageSettings:
    """Get cached object storage settings.

    Returns:
        Validated and frozen StorageSettings instance.
    """
    return StorageSettings()


def clear_all_caches() -> None:
    """Clear all settings caches.

    Useful for testing or when you need to force reload settings.
    In production, prefer process restarts over cache clearing.
    """
    get_app_settings.cache_clear()
    get_db_settings.cache_clear()
    get_rabbit_settings.cache_clear()
    get_logging_settings.cache_clear()
    get_otel_settings.cache_clear()
    get_redis_settings.cache_clear()
    get_auth_settings.cache_clear()
    get_backup_settings.cache_clear()
    get_consul_settings.cache_clear()
    get_storage_settings.cache_clear()
