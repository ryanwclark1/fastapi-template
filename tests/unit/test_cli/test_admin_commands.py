"""Comprehensive tests for database admin CLI commands.

This module tests all admin CLI commands including:
- Health checks with colored output
- Database statistics with table/JSON formatting
- Active connections monitoring
- Table sizes analysis
- Index health analysis
- Audit logs with filtering

Testing approach:
- Uses Click's CliRunner for command invocation
- Mocks database/service layer to avoid real database dependency
- Tests output formatting (table and JSON)
- Tests colored output for health status
- Tests command options and error handling
"""

from datetime import UTC, datetime, timedelta
import json
from unittest.mock import AsyncMock, MagicMock, patch

import click
from click.testing import CliRunner
import pytest

from example_service.cli.commands.admin import admin

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def cli_runner():
    """Create Click CLI runner for testing commands.

    Returns:
        CliRunner instance configured for testing.
    """
    return CliRunner()


@pytest.fixture
def mock_health_result():
    """Mock health check result with HEALTHY status.

    Returns:
        MagicMock configured with health check data.
    """
    mock_result = MagicMock()
    mock_result.status = "HEALTHY"
    mock_result.details = {
        "pool_stats": {
            "active": 5,
            "idle": 10,
            "total": 15,
            "max_size": 100,
        },
        "cache_hit_ratio": 95.5,
        "database_size": 2684354560,  # ~2.5 GB
        "warnings": [],
    }
    return mock_result


@pytest.fixture
def mock_degraded_health_result():
    """Mock health check result with DEGRADED status.

    Returns:
        MagicMock configured with degraded health data.
    """
    mock_result = MagicMock()
    mock_result.status = "DEGRADED"
    mock_result.details = {
        "pool_stats": {
            "active": 80,
            "idle": 5,
            "total": 85,
            "max_size": 100,
        },
        "cache_hit_ratio": 82.0,
        "database_size": 5368709120,
        "warnings": ["Cache hit ratio is below optimal threshold (85%)"],
    }
    return mock_result


@pytest.fixture
def mock_unhealthy_health_result():
    """Mock health check result with UNHEALTHY status.

    Returns:
        MagicMock configured with unhealthy health data.
    """
    mock_result = MagicMock()
    mock_result.status = "UNHEALTHY"
    mock_result.details = {
        "pool_stats": {
            "active": 95,
            "idle": 3,
            "total": 98,
            "max_size": 100,
        },
        "cache_hit_ratio": 65.0,
        "database_size": 10737418240,
        "warnings": [
            "Connection pool utilization is high: 98.0%",
            "Cache hit ratio is low: 65.0%",
        ],
    }
    return mock_result


@pytest.fixture
def mock_stats_result():
    """Mock database statistics result.

    Returns:
        MagicMock configured with database stats.
    """
    mock_result = MagicMock()
    mock_result.table_count = 42
    mock_result.index_count = 128
    mock_result.database_size = 5368709120
    mock_result.cache_hit_ratio = 95.5
    mock_result.active_connections = 15
    mock_result.max_connections = 100
    mock_result.transaction_rate = 123.45
    return mock_result


@pytest.fixture
def mock_connections_list():
    """Mock active connections list.

    Returns:
        List of MagicMock objects representing active connections.
    """
    connections = []
    for i in range(3):
        conn = MagicMock()
        conn.pid = 1000 + i
        conn.username = f"user_{i}"
        conn.state = "active" if i == 0 else "idle"
        conn.duration = 5.5 + i
        conn.query_preview = f"SELECT * FROM table_{i} WHERE id = 1"
        connections.append(conn)
    return connections


@pytest.fixture
def mock_table_sizes_list():
    """Mock table sizes list.

    Returns:
        List of MagicMock objects representing table sizes.
    """
    tables = []
    for i in range(3):
        table = MagicMock()
        table.table_name = f"table_{i}"
        table.row_count = (i + 1) * 10000
        table.table_size = (i + 1) * 10485760  # 10 MB increments
        table.index_size = (i + 1) * 5242880   # 5 MB increments
        table.total_size = table.table_size + table.index_size
        tables.append(table)
    return tables


