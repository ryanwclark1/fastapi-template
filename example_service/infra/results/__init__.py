"""Custom Taskiq result backends for task result storage.

This module provides Redis-based result backends as an alternative to taskiq-redis,
giving more control over the implementation and allowing for customization.
"""

from example_service.infra.results.redis_backend import (
    RedisAsyncClusterResultBackend,
    RedisAsyncResultBackend,
    RedisAsyncSentinelResultBackend,
)

__all__ = [
    "RedisAsyncResultBackend",
    "RedisAsyncClusterResultBackend",
    "RedisAsyncSentinelResultBackend",
]
