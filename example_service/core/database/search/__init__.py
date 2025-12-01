"""PostgreSQL full-text search infrastructure.

This module provides full-text search capabilities using PostgreSQL's
native tsvector/tsquery functionality:

- SearchableMixin: Add to models for automatic search vector management
- FullTextSearchFilter: Filter queries with ranked full-text search
- Highlighting utilities: Mark matching terms in results

Features:
- Stemming and stop word removal
- Ranking by relevance
- Multi-language support
- GIN index for fast searches

Usage:
    # Add to model
    class Article(Base, SearchableMixin):
        __tablename__ = "articles"
        __search_fields__ = ["title", "content"]
        __search_config__ = "english"

        title: Mapped[str] = mapped_column(String(255))
        content: Mapped[str] = mapped_column(Text)

    # Search with ranking
    stmt = select(Article)
    stmt = FullTextSearchFilter(
        Article.search_vector,
        query="python programming",
    ).apply(stmt)
"""

from example_service.core.database.search.filters import (
    FullTextSearchFilter,
    WebSearchFilter,
)
from example_service.core.database.search.mixins import SearchableMixin
from example_service.core.database.search.types import TSVECTOR

__all__ = [
    "TSVECTOR",
    "SearchableMixin",
    "FullTextSearchFilter",
    "WebSearchFilter",
]
