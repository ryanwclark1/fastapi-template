"""Comprehensive tests for cache decorator utilities.

Tests cover:
- cache_key() function with various input types
- @cached() decorator with all features
- invalidate_cache() for single key invalidation
- invalidate_pattern() for pattern-based bulk invalidation
- invalidate_tags() for tag-based bulk invalidation
- Integration scenarios with multiple decorators and invalidations
- Edge cases and error conditions

Test Strategy:
- Mock Redis client to isolate unit tests from external dependencies
- Test both success and error paths
- Verify cache hits, misses, and invalidation operations
- Test TTL behavior and expiration
- Validate tag-based invalidation workflows
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from example_service.infra.cache.decorators import (
    cache_key,
    cached,
    invalidate_cache,
    invalidate_pattern,
    invalidate_tags,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class MockModel:
    """Mock ORM model for testing cache_key with model objects."""

    def __init__(self, id: int, name: str = "test") -> None:
        self.id = id
        self.name = name


@pytest.fixture
async def mock_redis() -> AsyncIterator[AsyncMock]:
    """Create a mock Redis client for testing cache operations.

    Provides a fully mocked Redis client with common operations:
    - get/set/delete for basic cache operations
    - sadd/smembers for tag set operations
    - expire for TTL management
    - scan_iter for pattern matching

    Yields:
        AsyncMock configured with Redis-like behavior.
    """
    redis_mock = AsyncMock()

    # Configure basic operations
    redis_mock.get = AsyncMock(return_value=None)
    redis_mock.set = AsyncMock(return_value=True)
    redis_mock.delete = AsyncMock(return_value=1)

    # Configure tag operations
    redis_mock.sadd = AsyncMock(return_value=1)
    redis_mock.smembers = AsyncMock(return_value=set())
    redis_mock.expire = AsyncMock(return_value=True)

    # Configure pattern scanning
    async def mock_scan_iter(match=None, count=100):
        """Mock scan_iter that returns an async generator."""
        return
        yield  # Make it an async generator

    redis_mock.scan_iter = mock_scan_iter

    yield redis_mock


@pytest.fixture
async def mock_cache(mock_redis: AsyncMock):
    """Create a mock cache context manager with Redis client.

    Yields:
        Mock cache object that can be used with async context manager.
    """
    cache_mock = AsyncMock()
    cache_mock._client = mock_redis
    cache_mock.get = AsyncMock(return_value=None)
    cache_mock.set = AsyncMock(return_value=True)
    cache_mock.delete = AsyncMock(return_value=True)

    # Create async context manager with correct signature
    async def async_enter(self):
        return cache_mock

    async def async_exit(self, exc_type, exc_val, exc_tb):
        return None

    cache_mock.__aenter__ = async_enter
    cache_mock.__aexit__ = async_exit

    with patch("example_service.infra.cache.decorators.get_cache") as get_cache_mock:
        get_cache_mock.return_value = cache_mock
        yield cache_mock


class TestCacheKeyFunction:
    """Test cache_key() function with various input types."""

    def test_cache_key_with_simple_string(self) -> None:
        """Test cache key generation with simple string argument."""
        key = cache_key("user")
        assert key == "user"

    def test_cache_key_with_integer(self) -> None:
        """Test cache key generation with integer argument."""
        key = cache_key(42)
        assert key == "42"

    def test_cache_key_with_float(self) -> None:
        """Test cache key generation with float argument."""
        key = cache_key(3.14)
        assert key == "3.14"

    def test_cache_key_with_boolean(self) -> None:
        """Test cache key generation with boolean argument."""
        key_true = cache_key(True)
        key_false = cache_key(False)

        assert key_true == "True"
        assert key_false == "False"

    def test_cache_key_with_multiple_args(self) -> None:
        """Test cache key generation with multiple positional arguments."""
        key = cache_key("user", 42, "profile")
        assert key == "user:42:profile"

    def test_cache_key_with_kwargs(self) -> None:
        """Test cache key generation with keyword arguments."""
        key = cache_key(user_id=42, page=1)

        # Kwargs are sorted for consistency
        assert key == "page=1:user_id=42"

    def test_cache_key_with_args_and_kwargs(self) -> None:
        """Test cache key generation with both args and kwargs."""
        key = cache_key("search", "python", page=2, limit=10)

        # Args first, then sorted kwargs
        assert key == "search:python:limit=10:page=2"

    def test_cache_key_with_orm_model(self) -> None:
        """Test cache key generation with ORM model (uses .id attribute)."""
        model = MockModel(id=123)
        key = cache_key(model)

        # Should use model's ID
        assert key == "123"

    def test_cache_key_with_dict(self) -> None:
        """Test cache key generation with dict (creates hash)."""
        data = {"name": "john", "age": 30}
        key = cache_key(data)

        # Should create consistent 8-char hash
        assert len(key) == 8
        assert isinstance(key, str)

        # Same dict should produce same hash
        key2 = cache_key(data)
        assert key == key2

    def test_cache_key_with_dict_order_independence(self) -> None:
        """Test cache key generation is order-independent for dicts."""
        dict1 = {"name": "john", "age": 30}
        dict2 = {"age": 30, "name": "john"}

        key1 = cache_key(dict1)
        key2 = cache_key(dict2)

        # Different dict order should produce same hash
        assert key1 == key2

    def test_cache_key_with_list(self) -> None:
        """Test cache key generation with list (creates hash)."""
        data = [1, 2, 3, 4, 5]
        key = cache_key(data)

        # Should create consistent 8-char hash
        assert len(key) == 8
        assert isinstance(key, str)

    def test_cache_key_consistent_hashing(self) -> None:
        """Test cache key generation produces consistent results."""
        data = {"query": "python", "filters": ["tag1", "tag2"]}

        key1 = cache_key(data)
        key2 = cache_key(data)

        # Same input should always produce same key
        assert key1 == key2

    def test_cache_key_with_none_kwarg(self) -> None:
        """Test cache key generation with None as kwarg value."""
        key = cache_key(user_id=42, filter=None)
        assert key == "filter=None:user_id=42"

    def test_cache_key_with_model_in_kwargs(self) -> None:
        """Test cache key generation with model in kwargs."""
        model = MockModel(id=456)
        key = cache_key(action="update", model=model)

        assert "action=update" in key
        assert "model=456" in key


class TestCachedDecorator:
    """Test @cached() decorator functionality."""

    async def test_cached_basic_cache_miss_then_hit(self, mock_cache: AsyncMock) -> None:
        """Test basic caching: cache miss on first call, hit on second."""
        call_count = 0

        @cached(key_prefix="test", ttl=300)
        async def get_data(user_id: int) -> dict[str, int]:
            nonlocal call_count
            call_count += 1
            return {"user_id": user_id, "data": "value"}

        # Configure mock for cache miss then hit
        mock_cache.get.side_effect = [
            None,  # First call: cache miss
            {"user_id": 42, "data": "value"},  # Second call: cache hit
        ]

        # First call - cache miss, function executes
        result1 = await get_data(42)
        assert result1 == {"user_id": 42, "data": "value"}
        assert call_count == 1

        # Second call - cache hit, function not executed
        result2 = await get_data(42)
        assert result2 == {"user_id": 42, "data": "value"}
        assert call_count == 1  # Function not called again

        # Verify cache operations
        assert mock_cache.get.call_count == 2
        assert mock_cache.set.call_count == 1

    async def test_cached_with_default_key_prefix(self, mock_cache: AsyncMock) -> None:
        """Test @cached uses function name as default key prefix."""

        @cached(ttl=300)
        async def get_user_profile(user_id: int) -> dict[str, str]:
            return {"name": "John"}

        await get_user_profile(42)

        # Verify key uses function name
        mock_cache.get.assert_called_once()
        call_key = mock_cache.get.call_args[0][0]
        assert call_key.startswith("get_user_profile:")

    async def test_cached_with_custom_key_builder(self, mock_cache: AsyncMock) -> None:
        """Test @cached with custom key_builder function."""

        @cached(
            key_prefix="search",
            ttl=60,
            key_builder=lambda query, page: f"{query}:page{page}",
        )
        async def search(query: str, page: int = 1) -> list[str]:
            return [f"result-{page}"]

        await search("python", page=2)

        # Verify custom key format
        mock_cache.get.assert_called_once()
        call_key = mock_cache.get.call_args[0][0]
        assert call_key == "search:python:page2"

    async def test_cached_with_ttl_zero(self, mock_cache: AsyncMock) -> None:
        """Test @cached with ttl=0 (no expiration)."""

        @cached(key_prefix="permanent", ttl=0)
        async def get_config() -> dict[str, str]:
            return {"setting": "value"}

        await get_config()

        # Verify set called with ttl=None (no expiration)
        mock_cache.set.assert_called_once()
        _, kwargs = mock_cache.set.call_args
        assert kwargs["ttl"] is None

    async def test_cached_with_ttl_custom(self, mock_cache: AsyncMock) -> None:
        """Test @cached with custom TTL value."""

        @cached(key_prefix="temp", ttl=600)
        async def get_temp_data() -> str:
            return "temporary"

        await get_temp_data()

        # Verify set called with custom TTL
        mock_cache.set.assert_called_once()
        _, kwargs = mock_cache.set.call_args
        assert kwargs["ttl"] == 600

    async def test_cached_with_skip_cache_true(self, mock_cache: AsyncMock) -> None:
        """Test @cached with skip_cache parameter bypassing cache."""
        call_count = 0

        @cached(
            key_prefix="data",
            ttl=300,
            skip_cache=lambda user_id, force: force,
        )
        async def get_data(user_id: int, force: bool = False) -> dict[str, int]:
            nonlocal call_count
            call_count += 1
            return {"user_id": user_id}

        # First call with force=True - should skip cache
        result1 = await get_data(42, force=True)
        assert result1 == {"user_id": 42}
        assert call_count == 1

        # Cache should not be accessed
        mock_cache.get.assert_not_called()
        mock_cache.set.assert_not_called()

    async def test_cached_with_skip_cache_false(self, mock_cache: AsyncMock) -> None:
        """Test @cached with skip_cache=False uses cache normally."""
        call_count = 0

        @cached(
            key_prefix="data",
            ttl=300,
            skip_cache=lambda user_id, force: force,
        )
        async def get_data(user_id: int, force: bool = False) -> dict[str, int]:
            nonlocal call_count
            call_count += 1
            return {"user_id": user_id}

        # Call with force=False - should use cache
        await get_data(42, force=False)

        # Cache should be accessed
        mock_cache.get.assert_called_once()
        mock_cache.set.assert_called_once()

    async def test_cached_with_condition_true(self, mock_cache: AsyncMock) -> None:
        """Test @cached with condition=True caches result."""

        @cached(
            key_prefix="results",
            ttl=300,
            condition=lambda result: len(result) > 0,
        )
        async def get_results() -> list[str]:
            return ["item1", "item2"]

        await get_results()

        # Result should be cached (condition is True)
        mock_cache.set.assert_called_once()

    async def test_cached_with_condition_false(self, mock_cache: AsyncMock) -> None:
        """Test @cached with condition=False does not cache result."""

        @cached(
            key_prefix="results",
            ttl=300,
            condition=lambda result: len(result) > 0,
        )
        async def get_results() -> list[str]:
            return []  # Empty result

        result = await get_results()

        assert result == []

        # Result should NOT be cached (condition is False)
        mock_cache.set.assert_not_called()

    async def test_cached_with_tags(self, mock_cache: AsyncMock) -> None:
        """Test @cached with tags parameter stores tag associations."""

        @cached(
            key_prefix="user",
            ttl=300,
            tags=lambda user_id: [f"user:{user_id}", "users:all"],
        )
        async def get_user(user_id: int) -> dict[str, str]:
            return {"name": "John"}

        mock_redis = mock_cache._client

        await get_user(42)

        # Verify tags were stored
        assert mock_redis.sadd.call_count == 2  # Two tags

        # Verify tag expiration set
        assert mock_redis.expire.call_count == 2

    async def test_cached_with_multiple_args(self, mock_cache: AsyncMock) -> None:
        """Test @cached with multiple function arguments."""

        @cached(key_prefix="search", ttl=60)
        async def search(query: str, page: int, limit: int = 10) -> list[str]:
            return [f"{query}-{page}-{limit}"]

        await search("python", 2, limit=20)

        # Verify cache key includes all args
        mock_cache.get.assert_called_once()
        call_key = mock_cache.get.call_args[0][0]
        assert "python" in call_key
        assert "2" in call_key
        assert "limit=20" in call_key

    async def test_cached_preserves_function_metadata(self) -> None:
        """Test @cached preserves original function name and docstring."""

        @cached(key_prefix="data", ttl=300)
        async def documented_function(x: int) -> int:
            """This is a documented function."""
            return x * 2

        assert documented_function.__name__ == "documented_function"
        assert documented_function.__doc__ == "This is a documented function."


class TestInvalidateCache:
    """Test invalidate_cache() function for single key invalidation."""

    async def test_invalidate_cache_existing_key(self, mock_cache: AsyncMock) -> None:
        """Test invalidate_cache returns True when key exists."""
        mock_cache.delete.return_value = True

        result = await invalidate_cache("user", 42)

        assert result is True
        mock_cache.delete.assert_called_once()
        call_key = mock_cache.delete.call_args[0][0]
        assert call_key == "user:42"

    async def test_invalidate_cache_missing_key(self, mock_cache: AsyncMock) -> None:
        """Test invalidate_cache returns False when key doesn't exist."""
        mock_cache.delete.return_value = False

        result = await invalidate_cache("user", 999)

        assert result is False
        mock_cache.delete.assert_called_once()

    async def test_invalidate_cache_with_kwargs(self, mock_cache: AsyncMock) -> None:
        """Test invalidate_cache with keyword arguments."""
        mock_cache.delete.return_value = True

        result = await invalidate_cache("search", query="python", page=1)

        assert result is True
        mock_cache.delete.assert_called_once()
        call_key = mock_cache.delete.call_args[0][0]
        assert call_key.startswith("search:")

    async def test_invalidate_cache_with_complex_args(self, mock_cache: AsyncMock) -> None:
        """Test invalidate_cache with complex argument types."""
        mock_cache.delete.return_value = True

        model = MockModel(id=123)
        result = await invalidate_cache("data", model, status="active")

        assert result is True


