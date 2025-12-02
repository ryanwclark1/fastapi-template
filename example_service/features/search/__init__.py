"""Unified search feature using PostgreSQL full-text search.

Provides comprehensive search capabilities:
- Multi-entity search with a single query
- Multiple query syntax modes (plain, web, phrase)
- Result highlighting
- Relevance ranking
- Search suggestions/autocomplete

This module builds on the core FTS infrastructure in
`core/database/search/` to provide a high-level search API.

Usage:
    from example_service.features.search import SearchService

    service = SearchService(session)

    # Search across all entities
    results = await service.search(SearchRequest(
        query="important meeting",
        entity_types=["reminders"],
        highlight=True,
    ))

    # Get autocomplete suggestions
    suggestions = await service.suggest(SearchSuggestionRequest(
        prefix="imp",
    ))
"""

from __future__ import annotations

from .router import router
from .schemas import (
    EntitySearchResult,
    SearchableEntity,
    SearchCapabilitiesResponse,
    SearchHit,
    SearchRequest,
    SearchResponse,
    SearchSuggestion,
    SearchSuggestionRequest,
    SearchSuggestionsResponse,
    SearchSyntax,
)
from .service import SearchService, get_search_service

__all__ = [
    # Service
    "SearchService",
    "get_search_service",
    # Schemas
    "SearchSyntax",
    "SearchRequest",
    "SearchHit",
    "EntitySearchResult",
    "SearchResponse",
    "SearchSuggestionRequest",
    "SearchSuggestion",
    "SearchSuggestionsResponse",
    "SearchableEntity",
    "SearchCapabilitiesResponse",
    # Router
    "router",
]
