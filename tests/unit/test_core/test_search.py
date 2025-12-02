"""Unit tests for full-text search infrastructure."""

from __future__ import annotations

from unittest.mock import MagicMock

from sqlalchemy import Column, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

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
from example_service.core.database.search.parser import (
    ParsedQuery,
    SearchQueryParser,
    TokenType,
    QueryRewriter,
)
from example_service.core.database.search.utils import (
    FTSMigrationHelper,
    TrigramMigrationHelper,
    UnaccentMigrationHelper,
    generate_search_vector_sql,
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
# Test FuzzySearchFilter
# ──────────────────────────────────────────────────────────────


class TestFuzzySearchFilter:
    """Tests for FuzzySearchFilter (trigram-based)."""

    def test_empty_query_returns_unchanged(self):
        """Empty query should return statement unchanged."""

        class MockBase(DeclarativeBase):
            pass

        class MockModel(MockBase):
            __tablename__ = "test"
            id: Mapped[int] = mapped_column(primary_key=True)
            name: Mapped[str] = mapped_column()

        stmt = select(MockModel)
        search_filter = FuzzySearchFilter(
            MockModel.name,
            "",
        )

        result = search_filter.apply(stmt)
        assert str(result) == str(stmt)

    def test_single_field(self):
        """Filter should work with a single field."""
        mock_column = MagicMock()

        filter_ = FuzzySearchFilter(
            mock_column,
            "pythn",
            threshold=0.3,
        )

        assert filter_.query == "pythn"
        assert filter_.threshold == 0.3
        assert len(filter_.fields) == 1

    def test_multiple_fields(self):
        """Filter should work with multiple fields."""
        mock_col1 = MagicMock()
        mock_col2 = MagicMock()

        filter_ = FuzzySearchFilter(
            [mock_col1, mock_col2],
            "search",
        )

        assert len(filter_.fields) == 2

    def test_default_threshold(self):
        """Default threshold should be 0.3."""
        filter_ = FuzzySearchFilter(
            MagicMock(),
            "query",
        )

        assert filter_.threshold == 0.3

    def test_word_similarity_option(self):
        """Filter should support word_similarity mode."""
        filter_ = FuzzySearchFilter(
            MagicMock(),
            "query",
            use_word_similarity=True,
        )

        assert filter_.use_word_similarity is True


# ──────────────────────────────────────────────────────────────
# Test PhraseProximityFilter
# ──────────────────────────────────────────────────────────────


class TestPhraseProximityFilter:
    """Tests for PhraseProximityFilter."""

    def test_single_word_fallback(self):
        """Single word should fall back to plain search."""
        mock_column = MagicMock()

        filter_ = PhraseProximityFilter(
            mock_column,
            ["python"],
            max_distance=3,
        )

        assert len(filter_.words) == 1

    def test_multiple_words(self):
        """Multiple words should be stored."""
        mock_column = MagicMock()

        filter_ = PhraseProximityFilter(
            mock_column,
            ["full", "text", "search"],
            max_distance=2,
        )

        assert filter_.words == ["full", "text", "search"]
        assert filter_.max_distance == 2

    def test_default_distance_is_adjacent(self):
        """Default distance should be 1 (adjacent)."""
        filter_ = PhraseProximityFilter(
            MagicMock(),
            ["word1", "word2"],
        )

        assert filter_.max_distance == 1

    def test_whitespace_words_filtered(self):
        """Whitespace-only words should be filtered."""
        filter_ = PhraseProximityFilter(
            MagicMock(),
            ["  hello  ", "", "world"],
        )

        assert filter_.words == ["hello", "world"]


# ──────────────────────────────────────────────────────────────
# Test BoostedSearchFilter
# ──────────────────────────────────────────────────────────────


class TestBoostedSearchFilter:
    """Tests for BoostedSearchFilter."""

    def test_weight_boosts(self):
        """Filter should store weight boosts."""
        mock_column = MagicMock()

        filter_ = BoostedSearchFilter(
            mock_column,
            "python",
            weight_boosts={"A": 4.0, "B": 2.0},
        )

        assert filter_.weight_boosts["A"] == 4.0
        assert filter_.weight_boosts["B"] == 2.0

    def test_term_boosts(self):
        """Filter should store term boosts."""
        mock_column = MagicMock()

        filter_ = BoostedSearchFilter(
            mock_column,
            "python django",
            term_boosts={"python": 2.0},
        )

        assert filter_.term_boosts["python"] == 2.0


# ──────────────────────────────────────────────────────────────
# Test HybridSearchFilter
# ──────────────────────────────────────────────────────────────


class TestHybridSearchFilter:
    """Tests for HybridSearchFilter (FTS + Fuzzy)."""

    def test_stores_parameters(self):
        """Filter should store all parameters."""
        mock_search_col = MagicMock()
        mock_fuzzy_col = MagicMock()

        filter_ = HybridSearchFilter(
            search_column=mock_search_col,
            fuzzy_column=mock_fuzzy_col,
            query="python",
            fts_weight=0.8,
            fuzzy_weight=0.2,
        )

        assert filter_.search_column == mock_search_col
        assert filter_.fuzzy_column == mock_fuzzy_col
        assert filter_.fts_weight == 0.8
        assert filter_.fuzzy_weight == 0.2

    def test_default_weights(self):
        """Default weights should favor FTS."""
        filter_ = HybridSearchFilter(
            search_column=MagicMock(),
            fuzzy_column=MagicMock(),
            query="test",
        )

        assert filter_.fts_weight == 0.7
        assert filter_.fuzzy_weight == 0.3


# ──────────────────────────────────────────────────────────────
# Test MultiFieldSearchFilter
# ──────────────────────────────────────────────────────────────


class TestMultiFieldSearchFilter:
    """Tests for MultiFieldSearchFilter."""

    def test_stores_field_configs(self):
        """Filter should store field configurations."""
        mock_col1 = MagicMock()
        mock_col2 = MagicMock()

        filter_ = MultiFieldSearchFilter(
            field_configs=[(mock_col1, 4.0), (mock_col2, 1.0)],
            query="python",
        )

        assert len(filter_.field_configs) == 2
        assert filter_.field_configs[0][1] == 4.0
        assert filter_.field_configs[1][1] == 1.0

    def test_require_all_option(self):
        """Filter should support require_all mode."""
        filter_ = MultiFieldSearchFilter(
            field_configs=[(MagicMock(), 1.0)],
            query="test",
            require_all=True,
        )

        assert filter_.require_all is True


# ──────────────────────────────────────────────────────────────
# Test RankingOptions
# ──────────────────────────────────────────────────────────────


class TestRankingOptions:
    """Tests for RankingOptions."""

    def test_default_normalization(self):
        """Default should use SELF_PLUS_ONE normalization."""
        options = RankingOptions()
        assert options.normalization == RankNormalization.SELF_PLUS_ONE

    def test_cover_density_option(self):
        """Should support cover density ranking."""
        options = RankingOptions(use_cover_density=True)
        assert options.use_cover_density is True

    def test_custom_weights(self):
        """Should support custom weight configuration."""
        options = RankingOptions(weights=(0.1, 0.2, 0.3, 1.0))
        assert options.weights == (0.1, 0.2, 0.3, 1.0)


# ──────────────────────────────────────────────────────────────
# Test RankNormalization
# ──────────────────────────────────────────────────────────────


class TestRankNormalization:
    """Tests for RankNormalization flags."""

    def test_can_combine_flags(self):
        """Flags should be combinable with bitwise OR."""
        combined = RankNormalization.LOG_LENGTH | RankNormalization.UNIQUE_WORDS
        assert combined == 9  # 1 | 8

    def test_none_is_zero(self):
        """NONE should be 0."""
        assert RankNormalization.NONE == 0


# ──────────────────────────────────────────────────────────────
# Test SearchQueryParser
# ──────────────────────────────────────────────────────────────


class TestSearchQueryParser:
    """Tests for SearchQueryParser."""

    def test_parse_simple_query(self):
        """Parser should handle simple word queries."""
        parser = SearchQueryParser()
        result = parser.parse("python programming")

        assert result.original_query == "python programming"
        assert "python" in result.tsquery_parts
        assert "programming" in result.tsquery_parts

    def test_parse_quoted_phrase(self):
        """Parser should extract quoted phrases."""
        parser = SearchQueryParser()
        result = parser.parse('"exact phrase"')

        assert '"exact phrase"' in result.tsquery_parts

    def test_parse_field_term(self):
        """Parser should extract field:value terms."""
        parser = SearchQueryParser()
        result = parser.parse("title:python")

        assert "title" in result.field_filters
        assert "python" in result.field_filters["title"]

    def test_parse_field_phrase(self):
        """Parser should extract field:'phrase' terms."""
        parser = SearchQueryParser()
        result = parser.parse('author:"John Doe"')

        assert "author" in result.field_filters
        assert '"John Doe"' in result.field_filters["author"]

    def test_parse_exclusion(self):
        """Parser should extract -word exclusions."""
        parser = SearchQueryParser()
        result = parser.parse("python -java")

        assert "python" in result.tsquery_parts
        assert "java" in result.exclusions

    def test_parse_prefix(self):
        """Parser should extract word* prefix terms."""
        parser = SearchQueryParser()
        result = parser.parse("pytho*")

        assert "pytho" in result.prefix_terms

    def test_parse_fuzzy(self):
        """Parser should extract ~word fuzzy terms."""
        parser = SearchQueryParser()
        result = parser.parse("~python")

        assert "python" in result.fuzzy_terms

    def test_empty_query(self):
        """Parser should handle empty queries."""
        parser = SearchQueryParser()
        result = parser.parse("")

        assert result.original_query == ""
        assert not result.has_fts_query()

    def test_has_fts_query_true(self):
        """has_fts_query should be true with search terms."""
        parser = SearchQueryParser()
        result = parser.parse("python")

        assert result.has_fts_query() is True

    def test_has_field_filters(self):
        """has_field_filters should detect field searches."""
        parser = SearchQueryParser()
        result = parser.parse("title:test")

        assert result.has_field_filters() is True

    def test_has_exclusions(self):
        """has_exclusions should detect excluded terms."""
        parser = SearchQueryParser()
        result = parser.parse("-java")

        assert result.has_exclusions() is True


# ──────────────────────────────────────────────────────────────
# Test QueryRewriter
# ──────────────────────────────────────────────────────────────


class TestQueryRewriter:
    """Tests for QueryRewriter."""

    def test_expand_synonyms(self):
        """Rewriter should expand synonyms."""
        rewriter = QueryRewriter(
            synonyms={"python": ["py", "python3"]}
        )

        result = rewriter.expand_synonyms("python programming")

        assert "python" in result
        assert "OR" in result

    def test_remove_stop_words(self):
        """Rewriter should remove stop words."""
        rewriter = QueryRewriter(
            stop_words={"the", "a", "an"}
        )

        result = rewriter.remove_stop_words("the python programming")

        assert "the" not in result
        assert "python" in result

    def test_normalize_whitespace(self):
        """Rewriter should normalize whitespace."""
        rewriter = QueryRewriter()

        result = rewriter.normalize("  python    programming  ")

        assert result == "python programming"

    def test_min_word_length(self):
        """Rewriter should filter short words."""
        rewriter = QueryRewriter(min_word_length=3)

        result = rewriter.normalize("a in python")

        assert "a" not in result
        assert "in" not in result
        assert "python" in result


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

    def test_build_search_vector_sql_with_prefix(self):
        """Mixin should support prefix for triggers."""
        from example_service.core.database.search.mixins import SearchableMixin

        class TestModel(SearchableMixin):
            __tablename__ = "test"
            __search_fields__ = ["title"]
            __search_config__ = "english"

        model = TestModel()
        sql = model.build_search_vector_sql(prefix="NEW.")

        assert "NEW.title" in sql

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

    def test_get_backfill_sql(self):
        """Mixin should generate backfill SQL."""
        from example_service.core.database.search.mixins import SearchableMixin

        class TestModel(SearchableMixin):
            __tablename__ = "articles"
            __search_fields__ = ["title"]
            __search_config__ = "english"

        sql = TestModel.get_backfill_sql("articles")

        assert "UPDATE articles SET search_vector" in sql
        assert "to_tsvector" in sql

    def test_get_drop_trigger_sql(self):
        """Mixin should generate drop trigger SQL."""
        from example_service.core.database.search.mixins import SearchableMixin

        class TestModel(SearchableMixin):
            __tablename__ = "products"
            __search_fields__ = ["name"]

        sql = TestModel.get_drop_trigger_sql("products")

        assert "DROP TRIGGER IF EXISTS" in sql
        assert "DROP FUNCTION IF EXISTS" in sql

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

    def test_get_field_config(self):
        """Mixin should return field-specific config."""
        from example_service.core.database.search.mixins import SearchableMixin

        class TestModel(SearchableMixin):
            __tablename__ = "test"
            __search_fields__ = ["title", "content"]
            __search_config__ = "english"
            __search_field_configs__ = {"title": "simple"}

        assert TestModel.get_field_config("title") == "simple"
        assert TestModel.get_field_config("content") == "english"

    def test_get_field_weight(self):
        """Mixin should return field weight."""
        from example_service.core.database.search.mixins import SearchableMixin

        class TestModel(SearchableMixin):
            __tablename__ = "test"
            __search_fields__ = ["title"]
            __search_weights__ = {"title": "A"}

        assert TestModel.get_field_weight("title") == "A"
        assert TestModel.get_field_weight("unknown") == "D"


# ──────────────────────────────────────────────────────────────
# Test MultiLanguageSearchMixin
# ──────────────────────────────────────────────────────────────


class TestMultiLanguageSearchMixin:
    """Tests for MultiLanguageSearchMixin."""

    def test_get_search_trigger_sql_multilang(self):
        """Mixin should generate language-aware trigger SQL."""
        from example_service.core.database.search.mixins import MultiLanguageSearchMixin

        class TestModel(MultiLanguageSearchMixin):
            __tablename__ = "articles"
            __search_fields__ = ["title", "content"]
            __language_column__ = "language"
            __language_configs__ = {"en": "english", "es": "spanish"}

        sql = TestModel.get_search_trigger_sql("articles")

        assert "CASE NEW.language" in sql
        assert "english" in sql
        assert "spanish" in sql


# ──────────────────────────────────────────────────────────────
# Test FTSMigrationHelper
# ──────────────────────────────────────────────────────────────


class TestFTSMigrationHelper:
    """Tests for FTSMigrationHelper."""

    def test_default_names(self):
        """Helper should generate default names."""
        helper = FTSMigrationHelper(
            table_name="articles",
            search_fields=["title", "content"],
        )

        assert helper.index_name == "ix_articles_search_vector"
        assert helper.trigger_name == "articles_search_update"
        assert helper.function_name == "articles_search_vector_update"

    def test_custom_names(self):
        """Helper should accept custom names."""
        helper = FTSMigrationHelper(
            table_name="articles",
            search_fields=["title"],
            index_name="custom_idx",
            trigger_name="custom_trigger",
            function_name="custom_func",
        )

        assert helper.index_name == "custom_idx"
        assert helper.trigger_name == "custom_trigger"
        assert helper.function_name == "custom_func"

    def test_get_trigger_function_sql(self):
        """Helper should generate trigger function SQL."""
        helper = FTSMigrationHelper(
            table_name="posts",
            search_fields=["title", "body"],
            weights={"title": "A", "body": "B"},
        )

        sql = helper.get_trigger_function_sql()

        assert "CREATE OR REPLACE FUNCTION" in sql
        assert "posts_search_vector_update()" in sql
        assert "NEW.title" in sql
        assert "NEW.body" in sql

    def test_get_backfill_sql(self):
        """Helper should generate backfill SQL."""
        helper = FTSMigrationHelper(
            table_name="posts",
            search_fields=["title"],
        )

        sql = helper.get_backfill_sql()

        assert "UPDATE posts SET search_vector" in sql


# ──────────────────────────────────────────────────────────────
# Test TrigramMigrationHelper
# ──────────────────────────────────────────────────────────────


class TestTrigramMigrationHelper:
    """Tests for TrigramMigrationHelper."""

    def test_default_index_name(self):
        """Helper should generate default index name."""
        helper = TrigramMigrationHelper(
            table_name="products",
            field_name="name",
        )

        assert helper.index_name == "ix_products_name_trgm"

    def test_get_index_sql(self):
        """Helper should generate index creation SQL."""
        helper = TrigramMigrationHelper(
            table_name="products",
            field_name="name",
        )

        sql = helper.get_index_sql()

        assert "CREATE INDEX" in sql
        assert "gin_trgm_ops" in sql


# ──────────────────────────────────────────────────────────────
# Test UnaccentMigrationHelper
# ──────────────────────────────────────────────────────────────


class TestUnaccentMigrationHelper:
    """Tests for UnaccentMigrationHelper."""

    def test_get_config_sql(self):
        """Helper should generate config SQL."""
        helper = UnaccentMigrationHelper(
            config_name="english_unaccent",
            base_config="english",
        )

        sql = helper.get_config_sql()

        assert "CREATE TEXT SEARCH CONFIGURATION" in sql
        assert "unaccent" in sql


# ──────────────────────────────────────────────────────────────
# Test generate_search_vector_sql utility
# ──────────────────────────────────────────────────────────────


class TestGenerateSearchVectorSQL:
    """Tests for generate_search_vector_sql utility."""

    def test_basic_generation(self):
        """Should generate basic search vector SQL."""
        sql = generate_search_vector_sql(
            fields=["title", "content"],
            weights={"title": "A"},
            config="english",
        )

        assert "setweight" in sql
        assert "to_tsvector" in sql

    def test_with_prefix(self):
        """Should support column prefix."""
        sql = generate_search_vector_sql(
            fields=["title"],
            prefix="NEW.",
        )

        assert "NEW.title" in sql

    def test_empty_fields(self):
        """Should handle empty fields."""
        sql = generate_search_vector_sql(
            fields=[],
        )

        assert "to_tsvector('english', '')" in sql
