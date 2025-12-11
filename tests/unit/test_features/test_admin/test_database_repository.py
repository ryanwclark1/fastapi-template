"""Unit tests for DatabaseAdminRepository.

This module tests the database administration repository including:
- Connection pool statistics
- Database size queries
- Active connection counts
- Cache hit ratio queries
- Table and index health queries
- Replication lag monitoring
- Active query monitoring
- Database statistics summaries
- Audit logging
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch
from uuid import uuid4

import pytest
from sqlalchemy import text

from example_service.features.admin.database.repository import (
    DatabaseAdminRepository,
    get_database_admin_repository,
)


@pytest.fixture
def repository() -> DatabaseAdminRepository:
    """Create DatabaseAdminRepository instance."""
    return DatabaseAdminRepository()


@pytest.fixture
def mock_session() -> AsyncMock:
    """Create mock async database session."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


# =============================================================================
# Initialization Tests
# =============================================================================


class TestRepositoryInitialization:
    """Tests for repository initialization."""

    def test_repository_initialization(self, repository: DatabaseAdminRepository) -> None:
        """Test that repository initializes correctly."""
        assert repository is not None
        assert repository._logger is not None
        assert repository._lazy is not None

    def test_get_database_admin_repository_singleton(self) -> None:
        """Test that get_database_admin_repository returns singleton."""
        repo1 = get_database_admin_repository()
        repo2 = get_database_admin_repository()

        assert repo1 is repo2
        assert isinstance(repo1, DatabaseAdminRepository)


# =============================================================================
# Connection Pool Stats Tests
# =============================================================================