@pytest.fixture
def mock_index_health_list():
    """Mock index health list.

    Returns:
        List of MagicMock objects representing index health.
    """
    indexes = []
    for i in range(3):
        index = MagicMock()
        index.index_name = f"idx_table_{i}_id"
        index.table_name = f"table_{i}"
        index.size = (i + 1) * 2097152  # 2 MB increments
        index.scan_count = 100 - (i * 50)  # 100, 50, 0
        indexes.append(index)
    return indexes


@pytest.fixture
def mock_audit_logs_list():
    """Mock audit logs list.

    Returns:
        List of MagicMock objects representing audit logs.
    """
    logs = []
    now = datetime.now(UTC)
    for i in range(3):
        log = MagicMock()
        log.timestamp = now - timedelta(hours=i)
        log.action = f"action_{i}"
        log.target = f"target_{i}"
        log.result = "SUCCESS" if i % 2 == 0 else "FAILED"
        log.user_id = f"user_{i}@example.com"
        log.details = {"key": f"value_{i}"}
        logs.append(log)
    return logs


# =============================================================================
# Health Command Tests
# =============================================================================


class TestHealthCommand:
    """Tests for 'admin health' command."""

    def test_health_command_healthy_status(self, cli_runner, mock_health_result):
        """Test health command with HEALTHY status shows green output."""
        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            # Setup mock
            mock_session = AsyncMock()
            mock_get_db.return_value.__aenter__.return_value = mock_session

            with patch("example_service.features.admin.database.service.DatabaseAdminService") as mock_service_class:
                mock_service = AsyncMock()
                mock_service.get_health = AsyncMock(return_value=mock_health_result)
                mock_service_class.return_value = mock_service

                # Execute command
                result = cli_runner.invoke(admin, ["health"])

                # Assertions
                assert result.exit_code == 0
                assert "Database Health Check" in result.output
                assert "HEALTHY" in result.output
                assert "Connection Pool" in result.output
                assert "Cache Performance" in result.output
                assert "Storage" in result.output
                # Check for success message
                assert "Database is healthy and operating normally" in result.output

    def test_health_command_degraded_status(self, cli_runner, mock_degraded_health_result):
        """Test health command with DEGRADED status shows yellow output."""
        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value.__aenter__.return_value = mock_session

            with patch("example_service.features.admin.database.service.DatabaseAdminService") as mock_service_class:
                mock_service = AsyncMock()
                mock_service.get_health = AsyncMock(return_value=mock_degraded_health_result)
                mock_service_class.return_value = mock_service

                result = cli_runner.invoke(admin, ["health"])

                assert result.exit_code == 0
                assert "DEGRADED" in result.output
                assert "Database is operational but has some issues" in result.output
                # Check for warnings section
                assert "Warnings" in result.output
                assert "Cache hit ratio is below optimal threshold" in result.output

    def test_health_command_unhealthy_status(self, cli_runner, mock_unhealthy_health_result):
        """Test health command with UNHEALTHY status shows red output."""
        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value.__aenter__.return_value = mock_session

            with patch("example_service.features.admin.database.service.DatabaseAdminService") as mock_service_class:
                mock_service = AsyncMock()
                mock_service.get_health = AsyncMock(return_value=mock_unhealthy_health_result)
                mock_service_class.return_value = mock_service

                result = cli_runner.invoke(admin, ["health"])

                assert result.exit_code == 0
                assert "UNHEALTHY" in result.output
                assert "Database health check failed - immediate attention required" in result.output
                # Check for multiple warnings
                assert "Connection pool utilization is high" in result.output
                assert "Cache hit ratio is low" in result.output

    def test_health_command_displays_pool_stats(self, cli_runner, mock_health_result):
        """Test health command displays connection pool statistics."""
        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value.__aenter__.return_value = mock_session

            with patch("example_service.features.admin.database.service.DatabaseAdminService") as mock_service_class:
                mock_service = AsyncMock()
                mock_service.get_health = AsyncMock(return_value=mock_health_result)
                mock_service_class.return_value = mock_service

                result = cli_runner.invoke(admin, ["health"])

                assert result.exit_code == 0
                assert "Active:        5" in result.output
                assert "Idle:          10" in result.output
                assert "Total:         15" in result.output
                assert "Max Size:      100" in result.output

    def test_health_command_error_handling(self, cli_runner):
        """Test health command handles database errors gracefully."""
        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            # Simulate database connection error
            mock_get_db.side_effect = Exception("Database connection failed")

            result = cli_runner.invoke(admin, ["health"])

            assert result.exit_code == 1
            assert "Failed to get database health" in result.output


