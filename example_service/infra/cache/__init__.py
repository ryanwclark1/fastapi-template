"""Cache infrastructure using Redis."""
from __future__ import annotations

from example_service.infra.cache.redis import RedisCache, get_cache
from example_service.infra.cache.strategies import (
    CacheConfig,
    CacheManager,
    CacheStrategy,
    cached,
)

__all__ = [
    "CacheConfig",
    "CacheManager",
    "CacheStrategy",
    "RedisCache",
    "cached",
    "get_cache",
]
