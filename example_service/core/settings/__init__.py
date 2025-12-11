"""Modular Pydantic Settings v2 configuration.

This package provides a clean, modular settings architecture following 12-factor principles:
- Single source of truth via environment variables
- Modular settings by domain (app/db/broker/logging/otel)
- Optional YAML/conf.d file support for local development
- LRU-cached settings loaders for performance
- Immutable (frozen) settings models
- SecretStr for sensitive fields

Import settings via cached loaders (recommended for production):
    from example_service.core.settings import get_app_settings

Or use unified settings for convenient access to all domains:
    from example_service.core.settings import get_settings

    settings = get_settings()
    print(settings.app.host)
    print(settings.db.pool_size)

Configuration precedence (highest to lowest):
    1. init kwargs (testing/overrides)
    2. YAML/conf.d files (optional, local/dev)
    3. Environment variables (production)
    4. .env file (development only)
    5. secrets_dir (Kubernetes/Docker secrets)
"""

from __future__ import annotations

from .loader import (
    get_admin_settings,
    get_ai_settings,
    get_app_settings,
    get_auth_settings,
    get_backup_settings,
    get_consul_settings,
    get_datatransfer_settings,
    get_db_settings,
    get_email_settings,
    get_graphql_settings,
    get_health_settings,
    get_i18n_settings,
    get_job_settings,
    get_logging_settings,
    get_otel_settings,
    get_pagination_settings,
    get_rabbit_settings,
    get_redis_settings,
    get_search_settings,
    get_storage_settings,
    get_task_settings,
    get_webhook_settings,
    get_websocket_settings,
)
from .unified import Settings, get_settings

__all__ = [
    # Unified settings (convenient for development/testing)
    "Settings",
    # Individual domain loaders (recommended for production)
    "get_admin_settings",
    "get_ai_settings",
    "get_app_settings",
    "get_auth_settings",
    "get_backup_settings",
    "get_consul_settings",
    "get_datatransfer_settings",
    "get_db_settings",
    "get_email_settings",
    "get_graphql_settings",
    "get_health_settings",
    "get_i18n_settings",
    "get_job_settings",
    "get_logging_settings",
    "get_otel_settings",
    "get_pagination_settings",
    "get_rabbit_settings",
    "get_redis_settings",
    "get_search_settings",
    "get_settings",
    "get_storage_settings",
    "get_task_settings",
    "get_webhook_settings",
    "get_websocket_settings",
]
