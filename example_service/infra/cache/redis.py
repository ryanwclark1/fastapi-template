"""Redis cache client with automatic retry and connection pooling.

This module provides a high-level Redis cache client that includes:
- Connection pooling
- Automatic retry with exponential backoff
- Type-safe get/set operations
- Serialization/deserialization helpers
- Health checks
- Prometheus metrics with trace correlation
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import json
import logging
import time
from typing import TYPE_CHECKING, Any, cast

from opentelemetry import trace
from redis.asyncio import ConnectionPool, Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from example_service.core.settings import get_redis_settings
from example_service.infra.metrics.prometheus import (
    cache_commands_total,
    cache_connections_active,
    cache_evictions_total,
    cache_expired_keys_total,
    cache_hits_total,
    cache_keys_total,
    cache_keyspace_hits_total,
    cache_keyspace_misses_total,
    cache_memory_bytes,
    cache_memory_max_bytes,
    cache_misses_total,
    cache_operation_duration_seconds,
)
from example_service.utils.retry import retry

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable
else:  # pragma: no cover - typing fallback
    AsyncIterator = Any

logger = logging.getLogger(__name__)
redis_settings = get_redis_settings()


class RedisCache:
    """Redis cache client with retry logic and connection pooling.

    This class provides a high-level interface for caching operations
    with automatic retry on transient failures.

    Example:
            cache = RedisCache()
        await cache.connect()

        # Set a value
        await cache.set("key", {"data": "value"}, ttl=3600)

        # Get a value
        value = await cache.get("key")

        # Delete a value
        await cache.delete("key")

        await cache.disconnect()
    """

    def __init__(self) -> None:
        """Initialize Redis cache client."""
        self._pool: ConnectionPool | None = None
        self._client: Redis | None = None

    async def connect(self) -> None:
        """Establish connection to Redis with connection pooling.

        Uses settings from RedisSettings for connection parameters including
        timeouts, pool size, and SSL configuration.

        Raises:
            RedisConnectionError: If unable to connect to Redis.
        """
        logger.info(
            "Connecting to Redis",
            extra={
                "host": redis_settings.host,
                "port": redis_settings.port,
                "db": redis_settings.db,
                "max_connections": redis_settings.max_connections,
                "socket_timeout": redis_settings.socket_timeout,
            },
        )

        try:
            # Use connection_pool_kwargs() to get all settings-driven parameters
            self._pool = ConnectionPool.from_url(
                redis_settings.url,
                **redis_settings.connection_pool_kwargs(),
            )
            self._client = Redis(connection_pool=self._pool)

            # Test connection
            await cast("Awaitable[bool]", self._client.ping())

            logger.info("Redis connection established successfully")
        except Exception as e:
            logger.exception("Failed to connect to Redis", extra={"error": str(e)})
            raise

    async def disconnect(self) -> None:
        """Close Redis connection and cleanup resources."""
        logger.info("Disconnecting from Redis")

        if self._client:
            await cast("Any", self._client).aclose()
            self._client = None

        if self._pool:
            await cast("Any", self._pool).aclose()
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
            msg = "Redis client not connected. Call connect() first."
            raise RuntimeError(msg)
        return self._client

    def get_client(self) -> Redis:
        """Public accessor for the underlying Redis client."""
        return self.client

    @retry(
        max_attempts=redis_settings.max_retries,
        initial_delay=redis_settings.retry_delay,
        max_delay=5.0,
        exceptions=(RedisConnectionError, RedisTimeoutError),
        stop_after_delay=redis_settings.retry_timeout,
    )
    async def get(self, key: str) -> Any | None:
        """Get a value from cache with automatic retry and metrics.

        Args:
            key: Cache key.

        Returns:
            Cached value (deserialized from JSON) or None if not found.

        Raises:
            RedisConnectionError: If unable to connect after retries.
        """
        start_time = time.perf_counter()
        cache_name = "redis"

        try:
            value = await self.client.get(key)
            duration = time.perf_counter() - start_time

            # Get trace context for exemplar
            span = trace.get_current_span()
            trace_id = None
            if span and span.get_span_context().is_valid:
                trace_id = format(span.get_span_context().trace_id, "032x")

            # Record hit/miss
            if value is not None:
                if trace_id:
                    cache_hits_total.labels(cache_name=cache_name).inc(
                        exemplar={"trace_id": trace_id},
                    )
                else:
                    cache_hits_total.labels(cache_name=cache_name).inc()
            elif trace_id:
                cache_misses_total.labels(cache_name=cache_name).inc(
                    exemplar={"trace_id": trace_id},
                )
            else:
                cache_misses_total.labels(cache_name=cache_name).inc()

            # Record operation duration
            if trace_id:
                cache_operation_duration_seconds.labels(
                    operation="get", cache_name=cache_name,
                ).observe(duration, exemplar={"trace_id": trace_id})
            else:
                cache_operation_duration_seconds.labels(
                    operation="get", cache_name=cache_name,
                ).observe(duration)

            if value is None:
                return None

            # Try to deserialize as JSON, fallback to raw value
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value
        except Exception as e:
            logger.exception(
                "Failed to get value from cache",
                extra={"key": key, "error": str(e)},
            )
            raise

    @retry(
        max_attempts=redis_settings.max_retries,
        initial_delay=redis_settings.retry_delay,
        max_delay=5.0,
        exceptions=(RedisConnectionError, RedisTimeoutError),
        stop_after_delay=redis_settings.retry_timeout,
    )
    async def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
    ) -> bool:
        """Set a value in cache with automatic retry and metrics.

        Args:
            key: Cache key.
            value: Value to cache (will be JSON serialized if not a string).
            ttl: Time to live in seconds (optional).

        Returns:
            True if successful, False otherwise.

        Raises:
            RedisConnectionError: If unable to connect after retries.
        """
        start_time = time.perf_counter()
        cache_name = "redis"

        try:
            # Serialize to JSON if not a string
            if not isinstance(value, str):
                value = json.dumps(value)

            result = await self.client.set(key, value, ex=ttl)
            duration = time.perf_counter() - start_time

            # Get trace context for exemplar
            span = trace.get_current_span()
            trace_id = None
            if span and span.get_span_context().is_valid:
                trace_id = format(span.get_span_context().trace_id, "032x")

            # Record operation duration
            if trace_id:
                cache_operation_duration_seconds.labels(
                    operation="set", cache_name=cache_name,
                ).observe(duration, exemplar={"trace_id": trace_id})
            else:
                cache_operation_duration_seconds.labels(
                    operation="set", cache_name=cache_name,
                ).observe(duration)

            return bool(result)
        except Exception as e:
            logger.exception(
                "Failed to set value in cache",
                extra={"key": key, "error": str(e)},
            )
            raise

    async def ttl(self, key: str) -> int:
        """Get the time-to-live for a key in seconds."""
        if self._client is None:
            msg = "Redis client not connected. Call connect() first."
            raise RuntimeError(msg)
        ttl_value = await self._client.ttl(key)
        return int(ttl_value) if ttl_value is not None else -1

    def pipeline(self) -> Any:
        """Return a Redis pipeline for batch operations."""
        if self._client is None:
            msg = "Redis client not connected. Call connect() first."
            raise RuntimeError(msg)
        return self._client.pipeline()

    def scan_iter(self, match: str | None = None, count: int | None = None) -> Any:
        """Iterate over keys matching a pattern."""
        if self._client is None:
            msg = "Redis client not connected. Call connect() first."
            raise RuntimeError(msg)
        return self._client.scan_iter(match=match, count=count)

    async def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching a pattern."""
        if self._client is None:
            msg = "Redis client not connected. Call connect() first."
            raise RuntimeError(msg)

        keys = [key async for key in self.scan_iter(match=pattern)]
        if not keys:
            return 0

        deleted = await self._client.delete(*keys)
        return int(deleted) if deleted is not None else 0

    @retry(
        max_attempts=redis_settings.max_retries,
        initial_delay=redis_settings.retry_delay,
        max_delay=5.0,
        exceptions=(RedisConnectionError, RedisTimeoutError),
        stop_after_delay=redis_settings.retry_timeout,
    )
    async def delete(self, key: str) -> bool:
        """Delete a value from cache with automatic retry and metrics.

        Args:
            key: Cache key.

        Returns:
            True if key was deleted, False if key didn't exist.

        Raises:
            RedisConnectionError: If unable to connect after retries.
        """
        start_time = time.perf_counter()
        cache_name = "redis"

        try:
            result = await self.client.delete(key)
            duration = time.perf_counter() - start_time

            # Get trace context for exemplar
            span = trace.get_current_span()
            trace_id = None
            if span and span.get_span_context().is_valid:
                trace_id = format(span.get_span_context().trace_id, "032x")

            # Record operation duration
            if trace_id:
                cache_operation_duration_seconds.labels(
                    operation="delete", cache_name=cache_name,
                ).observe(duration, exemplar={"trace_id": trace_id})
            else:
                cache_operation_duration_seconds.labels(
                    operation="delete", cache_name=cache_name,
                ).observe(duration)

            return bool(result)
        except Exception as e:
            logger.exception(
                "Failed to delete value from cache",
                extra={"key": key, "error": str(e)},
            )
            raise

    @retry(
        max_attempts=redis_settings.max_retries,
        initial_delay=redis_settings.retry_delay,
        max_delay=5.0,
        exceptions=(RedisConnectionError, RedisTimeoutError),
        stop_after_delay=redis_settings.retry_timeout,
    )
    async def exists(self, key: str) -> bool:
        """Check if a key exists in cache with automatic retry and metrics.

        Args:
            key: Cache key.

        Returns:
            True if key exists, False otherwise.

        Raises:
            RedisConnectionError: If unable to connect after retries.
        """
        start_time = time.perf_counter()
        cache_name = "redis"

        try:
            result = await self.client.exists(key)
            duration = time.perf_counter() - start_time

            # Get trace context for exemplar
            span = trace.get_current_span()
            trace_id = None
            if span and span.get_span_context().is_valid:
                trace_id = format(span.get_span_context().trace_id, "032x")

            # Record operation duration
            if trace_id:
                cache_operation_duration_seconds.labels(
                    operation="exists", cache_name=cache_name,
                ).observe(duration, exemplar={"trace_id": trace_id})
            else:
                cache_operation_duration_seconds.labels(
                    operation="exists", cache_name=cache_name,
                ).observe(duration)

            return bool(result)
        except Exception as e:
            logger.exception(
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
            await cast("Awaitable[bool]", self.client.ping())
            return True
        except Exception as e:
            logger.exception("Redis health check failed", extra={"error": str(e)})
            return False

    async def collect_stats(self, cache_name: str = "redis") -> dict[str, Any]:
        """Collect Redis INFO stats and update Prometheus metrics.

        This method should be called periodically (e.g., every 15-30 seconds)
        to update infrastructure metrics from Redis server.

        Args:
            cache_name: Label value for cache_name in metrics.

        Returns:
            Dictionary with collected stats.

        Example:
                # In a background task
            stats = await cache.collect_stats()
            logger.debug("Redis stats", extra=stats)
        """
        try:
            # Get Redis INFO - returns dict with server stats
            info = await cast("Awaitable[dict[str, Any]]", self.client.info())

            # Memory metrics
            used_memory = info.get("used_memory", 0)
            max_memory = info.get("maxmemory", 0)
            cache_memory_bytes.labels(cache_name=cache_name).set(used_memory)
            cache_memory_max_bytes.labels(cache_name=cache_name).set(max_memory)

            # Key count (from db0 if available)
            db_info = info.get("db0", {})
            if isinstance(db_info, dict):
                keys = db_info.get("keys", 0)
            else:
                # Sometimes Redis returns this as a string like "keys=123,expires=45"
                keys = 0
                if isinstance(db_info, str):
                    for part in db_info.split(","):
                        if part.startswith("keys="):
                            keys = int(part.split("=")[1])
                            break
            cache_keys_total.labels(cache_name=cache_name).set(keys)

            # Connection count
            connected_clients = info.get("connected_clients", 0)
            cache_connections_active.labels(cache_name=cache_name).set(connected_clients)

            # Evictions and expirations (these are cumulative counters in Redis)
            # We track them as Prometheus counters by storing the previous value
            evicted_keys = info.get("evicted_keys", 0)
            expired_keys = info.get("expired_keys", 0)
            total_commands = info.get("total_commands_processed", 0)
            keyspace_hits = info.get("keyspace_hits", 0)
            keyspace_misses = info.get("keyspace_misses", 0)

            # Update counters with delta since last collection
            self._update_counter_metric(
                cache_evictions_total.labels(cache_name=cache_name),
                "_last_evicted_keys",
                evicted_keys,
            )
            self._update_counter_metric(
                cache_expired_keys_total.labels(cache_name=cache_name),
                "_last_expired_keys",
                expired_keys,
            )
            self._update_counter_metric(
                cache_commands_total.labels(cache_name=cache_name),
                "_last_total_commands",
                total_commands,
            )
            self._update_counter_metric(
                cache_keyspace_hits_total.labels(cache_name=cache_name),
                "_last_keyspace_hits",
                keyspace_hits,
            )
            self._update_counter_metric(
                cache_keyspace_misses_total.labels(cache_name=cache_name),
                "_last_keyspace_misses",
                keyspace_misses,
            )

            stats = {
                "used_memory": used_memory,
                "max_memory": max_memory,
                "keys": keys,
                "connected_clients": connected_clients,
                "evicted_keys": evicted_keys,
                "expired_keys": expired_keys,
                "total_commands": total_commands,
                "keyspace_hits": keyspace_hits,
                "keyspace_misses": keyspace_misses,
            }

            logger.debug("Redis stats collected", extra=stats)
            return stats

        except Exception as e:
            logger.warning("Failed to collect Redis stats", extra={"error": str(e)})
            return {}

    def _update_counter_metric(
        self,
        metric: Any,
        attr_name: str,
        current_value: int,
    ) -> None:
        """Update a Prometheus counter with delta from Redis cumulative value.

        Args:
            metric: Prometheus counter metric (already labeled).
            attr_name: Attribute name to store previous value on self.
            current_value: Current cumulative value from Redis.
        """
        # Get previous value, default to current (first run = no increment)
        previous = getattr(self, attr_name, current_value)
        delta = max(0, current_value - previous)

        if delta > 0:
            metric.inc(delta)

        # Store current value for next collection
        setattr(self, attr_name, current_value)


# Global cache instance
_cache: RedisCache | None = None


@asynccontextmanager
async def get_cache() -> AsyncIterator[RedisCache]:
    """Get the global Redis cache instance.

    This is a dependency that can be used in FastAPI endpoints.

    Yields:
        Redis cache instance.

    Example:
            @router.get("/data")
        async def get_data(
            cache: RedisCache = Depends(get_cache)
        ):
            data = await cache.get("my-key")
            if data is None:
                data = fetch_from_database()
                await cache.set("my-key", data, ttl=3600)
            return data
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


def get_cache_instance() -> RedisCache | None:
    """Get the global Redis cache instance if initialized.

    Returns:
        RedisCache instance or None if not initialized.

    Note:
        Use this for background tasks that need cache access.
        For request handlers, use the get_cache() context manager.
    """
    return _cache


async def collect_cache_stats() -> dict[str, Any]:
    """Collect cache statistics from the global cache instance.

    Returns:
        Dictionary with stats or empty dict if cache not available.

    Example:
            # In a periodic background task
        stats = await collect_cache_stats()
        if stats:
            logger.info("Cache stats", extra=stats)
    """
    if _cache is None:
        return {}
    return await _cache.collect_stats()