# =============================================================================
# Stats Command Tests
# =============================================================================


class TestStatsCommand:
    """Tests for 'admin stats' command."""

    def test_stats_command_table_format(self, cli_runner, mock_stats_result):
        """Test stats command with default table format."""
        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value.__aenter__.return_value = mock_session

            with patch("example_service.features.admin.database.service.DatabaseAdminService") as mock_service_class:
                mock_service = AsyncMock()
                mock_service.get_statistics = AsyncMock(return_value=mock_stats_result)
                mock_service_class.return_value = mock_service

                result = cli_runner.invoke(admin, ["stats"])

                assert result.exit_code == 0
                assert "Database Statistics" in result.output
                assert "Schema Statistics" in result.output
                assert "Total Tables:       42" in result.output
                assert "Total Indexes:      128" in result.output
                assert "Performance Metrics" in result.output
                assert "Cache Hit Ratio:    95.50%" in result.output
                assert "Transaction Rate:   123.45/sec" in result.output
                assert "Connection Statistics" in result.output
                assert "Active Connections: 15" in result.output
                assert "Max Connections:    100" in result.output

    def test_stats_command_json_format(self, cli_runner, mock_stats_result):
        """Test stats command with JSON format output."""
        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value.__aenter__.return_value = mock_session

            with patch("example_service.features.admin.database.service.DatabaseAdminService") as mock_service_class:
                mock_service = AsyncMock()
                mock_service.get_statistics = AsyncMock(return_value=mock_stats_result)
                mock_service_class.return_value = mock_service

                result = cli_runner.invoke(admin, ["stats", "--format", "json"])

                assert result.exit_code == 0
                # Parse JSON output
                output_data = json.loads(result.output)
                assert output_data["table_count"] == 42
                assert output_data["index_count"] == 128
                assert output_data["cache_hit_ratio"] == 95.5
                assert output_data["active_connections"] == 15
                assert output_data["max_connections"] == 100
                assert output_data["transaction_rate"] == 123.45

    def test_stats_command_calculates_utilization(self, cli_runner, mock_stats_result):
        """Test stats command calculates connection utilization percentage."""
        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value.__aenter__.return_value = mock_session

            with patch("example_service.features.admin.database.service.DatabaseAdminService") as mock_service_class:
                mock_service = AsyncMock()
                mock_service.get_statistics = AsyncMock(return_value=mock_stats_result)
                mock_service_class.return_value = mock_service

                result = cli_runner.invoke(admin, ["stats"])

                assert result.exit_code == 0
                # 15/100 = 15.0%
                assert "Utilization:        15.0%" in result.output

    def test_stats_command_error_handling(self, cli_runner):
        """Test stats command handles errors gracefully."""
        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            mock_get_db.side_effect = Exception("Statistics query failed")

            result = cli_runner.invoke(admin, ["stats"])

            assert result.exit_code == 1
            assert "Failed to get database statistics" in result.output


# =============================================================================
# Connections Command Tests
# =============================================================================


