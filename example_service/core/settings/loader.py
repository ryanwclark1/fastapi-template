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

from .admin import AdminSettings
from .ai import AISettings
from .app import AppSettings
from .auth import AuthSettings
from .backup import BackupSettings
from .consul import ConsulSettings
from .datatransfer import DataTransferSettings
from .email import EmailSettings
from .graphql import GraphQLSettings
from .health import HealthCheckSettings
from .i18n import I18nSettings
from .jobs import JobSettings
from .logs import LoggingSettings
from .otel import OtelSettings
from .pagination import PaginationSettings
from .postgres import PostgresSettings
from .rabbit import RabbitSettings
from .redis import RedisSettings
from .search import SearchSettings
from .storage import StorageSettings
from .tasks import TaskSettings
from .webhooks import WebhookSettings
from .websocket import WebSocketSettings


@lru_cache(maxsize=1)
def get_admin_settings() -> AdminSettings:
    """Get cached database admin settings.

    Returns:
        Validated and frozen AdminSettings instance.
    """
    return AdminSettings()


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


@lru_cache(maxsize=1)
def get_websocket_settings() -> WebSocketSettings:
    """Get cached WebSocket settings.

    Returns:
        Validated and frozen WebSocketSettings instance.
    """
    return WebSocketSettings()


@lru_cache(maxsize=1)
def get_graphql_settings() -> GraphQLSettings:
    """Get cached GraphQL settings.

    Returns:
        Validated and frozen GraphQLSettings instance.
    """
    return GraphQLSettings()


@lru_cache(maxsize=1)
def get_i18n_settings() -> I18nSettings:
    """Get cached internationalization settings.

    Returns:
        Validated and frozen I18nSettings instance.
    """
    return I18nSettings()


@lru_cache(maxsize=1)
def get_health_settings() -> HealthCheckSettings:
    """Get cached health check settings.

    Returns:
        Validated and frozen HealthCheckSettings instance.
    """
    return HealthCheckSettings()


@lru_cache(maxsize=1)
def get_task_settings() -> TaskSettings:
    """Get cached task management settings.

    Returns:
        Validated and frozen TaskSettings instance.
    """
    return TaskSettings()


@lru_cache(maxsize=1)
def get_email_settings() -> EmailSettings:
    """Get cached email settings.

    Returns:
        Validated and frozen EmailSettings instance.
    """
    return EmailSettings()


@lru_cache(maxsize=1)
def get_pagination_settings() -> PaginationSettings:
    """Get cached pagination settings.

    Returns:
        Validated and frozen PaginationSettings instance.
    """
    return PaginationSettings()


@lru_cache(maxsize=1)
def get_ai_settings() -> AISettings:
    """Get cached AI services settings.

    Returns:
        Validated and frozen AISettings instance.
    """
    return AISettings()


@lru_cache(maxsize=1)
def get_datatransfer_settings() -> DataTransferSettings:
    """Get cached data transfer settings.

    Returns:
        Validated and frozen DataTransferSettings instance.
    """
    return DataTransferSettings()


@lru_cache(maxsize=1)
def get_job_settings() -> JobSettings:
    """Get cached job management settings.

    Returns:
        Validated and frozen JobSettings instance.
    """
    return JobSettings()


@lru_cache(maxsize=1)
def get_search_settings() -> SearchSettings:
    """Get cached search settings.

    Returns:
        Validated and frozen SearchSettings instance.
    """
    return SearchSettings()


@lru_cache(maxsize=1)
def get_webhook_settings() -> WebhookSettings:
    """Get cached webhook settings.

    Returns:
        Validated and frozen WebhookSettings instance.
    """
    return WebhookSettings()


def clear_all_caches() -> None:
    """Clear all settings caches.

    Useful for testing or when you need to force reload settings.
    In production, prefer process restarts over cache clearing.
    """
    get_admin_settings.cache_clear()
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
    get_websocket_settings.cache_clear()
    get_graphql_settings.cache_clear()
    get_i18n_settings.cache_clear()
    get_health_settings.cache_clear()
    get_task_settings.cache_clear()
    get_email_settings.cache_clear()
    get_pagination_settings.cache_clear()
    get_ai_settings.cache_clear()
    get_datatransfer_settings.cache_clear()
    get_job_settings.cache_clear()
    get_search_settings.cache_clear()
    get_webhook_settings.cache_clear()


def clear_settings_cache() -> None:
    """Backward-compatible alias for clearing cached settings."""
    clear_all_caches()
