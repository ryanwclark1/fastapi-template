"""PostgreSQL TSVECTOR type and utilities for SQLAlchemy.

The TSVECTOR type represents a sorted list of distinct lexemes
(normalized words) for full-text search. PostgreSQL automatically:
- Normalizes text (lowercasing, stemming)
- Removes stop words
- Stores position information for phrase matching

This module provides:
- TSVECTOR: SQLAlchemy type decorator for TSVECTOR columns
- combine_vectors: Combine multiple tsvector columns for cross-table search
- CombinedVector: Expression type for combined vectors
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import func, literal
from sqlalchemy.dialects.postgresql import TSVECTOR as PG_TSVECTOR
from sqlalchemy.types import TypeDecorator, TypeEngine

if TYPE_CHECKING:
    from sqlalchemy.engine import Dialect
    from sqlalchemy.orm import InstrumentedAttribute
    from sqlalchemy.sql.expression import ColumnElement


class TSVECTOR(TypeDecorator):
    """SQLAlchemy type for PostgreSQL TSVECTOR columns.

    TSVECTOR is a document representation for full-text search.
    It contains a sorted list of lexemes with optional positions
    and weights.

    Usage:
        class Article(Base):
            search_vector: Mapped[str] = mapped_column(
                TSVECTOR,
                nullable=True,
            )

    The column stores preprocessed search data created by:
    - to_tsvector('english', 'The quick brown fox')
    - Returns: 'brown':3 'fox':4 'quick':2

    Note:
        This is a thin wrapper around PostgreSQL's native TSVECTOR.
        For SQLite testing, this column will be treated as TEXT.
    """

    impl = PG_TSVECTOR
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        """Load dialect-specific implementation.

        For PostgreSQL, use native TSVECTOR.
        For other databases (e.g., SQLite in tests), fall back to TEXT.
        """
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_TSVECTOR())
        # Fallback for SQLite testing
        from sqlalchemy import Text

        return dialect.type_descriptor(Text())


def combine_vectors(
    *vectors: InstrumentedAttribute[Any] | ColumnElement[Any],
    coalesce_nulls: bool = True,
) -> ColumnElement[Any]:
    """Combine multiple TSVECTOR columns using PostgreSQL's || operator.

    This is useful for cross-table search where you want to search
    across related entities in a joined query.

    Args:
        *vectors: TSVECTOR columns to combine.
        coalesce_nulls: If True, treat NULL vectors as empty (recommended
            for LEFT JOINs where related records may not exist).

    Returns:
        Combined TSVECTOR expression.

    Example:
        # Search across Article and its Category
        from example_service.core.database.search import combine_vectors, search

        stmt = (
            select(Article)
            .join(Category, Article.category_id == Category.id, isouter=True)
        )

        combined = combine_vectors(
            Article.search_vector,
            Category.search_vector,
        )

        # Use combined vector for search
        ts_query = func.websearch_to_tsquery("english", "python tutorial")
        stmt = stmt.where(combined.op("@@")(ts_query))

        # Or with the search function
        from example_service.core.database.search.filters import FullTextSearchFilter

        filter = FullTextSearchFilter(
            search_column=combined,
            query="python tutorial",
        )
        stmt = filter.apply(stmt)
    """
    if not vectors:
        raise ValueError("At least one vector is required")

    if len(vectors) == 1:
        return vectors[0]  # type: ignore[return-value]

    # Build combined expression using || operator
    if coalesce_nulls:
        # Wrap each vector in COALESCE to handle NULLs from LEFT JOINs
        # COALESCE(vector, to_tsvector('')) treats NULL as empty vector
        safe_vectors: list[InstrumentedAttribute[Any] | ColumnElement[Any]] = [
            func.coalesce(v, func.to_tsvector(literal(""))) for v in vectors
        ]
    else:
        safe_vectors = list(vectors)

    # Combine with || operator
    result: ColumnElement[Any] = safe_vectors[0]  # type: ignore[assignment]
    for vector in safe_vectors[1:]:
        result = result.op("||")(vector)

    return result


def weighted_vector(
    text_column: InstrumentedAttribute[Any] | ColumnElement[Any],
    weight: str = "D",
    config: str = "english",
) -> ColumnElement[Any]:
    """Create a weighted TSVECTOR from a text column.

    Useful for building search vectors with explicit weights at query time.

    Args:
        text_column: Text column to vectorize.
        weight: Weight class (A, B, C, or D).
        config: PostgreSQL text search configuration.

    Returns:
        Weighted TSVECTOR expression.

    Example:
        # Create weighted vector at query time
        title_vector = weighted_vector(Article.title, weight="A")
        body_vector = weighted_vector(Article.body, weight="B")

        combined = combine_vectors(title_vector, body_vector)
    """
    if weight not in ("A", "B", "C", "D"):
        raise ValueError(f"Weight must be A, B, C, or D, got: {weight}")

    tsvector = func.to_tsvector(config, func.coalesce(text_column, literal("")))
    return func.setweight(tsvector, weight)


__all__ = [
    "TSVECTOR",
    "combine_vectors",
    "weighted_vector",
]
