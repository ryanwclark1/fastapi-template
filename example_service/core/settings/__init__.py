"""Modular Pydantic Settings v2 configuration.

This package provides a clean, modular settings architecture following 12-factor principles:
- Single source of truth via environment variables
- Modular settings by domain (app/db/broker/logging/otel)
- Optional YAML/conf.d file support for local development
- LRU-cached settings loaders for performance
- Immutable (frozen) settings models
- SecretStr for sensitive fields

Import settings via cached loaders:
    from example_service.core.settings.loader import get_app_settings

Configuration precedence (highest to lowest):
    1. init kwargs (testing/overrides)
    2. YAML/conf.d files (optional, local/dev)
    3. Environment variables (production)
    4. .env file (development only)
    5. secrets_dir (Kubernetes/Docker secrets)
"""

from __future__ import annotations

from .combined import settings
from .loader import (
    get_app_settings,
    get_auth_settings,
    get_db_settings,
    get_logging_settings,
    get_otel_settings,
    get_rabbit_settings,
    get_redis_settings,
)

__all__ = [
    "settings",  # Combined settings object for backward compatibility
    "get_app_settings",
    "get_db_settings",
    "get_rabbit_settings",
    "get_redis_settings",
    "get_auth_settings",
    "get_logging_settings",
    "get_otel_settings",
]
