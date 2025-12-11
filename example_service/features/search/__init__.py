"""Unified search feature using PostgreSQL full-text search.

Provides comprehensive search capabilities:
- Multi-entity search with a single query
- Multiple query syntax modes (plain, web, phrase)
- Result highlighting
- Relevance ranking
- Search suggestions/autocomplete
- Synonym expansion for improved recall
- Click signal boosting for ranking
- Query intent classification
- Performance profiling and slow query detection
- Redis caching with circuit breaker
- A/B testing framework for experiments
- Semantic/vector search support

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

from .cache import SearchCache, SearchCacheConfig, get_search_cache, init_search_cache
from .circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerStats,
    CircuitState,
    get_circuit_breaker,
    get_circuit_stats,
)
from .config import (
    EntitySearchConfig,
    SearchConfiguration,
    SearchEntityRegistry,
    SearchFeature,
    SearchSettings,
    create_default_configuration,
    get_search_config,
    set_search_config,
)
from .experiments import (
    ExperimentConfig,
    ExperimentManager,
    ExperimentResults,
    ExperimentStatus,
    SearchExperiment,
)
from .intent import IntentClassifier, IntentType, QueryIntent, classify_query_intent
from .profiler import PerformanceStats, QueryProfile, QueryProfiler
from .ranking import ClickBoostRanker, ClickSignal, RankingConfig
from .router import router
from .schemas import (
    EntitySearchResult,
    SearchableEntity,
    SearchCapabilitiesResponse,
    SearchFilter,
    SearchHit,
    SearchRequest,
    SearchResponse,
    SearchSuggestion,
    SearchSuggestionRequest,
    SearchSuggestionsResponse,
    SearchSyntax,
)
from .service import SearchService, get_search_service
from .vector import (
    DistanceMetric,
    EmbeddingProvider,
    HybridSearchResult,
    VectorSearchConfig,
    VectorSearchResult,
    VectorSearchService,
)

__all__ = [
    # Circuit Breaker
    "CircuitBreaker",
    "CircuitBreakerStats",
    "CircuitState",
    # Ranking
    "ClickBoostRanker",
    "ClickSignal",
    # Vector Search
    "DistanceMetric",
    "EmbeddingProvider",
    # Configuration
    "EntitySearchConfig",
    # Schemas
    "EntitySearchResult",
    # Experiments
    "ExperimentConfig",
    "ExperimentManager",
    "ExperimentResults",
    "ExperimentStatus",
    "HybridSearchResult",
    # Intent
    "IntentClassifier",
    "IntentType",
    # Profiler
    "PerformanceStats",
    "QueryIntent",
    "QueryProfile",
    "QueryProfiler",
    "RankingConfig",
    # Cache
    "SearchCache",
    "SearchCacheConfig",
    "SearchCapabilitiesResponse",
    "SearchConfiguration",
    "SearchEntityRegistry",
    "SearchExperiment",
    "SearchFeature",
    "SearchFilter",
    "SearchHit",
    "SearchRequest",
    "SearchResponse",
    # Service
    "SearchService",
    "SearchSettings",
    "SearchSuggestion",
    "SearchSuggestionRequest",
    "SearchSuggestionsResponse",
    "SearchSyntax",
    "SearchableEntity",
    "VectorSearchConfig",
    "VectorSearchResult",
    "VectorSearchService",
    "classify_query_intent",
    "create_default_configuration",
    "get_circuit_breaker",
    "get_circuit_stats",
    "get_search_cache",
    "get_search_config",
    "get_search_service",
    "init_search_cache",
    # Router
    "router",
    "set_search_config",
]