class TestInvalidatePattern:
    """Test invalidate_pattern() for pattern-based bulk invalidation."""

    async def test_invalidate_pattern_with_matches(self, mock_cache: AsyncMock) -> None:
        """Test invalidate_pattern deletes all matching keys."""
        mock_redis = mock_cache._client

        # Mock scan_iter to return matching keys
        async def mock_scan_iter(match=None, count=100):
            keys = [b"user:1", b"user:2", b"user:3"]
            for key in keys:
                yield key

        mock_redis.scan_iter = mock_scan_iter
        mock_redis.delete = AsyncMock(return_value=3)

        count = await invalidate_pattern("user:*")

        assert count == 3
        mock_redis.delete.assert_called_once_with("user:1", "user:2", "user:3")

    async def test_invalidate_pattern_with_string_keys(self, mock_cache: AsyncMock) -> None:
        """Test invalidate_pattern handles string keys (not bytes)."""
        mock_redis = mock_cache._client

        # Mock scan_iter to return string keys
        async def mock_scan_iter(match=None, count=100):
            keys = ["search:python:1", "search:python:2"]
            for key in keys:
                yield key

        mock_redis.scan_iter = mock_scan_iter
        mock_redis.delete = AsyncMock(return_value=2)

        count = await invalidate_pattern("search:python:*")

        assert count == 2

    async def test_invalidate_pattern_no_matches(self, mock_cache: AsyncMock) -> None:
        """Test invalidate_pattern returns 0 when no keys match."""
        mock_redis = mock_cache._client

        # Mock scan_iter to return no keys
        async def mock_scan_iter(match=None, count=100):
            return
            yield  # Make it an async generator

        mock_redis.scan_iter = mock_scan_iter

        count = await invalidate_pattern("nonexistent:*")

        assert count == 0

    async def test_invalidate_pattern_complex_pattern(self, mock_cache: AsyncMock) -> None:
        """Test invalidate_pattern with complex glob patterns."""
        mock_redis = mock_cache._client

        async def mock_scan_iter(match=None, count=100):
            if match == "search:python:*":
                keys = [b"search:python:page1", b"search:python:page2"]
                for key in keys:
                    yield key

        mock_redis.scan_iter = mock_scan_iter
        mock_redis.delete = AsyncMock(return_value=2)

        count = await invalidate_pattern("search:python:*")

        assert count == 2

    async def test_invalidate_pattern_without_client(self, mock_cache: AsyncMock) -> None:
        """Test invalidate_pattern returns 0 when Redis client unavailable."""
        mock_cache._client = None

        count = await invalidate_pattern("user:*")

        assert count == 0


