"""PostgreSQL full-text search infrastructure.

This module provides comprehensive full-text search capabilities using
PostgreSQL's native tsvector/tsquery functionality:

Core Components:
- TSVECTOR: SQLAlchemy type for PostgreSQL TSVECTOR columns
- SearchableMixin: Add to models for automatic search vector management

Search Filters:
- FullTextSearchFilter: Standard FTS with ranking and prefix matching
- WebSearchFilter: Google-like query syntax support
- FuzzySearchFilter: Trigram-based similarity search (typo-tolerant)
- PhraseProximityFilter: Phrase matching with word distance control
- BoostedSearchFilter: Term and field boosting for relevance tuning
- HybridSearchFilter: Combined FTS and fuzzy search
- MultiFieldSearchFilter: Search across multiple TSVECTOR columns

Query Parsing:
- SearchQueryParser: Advanced query syntax parser (field:value, ranges, etc.)
- QueryRewriter: Query normalization and synonym expansion
- ParsedQuery: Structured representation of parsed queries

Migration Utilities:
- FTSMigrationHelper: Generate triggers, indexes, and backfill data
- TrigramMigrationHelper: Add pg_trgm fuzzy search indexes
- UnaccentMigrationHelper: Add accent-insensitive search

Ranking:
- RankNormalization: ts_rank normalization options
- RankingOptions: Configure ranking behavior

Features:
- Stemming and stop word removal
- Ranking by relevance (ts_rank, ts_rank_cd)
- Multi-language support
- GIN indexes for fast searches
- Fuzzy matching with pg_trgm
- Phrase proximity search
- Field-specific searching
- Query expansion and synonyms

Usage:
    # Add to model
    class Article(Base, SearchableMixin):
        __tablename__ = "articles"
        __search_fields__ = ["title", "content"]
        __search_config__ = "english"
        __search_weights__ = {"title": "A", "content": "B"}

        title: Mapped[str] = mapped_column(String(255))
        content: Mapped[str] = mapped_column(Text)

    # Basic search with ranking
    stmt = select(Article)
    stmt = FullTextSearchFilter(
        Article.search_vector,
        query="python programming",
    ).apply(stmt)

    # Web-style search with operators
    stmt = WebSearchFilter(
        Article.search_vector,
        query='"exact phrase" -exclude OR alternative',
    ).apply(stmt)

    # Fuzzy search (typo-tolerant)
    stmt = FuzzySearchFilter(
        Article.title,
        query="pythn",  # typo
        threshold=0.3,
    ).apply(stmt)

    # Hybrid search (FTS + fuzzy fallback)
    stmt = HybridSearchFilter(
        search_column=Article.search_vector,
        fuzzy_column=Article.title,
        query="python tutorial",
    ).apply(stmt)

    # Parse advanced queries
    parser = SearchQueryParser()
    parsed = parser.parse('title:python author:"John Doe" -draft')
"""

from example_service.core.database.search.analytics import (
    SearchAnalytics,
    SearchInsight,
    SearchQuery,
    SearchStats,
    SearchSuggestionLog,
)
from example_service.core.database.search.filters import (
    BoostedSearchFilter,
    FullTextSearchFilter,
    FuzzySearchFilter,
    HybridSearchFilter,
    MultiFieldSearchFilter,
    PhraseProximityFilter,
    RankingOptions,
    RankNormalization,
    WebSearchFilter,
)
from example_service.core.database.search.mixins import (
    MultiLanguageSearchMixin,
    SearchableMixin,
)
from example_service.core.database.search.parser import (
    ParsedQuery,
    QueryRewriter,
    SearchQueryParser,
    Token,
    TokenType,
    parse_search_query,
)
from example_service.core.database.search.synonyms import (
    DEFAULT_PROGRAMMING_SYNONYMS,
    SynonymDictionary,
    SynonymGroup,
    create_synonym_config_sql,
    create_synonym_dictionary_sql,
    get_default_synonyms,
)
from example_service.core.database.search.types import TSVECTOR
from example_service.core.database.search.utils import (
    FTSMigrationHelper,
    SearchFieldConfig,
    TrigramMigrationHelper,
    UnaccentMigrationHelper,
    build_ts_query_sql,
    generate_search_vector_sql,
)

__all__ = [
    # Types
    "TSVECTOR",
    # Mixins
    "SearchableMixin",
    "MultiLanguageSearchMixin",
    # Filters
    "FullTextSearchFilter",
    "WebSearchFilter",
    "FuzzySearchFilter",
    "PhraseProximityFilter",
    "BoostedSearchFilter",
    "HybridSearchFilter",
    "MultiFieldSearchFilter",
    # Ranking
    "RankNormalization",
    "RankingOptions",
    # Parser
    "SearchQueryParser",
    "QueryRewriter",
    "ParsedQuery",
    "Token",
    "TokenType",
    "parse_search_query",
    # Migration utilities
    "FTSMigrationHelper",
    "TrigramMigrationHelper",
    "UnaccentMigrationHelper",
    "SearchFieldConfig",
    "generate_search_vector_sql",
    "build_ts_query_sql",
    # Analytics
    "SearchAnalytics",
    "SearchInsight",
    "SearchQuery",
    "SearchStats",
    "SearchSuggestionLog",
    # Synonyms
    "SynonymDictionary",
    "SynonymGroup",
    "DEFAULT_PROGRAMMING_SYNONYMS",
    "get_default_synonyms",
    "create_synonym_config_sql",
    "create_synonym_dictionary_sql",
]
