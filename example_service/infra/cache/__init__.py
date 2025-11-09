"""Cache infrastructure using Redis."""
from __future__ import annotations

from example_service.infra.cache.redis import RedisCache, get_cache

__all__ = ["RedisCache", "get_cache"]