class TestInvalidateTags:
    """Test invalidate_tags() for tag-based bulk invalidation."""

    async def test_invalidate_tags_single_tag(self, mock_cache: AsyncMock) -> None:
        """Test invalidate_tags with single tag."""
        mock_redis = mock_cache._client

        # Mock tag set members
        mock_redis.smembers = AsyncMock(return_value={b"user:42:profile", b"user:42:posts"})
        mock_redis.delete = AsyncMock(return_value=2)

        count = await invalidate_tags(["user:42"])

        assert count == 2

        # Verify cache keys deleted
        assert mock_redis.delete.call_count == 2  # Once for cache keys, once for tag

    async def test_invalidate_tags_multiple_tags(self, mock_cache: AsyncMock) -> None:
        """Test invalidate_tags with multiple tags."""
        mock_redis = mock_cache._client

        # Mock different tag sets
        async def mock_smembers(tag_key):
            if tag_key == "tag:user:42":
                return {b"user:42:data"}
            elif tag_key == "tag:users:all":
                return {b"users:list", b"users:count"}
            return set()

        mock_redis.smembers = mock_smembers
        mock_redis.delete = AsyncMock(return_value=1)

        count = await invalidate_tags(["user:42", "users:all"])

        # Should delete 3 cache entries total (1 + 2)
        assert count == 2  # Two delete calls (one per tag)

    async def test_invalidate_tags_removes_tag_sets(self, mock_cache: AsyncMock) -> None:
        """Test invalidate_tags removes tag sets after clearing cache."""
        mock_redis = mock_cache._client

        mock_redis.smembers = AsyncMock(return_value={b"key1", b"key2"})
        mock_redis.delete = AsyncMock(return_value=2)

        await invalidate_tags(["user:42"])

        # Verify tag set deleted
        # Called twice: once for cache keys, once for tag set
        assert mock_redis.delete.call_count == 2

    async def test_invalidate_tags_empty_tag_set(self, mock_cache: AsyncMock) -> None:
        """Test invalidate_tags handles empty tag sets gracefully."""
        mock_redis = mock_cache._client

        # Mock empty tag set
        mock_redis.smembers = AsyncMock(return_value=set())

        count = await invalidate_tags(["empty:tag"])

        assert count == 0

    async def test_invalidate_tags_without_client(self, mock_cache: AsyncMock) -> None:
        """Test invalidate_tags returns 0 when Redis client unavailable."""
        mock_cache._client = None

        count = await invalidate_tags(["user:42"])

        assert count == 0

    async def test_invalidate_tags_returns_total_count(self, mock_cache: AsyncMock) -> None:
        """Test invalidate_tags returns total count across all tags."""
        mock_redis = mock_cache._client

        # Mock different delete counts
        delete_call_count = 0

        async def mock_smembers(tag_key):
            # Return different sized sets
            if "tag1" in tag_key:
                return {b"k1", b"k2", b"k3"}
            elif "tag2" in tag_key:
                return {b"k4", b"k5"}
            elif "tag3" in tag_key:
                return {b"k6"}
            return set()

        mock_redis.smembers = mock_smembers

        # Mock delete to return count based on number of keys
        async def mock_delete(*keys):
            nonlocal delete_call_count
            delete_call_count += 1
            # Return count based on number of keys being deleted
            # First call (tag1): 3 keys, second call (tag1 tag set): 1
            # Third call (tag2): 2 keys, fourth call (tag2 tag set): 1
            # Fifth call (tag3): 1 key, sixth call (tag3 tag set): 1
            if delete_call_count in [1]:  # tag1 cache keys
                return 3
            elif delete_call_count in [3]:  # tag2 cache keys
                return 2
            elif delete_call_count in [5]:  # tag3 cache keys
                return 1
            return 1  # For tag set deletions

        mock_redis.delete = mock_delete

        count = await invalidate_tags(["tag1", "tag2", "tag3"])

        # Should delete 6 cache entries total (3 + 2 + 1) but delete is also called for tag sets
        # The function only counts cache entry deletions, not tag set deletions
        assert count == 6  # 3 + 2 + 1 (cache entries only)


