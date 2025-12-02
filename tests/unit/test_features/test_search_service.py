"""Tests for SearchService utility behaviors."""

from __future__ import annotations

import pytest

from example_service.features.search import service as search_service


class DummyCache:
    pass


def test_get_capabilities_lists_entities():
    svc = search_service.SearchService(session=None, enable_analytics=False, enable_cache=False)
    capabilities = svc.get_capabilities()
    names = {entity.name for entity in capabilities.entities}
    assert "reminders" in names
    assert "users" in names
    assert "full_text_search" in capabilities.features


@pytest.mark.asyncio
async def test_get_cache_respects_flags(monkeypatch: pytest.MonkeyPatch):
    cache = DummyCache()
    svc = search_service.SearchService(session=None, enable_cache=True, cache=cache, enable_analytics=False)
    assert await svc._get_cache() is cache

    svc_disabled = search_service.SearchService(session=None, enable_cache=False, enable_analytics=False)
    assert await svc_disabled._get_cache() is None

    called = []

    async def fake_get_search_cache():
        called.append(True)
        return cache

    svc_global = search_service.SearchService(session=None, enable_cache=True, enable_analytics=False)
    monkeypatch.setattr(search_service, "get_search_cache", fake_get_search_cache)
    assert await svc_global._get_cache() is cache
    assert called
