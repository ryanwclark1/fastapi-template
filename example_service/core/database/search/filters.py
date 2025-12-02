"""Full-text search filters for SQLAlchemy queries.

This module provides comprehensive PostgreSQL full-text search capabilities:

Basic FTS:
- FullTextSearchFilter: Standard tsvector/tsquery matching with ranking
- WebSearchFilter: Google-like query syntax support

Advanced FTS:
- FuzzySearchFilter: Trigram-based similarity search (typo-tolerant)
- PhraseProximityFilter: Phrase matching with word distance control
- BoostedSearchFilter: Term and field boosting for relevance tuning
- HybridSearchFilter: Combines FTS with fuzzy fallback

Ranking:
- RankingOptions: Configure ts_rank normalization and cover density

Usage:
    from example_service.core.database.search import (
        FullTextSearchFilter,
        FuzzySearchFilter,
        HybridSearchFilter,
    )

    # Basic full-text search
    stmt = FullTextSearchFilter(
        Article.search_vector,
        "python web framework",
    ).apply(stmt)

    # Fuzzy search (tolerates typos)
    stmt = FuzzySearchFilter(
        Article.title,
        "pythn",  # typo
        threshold=0.3,
    ).apply(stmt)

    # Hybrid: FTS first, fuzzy fallback
    stmt = HybridSearchFilter(
        search_column=Article.search_vector,
        fuzzy_column=Article.title,
        query="python",
    ).apply(stmt)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntFlag
from typing import TYPE_CHECKING, Any

from sqlalchemy import Select, and_, case, func, literal, or_, text

from example_service.core.database.filters import StatementFilter

if TYPE_CHECKING:
    from sqlalchemy.orm import InstrumentedAttribute


class RankNormalization(IntFlag):
    """PostgreSQL ts_rank normalization options.

    These can be combined using bitwise OR:
        normalization = RankNormalization.LOG_LENGTH | RankNormalization.UNIQUE_WORDS

    Options:
        NONE: No normalization (default)
        LOG_LENGTH: Divide by 1 + log(document length)
        LENGTH: Divide by document length
        HARMONIC_DISTANCE: Divide by mean harmonic distance between extents
        UNIQUE_WORDS: Divide by number of unique words in document
        LOG_UNIQUE_WORDS: Divide by 1 + log(unique words)
        SELF_PLUS_ONE: Divide rank by itself + 1 (recommended)
    """

    NONE = 0
    LOG_LENGTH = 1
    LENGTH = 2
    HARMONIC_DISTANCE = 4
    UNIQUE_WORDS = 8
    LOG_UNIQUE_WORDS = 16
    SELF_PLUS_ONE = 32


@dataclass
class RankingOptions:
    """Configuration options for search result ranking.

    Attributes:
        normalization: Normalization mode for ts_rank
        use_cover_density: Use ts_rank_cd instead of ts_rank
            (considers proximity of matching lexemes)
        weights: Custom weights for A, B, C, D categories
            (default: {A: 1.0, B: 0.4, C: 0.2, D: 0.1})
    """

    normalization: int = RankNormalization.SELF_PLUS_ONE
    use_cover_density: bool = False
    weights: tuple[float, float, float, float] | None = None  # D, C, B, A order

    def get_rank_func(self) -> Any:
        """Get the appropriate ranking function.

        Returns:
            func.ts_rank or func.ts_rank_cd
        """
        return func.ts_rank_cd if self.use_cover_density else func.ts_rank


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
                modified_query = " ".join([*words[:-1], words[-1] + ":*"])
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
        ranking_options: RankingOptions | None = None,
    ) -> None:
        """Initialize web search filter.

        Args:
            search_column: The TSVECTOR column to search
            query: Web-style search query
            config: PostgreSQL text search configuration
            rank_order: Order by relevance
            ranking_options: Advanced ranking configuration
        """
        self.search_column = search_column
        self.query = query.strip() if query else ""
        self.config = config
        self.rank_order = rank_order
        self.ranking_options = ranking_options or RankingOptions()

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
            rank_func = self.ranking_options.get_rank_func()
            if self.ranking_options.weights:
                rank = rank_func(
                    self.ranking_options.weights,
                    self.search_column,
                    ts_query,
                    self.ranking_options.normalization,
                )
            else:
                rank = rank_func(
                    self.search_column,
                    ts_query,
                    self.ranking_options.normalization,
                )
            statement = statement.order_by(rank.desc())

        return statement


class FuzzySearchFilter(StatementFilter):
    """Trigram-based fuzzy search using pg_trgm.

    Uses PostgreSQL's trigram similarity for typo-tolerant searching.
    Requires the pg_trgm extension to be installed.

    This is complementary to full-text search:
    - FTS: Finds documents containing normalized words
    - Fuzzy: Finds similar strings even with typos

    Example:
        # Find products even with typos
        stmt = FuzzySearchFilter(
            Product.name,
            "pythn",  # typo for "python"
            threshold=0.3,
        ).apply(stmt)

        # Search multiple fields
        stmt = FuzzySearchFilter(
            [Product.name, Product.description],
            "pythn",
        ).apply(stmt)
    """

    def __init__(
        self,
        fields: InstrumentedAttribute[Any] | list[InstrumentedAttribute[Any]],
        query: str,
        *,
        threshold: float = 0.3,
        rank_order: bool = True,
        use_word_similarity: bool = False,
    ) -> None:
        """Initialize fuzzy search filter.

        Args:
            fields: Column(s) to search
            query: Search query string
            threshold: Minimum similarity threshold (0.0-1.0)
                Higher = stricter matching. Default 0.3 is PostgreSQL default.
            rank_order: Order by similarity (default True)
            use_word_similarity: Use word_similarity instead of similarity
                (better for matching words within longer text)
        """
        self.fields = [fields] if not isinstance(fields, list) else fields
        self.query = query.strip() if query else ""
        self.threshold = threshold
        self.rank_order = rank_order
        self.use_word_similarity = use_word_similarity

    def apply(self, statement: Select[Any]) -> Select[Any]:
        """Apply fuzzy search filter to statement."""
        if not self.query or not self.fields:
            return statement

        # Choose similarity function
        if self.use_word_similarity:
            sim_func = func.word_similarity
            threshold_op = "%>"
        else:
            sim_func = func.similarity
            threshold_op = "%"

        # Build conditions for each field
        conditions = []
        similarities = []

        for field in self.fields:
            # Similarity condition with threshold
            condition = field.op(threshold_op)(self.query)
            conditions.append(condition)

            # Similarity score for ranking
            similarity = sim_func(self.query, field)
            similarities.append(similarity)

        # Apply filter (any field matches)
        statement = statement.where(or_(*conditions))

        # Order by maximum similarity across fields
        if self.rank_order and similarities:
            if len(similarities) == 1:
                max_similarity = similarities[0]
            else:
                # Use GREATEST to get max similarity
                max_similarity = func.greatest(*similarities)
            statement = statement.order_by(max_similarity.desc())

        return statement

    def with_similarity_column(
        self,
        statement: Select[Any],
        column_name: str = "similarity",
    ) -> Select[Any]:
        """Add similarity score as a column to results.

        Args:
            statement: SQLAlchemy select statement
            column_name: Name for the similarity column

        Returns:
            Statement with similarity column added
        """
        if not self.query or not self.fields:
            return statement.add_columns(literal(0.0).label(column_name))

        sim_func = func.word_similarity if self.use_word_similarity else func.similarity

        if len(self.fields) == 1:
            similarity = sim_func(self.query, self.fields[0])
        else:
            similarities = [sim_func(self.query, f) for f in self.fields]
            similarity = func.greatest(*similarities)

        return statement.add_columns(similarity.label(column_name))


class PhraseProximityFilter(StatementFilter):
    """Phrase search with word proximity control.

    Searches for phrases where words appear near each other,
    using PostgreSQL's <N> (FOLLOWED BY with distance) operator.

    Example:
        # Find "python" followed by "web" within 3 words
        stmt = PhraseProximityFilter(
            Article.search_vector,
            ["python", "web"],
            max_distance=3,
        ).apply(stmt)

        # Exact phrase (distance 1 = adjacent)
        stmt = PhraseProximityFilter(
            Article.search_vector,
            ["full", "text", "search"],
            max_distance=1,
        ).apply(stmt)
    """

    def __init__(
        self,
        search_column: InstrumentedAttribute[Any],
        words: list[str],
        *,
        max_distance: int = 1,
        config: str = "english",
        rank_order: bool = True,
    ) -> None:
        """Initialize phrase proximity filter.

        Args:
            search_column: The TSVECTOR column to search
            words: List of words in the phrase
            max_distance: Maximum word distance (1 = adjacent)
            config: PostgreSQL text search configuration
            rank_order: Order by relevance
        """
        self.search_column = search_column
        self.words = [w.strip() for w in words if w.strip()]
        self.max_distance = max(1, max_distance)
        self.config = config
        self.rank_order = rank_order

    def apply(self, statement: Select[Any]) -> Select[Any]:
        """Apply phrase proximity filter to statement."""
        if len(self.words) < 2:
            # Single word - fall back to plain search
            if self.words:
                ts_query = func.plainto_tsquery(self.config, self.words[0])
                statement = statement.where(self.search_column.op("@@")(ts_query))
            return statement

        # Build proximity query: word1 <N> word2 <N> word3
        # Using raw SQL for the tsquery with FOLLOWED BY operator
        query_parts = []
        for word in self.words:
            # Normalize word using to_tsquery to get lexeme
            query_parts.append(word)

        # Create the proximity pattern
        # Format: 'word1' <-> 'word2' for adjacent, 'word1' <N> 'word2' for distance N
        operator = " <-> " if self.max_distance == 1 else f" <{self.max_distance}> "

        proximity_query = operator.join(f"'{w}'" for w in query_parts)

        # Use to_tsquery to parse the proximity pattern
        ts_query = func.to_tsquery(self.config, proximity_query)

        statement = statement.where(self.search_column.op("@@")(ts_query))

        if self.rank_order:
            # Use ts_rank_cd for better phrase ranking
            rank = func.ts_rank_cd(self.search_column, ts_query)
            statement = statement.order_by(rank.desc())

        return statement


class BoostedSearchFilter(StatementFilter):
    """Full-text search with term and field boosting.

    Allows boosting specific terms or fields to influence ranking.
    Useful for giving more importance to title matches vs body matches.

    Example:
        # Boost "python" over other terms
        stmt = BoostedSearchFilter(
            Article.search_vector,
            query="python web framework",
            term_boosts={"python": 2.0},
        ).apply(stmt)

        # Boost title matches (assumes title has weight A)
        stmt = BoostedSearchFilter(
            Article.search_vector,
            query="python",
            weight_boosts={
                "A": 4.0,  # Title
                "B": 2.0,  # Subtitle
                "C": 1.0,  # Body
                "D": 0.5,  # Metadata
            },
        ).apply(stmt)
    """

    def __init__(
        self,
        search_column: InstrumentedAttribute[Any],
        query: str,
        *,
        term_boosts: dict[str, float] | None = None,
        weight_boosts: dict[str, float] | None = None,
        config: str = "english",
        rank_order: bool = True,
    ) -> None:
        """Initialize boosted search filter.

        Args:
            search_column: The TSVECTOR column to search
            query: Search query string
            term_boosts: Dict mapping terms to boost multipliers
            weight_boosts: Dict mapping weight classes (A/B/C/D) to multipliers
            config: PostgreSQL text search configuration
            rank_order: Order by relevance
        """
        self.search_column = search_column
        self.query = query.strip() if query else ""
        self.term_boosts = term_boosts or {}
        self.weight_boosts = weight_boosts or {}
        self.config = config
        self.rank_order = rank_order

    def apply(self, statement: Select[Any]) -> Select[Any]:
        """Apply boosted search filter to statement."""
        if not self.query:
            return statement

        ts_query = func.websearch_to_tsquery(self.config, self.query)

        # Apply match filter
        statement = statement.where(self.search_column.op("@@")(ts_query))

        if self.rank_order:
            # Build custom weights array for ts_rank
            # Order: D, C, B, A (PostgreSQL convention)
            weights = (
                self.weight_boosts.get("D", 0.1),
                self.weight_boosts.get("C", 0.2),
                self.weight_boosts.get("B", 0.4),
                self.weight_boosts.get("A", 1.0),
            )

            rank = func.ts_rank(
                text(f"'{{{weights[0]}, {weights[1]}, {weights[2]}, {weights[3]}}}'"),
                self.search_column,
                ts_query,
                RankNormalization.SELF_PLUS_ONE,
            )
            statement = statement.order_by(rank.desc())

        return statement


class HybridSearchFilter(StatementFilter):
    """Combined full-text and fuzzy search.

    Uses FTS as primary search with fuzzy matching as fallback
    for handling typos and partial matches. The scores are combined
    for unified ranking.

    Example:
        # Primary FTS on search_vector, fuzzy fallback on title
        stmt = HybridSearchFilter(
            search_column=Article.search_vector,
            fuzzy_column=Article.title,
            query="python tutorial",
            fts_weight=0.7,
            fuzzy_weight=0.3,
        ).apply(stmt)
    """

    def __init__(
        self,
        search_column: InstrumentedAttribute[Any],
        fuzzy_column: InstrumentedAttribute[Any],
        query: str,
        *,
        config: str = "english",
        fts_weight: float = 0.7,
        fuzzy_weight: float = 0.3,
        fuzzy_threshold: float = 0.3,
        rank_order: bool = True,
    ) -> None:
        """Initialize hybrid search filter.

        Args:
            search_column: TSVECTOR column for full-text search
            fuzzy_column: Text column for fuzzy search
            query: Search query string
            config: PostgreSQL text search configuration
            fts_weight: Weight for FTS score (0.0-1.0)
            fuzzy_weight: Weight for fuzzy score (0.0-1.0)
            fuzzy_threshold: Minimum fuzzy similarity threshold
            rank_order: Order by combined relevance
        """
        self.search_column = search_column
        self.fuzzy_column = fuzzy_column
        self.query = query.strip() if query else ""
        self.config = config
        self.fts_weight = fts_weight
        self.fuzzy_weight = fuzzy_weight
        self.fuzzy_threshold = fuzzy_threshold
        self.rank_order = rank_order

    def apply(self, statement: Select[Any]) -> Select[Any]:
        """Apply hybrid search filter to statement."""
        if not self.query:
            return statement

        ts_query = func.websearch_to_tsquery(self.config, self.query)

        # FTS condition
        fts_condition = self.search_column.op("@@")(ts_query)

        # Fuzzy condition
        fuzzy_condition = self.fuzzy_column.op("%")(self.query)

        # Match if either FTS or fuzzy matches
        statement = statement.where(or_(fts_condition, fuzzy_condition))

        if self.rank_order:
            # FTS rank (0-1 normalized)
            fts_rank = func.ts_rank(
                self.search_column,
                ts_query,
                RankNormalization.SELF_PLUS_ONE,
            )

            # Fuzzy similarity (0-1)
            fuzzy_similarity = func.similarity(self.query, self.fuzzy_column)

            # Combined score
            # Use CASE to handle when one method doesn't match
            combined_rank = (
                case(
                    (fts_condition, fts_rank * self.fts_weight),
                    else_=literal(0.0),
                )
                + case(
                    (fuzzy_condition, fuzzy_similarity * self.fuzzy_weight),
                    else_=literal(0.0),
                )
            )

            statement = statement.order_by(combined_rank.desc())

        return statement

    def with_scores_column(
        self,
        statement: Select[Any],
        fts_column: str = "fts_score",
        fuzzy_column: str = "fuzzy_score",
        combined_column: str = "combined_score",
    ) -> Select[Any]:
        """Add individual and combined scores as columns.

        Args:
            statement: SQLAlchemy select statement
            fts_column: Name for FTS score column
            fuzzy_column: Name for fuzzy score column
            combined_column: Name for combined score column

        Returns:
            Statement with score columns added
        """
        if not self.query:
            return statement.add_columns(
                literal(0.0).label(fts_column),
                literal(0.0).label(fuzzy_column),
                literal(0.0).label(combined_column),
            )

        ts_query = func.websearch_to_tsquery(self.config, self.query)

        fts_score = func.ts_rank(
            self.search_column,
            ts_query,
            RankNormalization.SELF_PLUS_ONE,
        )
        fuzzy_score = func.similarity(self.query, self.fuzzy_column)
        combined_score = fts_score * self.fts_weight + fuzzy_score * self.fuzzy_weight

        return statement.add_columns(
            fts_score.label(fts_column),
            fuzzy_score.label(fuzzy_column),
            combined_score.label(combined_column),
        )


class MultiFieldSearchFilter(StatementFilter):
    """Search across multiple fields with individual weights.

    Useful when you have separate tsvector columns for different
    fields or want fine-grained control over field ranking.

    Example:
        stmt = MultiFieldSearchFilter(
            field_configs=[
                (Article.title_vector, 4.0),
                (Article.body_vector, 1.0),
                (Article.tags_vector, 2.0),
            ],
            query="python tutorial",
        ).apply(stmt)
    """

    def __init__(
        self,
        field_configs: list[tuple[InstrumentedAttribute[Any], float]],
        query: str,
        *,
        config: str = "english",
        require_all: bool = False,
        rank_order: bool = True,
    ) -> None:
        """Initialize multi-field search filter.

        Args:
            field_configs: List of (column, weight) tuples
            query: Search query string
            config: PostgreSQL text search configuration
            require_all: Require match in all fields (AND) vs any field (OR)
            rank_order: Order by weighted relevance
        """
        self.field_configs = field_configs
        self.query = query.strip() if query else ""
        self.config = config
        self.require_all = require_all
        self.rank_order = rank_order

    def apply(self, statement: Select[Any]) -> Select[Any]:
        """Apply multi-field search filter to statement."""
        if not self.query or not self.field_configs:
            return statement

        ts_query = func.websearch_to_tsquery(self.config, self.query)

        # Build match conditions for each field
        conditions = [
            column.op("@@")(ts_query) for column, _ in self.field_configs
        ]

        # Apply filter
        if self.require_all:
            statement = statement.where(and_(*conditions))
        else:
            statement = statement.where(or_(*conditions))

        if self.rank_order:
            # Calculate weighted sum of ranks
            weighted_ranks = [
                func.ts_rank(column, ts_query, RankNormalization.SELF_PLUS_ONE) * weight
                for column, weight in self.field_configs
            ]

            # Sum all weighted ranks
            total_rank = weighted_ranks[0]
            for rank in weighted_ranks[1:]:
                total_rank = total_rank + rank

            statement = statement.order_by(total_rank.desc())

        return statement


__all__ = [
    "BoostedSearchFilter",
    "FullTextSearchFilter",
    "FuzzySearchFilter",
    "HybridSearchFilter",
    "MultiFieldSearchFilter",
    "PhraseProximityFilter",
    "RankNormalization",
    "RankingOptions",
    "WebSearchFilter",
]