class TestConnectionsCommand:
    """Tests for 'admin connections' command."""

    def test_connections_command_default_limit(self, cli_runner, mock_connections_list):
        """Test connections command with default limit."""
        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value.__aenter__.return_value = mock_session

            with patch("example_service.features.admin.database.service.DatabaseAdminService") as mock_service_class:
                mock_service = AsyncMock()
                mock_service.get_active_connections = AsyncMock(return_value=mock_connections_list)
                mock_service_class.return_value = mock_service

                result = cli_runner.invoke(admin, ["connections"])

                assert result.exit_code == 0
                assert "Active Database Connections" in result.output
                assert "PID" in result.output
                assert "User" in result.output
                assert "State" in result.output
                assert "Duration" in result.output
                assert "Query Preview" in result.output
                # Check connection data
                assert "1000" in result.output
                assert "user_0" in result.output
                assert "SELECT * FROM table_0" in result.output

    def test_connections_command_custom_limit(self, cli_runner, mock_connections_list):
        """Test connections command with custom limit option."""
        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value.__aenter__.return_value = mock_session

            with patch("example_service.features.admin.database.service.DatabaseAdminService") as mock_service_class:
                mock_service = AsyncMock()
                mock_service.get_active_connections = AsyncMock(return_value=mock_connections_list)
                mock_service_class.return_value = mock_service

                result = cli_runner.invoke(admin, ["connections", "--limit", "20"])

                assert result.exit_code == 0
                # Verify service was called with correct limit
                mock_service.get_active_connections.assert_called_once()
                call_args = mock_service.get_active_connections.call_args
                assert call_args[1]["limit"] == 20

    def test_connections_command_no_active_connections(self, cli_runner):
        """Test connections command when no connections are active."""
        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value.__aenter__.return_value = mock_session

            with patch("example_service.features.admin.database.service.DatabaseAdminService") as mock_service_class:
                mock_service = AsyncMock()
                mock_service.get_active_connections = AsyncMock(return_value=[])
                mock_service_class.return_value = mock_service

                result = cli_runner.invoke(admin, ["connections"])

                assert result.exit_code == 0
                assert "No active connections found" in result.output

    def test_connections_command_formats_duration(self, cli_runner):
        """Test connections command formats duration correctly."""
        # Create connection with long duration
        long_conn = MagicMock()
        long_conn.pid = 9999
        long_conn.username = "long_user"
        long_conn.state = "active"
        long_conn.duration = 3665.5  # > 1 hour
        long_conn.query_preview = "SELECT * FROM long_table"

        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value.__aenter__.return_value = mock_session

            with patch("example_service.features.admin.database.service.DatabaseAdminService") as mock_service_class:
                mock_service = AsyncMock()
                mock_service.get_active_connections = AsyncMock(return_value=[long_conn])
                mock_service_class.return_value = mock_service

                result = cli_runner.invoke(admin, ["connections"])

                assert result.exit_code == 0
                # Duration should be formatted in hours
                assert "1.0h" in result.output or "1.0" in result.output

    def test_connections_command_error_handling(self, cli_runner):
        """Test connections command handles errors gracefully."""
        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            mock_get_db.side_effect = Exception("Connection query failed")

            result = cli_runner.invoke(admin, ["connections"])

            assert result.exit_code == 1
            assert "Failed to get active connections" in result.output


# =============================================================================
# Table Sizes Command Tests
# =============================================================================


