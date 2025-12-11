"""Performance tests for database operations.

Tests the performance of common database operations using
SQLAlchemy async queries.
"""

from __future__ import annotations

import pytest

pytest_plugins = ["pytest_asyncio"]


@pytest.fixture
def mock_records():
    """Generate mock records for batch operations."""
    return [
        {
            "id": f"id-{i}",
            "title": f"Record {i}",
            "description": f"Description for record {i}",
            "is_active": i % 2 == 0,
        }
        for i in range(100)
    ]


class TestQueryBuilding:
    """Benchmark SQLAlchemy query building (without execution)."""

    @pytest.mark.benchmark(group="query-building")
    def test_simple_select_build(self, benchmark):
        """Benchmark building a simple select query."""
        from sqlalchemy import Column, Integer, MetaData, String, Table, select

        metadata = MetaData()
        test_table = Table(
            "test",
            metadata,
            Column("id", Integer, primary_key=True),
            Column("name", String),
        )

        def build_query():
            return select(test_table).where(test_table.c.id == 1)

        result = benchmark(build_query)
        assert result is not None

    @pytest.mark.benchmark(group="query-building")
    def test_complex_select_build(self, benchmark):
        """Benchmark building a complex select query with joins."""
        from sqlalchemy import (
            Column,
            ForeignKey,
            Integer,
            MetaData,
            String,
            Table,
            select,
        )

        metadata = MetaData()
        users = Table(
            "users",
            metadata,
            Column("id", Integer, primary_key=True),
            Column("name", String),
        )
        posts = Table(
            "posts",
            metadata,
            Column("id", Integer, primary_key=True),
            Column("user_id", Integer, ForeignKey("users.id")),
            Column("title", String),
        )

        def build_query():
            return (
                select(users, posts)
                .join(posts, users.c.id == posts.c.user_id)
                .where(users.c.name.like("%test%"))
                .order_by(posts.c.title)
                .limit(100)
            )

        result = benchmark(build_query)
        assert result is not None

    @pytest.mark.benchmark(group="query-building")
    def test_insert_build(self, benchmark, mock_records):
        """Benchmark building bulk insert."""
        from sqlalchemy import Column, Integer, MetaData, String, Table, insert

        metadata = MetaData()
        test_table = Table(
            "test",
            metadata,
            Column("id", Integer, primary_key=True),
            Column("name", String),
            Column("description", String),
        )

        def build_insert():
            return insert(test_table).values(
                [{"name": r["title"], "description": r["description"]} for r in mock_records],
            )

        result = benchmark(build_insert)
        assert result is not None


class TestDataTransformation:
    """Benchmark data transformation operations common in DB workflows."""

    @pytest.mark.benchmark(group="data-transform")
    def test_dict_to_model_mapping(self, benchmark, mock_records):
        """Benchmark mapping dicts to a structure."""

        def transform():
            return [
                {
                    "title": r["title"].upper(),
                    "description": r["description"][:50],
                    "status": "active" if r["is_active"] else "inactive",
                }
                for r in mock_records
            ]

        result = benchmark(transform)
        assert len(result) == len(mock_records)

    @pytest.mark.benchmark(group="data-transform")
    def test_batch_chunking(self, benchmark, mock_records):
        """Benchmark chunking records into batches."""

        def chunk_records(records, size=10):
            return [records[i : i + size] for i in range(0, len(records), size)]

        result = benchmark(chunk_records, mock_records)
        assert len(result) == 10  # 100 records / 10 = 10 chunks
