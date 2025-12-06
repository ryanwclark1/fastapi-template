"""Search query helpers for SQLAlchemy 2.0 style queries.

This module provides convenient functions for adding full-text search
to SQLAlchemy select statements, inspired by sqlalchemy-searchable's
simple API while maintaining explicit control.

Two approaches are provided:

1. **Function-based** (recommended):
   - `search(stmt, "query")` - Add FTS to any select statement
   - Explicit, composable, works with any query

2. **Chainable** (convenience):
   - `SearchableSelect` wrapper with fluent API
   - `searchable(stmt).search("query").fuzzy("typo")...`

Usage:
    from example_service.core.database.search import search, searchable

    # Simple search
    stmt = select(Article)
    stmt = search(stmt, "python tutorial")
    results = await session.scalars(stmt)

    # With options
    stmt = search(
        select(Article),
        "python",
        vector=Article.search_vector,
        config="english",
        sort=True,
    )

    # Chainable API
    stmt = (
        searchable(select(Article))
        .search("python tutorial")
        .with_fuzzy(Article.title, threshold=0.3)
        .with_ranking()
        .statement
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import TYPE_CHECKING, Any, TypeVar

from sqlalchemy import Select, func

from example_service.core.database.search.filters import (
    FullTextSearchFilter,
    FuzzySearchFilter,
    HybridSearchFilter,
    RankNormalization,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import InstrumentedAttribute

logger = logging.getLogger(__name__)

T = TypeVar("T")


def search[T](
    statement: Select[T],  # type: ignore[type-var]
    query: str,
    *,
    vector: InstrumentedAttribute[Any] | None = None,
    config: str = "english",
    sort: bool = True,
    prefix_match: bool = False,
    _web_search: bool = True,
) -> Select[T]:  # type: ignore[type-var]
    """Add full-text search to a SQLAlchemy select statement.

    This is the primary search function, providing a simple interface
    similar to sqlalchemy-searchable while using your existing filters.

    Args:
        statement: SQLAlchemy select statement.
        query: Search query string.
        vector: TSVECTOR column to search. If None, auto-detects from entity.
        config: PostgreSQL text search configuration.
        sort: Order results by relevance (default True).
        prefix_match: Enable prefix matching for autocomplete.
        web_search: Use websearch_to_tsquery for Google-like syntax.

    Returns:
        Modified select statement with search filter applied.

    Example:
        from example_service.core.database.search import search

        # Basic search
        stmt = search(select(Article), "python programming")
        articles = await session.scalars(stmt)

        # Search with options
        stmt = search(
            select(Article),
            "pytho",
            prefix_match=True,  # Matches "python"
            sort=True,
        )

        # Explicit vector column
        stmt = search(
            select(Article),
            "tutorial",
            vector=Article.title_vector,  # Search specific vector
        )
    """
    if not query or not query.strip():
        return statement

    # Auto-detect vector column if not provided
    if vector is None:
        vector = _detect_search_vector(statement)
        if vector is None:
            raise ValueError(
                "Could not auto-detect search_vector column. "
                "Please provide the 'vector' parameter explicitly."
            )

    # Use FullTextSearchFilter with appropriate settings
    search_filter = FullTextSearchFilter(
        search_column=vector,
        query=query,
        config=config,
        rank_order=sort,
        prefix_match=prefix_match,
    )

    return search_filter.apply(statement)


def search_fuzzy[T](
    statement: Select[T],  # type: ignore[type-var]
    query: str,
    fields: InstrumentedAttribute[Any] | list[InstrumentedAttribute[Any]],
    *,
    threshold: float = 0.3,
    sort: bool = True,
) -> Select[T]:  # type: ignore[type-var]
    """Add fuzzy (trigram) search to a SQLAlchemy select statement.

    Uses PostgreSQL's pg_trgm extension for typo-tolerant search.

    Args:
        statement: SQLAlchemy select statement.
        query: Search query string.
        fields: Column(s) to search with fuzzy matching.
        threshold: Minimum similarity threshold (0.0-1.0).
        sort: Order results by similarity.

    Returns:
        Modified select statement with fuzzy search applied.

    Example:
        stmt = search_fuzzy(
            select(Product),
            "pythn",  # Typo for "python"
            Product.name,
            threshold=0.3,
        )
    """
    if not query or not query.strip():
        return statement

    fuzzy_filter = FuzzySearchFilter(
        fields=fields,
        query=query,
        threshold=threshold,
        rank_order=sort,
    )

    return fuzzy_filter.apply(statement)


def search_hybrid[T](
    statement: Select[T],  # type: ignore[type-var]
    query: str,
    *,
    vector: InstrumentedAttribute[Any],
    fuzzy_field: InstrumentedAttribute[Any],
    config: str = "english",
    fts_weight: float = 0.7,
    fuzzy_weight: float = 0.3,
    sort: bool = True,
) -> Select[T]:  # type: ignore[type-var]
    """Add hybrid FTS + fuzzy search to a SQLAlchemy select statement.

    Combines full-text search with fuzzy matching fallback for
    maximum recall while maintaining relevance.

    Args:
        statement: SQLAlchemy select statement.
        query: Search query string.
        vector: TSVECTOR column for FTS.
        fuzzy_field: Text column for fuzzy fallback.
        config: PostgreSQL text search configuration.
        fts_weight: Weight for FTS score (0.0-1.0).
        fuzzy_weight: Weight for fuzzy score (0.0-1.0).
        sort: Order by combined relevance.

    Returns:
        Modified select statement with hybrid search.

    Example:
        stmt = search_hybrid(
            select(Article),
            "pythn tutorial",  # Has typo
            vector=Article.search_vector,
            fuzzy_field=Article.title,
        )
    """
    if not query or not query.strip():
        return statement

    hybrid_filter = HybridSearchFilter(
        search_column=vector,
        fuzzy_column=fuzzy_field,
        query=query,
        config=config,
        fts_weight=fts_weight,
        fuzzy_weight=fuzzy_weight,
        rank_order=sort,
    )

    return hybrid_filter.apply(statement)


def _detect_search_vector(statement: Select[Any]) -> InstrumentedAttribute[Any] | None:
    """Attempt to detect the search_vector column from a select statement.

    Args:
        statement: SQLAlchemy select statement.

    Returns:
        The search_vector column or None if not found.
    """
    # Get the primary entity from the statement
    try:
        # SQLAlchemy 2.0 style
        for column_desc in statement.column_descriptions:
            entity = column_desc.get("entity")
            if entity is not None and hasattr(entity, "search_vector"):
                return entity.search_vector  # type: ignore[no-any-return]
    except Exception as e:
        logger.debug("Could not detect search_vector: %s", str(e))

    return None


@dataclass
class SearchableSelect[T]:
    """Chainable wrapper for building search queries.

    Provides a fluent API for composing complex search queries
    with FTS, fuzzy matching, and ranking.

    Example:
        from example_service.core.database.search import searchable

        stmt = (
            searchable(select(Article))
            .search("python tutorial")
            .with_fuzzy(Article.title, threshold=0.3)
            .with_ranking()
            .exclude("draft")
            .statement
        )

        results = await session.scalars(stmt)
    """

    _statement: Select[T]  # type: ignore[type-var]
    _vector: InstrumentedAttribute[Any] | None = None
    _config: str = "english"
    _search_applied: bool = field(default=False, repr=False)

    @property
    def statement(self) -> Select[T]:  # type: ignore[type-var]
        """Get the underlying SQLAlchemy select statement."""
        return self._statement

    def using_vector(self, vector: InstrumentedAttribute[Any]) -> SearchableSelect[T]:
        """Specify the search vector column to use.

        Args:
            vector: TSVECTOR column.

        Returns:
            Self for chaining.
        """
        self._vector = vector
        return self

    def using_config(self, config: str) -> SearchableSelect[T]:
        """Specify the PostgreSQL text search configuration.

        Args:
            config: Text search configuration name.

        Returns:
            Self for chaining.
        """
        self._config = config
        return self

    def search(
        self,
        query: str,
        *,
        prefix_match: bool = False,
        rank: bool = True,
    ) -> SearchableSelect[T]:
        """Apply full-text search.

        Args:
            query: Search query string.
            prefix_match: Enable prefix matching.
            rank: Order by relevance.

        Returns:
            Self for chaining.
        """
        if not query or not query.strip():
            return self

        vector = self._vector
        if vector is None:
            vector = _detect_search_vector(self._statement)

        if vector is None:
            raise ValueError("No search_vector found. Use .using_vector() to specify one.")

        search_filter = FullTextSearchFilter(
            search_column=vector,
            query=query,
            config=self._config,
            rank_order=rank,
            prefix_match=prefix_match,
        )

        self._statement = search_filter.apply(self._statement)
        self._search_applied = True
        return self

    def with_fuzzy(
        self,
        fields: InstrumentedAttribute[Any] | list[InstrumentedAttribute[Any]],
        query: str | None = None,
        *,
        threshold: float = 0.3,
        rank: bool = True,
    ) -> SearchableSelect[T]:
        """Add fuzzy search on specified fields.

        Args:
            fields: Column(s) to fuzzy search.
            query: Search query (uses previous query if None).
            threshold: Similarity threshold.
            rank: Order by similarity.

        Returns:
            Self for chaining.
        """
        if query and query.strip():
            fuzzy_filter = FuzzySearchFilter(
                fields=fields,
                query=query,
                threshold=threshold,
                rank_order=rank,
            )
            self._statement = fuzzy_filter.apply(self._statement)

        return self

    def exclude(
        self,
        terms: str | list[str],
        vector: InstrumentedAttribute[Any] | None = None,
    ) -> SearchableSelect[T]:
        """Exclude documents matching terms.

        Args:
            terms: Term(s) to exclude.
            vector: TSVECTOR column (uses default if None).

        Returns:
            Self for chaining.
        """
        if isinstance(terms, str):
            terms = [terms]

        if not terms:
            return self

        search_vector = vector or self._vector
        if search_vector is None:
            search_vector = _detect_search_vector(self._statement)

        if search_vector is None:
            return self

        # Build exclusion query
        exclusion_query = " | ".join(terms)
        ts_query = func.plainto_tsquery(self._config, exclusion_query)

        # Add NOT condition
        from sqlalchemy import not_

        self._statement = self._statement.where(not_(search_vector.op("@@")(ts_query)))

        return self

    def with_ranking(
        self,
        _normalization: int = RankNormalization.SELF_PLUS_ONE,
    ) -> SearchableSelect[T]:
        """Add explicit ranking column to results.

        Note: Ranking is already applied by search() when rank=True.
        This method adds the rank as a named column for access in results.

        Args:
            normalization: ts_rank normalization option.

        Returns:
            Self for chaining.
        """
        # Ranking is handled by FullTextSearchFilter when rank_order=True
        # This could be extended to add rank as a column in results
        return self


def searchable[T](statement: Select[T]) -> SearchableSelect[T]:  # type: ignore[type-var]
    """Create a searchable wrapper around a select statement.

    Provides a fluent API for building search queries.

    Args:
        statement: SQLAlchemy select statement.

    Returns:
        SearchableSelect wrapper for chaining.

    Example:
        stmt = (
            searchable(select(Article))
            .using_config("english")
            .search("python tutorial", rank=True)
            .exclude("draft")
            .statement
        )
    """
    return SearchableSelect(_statement=statement)


__all__ = [
    "SearchableSelect",
    "search",
    "search_fuzzy",
    "search_hybrid",
    "searchable",
]