class TestTableSizesCommand:
    """Tests for 'admin table-sizes' command."""

    def test_table_sizes_command_default_limit(self, cli_runner, mock_table_sizes_list):
        """Test table-sizes command with default limit."""
        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value.__aenter__.return_value = mock_session

            with patch("example_service.features.admin.database.service.DatabaseAdminService") as mock_service_class:
                with patch("example_service.core.database.admin_utils.format_bytes") as mock_format:
                    mock_format.side_effect = lambda x: f"{x / 1024 / 1024:.1f} MB"

                    mock_service = AsyncMock()
                    mock_service.get_table_sizes = AsyncMock(return_value=mock_table_sizes_list)
                    mock_service_class.return_value = mock_service

                    result = cli_runner.invoke(admin, ["table-sizes"])

                    assert result.exit_code == 0
                    assert "Table Sizes" in result.output
                    assert "Table Name" in result.output
                    assert "Rows" in result.output
                    assert "Table Size" in result.output
                    assert "Index Size" in result.output
                    assert "Total Size" in result.output
                    # Check table data
                    assert "table_0" in result.output
                    assert "table_1" in result.output
                    assert "table_2" in result.output

    def test_table_sizes_command_custom_limit(self, cli_runner, mock_table_sizes_list):
        """Test table-sizes command with custom limit option."""
        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value.__aenter__.return_value = mock_session

            with patch("example_service.features.admin.database.service.DatabaseAdminService") as mock_service_class:
                with patch("example_service.core.database.admin_utils.format_bytes"):
                    mock_service = AsyncMock()
                    mock_service.get_table_sizes = AsyncMock(return_value=mock_table_sizes_list)
                    mock_service_class.return_value = mock_service

                    result = cli_runner.invoke(admin, ["table-sizes", "--limit", "50"])

                    assert result.exit_code == 0
                    # Verify service was called with correct limit
                    mock_service.get_table_sizes.assert_called_once()
                    call_args = mock_service.get_table_sizes.call_args
                    assert call_args[1]["limit"] == 50

    def test_table_sizes_command_no_tables(self, cli_runner):
        """Test table-sizes command when no tables exist."""
        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value.__aenter__.return_value = mock_session

            with patch("example_service.features.admin.database.service.DatabaseAdminService") as mock_service_class:
                mock_service = AsyncMock()
                mock_service.get_table_sizes = AsyncMock(return_value=[])
                mock_service_class.return_value = mock_service

                result = cli_runner.invoke(admin, ["table-sizes"])

                assert result.exit_code == 0
                assert "No tables found" in result.output

    def test_table_sizes_command_formats_row_count(self, cli_runner):
        """Test table-sizes command formats row count with commas."""
        table = MagicMock()
        table.table_name = "large_table"
        table.row_count = 1234567
        table.table_size = 10485760
        table.index_size = 5242880
        table.total_size = 15728640

        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value.__aenter__.return_value = mock_session

            with patch("example_service.features.admin.database.service.DatabaseAdminService") as mock_service_class:
                with patch("example_service.core.database.admin_utils.format_bytes") as mock_format:
                    mock_format.return_value = "10.0 MB"

                    mock_service = AsyncMock()
                    mock_service.get_table_sizes = AsyncMock(return_value=[table])
                    mock_service_class.return_value = mock_service

                    result = cli_runner.invoke(admin, ["table-sizes"])

                    assert result.exit_code == 0
                    # Check for comma-formatted row count
                    assert "1,234,567" in result.output

    def test_table_sizes_command_error_handling(self, cli_runner):
        """Test table-sizes command handles errors gracefully."""
        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            mock_get_db.side_effect = Exception("Table size query failed")

            result = cli_runner.invoke(admin, ["table-sizes"])

            assert result.exit_code == 1
            assert "Failed to get table sizes" in result.output


# =============================================================================
# Index Health Command Tests
# =============================================================================


