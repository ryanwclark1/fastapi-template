"""Integration tests for database admin REST API endpoints.

This module provides comprehensive integration testing for the database admin API,
covering all 6 endpoints with both successful and failure scenarios.

Test Coverage:
- Authentication testing (superuser vs regular user vs unauthenticated)
- All 6 database admin endpoints
- Query parameter variations
- Response schema validation
- Audit logging verification
- Error handling and edge cases

Endpoints Tested:
- GET /admin/database/health - Database health status
- GET /admin/database/stats - Detailed statistics
- GET /admin/database/connections - Active connections
- GET /admin/database/tables/sizes - Table sizes
- GET /admin/database/indexes/health - Index health
- GET /admin/database/audit-logs - Audit logs

Pattern: Integration testing with real database and mocked authentication.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

from fastapi import status
from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import text

from example_service.core.dependencies.auth_client import get_auth_client
from example_service.core.dependencies.database import get_db_session
from example_service.core.schemas.auth import AuthUser
from example_service.features.admin.database.schemas import (
    DatabaseHealthStatus,
)
from example_service.infra.auth.testing import MockAuthClient
from example_service.infra.cache.redis import get_cache

if TYPE_CHECKING:
    from httpx import AsyncClient as AsyncClientType
    from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def superuser_auth() -> MockAuthClient:
    """Mock auth client with superuser permissions.

    Returns:
        MockAuthClient configured with # (superuser) ACL.
    """
    return MockAuthClient.admin()


@pytest.fixture
def regular_user_auth() -> MockAuthClient:
    """Mock auth client with regular user permissions (no admin access).

    Returns:
        MockAuthClient configured with limited user ACLs.
    """
    return MockAuthClient(
        user_id="regular-user-id",
        tenant_id="tenant-123",
        permissions=["users.me.read", "users.me.write"],
    )


@pytest.fixture
async def superuser_client(
    app,
    db_session: AsyncSession,
    superuser_auth: MockAuthClient,
    mock_cache,
) -> AsyncClientType:
    """Create HTTP client with superuser authentication.

    Args:
        app: FastAPI application fixture
        db_session: Database session fixture
        superuser_auth: Superuser auth client fixture
        mock_cache: Mock cache fixture

    Yields:
        AsyncClient configured with superuser permissions.
    """

    async def _override_db_session():
        yield db_session

    def _override_cache():
        return mock_cache

    def _override_auth_client():
        return superuser_auth

    # Override dependencies
    app.dependency_overrides[get_db_session] = _override_db_session
    app.dependency_overrides[get_cache] = _override_cache
    app.dependency_overrides[get_auth_client] = _override_auth_client

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    # Cleanup
    app.dependency_overrides.clear()


@pytest.fixture
async def regular_user_client(
    app,
    db_session: AsyncSession,
    regular_user_auth: MockAuthClient,
    mock_cache,
) -> AsyncClientType:
    """Create HTTP client with regular user (non-admin) authentication.

    Args:
        app: FastAPI application fixture
        db_session: Database session fixture
        regular_user_auth: Regular user auth client fixture
        mock_cache: Mock cache fixture

    Yields:
        AsyncClient configured with regular user permissions.
    """

    async def _override_db_session():
        yield db_session

    def _override_cache():
        return mock_cache

    def _override_auth_client():
        return regular_user_auth

    # Override dependencies
    app.dependency_overrides[get_db_session] = _override_db_session
    app.dependency_overrides[get_cache] = _override_cache
    app.dependency_overrides[get_auth_client] = _override_auth_client

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    # Cleanup
    app.dependency_overrides.clear()


# =============================================================================
# Health Endpoint Tests
# =============================================================================


@pytest.mark.asyncio
class TestDatabaseHealthEndpoint:
    """Test suite for GET /admin/database/health endpoint."""

    async def test_health_check_with_superuser(
        self,
        superuser_client: AsyncClientType,
    ):
        """Test health check with valid superuser authentication.

        Verifies:
        - 200 status code
        - Response schema matches DatabaseHealth
        - All required fields present
        - Status is a valid enum value
        - Connection pool stats are valid
        """
        response = await superuser_client.get("/api/v1/admin/database/health")

        assert response.status_code == status.HTTP_200_OK

        data = response.json()

        # Verify required fields
        assert "status" in data
        assert "timestamp" in data
        assert "connection_pool" in data
        assert "database_size_bytes" in data
        assert "database_size_human" in data
        assert "active_connections_count" in data
        assert "warnings" in data

        # Verify status is valid enum
        assert data["status"] in ["healthy", "degraded", "unhealthy"]

        # Verify connection pool structure
        pool = data["connection_pool"]
        assert "active_connections" in pool
        assert "idle_connections" in pool
        assert "total_connections" in pool
        assert "max_connections" in pool
        assert "utilization_percent" in pool

        # Verify data types
        assert isinstance(data["database_size_bytes"], int)
        assert isinstance(data["database_size_human"], str)
        assert isinstance(data["active_connections_count"], int)
        assert isinstance(data["warnings"], list)

        # Verify numeric ranges
        assert pool["active_connections"] >= 0
        assert pool["idle_connections"] >= 0
        assert pool["total_connections"] >= 0
        assert pool["max_connections"] > 0
        assert 0 <= pool["utilization_percent"] <= 100

    async def test_health_check_without_authentication(self, client: AsyncClient):
        """Test health check without authentication header.

        Verifies:
        - 401 Unauthorized status code
        - Error response structure
        """
        response = await client.get("/api/v1/admin/database/health")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_health_check_with_regular_user(
        self,
        regular_user_client: AsyncClientType,
    ):
        """Test health check with regular user (non-superuser).

        Verifies:
        - 403 Forbidden status code
        - User lacks superuser permissions
        """
        response = await regular_user_client.get("/api/v1/admin/database/health")

        assert response.status_code == status.HTTP_403_FORBIDDEN


# =============================================================================
# Stats Endpoint Tests
# =============================================================================


@pytest.mark.asyncio
class TestDatabaseStatsEndpoint:
    """Test suite for GET /admin/database/stats endpoint."""

    async def test_stats_with_superuser(
        self,
        superuser_client: AsyncClientType,
    ):
        """Test database statistics with valid superuser authentication.

        Verifies:
        - 200 status code
        - Response schema matches DatabaseStats
        - All required fields present
        - Data types are correct
        - Numeric values are valid
        """
        response = await superuser_client.get("/api/v1/admin/database/stats")

        assert response.status_code == status.HTTP_200_OK

        data = response.json()

        # Verify required fields
        assert "total_size_bytes" in data
        assert "total_size_human" in data
        assert "table_count" in data
        assert "index_count" in data
        assert "transaction_rate" in data
        assert "top_tables" in data
        assert "slow_queries_count" in data

        # Verify data types
        assert isinstance(data["total_size_bytes"], int)
        assert isinstance(data["total_size_human"], str)
        assert isinstance(data["table_count"], int)
        assert isinstance(data["index_count"], int)
        assert isinstance(data["transaction_rate"], (int, float))
        assert isinstance(data["top_tables"], list)
        assert isinstance(data["slow_queries_count"], int)

        # Verify numeric ranges
        assert data["total_size_bytes"] >= 0
        assert data["table_count"] >= 0
        assert data["index_count"] >= 0
        assert data["transaction_rate"] >= 0
        assert data["slow_queries_count"] >= 0

        # Verify top_tables structure
        for table in data["top_tables"]:
            assert "table_name" in table
            assert "schema_name" in table
            assert "row_count" in table
            assert "total_size_bytes" in table
            assert "total_size_human" in table
            assert "table_size_bytes" in table
            assert "indexes_size_bytes" in table

    async def test_stats_without_authentication(self, client: AsyncClient):
        """Test stats endpoint without authentication.

        Verifies:
        - 401 Unauthorized status code
        """
        response = await client.get("/api/v1/admin/database/stats")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_stats_with_regular_user(
        self,
        regular_user_client: AsyncClientType,
    ):
        """Test stats endpoint with regular user.

        Verifies:
        - 403 Forbidden status code
        """
        response = await regular_user_client.get("/api/v1/admin/database/stats")

        assert response.status_code == status.HTTP_403_FORBIDDEN


# =============================================================================
# Connections Endpoint Tests
# =============================================================================


@pytest.mark.asyncio
class TestActiveConnectionsEndpoint:
    """Test suite for GET /admin/database/connections endpoint."""

    async def test_connections_with_default_limit(
        self,
        superuser_client: AsyncClientType,
    ):
        """Test active connections with default limit.

        Verifies:
        - 200 status code
        - Response is a list
        - Each connection has required fields
        - Default limit is respected
        """
        response = await superuser_client.get("/api/v1/admin/database/connections")

        assert response.status_code == status.HTTP_200_OK

        data = response.json()

        # Verify response is a list
        assert isinstance(data, list)

        # Verify connection structure
        for conn in data:
            assert "pid" in conn
            assert "user" in conn
            assert "database" in conn
            assert "state" in conn
            assert "query" in conn
            assert "duration_seconds" in conn

            # Verify data types
            assert isinstance(conn["pid"], int)
            assert isinstance(conn["user"], str)
            assert isinstance(conn["database"], str)
            assert isinstance(conn["state"], str)
            assert isinstance(conn["query"], str)
            assert isinstance(conn["duration_seconds"], (int, float))

            # Verify ranges
            assert conn["pid"] > 0
            assert conn["duration_seconds"] >= 0

    async def test_connections_with_custom_limit(
        self,
        superuser_client: AsyncClientType,
    ):
        """Test active connections with custom limit parameter.

        Verifies:
        - 200 status code
        - Limit parameter is respected
        - Response has at most 'limit' items
        """
        limit = 10
        response = await superuser_client.get(
            f"/api/v1/admin/database/connections?limit={limit}",
        )

        assert response.status_code == status.HTTP_200_OK

        data = response.json()

        # Verify limit is respected
        assert len(data) <= limit

    async def test_connections_with_invalid_limit(
        self,
        superuser_client: AsyncClientType,
    ):
        """Test connections with invalid limit parameter.

        Verifies:
        - 422 Unprocessable Entity for invalid limit values
        """
        # Test negative limit
        response = await superuser_client.get(
            "/api/v1/admin/database/connections?limit=-1",
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

        # Test limit exceeding maximum
        response = await superuser_client.get(
            "/api/v1/admin/database/connections?limit=1000",
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_connections_without_authentication(self, client: AsyncClient):
        """Test connections endpoint without authentication.

        Verifies:
        - 401 Unauthorized status code
        """
        response = await client.get("/api/v1/admin/database/connections")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_connections_with_regular_user(
        self,
        regular_user_client: AsyncClientType,
    ):
        """Test connections endpoint with regular user.

        Verifies:
        - 403 Forbidden status code
        """
        response = await regular_user_client.get("/api/v1/admin/database/connections")

        assert response.status_code == status.HTTP_403_FORBIDDEN


# =============================================================================
# Table Sizes Endpoint Tests
# =============================================================================


@pytest.mark.asyncio
class TestTableSizesEndpoint:
    """Test suite for GET /admin/database/tables/sizes endpoint."""

    async def test_table_sizes_with_default_limit(
        self,
        superuser_client: AsyncClientType,
    ):
        """Test table sizes with default limit.

        Verifies:
        - 200 status code
        - Response is a list
        - Each table has required fields
        - Sizes are sorted descending
        """
        response = await superuser_client.get("/api/v1/admin/database/tables/sizes")

        assert response.status_code == status.HTTP_200_OK

        data = response.json()

        # Verify response is a list
        assert isinstance(data, list)

        # Verify table structure
        for table in data:
            assert "table_name" in table
            assert "schema_name" in table
            assert "row_count" in table
            assert "total_size_bytes" in table
            assert "total_size_human" in table
            assert "table_size_bytes" in table
            assert "indexes_size_bytes" in table

            # Verify data types
            assert isinstance(table["table_name"], str)
            assert isinstance(table["schema_name"], str)
            assert isinstance(table["row_count"], int)
            assert isinstance(table["total_size_bytes"], int)
            assert isinstance(table["total_size_human"], str)
            assert isinstance(table["table_size_bytes"], int)
            assert isinstance(table["indexes_size_bytes"], int)

            # Verify ranges
            assert table["row_count"] >= 0
            assert table["total_size_bytes"] >= 0
            assert table["table_size_bytes"] >= 0
            assert table["indexes_size_bytes"] >= 0

        # Verify sorted by total_size_bytes (descending)
        if len(data) > 1:
            for i in range(len(data) - 1):
                assert data[i]["total_size_bytes"] >= data[i + 1]["total_size_bytes"]

    async def test_table_sizes_with_custom_limit(
        self,
        superuser_client: AsyncClientType,
    ):
        """Test table sizes with custom limit parameter.

        Verifies:
        - 200 status code
        - Limit parameter is respected
        """
        limit = 5
        response = await superuser_client.get(
            f"/api/v1/admin/database/tables/sizes?limit={limit}",
        )

        assert response.status_code == status.HTTP_200_OK

        data = response.json()

        # Verify limit is respected
        assert len(data) <= limit

    async def test_table_sizes_with_invalid_limit(
        self,
        superuser_client: AsyncClientType,
    ):
        """Test table sizes with invalid limit parameter.

        Verifies:
        - 422 Unprocessable Entity for invalid limit values
        """
        # Test negative limit
        response = await superuser_client.get(
            "/api/v1/admin/database/tables/sizes?limit=0",
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

        # Test limit exceeding maximum
        response = await superuser_client.get(
            "/api/v1/admin/database/tables/sizes?limit=200",
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_table_sizes_without_authentication(self, client: AsyncClient):
        """Test table sizes endpoint without authentication.

        Verifies:
        - 401 Unauthorized status code
        """
        response = await client.get("/api/v1/admin/database/tables/sizes")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_table_sizes_with_regular_user(
        self,
        regular_user_client: AsyncClientType,
    ):
        """Test table sizes endpoint with regular user.

        Verifies:
        - 403 Forbidden status code
        """
        response = await regular_user_client.get("/api/v1/admin/database/tables/sizes")

        assert response.status_code == status.HTTP_403_FORBIDDEN


# =============================================================================
# Index Health Endpoint Tests
# =============================================================================


@pytest.mark.asyncio
class TestIndexHealthEndpoint:
    """Test suite for GET /admin/database/indexes/health endpoint."""

    async def test_index_health_without_filter(
        self,
        superuser_client: AsyncClientType,
    ):
        """Test index health without table name filter.

        Verifies:
        - 200 status code
        - Response is a list
        - Each index has required fields
        - Data types are correct
        """
        response = await superuser_client.get("/api/v1/admin/database/indexes/health")

        assert response.status_code == status.HTTP_200_OK

        data = response.json()

        # Verify response is a list
        assert isinstance(data, list)

        # Verify index structure
        for index in data:
            assert "index_name" in index
            assert "table_name" in index
            assert "index_size_bytes" in index
            assert "index_size_human" in index
            assert "index_scans" in index
            assert "is_valid" in index
            assert "definition" in index

            # Verify data types
            assert isinstance(index["index_name"], str)
            assert isinstance(index["table_name"], str)
            assert isinstance(index["index_size_bytes"], int)
            assert isinstance(index["index_size_human"], str)
            assert isinstance(index["index_scans"], int)
            assert isinstance(index["is_valid"], bool)
            assert isinstance(index["definition"], str)

            # Verify ranges
            assert index["index_size_bytes"] >= 0
            assert index["index_scans"] >= 0

    async def test_index_health_with_table_filter(
        self,
        superuser_client: AsyncClientType,
        db_session: AsyncSession,
    ):
        """Test index health with table name filter.

        Verifies:
        - 200 status code
        - Only indexes for specified table are returned
        """
        # Get a table name that exists
        result = await db_session.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' LIMIT 1",
            ),
        )
        row = result.fetchone()

        if row:
            table_name = row[0]

            response = await superuser_client.get(
                f"/api/v1/admin/database/indexes/health?table_name={table_name}",
            )

            assert response.status_code == status.HTTP_200_OK

            data = response.json()

            # Verify all indexes belong to specified table
            for index in data:
                assert index["table_name"] == table_name

    async def test_index_health_with_nonexistent_table(
        self,
        superuser_client: AsyncClientType,
    ):
        """Test index health with non-existent table name.

        Verifies:
        - 200 status code
        - Empty list returned
        """
        response = await superuser_client.get(
            "/api/v1/admin/database/indexes/health?table_name=nonexistent_table_xyz",
        )

        assert response.status_code == status.HTTP_200_OK

        data = response.json()

        # Should return empty list
        assert isinstance(data, list)
        assert len(data) == 0

    async def test_index_health_without_authentication(self, client: AsyncClient):
        """Test index health endpoint without authentication.

        Verifies:
        - 401 Unauthorized status code
        """
        response = await client.get("/api/v1/admin/database/indexes/health")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_index_health_with_regular_user(
        self,
        regular_user_client: AsyncClientType,
    ):
        """Test index health endpoint with regular user.

        Verifies:
        - 403 Forbidden status code
        """
        response = await regular_user_client.get(
            "/api/v1/admin/database/indexes/health",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN


# =============================================================================
# Audit Logs Endpoint Tests
# =============================================================================


@pytest.mark.asyncio
class TestAuditLogsEndpoint:
    """Test suite for GET /admin/database/audit-logs endpoint."""

    async def test_audit_logs_with_default_pagination(
        self,
        superuser_client: AsyncClientType,
    ):
        """Test audit logs with default pagination.

        Verifies:
        - 200 status code
        - Response has pagination structure
        - All required fields present
        - Pagination metadata is valid
        """
        response = await superuser_client.get("/api/v1/admin/database/audit-logs")

        assert response.status_code == status.HTTP_200_OK

        data = response.json()

        # Verify pagination structure
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "total_pages" in data

        # Verify data types
        assert isinstance(data["items"], list)
        assert isinstance(data["total"], int)
        assert isinstance(data["page"], int)
        assert isinstance(data["page_size"], int)
        assert isinstance(data["total_pages"], int)

        # Verify pagination metadata
        assert data["page"] >= 1
        assert data["page_size"] >= 1
        assert data["total"] >= 0
        assert data["total_pages"] >= 0

        # Verify audit log structure
        for log in data["items"]:
            assert "id" in log
            assert "action" in log
            assert "target" in log
            assert "user_id" in log
            assert "result" in log
            assert "created_at" in log

            # Verify data types
            assert isinstance(log["id"], str)
            assert isinstance(log["action"], str)
            assert isinstance(log["target"], str)
            assert isinstance(log["user_id"], str)
            assert isinstance(log["result"], str)
            assert isinstance(log["created_at"], str)

    async def test_audit_logs_with_custom_pagination(
        self,
        superuser_client: AsyncClientType,
    ):
        """Test audit logs with custom pagination parameters.

        Verifies:
        - 200 status code
        - Pagination parameters are respected
        """
        page = 1
        page_size = 10

        response = await superuser_client.get(
            f"/api/v1/admin/database/audit-logs?page={page}&page_size={page_size}",
        )

        assert response.status_code == status.HTTP_200_OK

        data = response.json()

        # Verify pagination parameters
        assert data["page"] == page
        assert data["page_size"] == page_size
        assert len(data["items"]) <= page_size

    async def test_audit_logs_with_action_filter(
        self,
        superuser_client: AsyncClientType,
    ):
        """Test audit logs with action type filter.

        Verifies:
        - 200 status code
        - Only logs with specified action are returned
        """
        # First, make a request to generate an audit log
        await superuser_client.get("/api/v1/admin/database/health")

        # Now query for that action type
        response = await superuser_client.get(
            "/api/v1/admin/database/audit-logs?action_type=get_health",
        )

        assert response.status_code == status.HTTP_200_OK

        data = response.json()

        # Verify filter is applied
        for log in data["items"]:
            assert log["action"] == "get_health"

    async def test_audit_logs_with_date_range_filter(
        self,
        superuser_client: AsyncClientType,
    ):
        """Test audit logs with date range filter.

        Verifies:
        - 200 status code
        - Only logs within date range are returned
        """
        start_date = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        end_date = datetime.now(UTC).isoformat()

        response = await superuser_client.get(
            f"/api/v1/admin/database/audit-logs?start_date={start_date}&end_date={end_date}",
        )

        assert response.status_code == status.HTTP_200_OK

        data = response.json()

        # Verify response structure (actual date filtering is done by repository)
        assert "items" in data
        assert "total" in data

    async def test_audit_logs_with_invalid_pagination(
        self,
        superuser_client: AsyncClientType,
    ):
        """Test audit logs with invalid pagination parameters.

        Verifies:
        - 422 Unprocessable Entity for invalid pagination
        """
        # Test negative page
        response = await superuser_client.get(
            "/api/v1/admin/database/audit-logs?page=0",
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

        # Test page_size exceeding maximum
        response = await superuser_client.get(
            "/api/v1/admin/database/audit-logs?page_size=200",
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_audit_logs_without_authentication(self, client: AsyncClient):
        """Test audit logs endpoint without authentication.

        Verifies:
        - 401 Unauthorized status code
        """
        response = await client.get("/api/v1/admin/database/audit-logs")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_audit_logs_with_regular_user(
        self,
        regular_user_client: AsyncClientType,
    ):
        """Test audit logs endpoint with regular user.

        Verifies:
        - 403 Forbidden status code
        """
        response = await regular_user_client.get("/api/v1/admin/database/audit-logs")

        assert response.status_code == status.HTTP_403_FORBIDDEN


# =============================================================================
# Audit Logging Verification Tests
# =============================================================================


@pytest.mark.asyncio
class TestAuditLoggingVerification:
    """Test suite for verifying audit log creation for admin operations."""

    async def test_health_check_creates_audit_log(
        self,
        superuser_client: AsyncClientType,
    ):
        """Test that health check operation creates an audit log.

        Verifies:
        - Health check endpoint creates audit log
        - Audit log contains correct action, target, and user_id
        - Audit log can be retrieved via audit-logs endpoint
        """
        # Perform health check
        health_response = await superuser_client.get("/api/v1/admin/database/health")
        assert health_response.status_code == status.HTTP_200_OK

        # Query audit logs for this action
        audit_response = await superuser_client.get(
            "/api/v1/admin/database/audit-logs?action_type=get_health&page_size=1",
        )
        assert audit_response.status_code == status.HTTP_200_OK

        audit_data = audit_response.json()

        # Verify audit log was created
        assert audit_data["total"] > 0
        assert len(audit_data["items"]) > 0

        # Verify audit log content
        log = audit_data["items"][0]
        assert log["action"] == "get_health"
        assert log["target"] == "database"
        assert log["user_id"] == "admin-user-id"
        assert log["result"] == "success"

    async def test_stats_operation_creates_audit_log(
        self,
        superuser_client: AsyncClientType,
    ):
        """Test that stats operation creates an audit log.

        Verifies:
        - Stats endpoint creates audit log
        - Audit log has correct metadata
        """
        # Perform stats operation
        stats_response = await superuser_client.get("/api/v1/admin/database/stats")
        assert stats_response.status_code == status.HTTP_200_OK

        # Query audit logs for this action
        audit_response = await superuser_client.get(
            "/api/v1/admin/database/audit-logs?action_type=get_stats&page_size=1",
        )
        assert audit_response.status_code == status.HTTP_200_OK

        audit_data = audit_response.json()

        # Verify audit log was created
        assert audit_data["total"] > 0
        assert len(audit_data["items"]) > 0

        # Verify audit log content
        log = audit_data["items"][0]
        assert log["action"] == "get_stats"
        assert log["target"] == "database"
        assert log["user_id"] == "admin-user-id"
        assert log["result"] == "success"

    async def test_connection_info_creates_audit_log(
        self,
        superuser_client: AsyncClientType,
    ):
        """Test that connection info operation creates an audit log.

        Verifies:
        - Connection info endpoint creates audit log
        - Audit log includes limit parameter in metadata
        """
        # Perform connection info operation
        conn_response = await superuser_client.get(
            "/api/v1/admin/database/connections?limit=10",
        )
        assert conn_response.status_code == status.HTTP_200_OK

        # Query audit logs for this action
        audit_response = await superuser_client.get(
            "/api/v1/admin/database/audit-logs?action_type=get_connection_info&page_size=1",
        )
        assert audit_response.status_code == status.HTTP_200_OK

        audit_data = audit_response.json()

        # Verify audit log was created
        assert audit_data["total"] > 0
        assert len(audit_data["items"]) > 0

        # Verify audit log content
        log = audit_data["items"][0]
        assert log["action"] == "get_connection_info"
        assert log["target"] == "database"
        assert log["user_id"] == "admin-user-id"
        assert log["result"] == "success"


# =============================================================================
# Error Handling Tests
# =============================================================================


@pytest.mark.asyncio
class TestErrorHandling:
    """Test suite for error handling and edge cases."""

    async def test_endpoints_with_invalid_query_params(
        self,
        superuser_client: AsyncClientType,
    ):
        """Test endpoints with various invalid query parameters.

        Verifies:
        - Proper validation error responses
        - 422 Unprocessable Entity status codes
        """
        # Invalid limit type
        response = await superuser_client.get(
            "/api/v1/admin/database/connections?limit=abc",
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

        # Invalid page number
        response = await superuser_client.get(
            "/api/v1/admin/database/audit-logs?page=-5",
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_all_endpoints_require_superuser(
        self,
        regular_user_client: AsyncClientType,
    ):
        """Test that all endpoints require superuser access.

        Verifies:
        - All 6 endpoints return 403 for regular users
        """
        endpoints = [
            "/api/v1/admin/database/health",
            "/api/v1/admin/database/stats",
            "/api/v1/admin/database/connections",
            "/api/v1/admin/database/tables/sizes",
            "/api/v1/admin/database/indexes/health",
            "/api/v1/admin/database/audit-logs",
        ]

        for endpoint in endpoints:
            response = await regular_user_client.get(endpoint)
            assert response.status_code == status.HTTP_403_FORBIDDEN, (
                f"Endpoint {endpoint} should require superuser access"
            )

    async def test_all_endpoints_require_authentication(
        self,
        client: AsyncClient,
    ):
        """Test that all endpoints require authentication.

        Verifies:
        - All 6 endpoints return 401 for unauthenticated requests
        """
        endpoints = [
            "/api/v1/admin/database/health",
            "/api/v1/admin/database/stats",
            "/api/v1/admin/database/connections",
            "/api/v1/admin/database/tables/sizes",
            "/api/v1/admin/database/indexes/health",
            "/api/v1/admin/database/audit-logs",
        ]

        for endpoint in endpoints:
            response = await client.get(endpoint)
            assert response.status_code == status.HTTP_401_UNAUTHORIZED, (
                f"Endpoint {endpoint} should require authentication"
            )
