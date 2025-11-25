"""Advanced caching strategies including cache-aside, write-through, and write-behind."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from functools import wraps
from typing import Any, TypeVar

from example_service.infra.cache import get_cache
from example_service.infra.metrics import tracking

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CacheStrategy(str, Enum):
    """Cache strategy types.

    - CACHE_ASIDE: Read from cache, fetch from source on miss (lazy loading)
    - WRITE_THROUGH: Write to cache and source synchronously
    - WRITE_BEHIND: Write to cache immediately, source asynchronously
    - REFRESH_AHEAD: Proactively refresh cache before expiration
    """

    CACHE_ASIDE = "cache_aside"
    WRITE_THROUGH = "write_through"
    WRITE_BEHIND = "write_behind"
    REFRESH_AHEAD = "refresh_ahead"


@dataclass
class CacheConfig:
    """Configuration for caching behavior.

    Attributes:
        ttl: Time to live in seconds
        key_prefix: Prefix for cache keys
        strategy: Caching strategy to use
        serialize: Function to serialize values
        deserialize: Function to deserialize values
        refresh_threshold: Threshold for refresh-ahead (0-1)
    """

    ttl: int = 300  # 5 minutes
    key_prefix: str = "cache"
    strategy: CacheStrategy = CacheStrategy.CACHE_ASIDE
    serialize: Callable[[Any], str] = lambda x: json.dumps(x)
    deserialize: Callable[[str], Any] = lambda x: json.loads(x)
    refresh_threshold: float = 0.8  # Refresh when 80% of TTL has elapsed


class CacheManager:
    """Advanced cache manager with multiple caching strategies.

    Provides cache-aside, write-through, write-behind, and refresh-ahead
    caching patterns with automatic serialization and metrics tracking.

    Example:
            cache = CacheManager()

        # Cache-aside pattern
        user = await cache.get_or_fetch(
            key="user:123",
            fetch_func=lambda: db.get_user(123),
            ttl=300
        )

        # Write-through pattern
        await cache.set_write_through(
            key="user:123",
            value=user,
            write_func=lambda: db.save_user(user)
        )
    """

    def __init__(self, config: CacheConfig | None = None) -> None:
        """Initialize cache manager.

        Args:
            config: Cache configuration (uses defaults if None)
        """
        self.config = config or CacheConfig()
        self._write_queue: asyncio.Queue[tuple[str, Any, Callable]] = asyncio.Queue()
        self._writer_task: asyncio.Task | None = None

    def _make_key(self, key: str) -> str:
        """Create prefixed cache key.

        Args:
            key: Base key

        Returns:
            Prefixed cache key
        """
        return f"{self.config.key_prefix}:{key}"

    def _hash_key(self, key: str) -> str:
        """Create hashed cache key for long keys.

        Args:
            key: Key to hash

        Returns:
            Hashed key (if long) or original key
        """
        if len(key) > 100:
            return hashlib.sha256(key.encode()).hexdigest()[:16]
        return key

    async def get(self, key: str) -> Any | None:
        """Get value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found
        """
        cache = get_cache()
        cache_key = self._make_key(self._hash_key(key))

        try:
            cached = await cache.get(cache_key)
            if cached:
                tracking.track_token_cache(True)  # Reusing cache hit metric
                return self.config.deserialize(cached)
            else:
                tracking.track_token_cache(False)
                return None
        except Exception as e:
            logger.error(f"Cache get failed for key {key}: {e}", exc_info=True)
            return None

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """Set value in cache.

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live in seconds (uses config default if None)

        Returns:
            True if successful
        """
        cache = get_cache()
        cache_key = self._make_key(self._hash_key(key))
        ttl = ttl or self.config.ttl

        try:
            serialized = self.config.serialize(value)
            await cache.set(cache_key, serialized, ex=ttl)
            return True
        except Exception as e:
            logger.error(f"Cache set failed for key {key}: {e}", exc_info=True)
            return False

    async def delete(self, key: str) -> bool:
        """Delete value from cache.

        Args:
            key: Cache key

        Returns:
            True if successful
        """
        cache = get_cache()
        cache_key = self._make_key(self._hash_key(key))

        try:
            await cache.delete(cache_key)
            return True
        except Exception as e:
            logger.error(f"Cache delete failed for key {key}: {e}", exc_info=True)
            return False

    # ============================================================================
    # Cache-Aside Pattern (Read-Through)
    # ============================================================================

    async def get_or_fetch(
        self,
        key: str,
        fetch_func: Callable[[], Any],
        ttl: int | None = None,
    ) -> Any:
        """Get value from cache or fetch from source (cache-aside pattern).

        This is the most common caching pattern. On cache miss, fetches from
        source and populates cache.

        Args:
            key: Cache key
            fetch_func: Async function to fetch value on cache miss
            ttl: Time to live in seconds

        Returns:
            Cached or fetched value

        Example:
                    user = await cache.get_or_fetch(
                key="user:123",
                fetch_func=lambda: database.get_user(123),
                ttl=300
            )
        """
        # Try to get from cache
        cached = await self.get(key)
        if cached is not None:
            return cached

        # Cache miss - fetch from source
        try:
            value = await fetch_func() if asyncio.iscoroutinefunction(fetch_func) else fetch_func()

            # Populate cache
            if value is not None:
                await self.set(key, value, ttl)

            return value
        except Exception as e:
            logger.error(f"Failed to fetch value for key {key}: {e}", exc_info=True)
            raise

    # ============================================================================
    # Write-Through Pattern
    # ============================================================================

    async def set_write_through(
        self,
        key: str,
        value: Any,
        write_func: Callable[[Any], None],
        ttl: int | None = None,
    ) -> bool:
        """Write to cache and source synchronously (write-through pattern).

        Ensures cache and source are always in sync. Slower writes but
        stronger consistency.

        Args:
            key: Cache key
            value: Value to write
            write_func: Async function to write to source
            ttl: Time to live in seconds

        Returns:
            True if both cache and source writes succeeded

        Example:
                    success = await cache.set_write_through(
                key="user:123",
                value=user_data,
                write_func=lambda v: database.save_user(v)
            )
        """
        try:
            # Write to source first
            if asyncio.iscoroutinefunction(write_func):
                await write_func(value)
            else:
                write_func(value)

            # Write to cache
            await self.set(key, value, ttl)

            return True
        except Exception as e:
            logger.error(f"Write-through failed for key {key}: {e}", exc_info=True)
            # Invalidate cache on write failure to maintain consistency
            await self.delete(key)
            raise

    # ============================================================================
    # Write-Behind Pattern (Write-Back)
    # ============================================================================

    async def set_write_behind(
        self,
        key: str,
        value: Any,
        write_func: Callable[[Any], None],
        ttl: int | None = None,
    ) -> bool:
        """Write to cache immediately, source asynchronously (write-behind pattern).

        Faster writes at the cost of eventual consistency. Writes to source
        are queued and processed asynchronously.

        Args:
            key: Cache key
            value: Value to write
            write_func: Async function to write to source
            ttl: Time to live in seconds

        Returns:
            True if cache write succeeded (source write is async)

        Example:
                    await cache.set_write_behind(
                key="user:123",
                value=user_data,
                write_func=lambda v: database.save_user(v)
            )
        """
        # Write to cache immediately
        success = await self.set(key, value, ttl)

        if success:
            # Queue write to source
            await self._write_queue.put((key, value, write_func))

            # Start writer task if not running
            if self._writer_task is None or self._writer_task.done():
                self._writer_task = asyncio.create_task(self._process_write_queue())

        return success

    async def _process_write_queue(self) -> None:
        """Process queued writes to source (background task)."""
        while True:
            try:
                # Get next write from queue (with timeout)
                key, value, write_func = await asyncio.wait_for(
                    self._write_queue.get(), timeout=1.0
                )

                try:
                    if asyncio.iscoroutinefunction(write_func):
                        await write_func(value)
                    else:
                        write_func(value)

                    logger.debug(f"Write-behind completed for key: {key}")
                except Exception as e:
                    logger.error(
                        f"Write-behind failed for key {key}: {e}",
                        exc_info=True,
                    )
                    # Could implement retry logic here

                self._write_queue.task_done()

            except TimeoutError:
                # No items in queue, check if we should keep running
                if self._write_queue.empty():
                    break
            except Exception as e:
                logger.error(f"Write queue processing error: {e}", exc_info=True)

    # ============================================================================
    # Refresh-Ahead Pattern
    # ============================================================================

    async def get_with_refresh(
        self,
        key: str,
        fetch_func: Callable[[], Any],
        ttl: int | None = None,
    ) -> Any:
        """Get value and proactively refresh if near expiration (refresh-ahead).

        Reduces cache misses by refreshing cache before expiration. Good for
        frequently accessed data with expensive fetch operations.

        Args:
            key: Cache key
            fetch_func: Async function to fetch value
            ttl: Time to live in seconds

        Returns:
            Cached or fetched value

        Example:
                    # Automatically refreshes when 80% of TTL has elapsed
            config = await cache.get_with_refresh(
                key="app:config",
                fetch_func=lambda: fetch_config_from_db(),
                ttl=3600
            )
        """
        cache = get_cache()
        cache_key = self._make_key(self._hash_key(key))
        ttl = ttl or self.config.ttl

        try:
            # Get value and TTL
            cached = await cache.get(cache_key)

            if cached:
                # Check remaining TTL
                remaining_ttl = await cache.ttl(cache_key)

                # Refresh if below threshold
                if remaining_ttl > 0 and remaining_ttl < (ttl * self.config.refresh_threshold):
                    # Trigger async refresh
                    asyncio.create_task(self._refresh_cache(key, fetch_func, ttl))

                return self.config.deserialize(cached)
            else:
                # Cache miss - fetch and store
                return await self.get_or_fetch(key, fetch_func, ttl)

        except Exception as e:
            logger.error(f"Refresh-ahead get failed for key {key}: {e}", exc_info=True)
            # Fall back to fetch
            return await fetch_func() if asyncio.iscoroutinefunction(fetch_func) else fetch_func()

    async def _refresh_cache(self, key: str, fetch_func: Callable[[], Any], ttl: int) -> None:
        """Refresh cache in background.

        Args:
            key: Cache key
            fetch_func: Function to fetch fresh value
            ttl: Time to live
        """
        try:
            value = await fetch_func() if asyncio.iscoroutinefunction(fetch_func) else fetch_func()
            if value is not None:
                await self.set(key, value, ttl)
                logger.debug(f"Cache refreshed for key: {key}")
        except Exception as e:
            logger.error(f"Cache refresh failed for key {key}: {e}", exc_info=True)

    # ============================================================================
    # Batch Operations
    # ============================================================================

    async def get_many(self, keys: list[str]) -> dict[str, Any]:
        """Get multiple values from cache.

        Args:
            keys: List of cache keys

        Returns:
            Dictionary of key -> value (only includes found keys)

        Example:
                    users = await cache.get_many(["user:1", "user:2", "user:3"])
        """
        cache = get_cache()
        cache_keys = [self._make_key(self._hash_key(k)) for k in keys]

        try:
            # Use pipeline for efficiency
            pipe = cache.pipeline()
            for cache_key in cache_keys:
                pipe.get(cache_key)

            results = await pipe.execute()

            # Build result dictionary
            output = {}
            for key, result in zip(keys, results, strict=False):
                if result:
                    output[key] = self.config.deserialize(result)

            return output
        except Exception as e:
            logger.error(f"Batch get failed: {e}", exc_info=True)
            return {}

    async def set_many(self, items: dict[str, Any], ttl: int | None = None) -> bool:
        """Set multiple values in cache.

        Args:
            items: Dictionary of key -> value
            ttl: Time to live in seconds

        Returns:
            True if all sets succeeded

        Example:
                    await cache.set_many({
                "user:1": user1,
                "user:2": user2,
                "user:3": user3
            }, ttl=300)
        """
        cache = get_cache()
        ttl = ttl or self.config.ttl

        try:
            # Use pipeline for efficiency
            pipe = cache.pipeline()
            for key, value in items.items():
                cache_key = self._make_key(self._hash_key(key))
                serialized = self.config.serialize(value)
                pipe.set(cache_key, serialized, ex=ttl)

            await pipe.execute()
            return True
        except Exception as e:
            logger.error(f"Batch set failed: {e}", exc_info=True)
            return False

    # ============================================================================
    # Cache Invalidation
    # ============================================================================

    async def invalidate_pattern(self, pattern: str) -> int:
        """Invalidate all keys matching a pattern.

        Args:
            pattern: Pattern to match (e.g., "user:*")

        Returns:
            Number of keys deleted

        Example:
                    # Invalidate all user caches
            deleted = await cache.invalidate_pattern("user:*")
        """
        cache = get_cache()
        full_pattern = self._make_key(pattern)

        try:
            # Find matching keys
            keys = []
            async for key in cache.scan_iter(match=full_pattern):
                keys.append(key)

            if keys:
                await cache.delete(*keys)
                logger.info(f"Invalidated {len(keys)} keys matching pattern: {pattern}")

            return len(keys)
        except Exception as e:
            logger.error(f"Pattern invalidation failed for {pattern}: {e}", exc_info=True)
            return 0


# ============================================================================
# Decorator for Automatic Caching
# ============================================================================


def cached(
    key_prefix: str,
    ttl: int = 300,
    key_func: Callable[..., str] | None = None,
    strategy: CacheStrategy = CacheStrategy.CACHE_ASIDE,
) -> Callable:
    """Decorator for automatic function result caching.

    Args:
        key_prefix: Prefix for cache keys
        ttl: Time to live in seconds
        key_func: Function to generate cache key from arguments
        strategy: Caching strategy to use

    Returns:
        Decorated function

    Example:
            @cached(key_prefix="user", ttl=300)
        async def get_user(user_id: int):
            return await db.query(User).filter(User.id == user_id).first()

        # Custom key function
        @cached(
            key_prefix="user",
            ttl=600,
            key_func=lambda user_id, include_posts: f"{user_id}:{include_posts}"
        )
        async def get_user_with_posts(user_id: int, include_posts: bool = False):
            # ...
    """
    cache_manager = CacheManager(CacheConfig(key_prefix=key_prefix, ttl=ttl, strategy=strategy))

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Generate cache key
            if key_func:
                key_suffix = key_func(*args, **kwargs)
            else:
                # Default: use function arguments
                key_parts = [str(arg) for arg in args] + [
                    f"{k}={v}" for k, v in sorted(kwargs.items())
                ]
                key_suffix = ":".join(key_parts) if key_parts else "default"

            cache_key = f"{func.__name__}:{key_suffix}"

            # Use appropriate strategy
            if strategy == CacheStrategy.REFRESH_AHEAD:
                return await cache_manager.get_with_refresh(
                    cache_key, lambda: func(*args, **kwargs), ttl
                )
            else:
                return await cache_manager.get_or_fetch(
                    cache_key, lambda: func(*args, **kwargs), ttl
                )

        return wrapper

    return decorator
