"""Cache decorators for function result caching.

This module provides decorators to cache function results in Redis with minimal
boilerplate. Inspired by Flask-Caching and accent-voice2 patterns.

Example:
    from example_service.infra.cache.decorators import cached, cache_key

    @cached(key_prefix="user", ttl=300)
    async def get_user(user_id: int) -> User:
        return await db.get(User, user_id)

    # Cached with key: "user:42"
    user = await get_user(42)

    # Custom key builder
    @cached(
        key_prefix="search",
        ttl=60,
        key_builder=lambda query, page: f"search:{query}:{page}"
    )
    async def search_users(query: str, page: int = 1) -> list[User]:
        return await db.search(query, page)

    # Tag-based invalidation
    @cached(key_prefix="user", ttl=300, tags=lambda user_id: [f"user:{user_id}"])
    async def get_user_with_posts(user_id: int) -> User:
        return await db.get_with_posts(user_id)

    # Invalidate by tag
    await invalidate_tags([f"user:{user_id}"])
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
from functools import wraps
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar, cast

from example_service.infra.cache.redis import get_cache

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

P = ParamSpec("P")
R = TypeVar("R")

logger = logging.getLogger(__name__)


def cache_key(*args: Any, **kwargs: Any) -> str:
    """Build cache key from function arguments.

    Args:
        *args: Positional arguments
        **kwargs: Keyword arguments

    Returns:
        Cache key string

    Example:
        key = cache_key(42, name="john")
        # Returns: "42:name=john"
    """
    parts: list[str] = []

    # Add positional args
    for arg in args:
        if hasattr(arg, "id"):
            # For ORM models, use ID
            parts.append(str(arg.id))
        elif isinstance(arg, (str, int, float, bool)):
            parts.append(str(arg))
        else:
            # Hash complex objects
            try:
                json_str = json.dumps(arg, sort_keys=True, default=str)
                # MD5 used for non-cryptographic cache key hashing
                hash_val = hashlib.md5(json_str.encode()).hexdigest()[:8]  # noqa: S324
                parts.append(hash_val)
            except (TypeError, ValueError):
                parts.append(str(hash(str(arg))))

    # Add keyword args (sorted for consistency)
    for key, value in sorted(kwargs.items()):
        if hasattr(value, "id"):
            parts.append(f"{key}={value.id}")
        elif isinstance(value, (str, int, float, bool, type(None))):
            parts.append(f"{key}={value}")
        else:
            try:
                json_str = json.dumps(value, sort_keys=True, default=str)
                # MD5 used for non-cryptographic cache key hashing
                hash_val = hashlib.md5(json_str.encode()).hexdigest()[:8]  # noqa: S324
                parts.append(f"{key}={hash_val}")
            except (TypeError, ValueError):
                parts.append(f"{key}={hash(str(value))}")

    return ":".join(parts)


def cached[R, **P](
    *,
    key_prefix: str | None = None,
    ttl: int = 300,
    key_builder: Callable[..., str] | None = None,
    tags: Callable[..., list[str]] | None = None,
    condition: Callable[[R], bool] | None = None,
    skip_cache: Callable[P, bool] | None = None,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Cache async function results in Redis.

    Args:
        key_prefix: Prefix for cache key (defaults to function name)
        ttl: Time-to-live in seconds (0 = no expiration)
        key_builder: Custom function to build cache key from args
        tags: Function to extract tags from args for invalidation
        condition: Function to determine if result should be cached
        skip_cache: Function to determine if cache should be skipped for this call

    Returns:
        Decorated function

    Example:
        @cached(key_prefix="user", ttl=300)
        async def get_user(user_id: int) -> User:
            return await db.get(User, user_id)

        # Cached with key: "user:42"
        user = await get_user(42)

        # Custom key builder
        @cached(
            key_prefix="search",
            key_builder=lambda q, p: f"search:{q}:{p}",
            ttl=60
        )
        async def search(query: str, page: int = 1) -> list[User]:
            return await db.search(query, page)

        # Conditional caching (only cache non-empty results)
        @cached(
            key_prefix="results",
            condition=lambda result: len(result) > 0,
            ttl=300
        )
        async def get_results() -> list[Item]:
            return await expensive_query()

        # Skip cache based on request
        @cached(
            key_prefix="data",
            skip_cache=lambda user_id, force: force,
            ttl=300
        )
        async def get_data(user_id: int, force: bool = False) -> Data:
            return await fetch_data(user_id)
    """

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        # Get function name for default key_prefix
        func_name = func.__name__
        prefix = key_prefix or func_name

        # Get function signature for default key building
        inspect.signature(func)

        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            # Check if we should skip cache for this call
            if skip_cache and skip_cache(*args, **kwargs):
                logger.debug(
                    f"Cache skipped for {func_name}",
                    extra={"function": func_name, "reason": "skip_cache=True"},
                )
                return await func(*args, **kwargs)

            # Build cache key
            key_suffix = key_builder(*args, **kwargs) if key_builder else cache_key(*args, **kwargs)

            full_key = f"{prefix}:{key_suffix}" if key_suffix else prefix

            # Try to get from cache
            async with get_cache() as cache:
                cached_value = await cache.get(full_key)

                if cached_value is not None:
                    logger.debug(
                        f"Cache hit for {func_name}",
                        extra={"function": func_name, "key": full_key},
                    )
                    return cast("R", cached_value)

                logger.debug(
                    f"Cache miss for {func_name}",
                    extra={"function": func_name, "key": full_key},
                )

                # Execute function
                result = await func(*args, **kwargs)

                # Check if we should cache this result
                if condition and not condition(result):
                    logger.debug(
                        f"Result not cached (condition=False) for {func_name}",
                        extra={"function": func_name, "key": full_key},
                    )
                    return result

                # Store in cache
                await cache.set(full_key, result, ttl=ttl if ttl > 0 else None)

                # Store tags if provided
                if tags:
                    tag_list = tags(*args, **kwargs)
                    for tag in tag_list:
                        tag_key = f"tag:{tag}"
                        # Add this cache key to the tag set
                        if cache._client:
                            await cache._client.sadd(tag_key, full_key)
                            # Set expiration on tag slightly longer than data
                            if ttl > 0:
                                await cache._client.expire(tag_key, ttl + 60)

                logger.debug(
                    f"Cached result for {func_name}",
                    extra={
                        "function": func_name,
                        "key": full_key,
                        "ttl": ttl,
                        "tags": tag_list if tags else None,
                    },
                )

                return result

        return wrapper

    return decorator


