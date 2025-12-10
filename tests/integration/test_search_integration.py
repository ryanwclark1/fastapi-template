"""Integration tests for PostgreSQL full-text search.

These tests run against a real PostgreSQL container to verify:
- Trigger execution for automatic search vector updates
- Ranking accuracy for different query types
- Fuzzy matching threshold tuning
- Search analytics recording
- Synonym expansion
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from tests.conftest import ENUM_DEFINITIONS

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
async def search_db_engine(postgres_container: str):
    """Create engine with pg_trgm extension for search tests.

    This fixture creates the necessary PostgreSQL extensions
    for full-text search testing.
    """
    engine = create_async_engine(
        postgres_container,
        echo=False,
        future=True,
    )

    # Create extensions needed for search
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS unaccent"))

    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def search_session(search_db_engine) -> AsyncSession:
    """Create session with search tables and triggers."""
    from example_service.core.database.base import Base
    from example_service.features.reminders import (
        models as reminder_models,
    )

    # Ensure enum types exist before creating tables
    enum_definitions = ENUM_DEFINITIONS

    async with search_db_engine.begin() as conn:
        for values, name in enum_definitions:
            values_sql = ", ".join(f"'{value}'" for value in values)
            await conn.execute(
                text(
                    f"""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = '{name}') THEN
                            CREATE TYPE {name} AS ENUM ({values_sql});
                        END IF;
                    END
                    $$;
                    """
                )
            )

        # Create all tables
        await conn.run_sync(Base.metadata.create_all)

        # Create the search trigger function and trigger
        await conn.execute(text("""
            CREATE OR REPLACE FUNCTION reminders_search_vector_update()
            RETURNS trigger AS $$
            BEGIN
                NEW.search_vector := setweight(to_tsvector('english', COALESCE(NEW.title, '')), 'A') ||
                                     setweight(to_tsvector('english', COALESCE(NEW.description, '')), 'B');
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """))

        await conn.execute(text("""
            DROP TRIGGER IF EXISTS reminders_search_update ON reminders;
            CREATE TRIGGER reminders_search_update
                BEFORE INSERT OR UPDATE ON reminders
                FOR EACH ROW
                EXECUTE FUNCTION reminders_search_vector_update();
        """))

        # Create GIN index for fast search
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_reminders_search_vector
            ON reminders USING gin(search_vector);
        """))

        # Create trigram index for fuzzy search
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_reminders_title_trgm
            ON reminders USING gin(title gin_trgm_ops);
        """))

    # Create session
    async_session_maker = sessionmaker(
        search_db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session_maker() as session:
        try:
            # Lower trigram threshold slightly so typo-based tests remain stable
            await session.execute(text("SET pg_trgm.similarity_threshold = 0.2"))
            yield session
        finally:
            await session.rollback()

    # Clean up
    async with search_db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# ============================================================================
# Trigger Execution Tests
# ============================================================================


class TestSearchTriggers:
    """Test that search triggers execute correctly."""

    @pytest.mark.asyncio
    async def test_trigger_populates_search_vector_on_insert(self, search_session):
        """Search vector should be populated automatically on INSERT."""
        from example_service.features.reminders.models import Reminder

        # Insert a reminder
        reminder = Reminder(
            title="Python Programming Tutorial",
            description="Learn Python basics and advanced concepts",
        )
        search_session.add(reminder)
        await search_session.commit()
        await search_session.refresh(reminder)

        # Verify search vector was populated
        result = await search_session.execute(
            text("""
                SELECT search_vector IS NOT NULL as has_vector,
                       ts_rank(search_vector, to_tsquery('english', 'python')) as rank
                FROM reminders WHERE id = :id
            """),
            {"id": reminder.id},
        )
        row = result.first()

        assert row.has_vector is True
        assert row.rank > 0

    @pytest.mark.asyncio
    async def test_trigger_updates_search_vector_on_update(self, search_session):
        """Search vector should be updated when content changes."""
        from example_service.features.reminders.models import Reminder

        # Insert a reminder
        reminder = Reminder(
            title="Original Title",
            description="Original description",
        )
        search_session.add(reminder)
        await search_session.commit()

        # Verify original doesn't match 'javascript'
        result = await search_session.execute(
            text("""
                SELECT ts_rank(search_vector, to_tsquery('english', 'javascript')) as rank
                FROM reminders WHERE id = :id
            """),
            {"id": reminder.id},
        )
        original_rank = result.scalar()
        assert original_rank == 0

        # Update the reminder
        reminder.title = "JavaScript Tutorial"
        await search_session.commit()

        # Verify search vector was updated
        result = await search_session.execute(
            text("""
                SELECT ts_rank(search_vector, to_tsquery('english', 'javascript')) as rank
                FROM reminders WHERE id = :id
            """),
            {"id": reminder.id},
        )
        new_rank = result.scalar()
        assert new_rank > 0


# ============================================================================
# Ranking Accuracy Tests
# ============================================================================


class TestSearchRanking:
    """Test search ranking accuracy."""

    @pytest.fixture
    async def sample_reminders(self, search_session):
        """Create sample reminders for ranking tests."""
        from example_service.features.reminders.models import Reminder

        reminders = [
            Reminder(
                title="Python Django Tutorial",
                description="Learn to build web apps with Django",
            ),
            Reminder(
                title="Python Basics",
                description="Python fundamentals for beginners. Python is great.",
            ),
            Reminder(
                title="JavaScript Fundamentals",
                description="Learn JavaScript with Python comparisons",
            ),
            Reminder(
                title="Machine Learning with Python",
                description="Python ML tutorial covering scikit-learn and tensorflow",
            ),
        ]

        for r in reminders:
            search_session.add(r)
        await search_session.commit()

        return reminders

    @pytest.mark.asyncio
    async def test_title_matches_rank_higher_than_description(
        self, search_session, sample_reminders
    ):
        """Title matches should rank higher due to weight 'A'."""
        result = await search_session.execute(
            text("""
                SELECT id, title,
                       ts_rank(search_vector, to_tsquery('english', 'python')) as rank
                FROM reminders
                WHERE search_vector @@ to_tsquery('english', 'python')
                ORDER BY rank DESC
            """)
        )
        rows = result.fetchall()

        # Python should be in multiple results
        assert len(rows) >= 3

        # First results should have Python in title
        top_titles = [r.title for r in rows[:2]]
        assert any("Python" in t for t in top_titles)

    @pytest.mark.asyncio
    async def test_phrase_search_accuracy(self, search_session, sample_reminders):
        """Phrase search should match exact sequences."""
        result = await search_session.execute(
            text("""
                SELECT id, title
                FROM reminders
                WHERE search_vector @@ phraseto_tsquery('english', 'python django')
            """)
        )
        rows = result.fetchall()

        # Should find "Python Django Tutorial"
        assert len(rows) == 1
        assert "Django" in rows[0].title

    @pytest.mark.asyncio
    async def test_web_search_exclusion(self, search_session, sample_reminders):
        """Web search with exclusion should work correctly."""
        result = await search_session.execute(
            text("""
                SELECT id, title
                FROM reminders
                WHERE search_vector @@ websearch_to_tsquery('english', 'python -django')
                ORDER BY ts_rank(search_vector, websearch_to_tsquery('english', 'python -django')) DESC
            """)
        )
        rows = result.fetchall()

        # Should find Python results but not Django
        assert len(rows) >= 2
        for row in rows:
            assert "Django" not in row.title

    @pytest.mark.asyncio
    async def test_or_search(self, search_session, sample_reminders):
        """OR search should find matches for any term."""
        result = await search_session.execute(
            text("""
                SELECT id, title
                FROM reminders
                WHERE search_vector @@ websearch_to_tsquery('english', 'django OR machine')
            """)
        )
        rows = result.fetchall()

        # Should find Django and Machine Learning tutorials
        assert len(rows) >= 2
        titles = [r.title for r in rows]
        assert any("Django" in t for t in titles)
        assert any("Machine" in t for t in titles)


# ============================================================================
# Fuzzy Matching Tests
# ============================================================================


class TestFuzzySearch:
    """Test fuzzy matching threshold tuning."""

    @pytest.fixture
    async def reminders_for_fuzzy(self, search_session):
        """Create reminders for fuzzy search testing."""
        from example_service.features.reminders.models import Reminder

        reminders = [
            Reminder(title="Python Programming", description="Python basics"),
            Reminder(title="JavaScript Guide", description="JS fundamentals"),
            Reminder(title="PostgreSQL Database", description="SQL queries"),
        ]

        for r in reminders:
            search_session.add(r)
        await search_session.commit()

        return reminders

    @pytest.mark.asyncio
    async def test_fuzzy_match_with_typo(self, search_session, reminders_for_fuzzy):
        """Fuzzy search should find results with typos."""
        # "pythn" is a typo for "python"
        result = await search_session.execute(
            text("""
                SELECT id, title, similarity(title, 'pythn') as sim
                FROM reminders
                WHERE title % 'pythn'
                ORDER BY sim DESC
            """)
        )
        rows = result.fetchall()

        # Should find Python Programming
        assert len(rows) >= 1
        assert "Python" in rows[0].title

    @pytest.mark.asyncio
    async def test_fuzzy_threshold_low(self, search_session, reminders_for_fuzzy):
        """Low threshold should return more matches."""
        # Set threshold to 0.2 (more permissive)
        await search_session.execute(text("SET pg_trgm.similarity_threshold = 0.2"))

        result = await search_session.execute(
            text("""
                SELECT id, title, similarity(title, 'postgrs') as sim
                FROM reminders
                WHERE title % 'postgrs'
            """)
        )
        rows = result.fetchall()

        # Should find PostgreSQL
        assert len(rows) >= 1
        assert "PostgreSQL" in rows[0].title

    @pytest.mark.asyncio
    async def test_fuzzy_threshold_high(self, search_session, reminders_for_fuzzy):
        """High threshold should require closer matches."""
        # Set threshold to 0.6 (more strict)
        await search_session.execute(text("SET pg_trgm.similarity_threshold = 0.6"))

        result = await search_session.execute(
            text("""
                SELECT id, title, similarity(title, 'pythn') as sim
                FROM reminders
                WHERE title % 'pythn'
            """)
        )
        rows = result.fetchall()

        # May not find matches with high threshold and short typo
        # This tests that threshold tuning works
        if rows:
            assert rows[0].sim >= 0.6

    @pytest.mark.asyncio
    async def test_word_similarity_for_long_text(self, search_session, reminders_for_fuzzy):
        """word_similarity works better for searching within longer text."""
        result = await search_session.execute(
            text("""
                SELECT id, title,
                       word_similarity('python', title) as wsim,
                       similarity('python', title) as sim
                FROM reminders
                ORDER BY wsim DESC
            """)
        )
        rows = result.fetchall()

        # Word similarity for 'python' in 'Python Programming' should be high
        python_row = next((r for r in rows if "Python" in r.title), None)
        assert python_row is not None
        assert python_row.wsim > python_row.sim  # word_similarity handles partial matches better


# ============================================================================
# Search Analytics Tests
# ============================================================================


class TestSearchAnalytics:
    """Test search analytics recording."""

    @pytest.fixture
    async def analytics_session(self, search_session):
        """Create search analytics tables."""
        await search_session.execute(text("""
            CREATE TABLE IF NOT EXISTS search_queries (
                id SERIAL PRIMARY KEY,
                query_text VARCHAR(500) NOT NULL,
                query_hash VARCHAR(64) NOT NULL,
                normalized_query VARCHAR(500),
                entity_types JSONB,
                results_count INTEGER DEFAULT 0,
                took_ms INTEGER DEFAULT 0,
                user_id VARCHAR(255),
                session_id VARCHAR(255),
                clicked_result BOOLEAN DEFAULT FALSE,
                clicked_position INTEGER,
                clicked_entity_id VARCHAR(255),
                search_syntax VARCHAR(50),
                metadata JSONB,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """))
        await search_session.commit()
        return search_session

    @pytest.mark.asyncio
    async def test_record_search_query(self, analytics_session):
        """Analytics should record search queries."""
        from example_service.core.database.search import SearchAnalytics

        analytics = SearchAnalytics(analytics_session)

        search = await analytics.record_search(
            query="python tutorial",
            results_count=42,
            took_ms=150,
            entity_types=["reminders", "posts"],
            search_syntax="web",
        )

        assert search.id is not None
        assert search.query_text == "python tutorial"
        assert search.results_count == 42
        assert search.took_ms == 150

    @pytest.mark.asyncio
    async def test_record_click(self, analytics_session):
        """Analytics should record search result clicks."""
        from example_service.core.database.search import SearchAnalytics

        analytics = SearchAnalytics(analytics_session)

        # Record a search first
        search = await analytics.record_search(
            query="test query",
            results_count=10,
            took_ms=100,
        )

        # Record a click
        await analytics.record_click(
            search_id=search.id,
            clicked_position=2,
            clicked_entity_id="reminder-123",
        )

        # Verify click was recorded
        result = await analytics_session.execute(
            text("SELECT clicked_result, clicked_position FROM search_queries WHERE id = :id"),
            {"id": search.id},
        )
        row = result.first()

        assert row.clicked_result is True
        assert row.clicked_position == 2

    @pytest.mark.asyncio
    async def test_zero_result_tracking(self, analytics_session):
        """Analytics should track zero-result queries."""
        from example_service.core.database.search import SearchAnalytics

        analytics = SearchAnalytics(analytics_session)

        # Record some searches with no results
        for query in ["nonexistent", "notfound", "nonexistent"]:
            await analytics.record_search(
                query=query,
                results_count=0,
                took_ms=50,
            )

        await analytics_session.commit()

        # Get zero result queries
        zero_results = await analytics.get_zero_result_queries(days=1)

        # Should find 'nonexistent' twice
        nonexistent = next((q for q in zero_results if q["query"] == "nonexistent"), None)
        assert nonexistent is not None
        assert nonexistent["count"] == 2


# ============================================================================
# Synonym Integration Tests
# ============================================================================


class TestSynonymIntegration:
    """Test synonym expansion integration."""

    @pytest.mark.asyncio
    async def test_synonym_expansion_in_query(self, search_session):
        """Synonym expansion should expand queries correctly."""
        from example_service.core.database.search import get_default_synonyms

        synonyms = get_default_synonyms()

        # Test expansion
        expanded = synonyms.expand_query("py tutorial")

        # Should include python variants
        assert "python" in expanded.lower()
        assert "py" in expanded.lower()
        assert "OR" in expanded

    @pytest.mark.asyncio
    async def test_query_rewriter_with_synonyms(self, search_session):
        """QueryRewriter should use synonym dictionary."""
        from example_service.core.database.search import (
            QueryRewriter,
            get_default_synonyms,
        )

        rewriter = QueryRewriter.with_dictionary(get_default_synonyms())

        # Expand a query with synonyms
        expanded = rewriter.expand_synonyms("py config")

        # Should expand both py and config
        assert "python" in expanded.lower()
        assert "OR" in expanded

    @pytest.mark.asyncio
    async def test_custom_synonym_dictionary(self, search_session):
        """Custom synonyms should work correctly."""
        from example_service.core.database.search import SynonymDictionary

        # Create custom synonyms
        synonyms = SynonymDictionary(name="custom")
        synonyms.add_group(["reminder", "todo", "task"])
        synonyms.add_pair("meeting", "appointment")

        # Test expansion
        expanded = synonyms.expand_query("reminder meeting")

        assert "todo" in expanded.lower()
        assert "task" in expanded.lower()
        assert "appointment" in expanded.lower()


# ============================================================================
# Combined Search Flow Tests
# ============================================================================


class TestSearchFlow:
    """Test complete search workflows."""

    @pytest.fixture
    async def populated_search_db(self, search_session):
        """Create a populated search database."""
        from example_service.features.reminders.models import Reminder

        # Create analytics table
        await search_session.execute(text("""
            CREATE TABLE IF NOT EXISTS search_queries (
                id SERIAL PRIMARY KEY,
                query_text VARCHAR(500) NOT NULL,
                query_hash VARCHAR(64) NOT NULL,
                normalized_query VARCHAR(500),
                entity_types JSONB,
                results_count INTEGER DEFAULT 0,
                took_ms INTEGER DEFAULT 0,
                user_id VARCHAR(255),
                session_id VARCHAR(255),
                clicked_result BOOLEAN DEFAULT FALSE,
                clicked_position INTEGER,
                clicked_entity_id VARCHAR(255),
                search_syntax VARCHAR(50),
                metadata JSONB,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """))

        # Create reminders
        reminders = [
            Reminder(title="Python Web Development", description="Django and Flask tutorials"),
            Reminder(title="Database Design", description="PostgreSQL best practices"),
            Reminder(title="API Development", description="RESTful Python APIs"),
            Reminder(title="Testing Guide", description="Python unit testing with pytest"),
            Reminder(title="DevOps Basics", description="Docker and Kubernetes"),
        ]

        for r in reminders:
            search_session.add(r)
        await search_session.commit()

        return search_session

    @pytest.mark.asyncio
    async def test_full_search_workflow(self, populated_search_db):
        """Test a complete search workflow with analytics."""
        session = populated_search_db

        # 1. Execute a full-text search
        result = await session.execute(
            text("""
                SELECT id, title, description,
                       ts_rank(search_vector, websearch_to_tsquery('english', 'python web')) as rank
                FROM reminders
                WHERE search_vector @@ websearch_to_tsquery('english', 'python web')
                ORDER BY rank DESC
                LIMIT 10
            """)
        )
        rows = result.fetchall()

        assert len(rows) >= 1
        # Python Web Development should rank highest
        assert "Python" in rows[0].title

        # 2. Record the search in analytics
        from example_service.core.database.search import SearchAnalytics

        analytics = SearchAnalytics(session)
        search_record = await analytics.record_search(
            query="python web",
            results_count=len(rows),
            took_ms=50,
            entity_types=["reminders"],
        )

        # 3. Simulate a click on the first result
        await analytics.record_click(
            search_id=search_record.id,
            clicked_position=1,
            clicked_entity_id=str(rows[0].id),
        )

        await session.commit()

        # 4. Get stats
        stats = await analytics.get_stats(days=1)
        assert stats.total_searches >= 1
        assert stats.click_through_rate > 0

    @pytest.mark.asyncio
    async def test_fuzzy_fallback_workflow(self, populated_search_db):
        """Test fuzzy fallback when FTS returns no results."""
        session = populated_search_db

        # 1. Try FTS search that returns nothing
        fts_result = await session.execute(
            text("""
                SELECT COUNT(*) as cnt
                FROM reminders
                WHERE search_vector @@ to_tsquery('english', 'pythno')
            """)
        )
        fts_count = fts_result.scalar()
        assert fts_count == 0  # Typo returns nothing

        # 2. Fall back to fuzzy search
        await session.execute(text("SET pg_trgm.similarity_threshold = 0.3"))

        fuzzy_result = await session.execute(
            text("""
                SELECT id, title, similarity(title, 'pythno') as sim
                FROM reminders
                WHERE title % 'pythno'
                ORDER BY sim DESC
                LIMIT 5
            """)
        )
        fuzzy_rows = fuzzy_result.fetchall()

        # Fuzzy should find Python results
        assert len(fuzzy_rows) >= 1
        assert "Python" in fuzzy_rows[0].title
