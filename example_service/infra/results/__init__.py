"""Custom Taskiq result backends for task result storage.

This module provides result backends as an alternative to taskiq-redis,
giving more control over the implementation and allowing for customization.

Available backends:
- RedisAsyncResultBackend: Standard Redis deployment
- RedisAsyncClusterResultBackend: Redis Cluster deployment
- RedisAsyncSentinelResultBackend: Redis Sentinel deployment (high availability)
- PostgresAsyncResultBackend: PostgreSQL deployment (persistent storage)
"""

from example_service.infra.results.postgres_backend import PostgresAsyncResultBackend
from example_service.infra.results.redis_backend import (
    RedisAsyncClusterResultBackend,
    RedisAsyncResultBackend,
    RedisAsyncSentinelResultBackend,
)

__all__ = [
    "RedisAsyncResultBackend",
    "RedisAsyncClusterResultBackend",
    "RedisAsyncSentinelResultBackend",
    "PostgresAsyncResultBackend",
]
