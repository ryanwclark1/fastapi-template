"""PostgreSQL TSVECTOR type for SQLAlchemy.

The TSVECTOR type represents a sorted list of distinct lexemes
(normalized words) for full-text search. PostgreSQL automatically:
- Normalizes text (lowercasing, stemming)
- Removes stop words
- Stores position information for phrase matching

This module provides the SQLAlchemy type decorator for mapping
TSVECTOR columns in Python.
"""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import TSVECTOR as PG_TSVECTOR
from sqlalchemy.types import TypeDecorator


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

    def load_dialect_impl(self, dialect):
        """Load dialect-specific implementation.

        For PostgreSQL, use native TSVECTOR.
        For other databases (e.g., SQLite in tests), fall back to TEXT.
        """
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_TSVECTOR())
        else:
            # Fallback for SQLite testing
            from sqlalchemy import Text

            return dialect.type_descriptor(Text())


__all__ = ["TSVECTOR"]