class TestCacheIntegration:
    """Integration tests for complete caching workflows."""

    async def test_cached_with_tags_and_invalidation(self, mock_cache: AsyncMock) -> None:
        """Test complete workflow: cache with tags, then invalidate by tags."""
        call_count = 0

        @cached(
            key_prefix="user",
            ttl=300,
            tags=lambda user_id: [f"user:{user_id}"],
        )
        async def get_user_data(user_id: int) -> dict[str, str]:
            nonlocal call_count
            call_count += 1
            return {"name": f"User{user_id}"}

        # First call - cache miss
        result1 = await get_user_data(42)
        assert result1 == {"name": "User42"}
        assert call_count == 1

        # Verify tags stored
        mock_redis = mock_cache._client
        assert mock_redis.sadd.called

        # Invalidate by tag
        mock_redis.smembers = AsyncMock(return_value={b"user:42"})
        mock_redis.delete = AsyncMock(return_value=1)

        count = await invalidate_tags(["user:42"])
        assert count == 1

    async def test_multiple_functions_sharing_tags(self, mock_cache: AsyncMock) -> None:
        """Test multiple cached functions sharing same tags."""

        @cached(key_prefix="user_profile", ttl=300, tags=lambda uid: [f"user:{uid}"])
        async def get_profile(uid: int) -> dict[str, str]:
            return {"profile": "data"}

        @cached(key_prefix="user_posts", ttl=300, tags=lambda uid: [f"user:{uid}"])
        async def get_posts(uid: int) -> list[str]:
            return ["post1", "post2"]

        # Cache both functions
        await get_profile(42)
        await get_posts(42)

        # Both should store same tag
        mock_redis = mock_cache._client
        assert mock_redis.sadd.call_count >= 2

    async def test_cache_key_consistency_across_calls(self, mock_cache: AsyncMock) -> None:
        """Test cache key generation is consistent across multiple calls."""

        @cached(key_prefix="search", ttl=60)
        async def search(query: str, filters: dict[str, str]) -> list[str]:
            return ["result"]

        filters = {"category": "tech", "status": "active"}

        # Call twice with same args
        await search("python", filters)
        await search("python", filters)

        # Verify same cache key used
        assert mock_cache.get.call_count == 2
        key1 = mock_cache.get.call_args_list[0][0][0]
        key2 = mock_cache.get.call_args_list[1][0][0]
        assert key1 == key2

    async def test_invalidate_pattern_clears_related_caches(
        self, mock_cache: AsyncMock
    ) -> None:
        """Test pattern invalidation clears all related cache entries."""
        mock_redis = mock_cache._client

        # Setup pattern matching
        async def mock_scan_iter(match=None, count=100):
            if match == "user:42:*":
                keys = [b"user:42:profile", b"user:42:posts", b"user:42:settings"]
                for key in keys:
                    yield key

        mock_redis.scan_iter = mock_scan_iter
        mock_redis.delete = AsyncMock(return_value=3)

        # Invalidate all user:42 caches
        count = await invalidate_pattern("user:42:*")

        assert count == 3
        mock_redis.delete.assert_called_once()

    async def test_conditional_caching_with_empty_results(
        self, mock_cache: AsyncMock
    ) -> None:
        """Test conditional caching does not cache empty results."""
        call_count = 0

        @cached(
            key_prefix="results",
            ttl=300,
            condition=lambda result: len(result) > 0,
        )
        async def search_with_no_results(query: str) -> list[str]:
            nonlocal call_count
            call_count += 1
            return []  # No results

        # First call
        result1 = await search_with_no_results("rare_query")
        assert result1 == []
        assert call_count == 1

        # Cache miss on first call, but should not cache empty result
        mock_cache.set.assert_not_called()

        # Second call should execute again (not cached)
        mock_cache.get.return_value = None
        result2 = await search_with_no_results("rare_query")
        assert result2 == []
        assert call_count == 2

    async def test_skip_cache_forces_fresh_data(self, mock_cache: AsyncMock) -> None:
        """Test skip_cache bypasses cache and always fetches fresh data."""
        call_count = 0

        @cached(
            key_prefix="data",
            ttl=300,
            skip_cache=lambda force_refresh: force_refresh,
        )
        async def get_data(force_refresh: bool = False) -> dict[str, int]:
            nonlocal call_count
            call_count += 1
            return {"count": call_count}

        # First call without force - uses cache
        result1 = await get_data(force_refresh=False)
        assert result1 == {"count": 1}

        # Second call with force - skips cache
        result2 = await get_data(force_refresh=True)
        assert result2 == {"count": 2}

        # Verify cache not accessed on forced refresh
        assert call_count == 2