class TestIndexHealthCommand:
    """Tests for 'admin index-health' command."""

    def test_index_health_command_all_tables(self, cli_runner, mock_index_health_list):
        """Test index-health command without table filter."""
        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value.__aenter__.return_value = mock_session

            with patch("example_service.features.admin.database.service.DatabaseAdminService") as mock_service_class:
                with patch("example_service.core.database.admin_utils.format_bytes") as mock_format:
                    mock_format.side_effect = lambda x: f"{x / 1024 / 1024:.1f} MB"

                    mock_service = AsyncMock()
                    mock_service.get_index_health = AsyncMock(return_value=mock_index_health_list)
                    mock_service_class.return_value = mock_service

                    result = cli_runner.invoke(admin, ["index-health"])

                    assert result.exit_code == 0
                    assert "Index Health" in result.output
                    assert "Index Name" in result.output
                    assert "Table" in result.output
                    assert "Size" in result.output
                    assert "Scans" in result.output
                    assert "Status" in result.output
                    # Check index data
                    assert "idx_table_0_id" in result.output
                    assert "idx_table_1_id" in result.output

    def test_index_health_command_with_table_filter(self, cli_runner, mock_index_health_list):
        """Test index-health command with table filter option."""
        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value.__aenter__.return_value = mock_session

            with patch("example_service.features.admin.database.service.DatabaseAdminService") as mock_service_class:
                with patch("example_service.core.database.admin_utils.format_bytes"):
                    mock_service = AsyncMock()
                    mock_service.get_index_health = AsyncMock(return_value=mock_index_health_list)
                    mock_service_class.return_value = mock_service

                    result = cli_runner.invoke(admin, ["index-health", "--table", "users"])

                    assert result.exit_code == 0
                    assert "Showing indexes for table: users" in result.output
                    # Verify service was called with table filter
                    mock_service.get_index_health.assert_called_once()
                    call_args = mock_service.get_index_health.call_args
                    assert call_args[1]["table_name"] == "users"

    def test_index_health_command_no_indexes(self, cli_runner):
        """Test index-health command when no indexes exist."""
        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value.__aenter__.return_value = mock_session

            with patch("example_service.features.admin.database.service.DatabaseAdminService") as mock_service_class:
                mock_service = AsyncMock()
                mock_service.get_index_health = AsyncMock(return_value=[])
                mock_service_class.return_value = mock_service

                result = cli_runner.invoke(admin, ["index-health"])

                assert result.exit_code == 0
                assert "No indexes found" in result.output

    def test_index_health_command_no_indexes_for_table(self, cli_runner):
        """Test index-health command when no indexes exist for specific table."""
        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value.__aenter__.return_value = mock_session

            with patch("example_service.features.admin.database.service.DatabaseAdminService") as mock_service_class:
                mock_service = AsyncMock()
                mock_service.get_index_health = AsyncMock(return_value=[])
                mock_service_class.return_value = mock_service

                result = cli_runner.invoke(admin, ["index-health", "--table", "empty_table"])

                assert result.exit_code == 0
                assert "No indexes found for table 'empty_table'" in result.output

    def test_index_health_command_detects_unused_indexes(self, cli_runner):
        """Test index-health command detects and warns about unused indexes."""
        # Create unused index (0 scans, > 1 MB)
        unused_index = MagicMock()
        unused_index.index_name = "idx_unused"
        unused_index.table_name = "some_table"
        unused_index.size = 2097152  # 2 MB
        unused_index.scan_count = 0

        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value.__aenter__.return_value = mock_session

            with patch("example_service.features.admin.database.service.DatabaseAdminService") as mock_service_class:
                with patch("example_service.core.database.admin_utils.format_bytes") as mock_format:
                    mock_format.return_value = "2.0 MB"

                    mock_service = AsyncMock()
                    mock_service.get_index_health = AsyncMock(return_value=[unused_index])
                    mock_service_class.return_value = mock_service

                    result = cli_runner.invoke(admin, ["index-health"])

                    assert result.exit_code == 0
                    assert "UNUSED" in result.output
                    assert "Found 1 unused index(es) > 1 MB" in result.output
                    assert "Consider dropping unused indexes" in result.output

    def test_index_health_command_error_handling(self, cli_runner):
        """Test index-health command handles errors gracefully."""
        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            mock_get_db.side_effect = Exception("Index health query failed")

            result = cli_runner.invoke(admin, ["index-health"])

            assert result.exit_code == 1
            assert "Failed to get index health" in result.output


# =============================================================================
# Audit Logs Command Tests
# =============================================================================


