"""Redis cache client with automatic retry and connection pooling.

This module provides a high-level Redis cache client that includes:
- Connection pooling
- Automatic retry with exponential backoff
- Type-safe get/set operations
- Serialization/deserialization helpers
- Health checks
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from redis.asyncio import ConnectionPool, Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from example_service.core.settings import get_redis_settings
from example_service.utils.retry import retry

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


class RedisCache:
    """Redis cache client with retry logic and connection pooling.

    This class provides a high-level interface for caching operations
    with automatic retry on transient failures.

    Example:
        ```python
        cache = RedisCache()
        await cache.connect()

        # Set a value
        await cache.set("key", {"data": "value"}, ttl=3600)

        # Get a value
        value = await cache.get("key")

        # Delete a value
        await cache.delete("key")

        await cache.disconnect()
        ```
    """

    def __init__(self) -> None:
        """Initialize Redis cache client."""
        self._pool: ConnectionPool | None = None
        self._client: Redis | None = None

    async def connect(self) -> None:
        """Establish connection to Redis with connection pooling.

        Raises:
            RedisConnectionError: If unable to connect to Redis.
        """
        logger.info("Connecting to Redis", extra={"url": get_redis_settings().get_url()})

        try:
            self._pool = ConnectionPool.from_url(
                get_redis_settings().get_url(),
                max_connections=20,
                decode_responses=True,
                encoding="utf-8",
            )
            self._client = Redis(connection_pool=self._pool)

            # Test connection
            await self._client.ping()

            logger.info("Redis connection established")
        except Exception as e:
            logger.exception("Failed to connect to Redis", extra={"error": str(e)})
            raise

    async def disconnect(self) -> None:
        """Close Redis connection and cleanup resources."""
        logger.info("Disconnecting from Redis")

        if self._client:
            await self._client.aclose()
            self._client = None

        if self._pool:
            await self._pool.aclose()
            self._pool = None

        logger.info("Redis connection closed")

    @property
    def client(self) -> Redis:
        """Get the Redis client instance.

        Returns:
            Redis client.

        Raises:
            RuntimeError: If not connected.
        """
        if self._client is None:
            raise RuntimeError("Redis client not connected. Call connect() first.")
        return self._client

    @retry(
        max_attempts=3,
        initial_delay=1.0,
        max_delay=5.0,
        exceptions=(RedisConnectionError, RedisTimeoutError),
    )
    async def get(self, key: str) -> Any | None:
        """Get a value from cache with automatic retry.

        Args:
            key: Cache key.

        Returns:
            Cached value (deserialized from JSON) or None if not found.

        Raises:
            RedisConnectionError: If unable to connect after retries.
        """
        try:
            value = await self.client.get(key)
            if value is None:
                return None

            # Try to deserialize as JSON, fallback to raw value
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value
        except Exception as e:
            logger.error(
                "Failed to get value from cache",
                extra={"key": key, "error": str(e)},
            )
            raise

    @retry(
        max_attempts=3,
        initial_delay=1.0,
        max_delay=5.0,
        exceptions=(RedisConnectionError, RedisTimeoutError),
    )
    async def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
    ) -> bool:
        """Set a value in cache with automatic retry.

        Args:
            key: Cache key.
            value: Value to cache (will be JSON serialized if not a string).
            ttl: Time to live in seconds (optional).

        Returns:
            True if successful, False otherwise.

        Raises:
            RedisConnectionError: If unable to connect after retries.
        """
        try:
            # Serialize to JSON if not a string
            if not isinstance(value, str):
                value = json.dumps(value)

            result = await self.client.set(key, value, ex=ttl)
            return bool(result)
        except Exception as e:
            logger.error(
                "Failed to set value in cache",
                extra={"key": key, "error": str(e)},
            )
            raise

    @retry(
        max_attempts=3,
        initial_delay=1.0,
        max_delay=5.0,
        exceptions=(RedisConnectionError, RedisTimeoutError),
    )
    async def delete(self, key: str) -> bool:
        """Delete a value from cache with automatic retry.

        Args:
            key: Cache key.

        Returns:
            True if key was deleted, False if key didn't exist.

        Raises:
            RedisConnectionError: If unable to connect after retries.
        """
        try:
            result = await self.client.delete(key)
            return bool(result)
        except Exception as e:
            logger.error(
                "Failed to delete value from cache",
                extra={"key": key, "error": str(e)},
            )
            raise

    @retry(
        max_attempts=3,
        initial_delay=1.0,
        max_delay=5.0,
        exceptions=(RedisConnectionError, RedisTimeoutError),
    )
    async def exists(self, key: str) -> bool:
        """Check if a key exists in cache with automatic retry.

        Args:
            key: Cache key.

        Returns:
            True if key exists, False otherwise.

        Raises:
            RedisConnectionError: If unable to connect after retries.
        """
        try:
            result = await self.client.exists(key)
            return bool(result)
        except Exception as e:
            logger.error(
                "Failed to check key existence in cache",
                extra={"key": key, "error": str(e)},
            )
            raise

    async def health_check(self) -> bool:
        """Check if Redis is healthy and responsive.

        Returns:
            True if healthy, False otherwise.
        """
        try:
            await self.client.ping()
            return True
        except Exception as e:
            logger.error("Redis health check failed", extra={"error": str(e)})
            return False


# Global cache instance
_cache: RedisCache | None = None


async def get_cache() -> AsyncIterator[RedisCache]:
    """Get the global Redis cache instance.

    This is a dependency that can be used in FastAPI endpoints.

    Yields:
        Redis cache instance.

    Example:
        ```python
        @router.get("/data")
        async def get_data(
            cache: RedisCache = Depends(get_cache)
        ):
            data = await cache.get("my-key")
            if data is None:
                data = fetch_from_database()
                await cache.set("my-key", data, ttl=3600)
            return data
        ```
    """
    global _cache
    if _cache is None:
        _cache = RedisCache()
        await _cache.connect()
    yield _cache


async def start_cache() -> None:
    """Initialize the global Redis cache.

    This should be called during application startup.
    """
    global _cache
    logger.info("Starting Redis cache")

    try:
        _cache = RedisCache()
        await _cache.connect()
        logger.info("Redis cache started successfully")
    except Exception as e:
        logger.exception("Failed to start Redis cache", extra={"error": str(e)})
        raise


async def stop_cache() -> None:
    """Close the global Redis cache.

    This should be called during application shutdown.
    """
    global _cache
    logger.info("Stopping Redis cache")

    if _cache:
        try:
            await _cache.disconnect()
            _cache = None
            logger.info("Redis cache stopped successfully")
        except Exception as e:
            logger.exception("Error stopping Redis cache", extra={"error": str(e)})
