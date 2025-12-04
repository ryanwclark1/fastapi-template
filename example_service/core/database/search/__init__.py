"""PostgreSQL full-text search infrastructure.

This module provides comprehensive full-text search capabilities using
PostgreSQL's native tsvector/tsquery functionality:

Core Components:
- TSVECTOR: SQLAlchemy type for PostgreSQL TSVECTOR columns
- SearchableMixin: Add to models for automatic search vector management
- make_searchable: Auto-configure FTS triggers on table creation (dev mode)

Search Functions (Simple API):
- search: Add FTS to any select statement
- search_fuzzy: Add fuzzy/trigram search
- search_hybrid: Combined FTS + fuzzy search
- searchable: Chainable search query builder

Search Filters (Explicit API):
- FullTextSearchFilter: Standard FTS with ranking and prefix matching
- WebSearchFilter: Google-like query syntax support
- FuzzySearchFilter: Trigram-based similarity search (typo-tolerant)
- PhraseProximityFilter: Phrase matching with word distance control
- BoostedSearchFilter: Term and field boosting for relevance tuning
- HybridSearchFilter: Combined FTS and fuzzy search
- MultiFieldSearchFilter: Search across multiple TSVECTOR columns

Vector Utilities:
- combine_vectors: Combine multiple tsvector columns for cross-table search
- weighted_vector: Create weighted tsvector from text at query time

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
- Cross-table combined search

Usage:
    # Simple API (recommended for most cases)
    from example_service.core.database.search import search, searchable

    stmt = search(select(Article), "python tutorial")
    results = await session.scalars(stmt)

    # Chainable API
    stmt = (
        searchable(select(Article))
        .search("python tutorial")
        .exclude("draft")
        .statement
    )

    # Cross-table search
    from example_service.core.database.search import combine_vectors

    stmt = select(Article).join(Category, isouter=True)
    combined = combine_vectors(Article.search_vector, Category.search_vector)
    stmt = search(stmt, "python", vector=combined)

    # Development mode - auto-create triggers
    from example_service.core.database.search import make_searchable

    Base = declarative_base()
    make_searchable(Base.metadata)

    class Article(Base, SearchableMixin):
        __tablename__ = "articles"
        __search_fields__ = ["title", "content"]
        __search_weights__ = {"title": "A", "content": "B"}
        # Triggers auto-created on table creation!

    # Explicit filters (for complex queries)
    stmt = FullTextSearchFilter(
        Article.search_vector,
        query="python programming",
    ).apply(stmt)

    # Fuzzy search (typo-tolerant)
    stmt = FuzzySearchFilter(
        Article.title,
        query="pythn",  # typo
        threshold=0.3,
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
from example_service.core.database.search.automation import (
    SearchableConfig,
    SearchManager,
    get_search_manager,
    make_searchable,
    remove_searchable_listeners,
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
from example_service.core.database.search.query import (
    SearchableSelect,
    search,
    search_fuzzy,
    search_hybrid,
    searchable,
)
from example_service.core.database.search.synonyms import (
    DEFAULT_PROGRAMMING_SYNONYMS,
    SynonymDictionary,
    SynonymGroup,
    create_synonym_config_sql,
    create_synonym_dictionary_sql,
    get_default_synonyms,
)
from example_service.core.database.search.types import (
    TSVECTOR,
    combine_vectors,
    weighted_vector,
)
from example_service.core.database.search.utils import (
    FTSMigrationHelper,
    SearchFieldConfig,
    TrigramMigrationHelper,
    UnaccentMigrationHelper,
    build_ts_query_sql,
    generate_search_vector_sql,
)

__all__ = [
    # Synonyms
    "DEFAULT_PROGRAMMING_SYNONYMS",
    # Types
    "TSVECTOR",
    # Filters (explicit API)
    "BoostedSearchFilter",
    # Migration utilities
    "FTSMigrationHelper",
    "FullTextSearchFilter",
    "FuzzySearchFilter",
    "HybridSearchFilter",
    "MultiFieldSearchFilter",
    # Mixins
    "MultiLanguageSearchMixin",
    # Parser
    "ParsedQuery",
    "PhraseProximityFilter",
    "QueryRewriter",
    # Ranking
    "RankNormalization",
    "RankingOptions",
    # Analytics
    "SearchAnalytics",
    "SearchFieldConfig",
    "SearchInsight",
    # Automation (dev mode)
    "SearchManager",
    "SearchQuery",
    "SearchQueryParser",
    "SearchStats",
    "SearchSuggestionLog",
    "SearchableConfig",
    "SearchableMixin",
    # Simple search API
    "SearchableSelect",
    "SynonymDictionary",
    "SynonymGroup",
    "Token",
    "TokenType",
    "TrigramMigrationHelper",
    "UnaccentMigrationHelper",
    "WebSearchFilter",
    "build_ts_query_sql",
    # Vector utilities
    "combine_vectors",
    "create_synonym_config_sql",
    "create_synonym_dictionary_sql",
    "generate_search_vector_sql",
    "get_default_synonyms",
    "get_search_manager",
    "make_searchable",
    "parse_search_query",
    "remove_searchable_listeners",
    "search",
    "search_fuzzy",
    "search_hybrid",
    "searchable",
    "weighted_vector",
]