class TestAuditLogsCommand:
    """Tests for 'admin audit-logs' command."""

    def test_audit_logs_command_default_options(self, cli_runner, mock_audit_logs_list):
        """Test audit-logs command with default options (7 days)."""
        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value.__aenter__.return_value = mock_session

            with patch("example_service.features.admin.database.service.DatabaseAdminService") as mock_service_class:
                mock_service = AsyncMock()
                mock_service.get_audit_logs = AsyncMock(return_value=mock_audit_logs_list)
                mock_service_class.return_value = mock_service

                result = cli_runner.invoke(admin, ["audit-logs"])

                assert result.exit_code == 0
                assert "Admin Audit Logs" in result.output
                assert "Timestamp" in result.output
                assert "Action" in result.output
                assert "Target" in result.output
                assert "Result" in result.output
                assert "User" in result.output
                # Check log data
                assert "action_0" in result.output
                assert "SUCCESS" in result.output

    def test_audit_logs_command_with_action_filter(self, cli_runner, mock_audit_logs_list):
        """Test audit-logs command with action filter."""
        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value.__aenter__.return_value = mock_session

            with patch("example_service.features.admin.database.service.DatabaseAdminService") as mock_service_class:
                mock_service = AsyncMock()
                mock_service.get_audit_logs = AsyncMock(return_value=mock_audit_logs_list)
                mock_service_class.return_value = mock_service

                result = cli_runner.invoke(admin, ["audit-logs", "--action", "vacuum"])

                assert result.exit_code == 0
                assert "Filtering by action: vacuum" in result.output
                # Verify service was called with action filter
                mock_service.get_audit_logs.assert_called_once()
                call_args = mock_service.get_audit_logs.call_args
                assert "action" in call_args[1]["filters"]
                assert call_args[1]["filters"]["action"] == "vacuum"

    def test_audit_logs_command_with_user_filter(self, cli_runner, mock_audit_logs_list):
        """Test audit-logs command with user filter."""
        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value.__aenter__.return_value = mock_session

            with patch("example_service.features.admin.database.service.DatabaseAdminService") as mock_service_class:
                mock_service = AsyncMock()
                mock_service.get_audit_logs = AsyncMock(return_value=mock_audit_logs_list)
                mock_service_class.return_value = mock_service

                result = cli_runner.invoke(admin, ["audit-logs", "--user", "admin@example.com"])

                assert result.exit_code == 0
                assert "Filtering by user: admin@example.com" in result.output
                # Verify service was called with user filter
                mock_service.get_audit_logs.assert_called_once()
                call_args = mock_service.get_audit_logs.call_args
                assert "user_id" in call_args[1]["filters"]
                assert call_args[1]["filters"]["user_id"] == "admin@example.com"

    def test_audit_logs_command_with_days_option(self, cli_runner, mock_audit_logs_list):
        """Test audit-logs command with custom days option."""
        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value.__aenter__.return_value = mock_session

            with patch("example_service.features.admin.database.service.DatabaseAdminService") as mock_service_class:
                mock_service = AsyncMock()
                mock_service.get_audit_logs = AsyncMock(return_value=mock_audit_logs_list)
                mock_service_class.return_value = mock_service

                result = cli_runner.invoke(admin, ["audit-logs", "--days", "30"])

                assert result.exit_code == 0
                assert "Showing 3 audit log entries from the last 30 days" in result.output

    def test_audit_logs_command_with_multiple_filters(self, cli_runner, mock_audit_logs_list):
        """Test audit-logs command with multiple filters."""
        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value.__aenter__.return_value = mock_session

            with patch("example_service.features.admin.database.service.DatabaseAdminService") as mock_service_class:
                mock_service = AsyncMock()
                mock_service.get_audit_logs = AsyncMock(return_value=mock_audit_logs_list)
                mock_service_class.return_value = mock_service

                result = cli_runner.invoke(
                    admin,
                    ["audit-logs", "--action", "vacuum", "--user", "admin@example.com", "--days", "14"],
                )

                assert result.exit_code == 0
                assert "Filtering by action: vacuum" in result.output
                assert "Filtering by user: admin@example.com" in result.output
                # Verify filters passed to service
                call_args = mock_service.get_audit_logs.call_args
                assert call_args[1]["filters"]["action"] == "vacuum"
                assert call_args[1]["filters"]["user_id"] == "admin@example.com"

    def test_audit_logs_command_no_logs_found(self, cli_runner):
        """Test audit-logs command when no logs are found."""
        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value.__aenter__.return_value = mock_session

            with patch("example_service.features.admin.database.service.DatabaseAdminService") as mock_service_class:
                mock_service = AsyncMock()
                mock_service.get_audit_logs = AsyncMock(return_value=[])
                mock_service_class.return_value = mock_service

                result = cli_runner.invoke(admin, ["audit-logs"])

                assert result.exit_code == 0
                assert "No audit logs found in the last 7 days" in result.output

    def test_audit_logs_command_displays_details(self, cli_runner, mock_audit_logs_list):
        """Test audit-logs command displays log details."""
        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value.__aenter__.return_value = mock_session

            with patch("example_service.features.admin.database.service.DatabaseAdminService") as mock_service_class:
                mock_service = AsyncMock()
                mock_service.get_audit_logs = AsyncMock(return_value=mock_audit_logs_list)
                mock_service_class.return_value = mock_service

                result = cli_runner.invoke(admin, ["audit-logs"])

                assert result.exit_code == 0
                # Check that details are displayed
                assert "Details:" in result.output
                assert "value_" in result.output

    def test_audit_logs_command_error_handling(self, cli_runner):
        """Test audit-logs command handles errors gracefully."""
        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            mock_get_db.side_effect = Exception("Audit log query failed")

            result = cli_runner.invoke(admin, ["audit-logs"])

            assert result.exit_code == 1
            assert "Failed to get audit logs" in result.output


