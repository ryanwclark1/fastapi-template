"""Search result caching with Redis.

Provides caching functionality for frequent search queries to reduce
database load and improve response times.

Features:
- Automatic cache key generation from search parameters
- Configurable TTL per query type
- Cache invalidation helpers
- Metrics for cache hit/miss rates

Usage:
    from example_service.features.search.cache import SearchCache

    # Initialize with Redis cache
    search_cache = SearchCache(redis_cache)

    # Get cached results
    cached = await search_cache.get(request)
    if cached:
        return cached

    # Execute search and cache results
    results = await service.search(request)
    await search_cache.set(request, results)
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from example_service.infra.cache.redis import RedisCache

logger = logging.getLogger(__name__)


@dataclass
class SearchCacheConfig:
    """Configuration for search caching."""

    enabled: bool = True
    default_ttl: int = 300  # 5 minutes
    suggestion_ttl: int = 600  # 10 minutes
    analytics_ttl: int = 60  # 1 minute (analytics should be fresh)
    max_query_length: int = 200  # Don't cache very long queries
    cache_prefix: str = "search"
    min_results_to_cache: int = 0  # Cache even zero-result queries
    cache_empty_results: bool = True  # Whether to cache zero-result queries


class SearchCache:
    """Redis cache for search results.

    Caches search results to reduce database load for frequently
    executed queries.

    Example:
        cache = SearchCache(redis_cache)

        # Check for cached results
        cached = await cache.get_search_results(request)
        if cached:
            return cached

        # Execute search
        results = await search_service.search(request)

        # Cache results
        await cache.set_search_results(request, results)
        return results
    """

    def __init__(
        self,
        redis_cache: RedisCache,
        config: SearchCacheConfig | None = None,
    ) -> None:
        """Initialize search cache.

        Args:
            redis_cache: Redis cache instance.
            config: Cache configuration (optional).
        """
        self.redis = redis_cache
        self.config = config or SearchCacheConfig()

    def _generate_cache_key(
        self,
        prefix: str,
        params: dict[str, Any],
    ) -> str:
        """Generate a cache key from parameters.

        Creates a deterministic hash from search parameters.

        Args:
            prefix: Key prefix (e.g., "search", "suggest").
            params: Search parameters.

        Returns:
            Cache key string.
        """
        # Sort params for consistent key generation
        sorted_params = json.dumps(params, sort_keys=True, default=str)
        # MD5 used for non-cryptographic cache key hashing
        param_hash = hashlib.md5(sorted_params.encode()).hexdigest()[:16]  # noqa: S324

        return f"{self.config.cache_prefix}:{prefix}:{param_hash}"

    def _request_to_params(self, request: Any) -> dict[str, Any]:
        """Convert a request object to cacheable parameters.

        Args:
            request: Request object (SearchRequest, etc.)

        Returns:
            Dictionary of parameters.
        """
        if hasattr(request, "model_dump"):
            return request.model_dump()  # type: ignore[no-any-return]
        if hasattr(request, "__dict__"):
            return {k: v for k, v in request.__dict__.items() if not k.startswith("_")}
        return {}

    async def get_search_results(
        self,
        request: Any,
    ) -> dict[str, Any] | None:
        """Get cached search results.

        Args:
            request: Search request.

        Returns:
            Cached results or None if not found.
        """
        if not self.config.enabled:
            return None

        params = self._request_to_params(request)

        # Don't cache very long queries
        if len(params.get("query", "")) > self.config.max_query_length:
            return None

        cache_key = self._generate_cache_key("results", params)

        try:
            cached = await self.redis.get(cache_key)
            if cached:
                logger.debug("Search cache hit for key: %s", cache_key)
                return cached  # type: ignore[no-any-return]
        except Exception as e:
            logger.warning("Failed to get search cache: %s", e)

        return None

    async def set_search_results(
        self,
        request: Any,
        results: Any,
        ttl: int | None = None,
    ) -> bool:
        """Cache search results.

        Args:
            request: Search request.
            results: Search results to cache.
            ttl: Time to live in seconds (optional).

        Returns:
            True if cached successfully.
        """
        if not self.config.enabled:
            return False

        params = self._request_to_params(request)

        # Don't cache very long queries
        if len(params.get("query", "")) > self.config.max_query_length:
            return False

        # Check if we should cache based on result count
        results_dict = self._request_to_params(results)
        total_hits = results_dict.get("total_hits", 0)

        if not self.config.cache_empty_results and total_hits == 0:
            return False

        if total_hits < self.config.min_results_to_cache:
            return False

        cache_key = self._generate_cache_key("results", params)
        cache_ttl = ttl or self.config.default_ttl

        try:
            await self.redis.set(cache_key, results_dict, ttl=cache_ttl)
            logger.debug("Cached search results for key: %s", cache_key)
            return True
        except Exception as e:
            logger.warning("Failed to set search cache: %s", e)
            return False

    async def get_suggestions(
        self,
        prefix: str,
        entity_type: str | None = None,
    ) -> dict[str, Any] | None:
        """Get cached suggestions.

        Args:
            prefix: Search prefix.
            entity_type: Optional entity type filter.

        Returns:
            Cached suggestions or None.
        """
        if not self.config.enabled:
            return None

        params = {"prefix": prefix, "entity_type": entity_type}
        cache_key = self._generate_cache_key("suggest", params)

        try:
            cached = await self.redis.get(cache_key)
            if cached:
                logger.debug("Suggestion cache hit for key: %s", cache_key)
                return cached  # type: ignore[no-any-return]
        except Exception as e:
            logger.warning("Failed to get suggestion cache: %s", e)

        return None

    async def set_suggestions(
        self,
        prefix: str,
        suggestions: Any,
        entity_type: str | None = None,
        ttl: int | None = None,
    ) -> bool:
        """Cache suggestions.

        Args:
            prefix: Search prefix.
            suggestions: Suggestions response.
            entity_type: Optional entity type filter.
            ttl: Time to live in seconds.

        Returns:
            True if cached successfully.
        """
        if not self.config.enabled:
            return False

        params = {"prefix": prefix, "entity_type": entity_type}
        cache_key = self._generate_cache_key("suggest", params)
        cache_ttl = ttl or self.config.suggestion_ttl

        try:
            suggestions_dict = self._request_to_params(suggestions)
            await self.redis.set(cache_key, suggestions_dict, ttl=cache_ttl)
            logger.debug("Cached suggestions for key: %s", cache_key)
            return True
        except Exception as e:
            logger.warning("Failed to set suggestion cache: %s", e)
            return False

    async def invalidate_search(
        self,
        query: str | None = None,
    ) -> int:
        """Invalidate search cache.

        Args:
            query: Specific query to invalidate, or all if None.

        Returns:
            Number of keys invalidated.
        """
        if query:
            # Invalidate specific query (all variations)
            pattern = f"{self.config.cache_prefix}:results:*"
        else:
            # Invalidate all search results
            pattern = f"{self.config.cache_prefix}:results:*"

        try:
            deleted = await self.redis.delete_pattern(pattern)
            logger.info("Invalidated %s search cache entries", deleted)
            return deleted
        except Exception as e:
            logger.warning("Failed to invalidate search cache: %s", e)
            return 0

    async def invalidate_suggestions(self) -> int:
        """Invalidate all suggestions cache.

        Returns:
            Number of keys invalidated.
        """
        pattern = f"{self.config.cache_prefix}:suggest:*"

        try:
            deleted = await self.redis.delete_pattern(pattern)
            logger.info("Invalidated %s suggestion cache entries", deleted)
            return deleted
        except Exception as e:
            logger.warning("Failed to invalidate suggestion cache: %s", e)
            return 0

    async def invalidate_all(self) -> int:
        """Invalidate all search-related cache.

        Returns:
            Number of keys invalidated.
        """
        pattern = f"{self.config.cache_prefix}:*"

        try:
            deleted = await self.redis.delete_pattern(pattern)
            logger.info("Invalidated %s total search cache entries", deleted)
            return deleted
        except Exception as e:
            logger.warning("Failed to invalidate all search cache: %s", e)
            return 0

    async def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with cache statistics.
        """
        stats = {
            "enabled": self.config.enabled,
            "default_ttl": self.config.default_ttl,
            "suggestion_ttl": self.config.suggestion_ttl,
        }

        try:
            # Count cached keys
            search_keys = []
            suggest_keys = []

            async for key in self.redis.scan_iter(
                match=f"{self.config.cache_prefix}:results:*"
            ):
                search_keys.append(key)

            async for key in self.redis.scan_iter(
                match=f"{self.config.cache_prefix}:suggest:*"
            ):
                suggest_keys.append(key)

            stats["cached_search_results"] = len(search_keys)
            stats["cached_suggestions"] = len(suggest_keys)
            stats["total_cached_keys"] = len(search_keys) + len(suggest_keys)

        except Exception as e:
            logger.warning("Failed to get cache stats: %s", e)
            stats["error"] = str(e)  # type: ignore[assignment]

        return stats


# Global cache instance
_search_cache: SearchCache | None = None


async def get_search_cache() -> SearchCache | None:
    """Get the global search cache instance.

    Returns:
        SearchCache instance or None if not initialized.
    """
    global _search_cache
    return _search_cache


async def init_search_cache(redis_cache: RedisCache) -> SearchCache:
    """Initialize the global search cache.

    Args:
        redis_cache: Redis cache instance.

    Returns:
        Initialized SearchCache.
    """
    global _search_cache
    _search_cache = SearchCache(redis_cache)
    logger.info("Search cache initialized")
    return _search_cache


__all__ = [
    "SearchCache",
    "SearchCacheConfig",
    "get_search_cache",
    "init_search_cache",
]
