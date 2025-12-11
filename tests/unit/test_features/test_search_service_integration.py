"""Focused tests for SearchService behavior without touching the DB."""

from __future__ import annotations

import pytest

from example_service.features.search import service as search_service
from example_service.features.search.config import (
    EntitySearchConfig,
    SearchConfiguration,
    SearchEntityRegistry,
    SearchSettings,
)
from example_service.features.search.schemas import (
    DidYouMeanSuggestion,
    EntitySearchResult,
    FacetResult,
    SearchRequest,
    SearchResponse,
)


def _single_entity_config() -> SearchConfiguration:
    """Build a minimal configuration with a single reminders entity."""
    registry = SearchEntityRegistry()
    registry.register(
        "reminders",
        EntitySearchConfig(
            display_name="Reminders",
            model_path="example_service.features.reminders.models.Reminder",
            search_fields=["title"],
            title_field="title",
            snippet_field="description",
            fuzzy_fields=["title"],
            facet_fields=[],
        ),
    )
    return SearchConfiguration(settings=SearchSettings(), entity_registry=registry)


@pytest.mark.asyncio
async def test_search_uses_cache_and_sets_results(monkeypatch: pytest.MonkeyPatch) -> None:

    class Cache:
        def __init__(self):
            self.set_called = False

        async def get_search_results(self, request):
            return None

        async def set_search_results(self, request, response):
            self.set_called = True

    svc = search_service.SearchService(
        session=None,
        enable_cache=True,
        cache=Cache(),
        enable_analytics=False,
        enable_fuzzy_fallback=False,
        config=_single_entity_config(),
    )
    async def stub_search(entity_type, req, expanded_query, intent):
        return EntitySearchResult(entity_type=entity_type, total=1, hits=[])

    monkeypatch.setattr(svc, "_search_entity", stub_search)

    resp = await svc.search(SearchRequest(query="hello"))
    assert isinstance(resp, SearchResponse)
    assert resp.total_hits == 1
    assert svc._cache.set_called  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_search_records_analytics_and_handles_low_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    analytics_calls = []

    class Analytics:
        async def record_search(self, **kwargs):
            analytics_calls.append(kwargs)

    svc = search_service.SearchService(
        session=None,
        enable_cache=False,
        enable_analytics=True,
        enable_fuzzy_fallback=True,
        config=_single_entity_config(),
    )
    svc._analytics = Analytics()  # type: ignore[assignment]

    async def stub_search(entity_type, req, expanded_query, intent):
        return EntitySearchResult(
            entity_type=entity_type,
            total=0,
            hits=[],
            facets=[FacetResult(field="f", values=[], display_name="f")],
        )

    monkeypatch.setattr(svc, "_search_entity", stub_search)
    async def stub_suggestions(query):
        return ["sugg"]

    async def stub_dym(*_, **__):
        return DidYouMeanSuggestion(
            original_query="none", suggested_query="other", confidence=0.9,
        )

    monkeypatch.setattr(svc, "_generate_did_you_mean", stub_dym)
    monkeypatch.setattr(svc, "_generate_suggestions", stub_suggestions)

    resp = await svc.search(SearchRequest(query="none", include_facets=True))
    assert resp.did_you_mean is not None
    assert resp.suggestions == ["sugg"]
    assert analytics_calls
    assert analytics_calls[0]["results_count"] == 0
