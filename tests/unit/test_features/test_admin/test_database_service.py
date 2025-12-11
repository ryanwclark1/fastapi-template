"""Unit tests for DatabaseAdminService.

This module tests the database administration service including:
- Health status determination
- Rate limiting functionality
- Statistics aggregation
- Connection info retrieval
- Table and index health queries
- Audit log management
- Data transformation (dicts -> Pydantic schemas)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
import pytest

from example_service.features.admin.database.schemas import (
    AuditLogFilters,
    DatabaseHealthStatus,
)
from example_service.features.admin.database.service import (
    DatabaseAdminService,
    get_database_admin_service,
)

if TYPE_CHECKING:
    from example_service.core.settings.admin import AdminSettings
    from example_service.features.admin.database.repository import (
        DatabaseAdminRepository,
    )


@pytest.fixture
def mock_repository() -> MagicMock:
    """Create mock DatabaseAdminRepository."""
    repo = MagicMock()
    repo.get_connection_pool_stats = AsyncMock()
    repo.get_database_size = AsyncMock()
    repo.get_active_connections_count = AsyncMock()
    repo.get_cache_hit_ratio = AsyncMock()
    repo.get_replication_lag = AsyncMock()
    repo.get_database_stats_summary = AsyncMock()
    repo.get_table_sizes = AsyncMock()
    repo.get_index_health = AsyncMock()
    repo.get_active_queries = AsyncMock()
    repo.log_admin_action = AsyncMock()
    repo.get_audit_logs = AsyncMock()
    return repo


@pytest.fixture
def mock_settings() -> MagicMock:
    """Create mock AdminSettings."""
    settings = MagicMock()
    settings.connection_pool_warning_threshold = 75.0
    settings.connection_pool_critical_threshold = 90.0
    settings.cache_hit_ratio_warning_threshold = 85.0
    settings.rate_limit_enabled = True
    settings.rate_limit_window_seconds = 60
    settings.rate_limit_max_ops = 10
    return settings


@pytest.fixture
def service(
    mock_repository: MagicMock,
    mock_settings: MagicMock,
) -> DatabaseAdminService:
    """Create DatabaseAdminService with mocked dependencies."""
    return DatabaseAdminService(mock_repository, mock_settings)


@pytest.fixture
def mock_session() -> AsyncMock:
    """Create mock async database session."""
    return AsyncMock()


# =============================================================================
# Initialization Tests
# =============================================================================


class TestServiceInitialization:
    """Tests for service initialization."""

    def test_service_initialization(
        self,
        mock_repository: MagicMock,
        mock_settings: MagicMock,
    ) -> None:
        """Test that service initializes correctly."""
        service = DatabaseAdminService(mock_repository, mock_settings)

        assert service.repository == mock_repository
        assert service.settings == mock_settings
        assert service._rate_limiter is not None

    def test_get_database_admin_service_factory(
        self,
        mock_repository: MagicMock,
        mock_settings: MagicMock,
    ) -> None:
        """Test factory function."""
        service = get_database_admin_service(mock_repository, mock_settings)

        assert isinstance(service, DatabaseAdminService)
        assert service.repository == mock_repository


# =============================================================================
# Health Check Tests
# =============================================================================


class TestGetHealth:
    """Tests for get_health method."""

    @pytest.mark.asyncio
    async def test_get_health_healthy_status(
        self,
        service: DatabaseAdminService,
        mock_session: AsyncMock,
        mock_repository: MagicMock,
    ) -> None:
        """Test health check returning HEALTHY status."""
        # Mock repository responses
        mock_repository.get_connection_pool_stats.return_value = {
            "active_connections": 10,
            "idle_connections": 15,
            "total_connections": 25,
            "max_connections": 100,
        }
        mock_repository.get_database_size.return_value = 2684354560
        mock_repository.get_active_connections_count.return_value = 10
        mock_repository.get_cache_hit_ratio.return_value = 98.5
        mock_repository.get_replication_lag.return_value = None

        health = await service.get_health(mock_session, "admin_123")

        assert health.status == DatabaseHealthStatus.HEALTHY
        assert health.connection_pool.total_connections == 25
        assert health.connection_pool.utilization_percent == 25.0
        assert health.database_size_bytes == 2684354560
        assert health.cache_hit_ratio == 0.985  # Converted to ratio
        assert len(health.warnings) == 0

    @pytest.mark.asyncio
    async def test_get_health_degraded_status_high_pool_utilization(
        self,
        service: DatabaseAdminService,
        mock_session: AsyncMock,
        mock_repository: MagicMock,
    ) -> None:
        """Test health check returning DEGRADED due to high pool utilization."""
        mock_repository.get_connection_pool_stats.return_value = {
            "active_connections": 80,
            "idle_connections": 0,
            "total_connections": 80,
            "max_connections": 100,
        }
        mock_repository.get_database_size.return_value = 1000000
        mock_repository.get_active_connections_count.return_value = 80
        mock_repository.get_cache_hit_ratio.return_value = 95.0
        mock_repository.get_replication_lag.return_value = None

        health = await service.get_health(mock_session, "admin_123")

        assert health.status == DatabaseHealthStatus.DEGRADED
        assert health.connection_pool.utilization_percent == 80.0
        assert len(health.warnings) > 0
        assert any("pool utilization is high" in w for w in health.warnings)

    @pytest.mark.asyncio
    async def test_get_health_degraded_status_low_cache_ratio(
        self,
        service: DatabaseAdminService,
        mock_session: AsyncMock,
        mock_repository: MagicMock,
    ) -> None:
        """Test health check returning DEGRADED due to low cache hit ratio."""
        mock_repository.get_connection_pool_stats.return_value = {
            "active_connections": 10,
            "idle_connections": 15,
            "total_connections": 25,
            "max_connections": 100,
        }
        mock_repository.get_database_size.return_value = 1000000
        mock_repository.get_active_connections_count.return_value = 10
        mock_repository.get_cache_hit_ratio.return_value = 80.0  # Below 85%
        mock_repository.get_replication_lag.return_value = None

        health = await service.get_health(mock_session, "admin_123")

        assert health.status == DatabaseHealthStatus.DEGRADED
        assert len(health.warnings) > 0
        assert any("Cache hit ratio is low" in w for w in health.warnings)

    @pytest.mark.asyncio
    async def test_get_health_unhealthy_status_critical_pool(
        self,
        service: DatabaseAdminService,
        mock_session: AsyncMock,
        mock_repository: MagicMock,
    ) -> None:
        """Test health check returning UNHEALTHY due to critical pool usage."""
        mock_repository.get_connection_pool_stats.return_value = {
            "active_connections": 95,
            "idle_connections": 0,
            "total_connections": 95,
            "max_connections": 100,
        }
        mock_repository.get_database_size.return_value = 1000000
        mock_repository.get_active_connections_count.return_value = 95
        mock_repository.get_cache_hit_ratio.return_value = 90.0
        mock_repository.get_replication_lag.return_value = None

        health = await service.get_health(mock_session, "admin_123")

        assert health.status == DatabaseHealthStatus.UNHEALTHY
        assert health.connection_pool.utilization_percent == 95.0

    @pytest.mark.asyncio
    async def test_get_health_unhealthy_status_very_low_cache(
        self,
        service: DatabaseAdminService,
        mock_session: AsyncMock,
        mock_repository: MagicMock,
    ) -> None:
        """Test health check returning UNHEALTHY due to very low cache ratio."""
        mock_repository.get_connection_pool_stats.return_value = {
            "active_connections": 10,
            "idle_connections": 15,
            "total_connections": 25,
            "max_connections": 100,
        }
        mock_repository.get_database_size.return_value = 1000000
        mock_repository.get_active_connections_count.return_value = 10
        mock_repository.get_cache_hit_ratio.return_value = 65.0  # Below 70%
        mock_repository.get_replication_lag.return_value = None

        health = await service.get_health(mock_session, "admin_123")

        assert health.status == DatabaseHealthStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_get_health_with_replication_lag_warning(
        self,
        service: DatabaseAdminService,
        mock_session: AsyncMock,
        mock_repository: MagicMock,
    ) -> None:
        """Test health check with replication lag warning."""
        mock_repository.get_connection_pool_stats.return_value = {
            "active_connections": 10,
            "idle_connections": 15,
            "total_connections": 25,
            "max_connections": 100,
        }
        mock_repository.get_database_size.return_value = 1000000
        mock_repository.get_active_connections_count.return_value = 10
        mock_repository.get_cache_hit_ratio.return_value = 95.0
        mock_repository.get_replication_lag.return_value = 10.5  # > 5s

        health = await service.get_health(mock_session, "admin_123")

        assert health.replication_lag_seconds == 10.5
        assert any("Replication lag is high" in w for w in health.warnings)

    @pytest.mark.asyncio
    async def test_get_health_null_cache_ratio(
        self,
        service: DatabaseAdminService,
        mock_session: AsyncMock,
        mock_repository: MagicMock,
    ) -> None:
        """Test health check when cache ratio is None."""
        mock_repository.get_connection_pool_stats.return_value = {
            "active_connections": 10,
            "idle_connections": 15,
            "total_connections": 25,
            "max_connections": 100,
        }
        mock_repository.get_database_size.return_value = 1000000
        mock_repository.get_active_connections_count.return_value = 10
        mock_repository.get_cache_hit_ratio.return_value = None
        mock_repository.get_replication_lag.return_value = None

        health = await service.get_health(mock_session, "admin_123")

        assert health.cache_hit_ratio is None
        assert health.status == DatabaseHealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_get_health_logs_audit_entry(
        self,
        service: DatabaseAdminService,
        mock_session: AsyncMock,
        mock_repository: MagicMock,
    ) -> None:
        """Test that health check logs audit entry."""
        mock_repository.get_connection_pool_stats.return_value = {
            "active_connections": 10,
            "idle_connections": 15,
            "total_connections": 25,
            "max_connections": 100,
        }
        mock_repository.get_database_size.return_value = 1000000
        mock_repository.get_active_connections_count.return_value = 10
        mock_repository.get_cache_hit_ratio.return_value = 95.0
        mock_repository.get_replication_lag.return_value = None

        await service.get_health(mock_session, "admin_123")

        mock_repository.log_admin_action.assert_awaited_once()
        call_kwargs = mock_repository.log_admin_action.call_args.kwargs
        assert call_kwargs["action"] == "get_health"
        assert call_kwargs["user_id"] == "admin_123"
        assert call_kwargs["result"] == "success"

    @pytest.mark.asyncio
    async def test_get_health_error_handling(
        self,
        service: DatabaseAdminService,
        mock_session: AsyncMock,
        mock_repository: MagicMock,
    ) -> None:
        """Test error handling in health check."""
        mock_repository.get_connection_pool_stats.side_effect = Exception(
            "Database error",
        )

        with pytest.raises(Exception, match="Database error"):
            await service.get_health(mock_session, "admin_123")


# =============================================================================
# Get Stats Tests
# =============================================================================


class TestGetStats:
    """Tests for get_stats method."""

    @pytest.mark.asyncio
    async def test_get_stats_success(
        self,
        service: DatabaseAdminService,
        mock_session: AsyncMock,
        mock_repository: MagicMock,
    ) -> None:
        """Test successfully getting database statistics."""
        mock_repository.get_database_size.return_value = 5368709120
        mock_repository.get_database_stats_summary.return_value = {
            "table_count": 45,
            "index_count": 123,
            "total_transactions": 1500000,
            "tup_returned": 50000000,
            "tup_fetched": 25000000,
            "tup_inserted": 500000,
            "tup_updated": 200000,
            "tup_deleted": 10000,
        }
        mock_repository.get_cache_hit_ratio.return_value = 98.0
        mock_repository.get_table_sizes.return_value = [
            {
                "schemaname": "public",
                "tablename": "users",
                "total_bytes": 52428800,
                "table_bytes": 41943040,
                "indexes_bytes": 10485760,
                "row_count": 150000,
            },
        ]
        mock_repository.get_active_queries.return_value = []

        stats = await service.get_stats(mock_session, "admin_123")

        assert stats.total_size_bytes == 5368709120
        assert stats.table_count == 45
        assert stats.index_count == 123
        assert stats.cache_hit_ratio == 0.98
        assert len(stats.top_tables) == 1
        assert stats.top_tables[0].table_name == "users"
        assert stats.slow_queries_count == 0

    @pytest.mark.asyncio
    async def test_get_stats_with_slow_queries(
        self,
        service: DatabaseAdminService,
        mock_session: AsyncMock,
        mock_repository: MagicMock,
    ) -> None:
        """Test stats with slow queries detected."""
        mock_repository.get_database_size.return_value = 1000000
        mock_repository.get_database_stats_summary.return_value = {
            "table_count": 10,
            "index_count": 20,
            "total_transactions": 1000,
            "tup_returned": 100,
            "tup_fetched": 50,
            "tup_inserted": 10,
            "tup_updated": 5,
            "tup_deleted": 0,
        }
        mock_repository.get_cache_hit_ratio.return_value = 95.0
        mock_repository.get_table_sizes.return_value = []
        # Mock slow queries (> 10 seconds)
        mock_repository.get_active_queries.return_value = [
            {"duration_seconds": 15.5},
            {"duration_seconds": 20.0},
            {"duration_seconds": 5.0},  # Not slow
        ]

        stats = await service.get_stats(mock_session, "admin_123")

        assert stats.slow_queries_count == 2

    @pytest.mark.asyncio
    async def test_get_stats_null_cache_ratio(
        self,
        service: DatabaseAdminService,
        mock_session: AsyncMock,
        mock_repository: MagicMock,
    ) -> None:
        """Test stats when cache ratio is None."""
        mock_repository.get_database_size.return_value = 1000000
        mock_repository.get_database_stats_summary.return_value = {
            "table_count": 10,
            "index_count": 20,
            "total_transactions": 0,
            "tup_returned": 0,
            "tup_fetched": 0,
            "tup_inserted": 0,
            "tup_updated": 0,
            "tup_deleted": 0,
        }
        mock_repository.get_cache_hit_ratio.return_value = None
        mock_repository.get_table_sizes.return_value = []
        mock_repository.get_active_queries.return_value = []

        stats = await service.get_stats(mock_session, "admin_123")

        assert stats.cache_hit_ratio is None


# =============================================================================
# Get Connection Info Tests
# =============================================================================


class TestGetConnectionInfo:
    """Tests for get_connection_info method."""

    @pytest.mark.asyncio
    async def test_get_connection_info_success(
        self,
        service: DatabaseAdminService,
        mock_session: AsyncMock,
        mock_repository: MagicMock,
    ) -> None:
        """Test successfully getting connection info."""
        mock_repository.get_active_queries.return_value = [
            {
                "pid": 12345,
                "user": "app_user",
                "database": "production",
                "state": "active",
                "query": "SELECT * FROM users",
                "duration_seconds": 2.5,
                "wait_event": None,
            },
        ]

        queries = await service.get_connection_info(mock_session, "admin_123", limit=100)

        assert len(queries) == 1
        assert queries[0].pid == 12345
        assert queries[0].user == "app_user"
        assert queries[0].duration_seconds == 2.5

    @pytest.mark.asyncio
    async def test_get_connection_info_empty(
        self,
        service: DatabaseAdminService,
        mock_session: AsyncMock,
        mock_repository: MagicMock,
    ) -> None:
        """Test when no active connections exist."""
        mock_repository.get_active_queries.return_value = []

        queries = await service.get_connection_info(mock_session, "admin_123")

        assert len(queries) == 0


# =============================================================================
# Get Table Sizes Tests
# =============================================================================


class TestGetTableSizes:
    """Tests for get_table_sizes method."""

    @pytest.mark.asyncio
    async def test_get_table_sizes_success(
        self,
        service: DatabaseAdminService,
        mock_session: AsyncMock,
        mock_repository: MagicMock,
    ) -> None:
        """Test successfully getting table sizes."""
        mock_repository.get_table_sizes.return_value = [
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

        tables = await service.get_table_sizes(mock_session, "admin_123", limit=10)

        assert len(tables) == 2
        assert tables[0].table_name == "users"
        assert tables[0].row_count == 150000
        assert "50" in tables[0].total_size_human  # Should contain "50 MB"
        assert tables[1].table_name == "posts"

    @pytest.mark.asyncio
    async def test_get_table_sizes_empty(
        self,
        service: DatabaseAdminService,
        mock_session: AsyncMock,
        mock_repository: MagicMock,
    ) -> None:
        """Test when no tables exist."""
        mock_repository.get_table_sizes.return_value = []

        tables = await service.get_table_sizes(mock_session, "admin_123")

        assert len(tables) == 0


# =============================================================================
# Get Index Health Tests
# =============================================================================


class TestGetIndexHealth:
    """Tests for get_index_health method."""

    @pytest.mark.asyncio
    async def test_get_index_health_success(
        self,
        service: DatabaseAdminService,
        mock_session: AsyncMock,
        mock_repository: MagicMock,
    ) -> None:
        """Test successfully getting index health."""
        mock_repository.get_index_health.return_value = [
            {
                "index_name": "idx_users_email",
                "table_name": "users",
                "index_size_bytes": 10485760,
                "index_scans": 45000,
                "is_valid": True,
                "definition": "CREATE INDEX idx_users_email ON users (email)",
            },
        ]

        indexes = await service.get_index_health(mock_session, "admin_123")

        assert len(indexes) == 1
        assert indexes[0].index_name == "idx_users_email"
        assert indexes[0].index_scans == 45000
        assert indexes[0].is_valid is True
        assert indexes[0].bloat_percent is None  # Not yet implemented

    @pytest.mark.asyncio
    async def test_get_index_health_with_table_filter(
        self,
        service: DatabaseAdminService,
        mock_session: AsyncMock,
        mock_repository: MagicMock,
    ) -> None:
        """Test getting index health for specific table."""
        mock_repository.get_index_health.return_value = []

        await service.get_index_health(mock_session, "admin_123", table_name="users")

        mock_repository.get_index_health.assert_awaited_once_with(
            mock_session,
            table_name="users",
        )


# =============================================================================
# Get Audit Logs Tests
# =============================================================================


class TestGetAuditLogs:
    """Tests for get_audit_logs method."""

    @pytest.mark.asyncio
    async def test_get_audit_logs_success(
        self,
        service: DatabaseAdminService,
        mock_session: AsyncMock,
        mock_repository: MagicMock,
    ) -> None:
        """Test successfully getting audit logs."""
        now = datetime.now(UTC)
        mock_repository.get_audit_logs.return_value = {
            "items": [
                {
                    "id": "log-1",
                    "action": "get_health",
                    "target": "database",
                    "user_id": "admin_123",
                    "tenant_id": None,
                    "result": "success",
                    "duration_seconds": 0.5,
                    "metadata": {},
                    "created_at": now,
                },
            ],
            "total": 1,
            "limit": 50,
            "offset": 0,
        }

        filters = AuditLogFilters(page=1, page_size=50)
        response = await service.get_audit_logs(mock_session, "admin_123", filters)

        assert response.total == 1
        assert len(response.items) == 1
        assert response.items[0].action == "get_health"
        assert response.page == 1
        assert response.total_pages == 1

    @pytest.mark.asyncio
    async def test_get_audit_logs_with_filters(
        self,
        service: DatabaseAdminService,
        mock_session: AsyncMock,
        mock_repository: MagicMock,
    ) -> None:
        """Test getting audit logs with filters applied."""
        now = datetime.now(UTC)
        start_date = now - timedelta(days=7)
        end_date = now

        mock_repository.get_audit_logs.return_value = {
            "items": [],
            "total": 0,
            "limit": 50,
            "offset": 0,
        }

        filters = AuditLogFilters(
            action_type="get_health",
            user_id="admin_123",
            start_date=start_date,
            end_date=end_date,
            page=1,
            page_size=50,
        )
        await service.get_audit_logs(mock_session, "admin_123", filters)

        mock_repository.get_audit_logs.assert_awaited_once()
        call_kwargs = mock_repository.get_audit_logs.call_args.kwargs
        assert call_kwargs["action_type"] == "get_health"
        assert call_kwargs["start_date"] == start_date

    @pytest.mark.asyncio
    async def test_get_audit_logs_pagination(
        self,
        service: DatabaseAdminService,
        mock_session: AsyncMock,
        mock_repository: MagicMock,
    ) -> None:
        """Test audit logs pagination calculation."""
        mock_repository.get_audit_logs.return_value = {
            "items": [],
            "total": 150,
            "limit": 50,
            "offset": 0,
        }

        filters = AuditLogFilters(page=1, page_size=50)
        response = await service.get_audit_logs(mock_session, "admin_123", filters)

        assert response.total == 150
        assert response.total_pages == 3  # 150 / 50 = 3


# =============================================================================
# Rate Limiting Tests
# =============================================================================


class TestRateLimiting:
    """Tests for rate limiting functionality."""

    @pytest.mark.asyncio
    async def test_rate_limit_not_exceeded(
        self,
        service: DatabaseAdminService,
        mock_session: AsyncMock,
        mock_repository: MagicMock,
    ) -> None:
        """Test that operations work when rate limit not exceeded."""
        mock_repository.get_connection_pool_stats.return_value = {
            "active_connections": 10,
            "idle_connections": 15,
            "total_connections": 25,
            "max_connections": 100,
        }
        mock_repository.get_database_size.return_value = 1000000
        mock_repository.get_active_connections_count.return_value = 10
        mock_repository.get_cache_hit_ratio.return_value = 95.0
        mock_repository.get_replication_lag.return_value = None

        # Should succeed
        await service.get_health(mock_session, "admin_123")

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded(
        self,
        service: DatabaseAdminService,
        mock_session: AsyncMock,
        mock_repository: MagicMock,
    ) -> None:
        """Test that rate limit raises HTTPException when exceeded."""
        mock_repository.get_connection_pool_stats.return_value = {
            "active_connections": 10,
            "idle_connections": 15,
            "total_connections": 25,
            "max_connections": 100,
        }
        mock_repository.get_database_size.return_value = 1000000
        mock_repository.get_active_connections_count.return_value = 10
        mock_repository.get_cache_hit_ratio.return_value = 95.0
        mock_repository.get_replication_lag.return_value = None

        # Call 11 times (max is 10)
        for _ in range(10):
            await service.get_health(mock_session, "admin_123")

        # 11th call should raise
        with pytest.raises(HTTPException) as exc_info:
            await service.get_health(mock_session, "admin_123")

        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_rate_limit_per_operation(
        self,
        service: DatabaseAdminService,
        mock_session: AsyncMock,
        mock_repository: MagicMock,
    ) -> None:
        """Test that rate limit is per operation type."""
        # Setup mocks
        mock_repository.get_connection_pool_stats.return_value = {
            "active_connections": 10,
            "idle_connections": 15,
            "total_connections": 25,
            "max_connections": 100,
        }
        mock_repository.get_database_size.return_value = 1000000
        mock_repository.get_active_connections_count.return_value = 10
        mock_repository.get_cache_hit_ratio.return_value = 95.0
        mock_repository.get_replication_lag.return_value = None
        mock_repository.get_database_stats_summary.return_value = {
            "table_count": 10,
            "index_count": 20,
            "total_transactions": 100,
            "tup_returned": 100,
            "tup_fetched": 50,
            "tup_inserted": 10,
            "tup_updated": 5,
            "tup_deleted": 0,
        }
        mock_repository.get_table_sizes.return_value = []
        mock_repository.get_active_queries.return_value = []

        # Call get_health 10 times
        for _ in range(10):
            await service.get_health(mock_session, "admin_123")

        # get_stats should still work (different operation)
        await service.get_stats(mock_session, "admin_123")

    @pytest.mark.asyncio
    async def test_rate_limit_disabled(
        self,
        mock_repository: MagicMock,
        mock_settings: MagicMock,
        mock_session: AsyncMock,
    ) -> None:
        """Test that operations work when rate limiting is disabled."""
        mock_settings.rate_limit_enabled = False
        service = DatabaseAdminService(mock_repository, mock_settings)

        mock_repository.get_connection_pool_stats.return_value = {
            "active_connections": 10,
            "idle_connections": 15,
            "total_connections": 25,
            "max_connections": 100,
        }
        mock_repository.get_database_size.return_value = 1000000
        mock_repository.get_active_connections_count.return_value = 10
        mock_repository.get_cache_hit_ratio.return_value = 95.0
        mock_repository.get_replication_lag.return_value = None

        # Should succeed even after 20 calls
        for _ in range(20):
            await service.get_health(mock_session, "admin_123")


# =============================================================================
# Health Status Determination Tests
# =============================================================================


class TestDetermineHealthStatus:
    """Tests for _determine_health_status method."""

    def test_determine_health_status_healthy(self, service: DatabaseAdminService) -> None:
        """Test HEALTHY status determination."""
        status = service._determine_health_status(
            warnings=[],
            connection_utilization=50.0,
            cache_hit_ratio=95.0,
        )

        assert status == DatabaseHealthStatus.HEALTHY

    def test_determine_health_status_degraded_warnings(
        self,
        service: DatabaseAdminService,
    ) -> None:
        """Test DEGRADED status when warnings present."""
        status = service._determine_health_status(
            warnings=["Some warning"],
            connection_utilization=50.0,
            cache_hit_ratio=95.0,
        )

        assert status == DatabaseHealthStatus.DEGRADED

    def test_determine_health_status_degraded_pool_warning(
        self,
        service: DatabaseAdminService,
    ) -> None:
        """Test DEGRADED status for pool utilization above warning threshold."""
        status = service._determine_health_status(
            warnings=[],
            connection_utilization=80.0,  # Above 75% warning threshold
            cache_hit_ratio=95.0,
        )

        assert status == DatabaseHealthStatus.DEGRADED

    def test_determine_health_status_degraded_cache_warning(
        self,
        service: DatabaseAdminService,
    ) -> None:
        """Test DEGRADED status for cache ratio below warning threshold."""
        status = service._determine_health_status(
            warnings=[],
            connection_utilization=50.0,
            cache_hit_ratio=80.0,  # Below 85% warning threshold
        )

        assert status == DatabaseHealthStatus.DEGRADED

    def test_determine_health_status_unhealthy_pool_critical(
        self,
        service: DatabaseAdminService,
    ) -> None:
        """Test UNHEALTHY status for pool utilization above critical threshold."""
        status = service._determine_health_status(
            warnings=[],
            connection_utilization=95.0,  # Above 90% critical threshold
            cache_hit_ratio=95.0,
        )

        assert status == DatabaseHealthStatus.UNHEALTHY

    def test_determine_health_status_unhealthy_cache_critical(
        self,
        service: DatabaseAdminService,
    ) -> None:
        """Test UNHEALTHY status for cache ratio below critical threshold."""
        status = service._determine_health_status(
            warnings=[],
            connection_utilization=50.0,
            cache_hit_ratio=65.0,  # Below 70% critical threshold
        )

        assert status == DatabaseHealthStatus.UNHEALTHY

    def test_determine_health_status_null_cache_ratio(
        self,
        service: DatabaseAdminService,
    ) -> None:
        """Test status determination with null cache ratio."""
        status = service._determine_health_status(
            warnings=[],
            connection_utilization=50.0,
            cache_hit_ratio=None,
        )

        assert status == DatabaseHealthStatus.HEALTHY


# =============================================================================
# Audit Logging Tests
# =============================================================================


class TestAuditLogging:
    """Tests for audit logging functionality."""

    @pytest.mark.asyncio
    async def test_log_operation_success(
        self,
        service: DatabaseAdminService,
        mock_session: AsyncMock,
        mock_repository: MagicMock,
    ) -> None:
        """Test successful audit log creation."""
        await service._log_operation(
            session=mock_session,
            action="test_action",
            target="test_target",
            user_id="user_123",
            result="success",
            duration=0.5,
            metadata={"key": "value"},
        )

        mock_repository.log_admin_action.assert_awaited_once()
        call_kwargs = mock_repository.log_admin_action.call_args.kwargs
        assert call_kwargs["action"] == "test_action"
        assert call_kwargs["target"] == "test_target"
        assert call_kwargs["user_id"] == "user_123"
        assert call_kwargs["result"] == "success"
        assert call_kwargs["metadata"] == {"key": "value"}

    @pytest.mark.asyncio
    async def test_log_operation_fire_and_forget(
        self,
        service: DatabaseAdminService,
        mock_session: AsyncMock,
        mock_repository: MagicMock,
    ) -> None:
        """Test that audit logging failures don't raise exceptions."""
        mock_repository.log_admin_action.side_effect = Exception("Logging failed")

        # Should not raise exception (fire-and-forget pattern)
        await service._log_operation(
            session=mock_session,
            action="test_action",
            target="test_target",
            user_id="user_123",
            result="success",
            duration=0.5,
        )


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Tests for error handling in service methods."""

    @pytest.mark.asyncio
    async def test_get_stats_error_handling(
        self,
        service: DatabaseAdminService,
        mock_session: AsyncMock,
        mock_repository: MagicMock,
    ) -> None:
        """Test error handling in get_stats."""
        mock_repository.get_database_size.side_effect = Exception("Database error")

        with pytest.raises(Exception, match="Database error"):
            await service.get_stats(mock_session, "admin_123")

    @pytest.mark.asyncio
    async def test_get_connection_info_error_handling(
        self,
        service: DatabaseAdminService,
        mock_session: AsyncMock,
        mock_repository: MagicMock,
    ) -> None:
        """Test error handling in get_connection_info."""
        mock_repository.get_active_queries.side_effect = Exception("Query failed")

        with pytest.raises(Exception, match="Query failed"):
            await service.get_connection_info(mock_session, "admin_123")

    @pytest.mark.asyncio
    async def test_get_table_sizes_error_handling(
        self,
        service: DatabaseAdminService,
        mock_session: AsyncMock,
        mock_repository: MagicMock,
    ) -> None:
        """Test error handling in get_table_sizes."""
        mock_repository.get_table_sizes.side_effect = Exception("Size query failed")

        with pytest.raises(Exception, match="Size query failed"):
            await service.get_table_sizes(mock_session, "admin_123")


__all__ = [
    "TestAuditLogging",
    "TestDetermineHealthStatus",
    "TestErrorHandling",
    "TestGetAuditLogs",
    "TestGetConnectionInfo",
    "TestGetHealth",
    "TestGetIndexHealth",
    "TestGetStats",
    "TestGetTableSizes",
    "TestRateLimiting",
    "TestServiceInitialization",
]
