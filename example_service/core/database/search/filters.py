"""Full-text search filter for SQLAlchemy queries.

The FullTextSearchFilter applies PostgreSQL's powerful full-text search
to queries, including:
- Lexeme normalization (stemming, lowercasing)
- Stop word removal
- Relevance ranking
- Prefix matching for autocomplete

Usage:
    from example_service.core.database.search import FullTextSearchFilter

    # Basic search
    stmt = select(Article)
    stmt = FullTextSearchFilter(
        Article.search_vector,
        "python web framework",
    ).apply(stmt)

    # With prefix matching (for autocomplete)
    stmt = FullTextSearchFilter(
        Article.search_vector,
        "pyth",
        prefix_match=True,
    ).apply(stmt)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import Select, func, literal

from example_service.core.database.filters import StatementFilter

if TYPE_CHECKING:
    from sqlalchemy.orm import InstrumentedAttribute


class FullTextSearchFilter(StatementFilter):
    """PostgreSQL full-text search filter with ranking.

    Applies full-text search to a query using PostgreSQL's tsvector
    and tsquery capabilities. Supports:
    - Plain text queries (words joined with AND)
    - Phrase queries (exact phrase matching)
    - Prefix queries (for autocomplete)
    - Relevance ranking

    Example:
        # Search articles for "python programming"
        stmt = select(Article)
        stmt = FullTextSearchFilter(
            Article.search_vector,
            "python programming",
            config="english",
        ).apply(stmt)

        # Results are filtered and ordered by relevance

    Attributes:
        search_column: TSVECTOR column to search
        query: Search query string
        config: PostgreSQL text search configuration
        rank_order: Whether to order by relevance
        prefix_match: Enable prefix matching for autocomplete
    """

    def __init__(
        self,
        search_column: InstrumentedAttribute[Any],
        query: str,
        *,
        config: str = "english",
        rank_order: bool = True,
        prefix_match: bool = False,
        rank_normalization: int = 32,
    ) -> None:
        """Initialize full-text search filter.

        Args:
            search_column: The TSVECTOR column to search
            query: Search query string (plain text)
            config: PostgreSQL text search configuration
                    (english, simple, spanish, etc.)
            rank_order: Order results by relevance (default True)
            prefix_match: Enable prefix matching for last word
                          (useful for autocomplete)
            rank_normalization: Normalization option for ts_rank:
                - 0: Default (no normalization)
                - 1: Divides by 1 + log(document length)
                - 2: Divides by document length
                - 4: Divides by mean harmonic distance
                - 8: Divides by unique words in document
                - 16: Divides by 1 + log(unique words)
                - 32: Divides by itself + 1 (recommended)
        """
        self.search_column = search_column
        self.query = query.strip() if query else ""
        self.config = config
        self.rank_order = rank_order
        self.prefix_match = prefix_match
        self.rank_normalization = rank_normalization

    def apply(self, statement: Select[Any]) -> Select[Any]:
        """Apply full-text search filter to statement.

        If the query is empty or only whitespace, returns the
        statement unchanged.

        The filter:
        1. Converts query to tsquery
        2. Adds WHERE clause matching documents
        3. Orders by relevance rank (if enabled)
        """
        if not self.query:
            return statement

        # Build tsquery based on options
        ts_query = self._build_tsquery()

        # Apply match filter
        statement = statement.where(self.search_column.op("@@")(ts_query))

        # Apply ranking if enabled
        if self.rank_order:
            rank = func.ts_rank(
                self.search_column,
                ts_query,
                self.rank_normalization,
            )
            statement = statement.order_by(rank.desc())

        return statement

    def _build_tsquery(self) -> Any:
        """Build PostgreSQL tsquery from search string.

        Converts plain text query to tsquery using appropriate
        function based on options.
        """
        if self.prefix_match:
            # For prefix matching, we need to handle the last word specially
            # Split into words and add :* to the last word
            words = self.query.split()
            if words:
                # Add prefix match to last word
                modified_query = " ".join(words[:-1] + [words[-1] + ":*"])
                return func.to_tsquery(self.config, modified_query)

        # Use plainto_tsquery for simple AND matching of words
        return func.plainto_tsquery(self.config, self.query)

    def with_rank_column(
        self,
        statement: Select[Any],
        column_name: str = "search_rank",
    ) -> Select[Any]:
        """Add rank as a named column to the query.

        Useful when you need to access the rank value in results.

        Args:
            statement: SQLAlchemy select statement
            column_name: Name for the rank column

        Returns:
            Statement with rank column added

        Example:
            stmt = select(Article)
            stmt = filter.apply(stmt)
            stmt = filter.with_rank_column(stmt)

            result = await session.execute(stmt)
            for row in result:
                print(row.Article, row.search_rank)
        """
        if not self.query:
            # Add a dummy rank column
            return statement.add_columns(literal(0.0).label(column_name))

        ts_query = self._build_tsquery()
        rank = func.ts_rank(
            self.search_column,
            ts_query,
            self.rank_normalization,
        ).label(column_name)

        return statement.add_columns(rank)


class WebSearchFilter(StatementFilter):
    """Web-style full-text search with operators.

    Supports Google-like search syntax:
    - "exact phrase": Phrase matching
    - -word: Exclude word
    - word1 OR word2: Either word
    - word1 word2: Both words (AND)

    Uses PostgreSQL's websearch_to_tsquery for parsing.

    Example:
        # Search for articles with "python" but not "java"
        stmt = WebSearchFilter(
            Article.search_vector,
            "python -java",
        ).apply(stmt)
    """

    def __init__(
        self,
        search_column: InstrumentedAttribute[Any],
        query: str,
        *,
        config: str = "english",
        rank_order: bool = True,
    ) -> None:
        """Initialize web search filter.

        Args:
            search_column: The TSVECTOR column to search
            query: Web-style search query
            config: PostgreSQL text search configuration
            rank_order: Order by relevance
        """
        self.search_column = search_column
        self.query = query.strip() if query else ""
        self.config = config
        self.rank_order = rank_order

    def apply(self, statement: Select[Any]) -> Select[Any]:
        """Apply web search filter to statement."""
        if not self.query:
            return statement

        # Use websearch_to_tsquery for web-style parsing
        ts_query = func.websearch_to_tsquery(self.config, self.query)

        # Apply match filter
        statement = statement.where(self.search_column.op("@@")(ts_query))

        # Apply ranking
        if self.rank_order:
            rank = func.ts_rank(self.search_column, ts_query)
            statement = statement.order_by(rank.desc())

        return statement


__all__ = ["FullTextSearchFilter", "WebSearchFilter"]