# =============================================================================
# Edge Cases and Error Handling Tests
# =============================================================================


class TestEdgeCasesAndErrors:
    """Tests for edge cases and error handling across all commands."""

    def test_invalid_format_option(self, cli_runner):
        """Test stats command rejects invalid format option."""
        result = cli_runner.invoke(admin, ["stats", "--format", "xml"])

        assert result.exit_code != 0
        # Click should reject invalid choice

    def test_negative_limit_option(self, cli_runner):
        """Test connections command with negative limit."""
        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value.__aenter__.return_value = mock_session

            with patch("example_service.features.admin.database.service.DatabaseAdminService") as mock_service_class:
                mock_service = AsyncMock()
                mock_service.get_active_connections = AsyncMock(return_value=[])
                mock_service_class.return_value = mock_service

                # Click should handle integer validation
                result = cli_runner.invoke(admin, ["connections", "--limit", "-5"])
                assert result.exit_code != 0

                # Command may execute with negative value or Click may reject it
                # The actual behavior depends on Click's integer type handling

    def test_missing_dependencies_import_error(self, cli_runner):
        """Test command handles missing import gracefully."""
        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            # Simulate import error
            mock_get_db.side_effect = ImportError("Module not found")

            result = cli_runner.invoke(admin, ["health"])

            assert result.exit_code == 1
            assert "Failed to get database health" in result.output

    def test_health_command_with_missing_format_bytes(self, cli_runner, mock_health_result):
        """Test health command handles missing format_bytes import."""
        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value.__aenter__.return_value = mock_session

            # Mock format_bytes to raise ImportError
            with patch("example_service.core.database.admin_utils.format_bytes") as mock_format:
                mock_format.side_effect = ImportError("format_bytes not available")

                with patch("example_service.features.admin.database.service.DatabaseAdminService"):
                    result = cli_runner.invoke(admin, ["health"])

                    assert result.exit_code == 1


# =============================================================================
# Integration-like Tests
# =============================================================================


class TestCommandIntegration:
    """Integration-like tests that test commands more holistically."""

    def test_health_command_full_workflow(self, cli_runner, mock_health_result):
        """Test complete health check workflow."""
        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value.__aenter__.return_value = mock_session

            with patch("example_service.features.admin.database.dao.DatabaseAdminDAO") as mock_dao_class:
                with patch("example_service.core.settings.get_admin_settings") as mock_settings:
                    with patch("example_service.features.admin.database.service.DatabaseAdminService") as mock_service_class:
                        # Setup complete mock chain
                        mock_service = AsyncMock()
                        mock_service.get_health = AsyncMock(return_value=mock_health_result)
                        mock_service_class.return_value = mock_service

                        result = cli_runner.invoke(admin, ["health"])

                        # Verify all steps executed
                        assert result.exit_code == 0
                        mock_get_db.assert_called_once()
                        mock_dao_class.assert_called_once()
                        mock_settings.assert_called_once()
                        mock_service_class.assert_called_once()
                        mock_service.get_health.assert_called_once()

    def test_stats_command_json_format_complete(self, cli_runner, mock_stats_result):
        """Test stats command JSON output is valid and complete."""
        with patch("example_service.infra.database.session.get_async_session") as mock_get_db:
            mock_session = AsyncMock()
            mock_get_db.return_value.__aenter__.return_value = mock_session

            with patch("example_service.features.admin.database.service.DatabaseAdminService") as mock_service_class:
                mock_service = AsyncMock()
                mock_service.get_statistics = AsyncMock(return_value=mock_stats_result)
                mock_service_class.return_value = mock_service

                result = cli_runner.invoke(admin, ["stats", "--format", "json"])

                assert result.exit_code == 0

                # Validate JSON structure
                data = json.loads(result.output)
                required_fields = [
                    "table_count",
                    "index_count",
                    "database_size",
                    "cache_hit_ratio",
                    "active_connections",
                    "max_connections",
                    "transaction_rate",
                ]
                for field in required_fields:
                    assert field in data, f"Missing field: {field}"