async def invalidate_cache(key_prefix: str, *args: Any, **kwargs: Any) -> bool:
    """Invalidate a specific cache entry.

    Args:
        key_prefix: Cache key prefix
        *args: Function arguments to build key
        **kwargs: Function keyword arguments

    Returns:
        True if key was deleted, False otherwise

    Example:
        # Invalidate specific user cache
        await invalidate_cache("user", 42)

        # Invalidate with kwargs
        await invalidate_cache("search", query="john", page=1)
    """
    key_suffix = cache_key(*args, **kwargs)
    full_key = f"{key_prefix}:{key_suffix}" if key_suffix else key_prefix

    async with get_cache() as cache:
        deleted = await cache.delete(full_key)
        logger.debug(
            "Cache invalidation",
            extra={"key": full_key, "deleted": deleted},
        )
        return deleted


async def invalidate_pattern(pattern: str) -> int:
    """Invalidate all cache entries matching a pattern.

    Uses Redis SCAN to find matching keys and delete them.
    Patterns use Redis glob-style matching: * matches any string,
    ? matches any single character.

    Args:
        pattern: Redis pattern (e.g., "user:*", "search:john:*")

    Returns:
        Number of keys deleted

    Example:
        # Invalidate all user caches
        deleted = await invalidate_pattern("user:*")

        # Invalidate all search caches for a query
        deleted = await invalidate_pattern("search:python:*")

    Warning:
        Can be slow on large datasets. Use with caution in production.
        Consider using tags for bulk invalidation instead.
    """
    async with get_cache() as cache:
        if not cache._client:
            logger.warning("Cache client not available for pattern invalidation")
            return 0

        # Collect matching keys
        keys_to_delete: list[str] = []
        async for key in cache._client.scan_iter(match=pattern, count=100):
            if isinstance(key, bytes):
                keys_to_delete.append(key.decode())
            else:
                keys_to_delete.append(key)

        # Delete in batches
        if keys_to_delete:
            deleted = await cache._client.delete(*keys_to_delete)
            logger.info(
                "Pattern cache invalidation",
                extra={"pattern": pattern, "deleted": deleted, "matched": len(keys_to_delete)},
            )
            return deleted

        logger.debug(
            "Pattern cache invalidation (no matches)",
            extra={"pattern": pattern},
        )
        return 0


async def invalidate_tags(tag_list: list[str]) -> int:
    """Invalidate all cache entries associated with given tags.

    Args:
        tag_list: List of tags to invalidate

    Returns:
        Total number of cache entries deleted

    Example:
        # Invalidate all caches for a user
        deleted = await invalidate_tags(["user:42"])

        # Invalidate multiple related caches
        deleted = await invalidate_tags(["user:42", "users:all", "team:5"])
    """
    async with get_cache() as cache:
        if not cache._client:
            logger.warning("Cache client not available for tag invalidation")
            return 0

        total_deleted = 0

        for tag in tag_list:
            tag_key = f"tag:{tag}"

            # Get all cache keys for this tag
            cache_keys = await cache._client.smembers(tag_key)

            if cache_keys:
                # Delete all associated cache entries
                deleted = await cache._client.delete(*cache_keys)
                total_deleted += deleted

                # Delete the tag set itself
                await cache._client.delete(tag_key)

                logger.debug(
                    "Tag cache invalidation",
                    extra={"tag": tag, "deleted": deleted, "keys": len(cache_keys)},
                )

        logger.info(
            "Tags cache invalidation complete",
            extra={"tags": tag_list, "total_deleted": total_deleted},
        )

        return total_deleted


__all__ = [
    "cache_key",
    "cached",
    "invalidate_cache",
    "invalidate_pattern",
    "invalidate_tags",
]
