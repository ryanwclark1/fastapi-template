"""Tests for search cache utilities."""

from __future__ import annotations

import asyncio

import pytest

from example_service.features.search.cache import (
    SearchCache,
    SearchCacheConfig,
    init_search_cache,
)


class DummyRedis:
    def __init__(self):
        self.storage = {}

    async def get(self, key):
        return self.storage.get(key)

    async def set(self, key, value, ttl=None):
        self.storage[key] = value
        return True

    async def delete_pattern(self, pattern: str):
        prefix = pattern.rstrip("*")
        keys = [k for k in self.storage if k.startswith(prefix)]
        for k in keys:
            del self.storage[k]
        return len(keys)

    async def scan_iter(self, match: str):
        prefix = match.rstrip("*")
        for k in self.storage:
            if k.startswith(prefix):
                yield k


class DummyRequest:
    def __init__(self, query="hi"):
        self.query = query

    def model_dump(self):
        return {"query": self.query, "filters": None}


class DummyResults:
    def __init__(self, total_hits: int):
        self.total_hits = total_hits

    def model_dump(self):
        return {"total_hits": self.total_hits}


@pytest.mark.asyncio
async def test_search_cache_set_and_get_results():
    cache = SearchCache(DummyRedis(), SearchCacheConfig())
    request = DummyRequest(query="hello")
    results = DummyResults(total_hits=2)

    stored = await cache.set_search_results(request, results)
    assert stored is True
    cached = await cache.get_search_results(request)
    assert cached["total_hits"] == 2


@pytest.mark.asyncio
async def test_search_cache_respects_max_query_length():
    cache = SearchCache(DummyRedis(), SearchCacheConfig(max_query_length=3))
    request = DummyRequest(query="toolong")
    results = DummyResults(total_hits=2)

    stored = await cache.set_search_results(request, results)
    assert stored is False
    assert await cache.get_search_results(request) is None


@pytest.mark.asyncio
async def test_suggestions_cache_and_stats(monkeypatch: pytest.MonkeyPatch):
    redis = DummyRedis()
    cache = SearchCache(redis, SearchCacheConfig())

    class Suggest:
        def __init__(self):
            self.items = [1, 2]

        def model_dump(self):
            return {"items": self.items}

    await cache.set_suggestions(prefix="ab", suggestions=Suggest(), entity_type=None)
    assert await cache.get_suggestions("ab") == {"items": [1, 2]}

    stats = await cache.get_cache_stats()
    assert stats["total_cached_keys"] >= 1


@pytest.mark.asyncio
async def test_invalidation_helpers():
    redis = DummyRedis()
    cache = SearchCache(redis, SearchCacheConfig())
    request = DummyRequest(query="hello")
    await cache.set_search_results(request, DummyResults(total_hits=1))
    await cache.set_suggestions(prefix="ab", suggestions=DummyResults(total_hits=0), entity_type=None)

    assert await cache.invalidate_search() >= 1
    assert await cache.invalidate_suggestions() >= 0
    assert await cache.invalidate_all() >= 0


@pytest.mark.asyncio
async def test_global_cache_init(monkeypatch: pytest.MonkeyPatch):
    redis = DummyRedis()
    cache = await init_search_cache(redis)
    assert cache.redis is redis
