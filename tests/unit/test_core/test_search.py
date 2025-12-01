"""Unit tests for full-text search infrastructure."""

from __future__ import annotations

from unittest.mock import MagicMock

from sqlalchemy import Column, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from example_service.core.database.search.filters import (
    FullTextSearchFilter,
    WebSearchFilter,
)
from example_service.core.database.search.types import TSVECTOR

# ──────────────────────────────────────────────────────────────
# Test TSVECTOR Type
# ──────────────────────────────────────────────────────────────


class TestTSVECTOR:
    """Tests for TSVECTOR SQLAlchemy type."""

    def test_tsvector_cache_ok(self):
        """TSVECTOR should be cacheable."""
        assert TSVECTOR.cache_ok is True

    def test_tsvector_postgres_impl(self):
        """TSVECTOR should use PostgreSQL's native type."""
        tsvector = TSVECTOR()
        mock_dialect = MagicMock()
        mock_dialect.name = "postgresql"

        # Should not raise
        impl = tsvector.load_dialect_impl(mock_dialect)
        assert impl is not None

    def test_tsvector_sqlite_fallback(self):
        """TSVECTOR should fallback to TEXT for SQLite."""
        tsvector = TSVECTOR()
        mock_dialect = MagicMock()
        mock_dialect.name = "sqlite"

        # Should fall back to TEXT
        impl = tsvector.load_dialect_impl(mock_dialect)
        assert impl is not None


# ──────────────────────────────────────────────────────────────
# Test FullTextSearchFilter
# ──────────────────────────────────────────────────────────────


class TestFullTextSearchFilter:
    """Tests for FullTextSearchFilter."""

    def test_empty_query_returns_unchanged(self):
        """Empty query should return statement unchanged."""

        class MockBase(DeclarativeBase):
            pass

        class MockModel(MockBase):
            __tablename__ = "test"
            id: Mapped[int] = mapped_column(primary_key=True)
            search_vector = Column(TSVECTOR)

        stmt = select(MockModel)
        search_filter = FullTextSearchFilter(
            MockModel.search_vector,
            "",
        )

        result = search_filter.apply(stmt)

        # Should be the same statement (no WHERE clause added)
        assert str(result) == str(stmt)

    def test_whitespace_query_returns_unchanged(self):
        """Whitespace-only query should return statement unchanged."""

        class MockBase(DeclarativeBase):
            pass

        class MockModel(MockBase):
            __tablename__ = "test"
            id: Mapped[int] = mapped_column(primary_key=True)
            search_vector = Column(TSVECTOR)

        stmt = select(MockModel)
        search_filter = FullTextSearchFilter(
            MockModel.search_vector,
            "   ",
        )

        result = search_filter.apply(stmt)
        assert str(result) == str(stmt)

    def test_query_strips_whitespace(self):
        """Query should be stripped of leading/trailing whitespace."""
        filter_ = FullTextSearchFilter(
            MagicMock(),
            "  hello world  ",
        )

        assert filter_.query == "hello world"

    def test_filter_stores_parameters(self):
        """Filter should store all configuration parameters."""
        mock_column = MagicMock()

        filter_ = FullTextSearchFilter(
            mock_column,
            "search terms",
            config="spanish",
            rank_order=False,
            prefix_match=True,
            rank_normalization=16,
        )

        assert filter_.search_column == mock_column
        assert filter_.query == "search terms"
        assert filter_.config == "spanish"
        assert filter_.rank_order is False
        assert filter_.prefix_match is True
        assert filter_.rank_normalization == 16

    def test_default_parameters(self):
        """Filter should have sensible defaults."""
        filter_ = FullTextSearchFilter(
            MagicMock(),
            "query",
        )

        assert filter_.config == "english"
        assert filter_.rank_order is True
        assert filter_.prefix_match is False
        assert filter_.rank_normalization == 32

    def test_build_tsquery_plain(self):
        """Plain mode should use plainto_tsquery."""
        mock_column = MagicMock()
        filter_ = FullTextSearchFilter(
            mock_column,
            "python programming",
            prefix_match=False,
        )

        ts_query = filter_._build_tsquery()

        # Should use plainto_tsquery function
        assert "plainto_tsquery" in str(ts_query)

    def test_build_tsquery_prefix(self):
        """Prefix mode should add :* to last word."""
        mock_column = MagicMock()
        filter_ = FullTextSearchFilter(
            mock_column,
            "pyt",
            prefix_match=True,
        )

        ts_query = filter_._build_tsquery()

        # Should use to_tsquery with :*
        assert "to_tsquery" in str(ts_query)