class TestGetConnectionPoolStats:
    """Tests for get_connection_pool_stats method."""

    @pytest.mark.asyncio
    async def test_get_connection_pool_stats_success(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test successfully getting connection pool statistics."""
        # Mock result
        mock_result = MagicMock()
        mock_row = {
            "active_connections": 8,
            "idle_connections": 12,
            "total_connections": 20,
            "max_connections": 100,
        }
        mock_result.mappings().first.return_value = mock_row
        mock_session.execute.return_value = mock_result

        stats = await repository.get_connection_pool_stats(mock_session)

        assert stats["active_connections"] == 8
        assert stats["idle_connections"] == 12
        assert stats["total_connections"] == 20
        assert stats["max_connections"] == 100

        # Verify query execution
        assert mock_session.execute.call_count == 2  # SET timeout + query
        # Both timeout and actual query were executed
        mock_session.execute.assert_called()

    @pytest.mark.asyncio
    async def test_get_connection_pool_stats_no_results(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test handling when no results are returned."""
        mock_result = MagicMock()
        mock_result.mappings().first.return_value = None
        mock_session.execute.return_value = mock_result

        stats = await repository.get_connection_pool_stats(mock_session)

        assert stats["active_connections"] == 0
        assert stats["idle_connections"] == 0
        assert stats["total_connections"] == 0
        assert stats["max_connections"] == 0

    @pytest.mark.asyncio
    async def test_get_connection_pool_stats_null_values(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test handling null values in results."""
        mock_result = MagicMock()
        mock_row = {
            "active_connections": None,
            "idle_connections": None,
            "total_connections": 10,
            "max_connections": 100,
        }
        mock_result.mappings().first.return_value = mock_row
        mock_session.execute.return_value = mock_result

        stats = await repository.get_connection_pool_stats(mock_session)

        assert stats["active_connections"] == 0  # Null converted to 0
        assert stats["idle_connections"] == 0
        assert stats["total_connections"] == 10
        assert stats["max_connections"] == 100

    @pytest.mark.asyncio
    async def test_get_connection_pool_stats_error(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test error handling during query execution."""
        mock_session.execute.side_effect = Exception("Database error")

        with pytest.raises(Exception, match="Database error"):
            await repository.get_connection_pool_stats(mock_session)


# =============================================================================
# Database Size Tests
# =============================================================================


class TestGetDatabaseSize:
    """Tests for get_database_size method."""

    @pytest.mark.asyncio
    async def test_get_database_size_success(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test successfully getting database size."""
        mock_result = MagicMock()
        mock_row = {"size_bytes": 2684354560}  # 2.5 GB
        mock_result.mappings().first.return_value = mock_row
        mock_session.execute.return_value = mock_result

        size = await repository.get_database_size(mock_session)

        assert size == 2684354560
        assert mock_session.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_get_database_size_no_results(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test handling when no size is returned."""
        mock_result = MagicMock()
        mock_result.mappings().first.return_value = None
        mock_session.execute.return_value = mock_result

        size = await repository.get_database_size(mock_session)

        assert size == 0

    @pytest.mark.asyncio
    async def test_get_database_size_null_value(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test handling null size value."""
        mock_result = MagicMock()
        mock_row = {"size_bytes": None}
        mock_result.mappings().first.return_value = mock_row
        mock_session.execute.return_value = mock_result

        size = await repository.get_database_size(mock_session)

        assert size == 0


# =============================================================================
# Active Connections Count Tests
# =============================================================================


class TestGetActiveConnectionsCount:
    """Tests for get_active_connections_count method."""

    @pytest.mark.asyncio
    async def test_get_active_connections_count_success(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test successfully getting active connections count."""
        mock_result = MagicMock()
        mock_row = {"active_count": 15}
        mock_result.mappings().first.return_value = mock_row
        mock_session.execute.return_value = mock_result

        count = await repository.get_active_connections_count(mock_session)

        assert count == 15

    @pytest.mark.asyncio
    async def test_get_active_connections_count_zero(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test when there are no active connections."""
        mock_result = MagicMock()
        mock_row = {"active_count": 0}
        mock_result.mappings().first.return_value = mock_row
        mock_session.execute.return_value = mock_result

        count = await repository.get_active_connections_count(mock_session)

        assert count == 0

    @pytest.mark.asyncio
    async def test_get_active_connections_count_no_results(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test when no results are returned."""
        mock_result = MagicMock()
        mock_result.mappings().first.return_value = None
        mock_session.execute.return_value = mock_result

        count = await repository.get_active_connections_count(mock_session)

        assert count == 0


# =============================================================================
# Cache Hit Ratio Tests
# =============================================================================


class TestGetCacheHitRatio:
    """Tests for get_cache_hit_ratio method."""

    @pytest.mark.asyncio
    async def test_get_cache_hit_ratio_success(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test successfully getting cache hit ratio."""
        mock_result = MagicMock()
        mock_row = {"cache_hit_ratio": 98.5}
        mock_result.mappings().first.return_value = mock_row
        mock_session.execute.return_value = mock_result

        ratio = await repository.get_cache_hit_ratio(mock_session)

        assert ratio == 98.5

    @pytest.mark.asyncio
    async def test_get_cache_hit_ratio_no_data(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test when no cache data is available."""
        mock_result = MagicMock()
        mock_result.mappings().first.return_value = None
        mock_session.execute.return_value = mock_result

        ratio = await repository.get_cache_hit_ratio(mock_session)

        assert ratio is None

    @pytest.mark.asyncio
    async def test_get_cache_hit_ratio_null_value(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test when cache ratio is null."""
        mock_result = MagicMock()
        mock_row = {"cache_hit_ratio": None}
        mock_result.mappings().first.return_value = mock_row
        mock_session.execute.return_value = mock_result

        ratio = await repository.get_cache_hit_ratio(mock_session)

        assert ratio is None


# =============================================================================
# Table Sizes Tests
# =============================================================================


class TestGetTableSizes:
    """Tests for get_table_sizes method."""

    @pytest.mark.asyncio
    async def test_get_table_sizes_success(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test successfully getting table sizes."""
        mock_result = MagicMock()
        mock_rows = [
            {
                "schemaname": "public",
                "tablename": "users",
                "total_bytes": 52428800,
                "table_bytes": 41943040,
                "indexes_bytes": 10485760,
                "row_count": 150000,
            },
            {
                "schemaname": "public",
                "tablename": "posts",
                "total_bytes": 10485760,
                "table_bytes": 8388608,
                "indexes_bytes": 2097152,
                "row_count": 50000,
            },
        ]
        mock_result.mappings().all.return_value = mock_rows
        mock_session.execute.return_value = mock_result

        tables = await repository.get_table_sizes(mock_session, limit=10)

        assert len(tables) == 2
        assert tables[0]["tablename"] == "users"
        assert tables[0]["total_bytes"] == 52428800
        assert tables[0]["row_count"] == 150000
        assert tables[1]["tablename"] == "posts"

    @pytest.mark.asyncio
    async def test_get_table_sizes_empty(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test when no tables are returned."""
        mock_result = MagicMock()
        mock_result.mappings().all.return_value = []
        mock_session.execute.return_value = mock_result

        tables = await repository.get_table_sizes(mock_session, limit=50)

        assert len(tables) == 0

    @pytest.mark.asyncio
    async def test_get_table_sizes_null_values(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test handling null values in table data."""
        mock_result = MagicMock()
        mock_rows = [
            {
                "schemaname": "public",
                "tablename": "temp_table",
                "total_bytes": None,
                "table_bytes": None,
                "indexes_bytes": None,
                "row_count": None,
            },
        ]
        mock_result.mappings().all.return_value = mock_rows
        mock_session.execute.return_value = mock_result

        tables = await repository.get_table_sizes(mock_session, limit=10)

        assert len(tables) == 1
        assert tables[0]["total_bytes"] == 0
        assert tables[0]["table_bytes"] == 0
        assert tables[0]["indexes_bytes"] == 0
        assert tables[0]["row_count"] == 0

    @pytest.mark.asyncio
    async def test_get_table_sizes_respects_limit(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test that limit parameter is passed to query."""
        mock_result = MagicMock()
        mock_result.mappings().all.return_value = []
        mock_session.execute.return_value = mock_result

        await repository.get_table_sizes(mock_session, limit=5)

        # Check that limit was passed in params
        call_args = mock_session.execute.call_args_list[1]  # Second call is the query
        assert call_args[0][1] == {"limit": 5}


# =============================================================================
# Index Health Tests
# =============================================================================


class TestGetIndexHealth:
    """Tests for get_index_health method."""

    @pytest.mark.asyncio
    async def test_get_index_health_all_tables(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test getting index health for all tables."""
        mock_result = MagicMock()
        mock_rows = [
            {
                "index_name": "idx_users_email",
                "table_name": "users",
                "index_size_bytes": 10485760,
                "index_scans": 45000,
                "is_valid": True,
                "definition": "CREATE INDEX idx_users_email ON users (email)",
            },
        ]
        mock_result.mappings().all.return_value = mock_rows
        mock_session.execute.return_value = mock_result

        indexes = await repository.get_index_health(mock_session)

        assert len(indexes) == 1
        assert indexes[0]["index_name"] == "idx_users_email"
        assert indexes[0]["table_name"] == "users"
        assert indexes[0]["index_scans"] == 45000
        assert indexes[0]["is_valid"] is True

    @pytest.mark.asyncio
    async def test_get_index_health_specific_table(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test getting index health for specific table."""
        mock_result = MagicMock()
        mock_result.mappings().all.return_value = []
        mock_session.execute.return_value = mock_result

        await repository.get_index_health(mock_session, table_name="users")

        # Verify table filter was added to query
        call_args = mock_session.execute.call_args_list[1]
        assert call_args[0][1] == {"table_name": "users"}

    @pytest.mark.asyncio
    async def test_get_index_health_empty(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test when no indexes are returned."""
        mock_result = MagicMock()
        mock_result.mappings().all.return_value = []
        mock_session.execute.return_value = mock_result

        indexes = await repository.get_index_health(mock_session)

        assert len(indexes) == 0

    @pytest.mark.asyncio
    async def test_get_index_health_null_values(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test handling null values in index data."""
        mock_result = MagicMock()
        mock_rows = [
            {
                "index_name": "test_index",
                "table_name": "test_table",
                "index_size_bytes": None,
                "index_scans": None,
                "is_valid": False,
                "definition": None,
            },
        ]
        mock_result.mappings().all.return_value = mock_rows
        mock_session.execute.return_value = mock_result

        indexes = await repository.get_index_health(mock_session)

        assert len(indexes) == 1
        assert indexes[0]["index_size_bytes"] == 0
        assert indexes[0]["index_scans"] == 0
        assert indexes[0]["definition"] == ""


# =============================================================================
# Replication Lag Tests
# =============================================================================


class TestGetReplicationLag:
    """Tests for get_replication_lag method."""

    @pytest.mark.asyncio
    async def test_get_replication_lag_replica(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test getting replication lag on replica database."""
        mock_result = MagicMock()
        mock_row = {"lag_seconds": 0.5}
        mock_result.mappings().first.return_value = mock_row
        mock_session.execute.return_value = mock_result

        lag = await repository.get_replication_lag(mock_session)

        assert lag == 0.5

    @pytest.mark.asyncio
    async def test_get_replication_lag_primary(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test getting replication lag on primary database (returns None)."""
        mock_result = MagicMock()
        mock_row = {"lag_seconds": None}
        mock_result.mappings().first.return_value = mock_row
        mock_session.execute.return_value = mock_result

        lag = await repository.get_replication_lag(mock_session)

        assert lag is None

    @pytest.mark.asyncio
    async def test_get_replication_lag_no_results(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test when no results are returned."""
        mock_result = MagicMock()
        mock_result.mappings().first.return_value = None
        mock_session.execute.return_value = mock_result

        lag = await repository.get_replication_lag(mock_session)

        assert lag is None


# =============================================================================
# Active Queries Tests
# =============================================================================


class TestGetActiveQueries:
    """Tests for get_active_queries method."""

    @pytest.mark.asyncio
    async def test_get_active_queries_success(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test successfully getting active queries."""
        mock_result = MagicMock()
        mock_rows = [
            {
                "pid": 12345,
                "user": "app_user",
                "database": "production",
                "state": "active",
                "query": "SELECT * FROM users WHERE email = $1",
                "duration_seconds": 2.5,
                "wait_event": "ClientRead",
            },
        ]
        mock_result.mappings().all.return_value = mock_rows
        mock_session.execute.return_value = mock_result

        queries = await repository.get_active_queries(mock_session, limit=100)

        assert len(queries) == 1
        assert queries[0]["pid"] == 12345
        assert queries[0]["user"] == "app_user"
        assert queries[0]["state"] == "active"
        assert queries[0]["duration_seconds"] == 2.5

    @pytest.mark.asyncio
    async def test_get_active_queries_empty(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test when no active queries exist."""
        mock_result = MagicMock()
        mock_result.mappings().all.return_value = []
        mock_session.execute.return_value = mock_result

        queries = await repository.get_active_queries(mock_session, limit=100)

        assert len(queries) == 0

    @pytest.mark.asyncio
    async def test_get_active_queries_null_values(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test handling null values in query data."""
        mock_result = MagicMock()
        mock_rows = [
            {
                "pid": 123,
                "user": None,
                "database": None,
                "state": None,
                "query": None,
                "duration_seconds": None,
                "wait_event": None,
            },
        ]
        mock_result.mappings().all.return_value = mock_rows
        mock_session.execute.return_value = mock_result

        queries = await repository.get_active_queries(mock_session, limit=100)

        assert len(queries) == 1
        assert queries[0]["user"] == ""
        assert queries[0]["database"] == ""
        assert queries[0]["query"] == ""
        assert queries[0]["duration_seconds"] == 0.0
        assert queries[0]["wait_event"] is None


# =============================================================================
# Database Stats Summary Tests
# =============================================================================


class TestGetDatabaseStatsSummary:
    """Tests for get_database_stats_summary method."""

    @pytest.mark.asyncio
    async def test_get_database_stats_summary_success(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test successfully getting database stats summary."""
        mock_result = MagicMock()
        mock_row = {
            "table_count": 45,
            "index_count": 123,
            "total_transactions": 1500000,
            "tup_returned": 50000000,
            "tup_fetched": 25000000,
            "tup_inserted": 500000,
            "tup_updated": 200000,
            "tup_deleted": 10000,
        }
        mock_result.mappings().first.return_value = mock_row
        mock_session.execute.return_value = mock_result

        stats = await repository.get_database_stats_summary(mock_session)

        assert stats["table_count"] == 45
        assert stats["index_count"] == 123
        assert stats["total_transactions"] == 1500000
        assert stats["tup_inserted"] == 500000

    @pytest.mark.asyncio
    async def test_get_database_stats_summary_no_results(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test when no stats are returned."""
        mock_result = MagicMock()
        mock_result.mappings().first.return_value = None
        mock_session.execute.return_value = mock_result

        stats = await repository.get_database_stats_summary(mock_session)

        assert stats["table_count"] == 0
        assert stats["index_count"] == 0
        assert stats["total_transactions"] == 0

    @pytest.mark.asyncio
    async def test_get_database_stats_summary_null_values(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test handling null values in stats."""
        mock_result = MagicMock()
        mock_row = {
            "table_count": None,
            "index_count": None,
            "total_transactions": None,
            "tup_returned": None,
            "tup_fetched": None,
            "tup_inserted": None,
            "tup_updated": None,
            "tup_deleted": None,
        }
        mock_result.mappings().first.return_value = mock_row
        mock_session.execute.return_value = mock_result

        stats = await repository.get_database_stats_summary(mock_session)

        assert all(value == 0 for value in stats.values())


# =============================================================================
# Audit Logging Tests
# =============================================================================


class TestLogAdminAction:
    """Tests for log_admin_action method."""

    @pytest.mark.asyncio
    async def test_log_admin_action_success(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test successfully logging admin action."""
        now = datetime.now(UTC)
        action_id = str(uuid4())

        await repository.log_admin_action(
            mock_session,
            id=action_id,
            action="vacuum_table",
            target="users",
            user_id="admin_123",
            tenant_id="tenant_abc",
            result="success",
            duration_seconds=45.2,
            metadata={"table_name": "users", "vacuum_type": "full"},
            created_at=now,
        )

        # Verify execute was called (timeout + insert)
        assert mock_session.execute.call_count == 2
        # Verify commit was called
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_log_admin_action_default_created_at(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test logging with default created_at timestamp."""
        action_id = str(uuid4())

        await repository.log_admin_action(
            mock_session,
            id=action_id,
            action="reindex",
            target="idx_users_email",
            user_id="admin_123",
            tenant_id=None,
            result="success",
            duration_seconds=10.5,
            metadata={},
        )

        # Verify execute and commit were called
        assert mock_session.execute.call_count == 2
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_log_admin_action_error_rollback(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test that errors trigger rollback."""
        mock_session.execute.side_effect = Exception("Database error")
        action_id = str(uuid4())

        with pytest.raises(Exception, match="Database error"):
            await repository.log_admin_action(
                mock_session,
                id=action_id,
                action="vacuum",
                target="users",
                user_id="admin",
                tenant_id=None,
                result="failure",
                duration_seconds=0,
                metadata={},
            )

        mock_session.rollback.assert_awaited_once()


# =============================================================================
# Get Audit Logs Tests
# =============================================================================


class TestGetAuditLogs:
    """Tests for get_audit_logs method."""

    @pytest.mark.asyncio
    async def test_get_audit_logs_no_filters(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test getting audit logs without filters."""
        now = datetime.now(UTC)
        mock_count_result = MagicMock()
        mock_count_result.mappings().first.return_value = {"total": 5}

        mock_data_result = MagicMock()
        mock_rows = [
            {
                "id": str(uuid4()),
                "action": "vacuum_table",
                "target": "users",
                "user_id": "admin",
                "tenant_id": None,
                "result": "success",
                "duration_seconds": 45.0,
                "metadata": {},
                "created_at": now,
            }
            for _ in range(5)
        ]
        mock_data_result.mappings().all.return_value = mock_rows

        mock_session.execute.side_effect = [
            MagicMock(),  # SET timeout for count query
            mock_count_result,  # Count result
            MagicMock(),  # SET timeout for data query
            mock_data_result,  # Data result
        ]

        result = await repository.get_audit_logs(mock_session, limit=50, offset=0)

        assert result["total"] == 5
        assert len(result["items"]) == 5
        assert result["limit"] == 50
        assert result["offset"] == 0

    @pytest.mark.asyncio
    async def test_get_audit_logs_with_action_filter(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test getting audit logs filtered by action type."""
        mock_count_result = MagicMock()
        mock_count_result.mappings().first.return_value = {"total": 2}
        mock_data_result = MagicMock()
        mock_data_result.mappings().all.return_value = []

        mock_session.execute.side_effect = [
            MagicMock(),
            mock_count_result,
            MagicMock(),
            mock_data_result,
        ]

        result = await repository.get_audit_logs(
            mock_session,
            action_type="vacuum_table",
            limit=50,
            offset=0,
        )

        assert result["total"] == 2

    @pytest.mark.asyncio
    async def test_get_audit_logs_with_date_range(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test getting audit logs filtered by date range."""
        now = datetime.now(UTC)
        start_date = now - timedelta(days=7)
        end_date = now

        mock_count_result = MagicMock()
        mock_count_result.mappings().first.return_value = {"total": 10}
        mock_data_result = MagicMock()
        mock_data_result.mappings().all.return_value = []

        mock_session.execute.side_effect = [
            MagicMock(),
            mock_count_result,
            MagicMock(),
            mock_data_result,
        ]

        result = await repository.get_audit_logs(
            mock_session,
            start_date=start_date,
            end_date=end_date,
            limit=50,
            offset=0,
        )

        assert result["total"] == 10

    @pytest.mark.asyncio
    async def test_get_audit_logs_pagination(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test audit logs pagination."""
        mock_count_result = MagicMock()
        mock_count_result.mappings().first.return_value = {"total": 100}
        mock_data_result = MagicMock()
        mock_data_result.mappings().all.return_value = []

        mock_session.execute.side_effect = [
            MagicMock(),
            mock_count_result,
            MagicMock(),
            mock_data_result,
        ]

        result = await repository.get_audit_logs(
            mock_session,
            limit=20,
            offset=40,
        )

        assert result["total"] == 100
        assert result["limit"] == 20
        assert result["offset"] == 40

    @pytest.mark.asyncio
    async def test_get_audit_logs_empty_results(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test getting audit logs when none exist."""
        mock_count_result = MagicMock()
        mock_count_result.mappings().first.return_value = {"total": 0}
        mock_data_result = MagicMock()
        mock_data_result.mappings().all.return_value = []

        mock_session.execute.side_effect = [
            MagicMock(),
            mock_count_result,
            MagicMock(),
            mock_data_result,
        ]

        result = await repository.get_audit_logs(mock_session, limit=50, offset=0)

        assert result["total"] == 0
        assert len(result["items"]) == 0


# =============================================================================
# Timeout Execution Tests
# =============================================================================


class TestExecuteWithTimeout:
    """Tests for _execute_with_timeout method."""

    @pytest.mark.asyncio
    async def test_execute_with_timeout_success(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test successful query execution with timeout."""
        mock_result = MagicMock()
        mock_session.execute.return_value = mock_result

        result = await repository._execute_with_timeout(
            mock_session,
            "SELECT 1",
            timeout_seconds=30,
        )

        assert result == mock_result
        # Verify two executes: SET timeout + actual query
        assert mock_session.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_execute_with_timeout_with_params(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test query execution with parameters."""
        mock_result = MagicMock()
        mock_session.execute.return_value = mock_result

        await repository._execute_with_timeout(
            mock_session,
            "SELECT * FROM users WHERE id = :user_id",
            params={"user_id": "123"},
            timeout_seconds=30,
        )

        # Check that params were passed
        call_args = mock_session.execute.call_args_list[1]
        assert call_args[0][1] == {"user_id": "123"}

    @pytest.mark.asyncio
    async def test_execute_with_timeout_error(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test error handling during query execution."""
        mock_session.execute.side_effect = Exception("Query failed")

        with pytest.raises(Exception, match="Query failed"):
            await repository._execute_with_timeout(
                mock_session,
                "SELECT 1",
                timeout_seconds=30,
            )

    @pytest.mark.asyncio
    async def test_execute_with_timeout_custom_timeout(
        self,
        repository: DatabaseAdminRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test using custom timeout value."""
        mock_result = MagicMock()
        mock_session.execute.return_value = mock_result

        await repository._execute_with_timeout(
            mock_session,
            "SELECT 1",
            timeout_seconds=60,
        )

        # Verify timeout was set (two executes: timeout + query)
        assert mock_session.execute.call_count == 2


__all__ = [
    "TestExecuteWithTimeout",
    "TestGetActiveConnectionsCount",
    "TestGetActiveQueries",
    "TestGetAuditLogs",
    "TestGetCacheHitRatio",
    "TestGetConnectionPoolStats",
    "TestGetDatabaseSize",
    "TestGetDatabaseStatsSummary",
    "TestGetIndexHealth",
    "TestGetReplicationLag",
    "TestGetTableSizes",
    "TestLogAdminAction",
    "TestRepositoryInitialization",
]