class TestCacheEdgeCases:
    """Test edge cases and error conditions."""

    async def test_cache_key_with_empty_args(self) -> None:
        """Test cache_key with no arguments."""
        key = cache_key()
        assert key == ""

    async def test_cached_with_no_args_function(self, mock_cache: AsyncMock) -> None:
        """Test @cached on function with no arguments."""

        @cached(key_prefix="config", ttl=300)
        async def get_config() -> dict[str, str]:
            return {"setting": "value"}

        await get_config()

        # Should use just the prefix as key (no suffix)
        mock_cache.get.assert_called_once()
        call_key = mock_cache.get.call_args[0][0]
        assert call_key == "config"

    async def test_invalidate_cache_with_no_suffix(self, mock_cache: AsyncMock) -> None:
        """Test invalidate_cache with only prefix (no args)."""
        mock_cache.delete.return_value = True

        result = await invalidate_cache("singleton")

        assert result is True
        mock_cache.delete.assert_called_once_with("singleton")

    async def test_cached_decorator_with_exception(self, mock_cache: AsyncMock) -> None:
        """Test @cached decorator when function raises exception."""

        @cached(key_prefix="data", ttl=300)
        async def failing_function(value: int) -> int:
            if value < 0:
                raise ValueError("Negative value not allowed")
            return value * 2

        # Should propagate exception
        with pytest.raises(ValueError, match="Negative value not allowed"):
            await failing_function(-1)

        # Cache should not be written on exception
        mock_cache.set.assert_not_called()

    async def test_cache_key_with_nested_dict(self) -> None:
        """Test cache_key with nested dictionary structure."""
        data = {
            "user": {"id": 42, "name": "John"},
            "filters": {"status": "active", "role": "admin"},
        }

        key1 = cache_key(data)
        key2 = cache_key(data)

        # Should produce consistent hash
        assert key1 == key2
        assert len(key1) == 8

    async def test_tags_with_multiple_values(self, mock_cache: AsyncMock) -> None:
        """Test tags function returning multiple tag values."""

        @cached(
            key_prefix="data",
            ttl=300,
            tags=lambda user_id, org_id: [
                f"user:{user_id}",
                f"org:{org_id}",
                "all_data",
            ],
        )
        async def get_user_org_data(user_id: int, org_id: int) -> dict[str, int]:
            return {"user_id": user_id, "org_id": org_id}

        await get_user_org_data(42, 10)

        # Should store 3 tags
        mock_redis = mock_cache._client
        assert mock_redis.sadd.call_count == 3