# ──────────────────────────────────────────────────────────────
# Test WebSearchFilter
# ──────────────────────────────────────────────────────────────


class TestWebSearchFilter:
    """Tests for WebSearchFilter (Google-like syntax)."""

    def test_empty_query_returns_unchanged(self):
        """Empty query should return statement unchanged."""

        class MockBase(DeclarativeBase):
            pass

        class MockModel(MockBase):
            __tablename__ = "test"
            id: Mapped[int] = mapped_column(primary_key=True)
            search_vector = Column(TSVECTOR)

        stmt = select(MockModel)
        search_filter = WebSearchFilter(
            MockModel.search_vector,
            "",
        )

        result = search_filter.apply(stmt)
        assert str(result) == str(stmt)

    def test_filter_stores_parameters(self):
        """Filter should store configuration parameters."""
        mock_column = MagicMock()

        filter_ = WebSearchFilter(
            mock_column,
            '"exact phrase" -excluded',
            config="german",
            rank_order=False,
        )

        assert filter_.search_column == mock_column
        assert filter_.query == '"exact phrase" -excluded'
        assert filter_.config == "german"
        assert filter_.rank_order is False

    def test_default_parameters(self):
        """Filter should have sensible defaults."""
        filter_ = WebSearchFilter(
            MagicMock(),
            "query",
        )

        assert filter_.config == "english"
        assert filter_.rank_order is True


# ──────────────────────────────────────────────────────────────
# Test SearchableMixin
# ──────────────────────────────────────────────────────────────


class TestSearchableMixin:
    """Tests for SearchableMixin."""

    def test_build_search_vector_sql(self):
        """Mixin should generate correct SQL for search vector update."""
        from example_service.core.database.search.mixins import SearchableMixin

        class TestModel(SearchableMixin):
            __tablename__ = "test_model"
            __search_fields__ = ["title", "content"]
            __search_config__ = "english"
            __search_weights__ = {"title": "A", "content": "B"}

        model = TestModel()
        sql = model.build_search_vector_sql()

        assert "setweight" in sql
        assert "to_tsvector" in sql
        assert "'english'" in sql
        assert "title" in sql
        assert "content" in sql
        assert "'A'" in sql
        assert "'B'" in sql

    def test_get_search_trigger_sql(self):
        """Mixin should generate trigger creation SQL."""
        from example_service.core.database.search.mixins import SearchableMixin

        class TestModel(SearchableMixin):
            __tablename__ = "products"
            __search_fields__ = ["name", "description"]
            __search_config__ = "english"
            __search_weights__ = {"name": "A"}

        sql = TestModel.get_search_trigger_sql("products")

        assert "CREATE OR REPLACE FUNCTION" in sql
        assert "products_search_vector_update()" in sql
        assert "CREATE TRIGGER" in sql
        assert "BEFORE INSERT OR UPDATE" in sql
        assert "products" in sql

    def test_empty_search_fields(self):
        """Empty search fields should generate minimal SQL."""
        from example_service.core.database.search.mixins import SearchableMixin

        class TestModel(SearchableMixin):
            __tablename__ = "empty_model"
            __search_fields__ = []
            __search_config__ = "simple"

        model = TestModel()
        sql = model.build_search_vector_sql()

        assert "to_tsvector('simple', '')" in sql
