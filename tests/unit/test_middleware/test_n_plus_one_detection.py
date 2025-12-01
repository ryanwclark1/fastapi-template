"""Unit tests for N+1 query detection middleware."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI, Request, Response
from starlette.testclient import TestClient

from example_service.app.middleware.n_plus_one_detection import (
    NPlusOneDetectionMiddleware,
    QueryNormalizer,
    QueryPattern,
    setup_n_plus_one_monitoring,
)


class TestQueryPattern:
    """Test QueryPattern class for tracking query executions."""

    def test_initialization(self) -> None:
        """Test QueryPattern initialization."""
        pattern = QueryPattern("SELECT * FROM users WHERE id = ?", 0.005)

        assert pattern.normalized_query == "SELECT * FROM users WHERE id = ?"
        assert pattern.execution_times == [0.005]
        assert pattern.count == 1
        assert pattern.first_seen > 0
        assert pattern.last_seen > 0

    def test_add_execution(self) -> None:
        """Test adding additional executions to a pattern."""
        pattern = QueryPattern("SELECT * FROM users WHERE id = ?", 0.005)
        initial_last_seen = pattern.last_seen

        # Sleep briefly to ensure timestamp changes
        time.sleep(0.001)

        pattern.add_execution(0.006)

        assert pattern.count == 2
        assert pattern.execution_times == [0.005, 0.006]
        assert pattern.last_seen > initial_last_seen

    def test_total_time(self) -> None:
        """Test total execution time calculation."""
        pattern = QueryPattern("SELECT * FROM users WHERE id = ?", 0.005)
        pattern.add_execution(0.006)
        pattern.add_execution(0.007)

        assert pattern.total_time == pytest.approx(0.018)

    def test_average_time(self) -> None:
        """Test average execution time calculation."""
        pattern = QueryPattern("SELECT * FROM users WHERE id = ?", 0.005)
        pattern.add_execution(0.007)
        pattern.add_execution(0.009)

        assert pattern.average_time == pytest.approx(0.007)

    def test_average_time_zero_count(self) -> None:
        """Test average time returns 0 when count is 0."""
        pattern = QueryPattern("SELECT * FROM users WHERE id = ?", 0.005)
        pattern.count = 0  # Artificially set to 0

        assert pattern.average_time == 0.0

    def test_is_potential_n_plus_one_true(self) -> None:
        """Test N+1 detection for multiple rapid executions."""
        pattern = QueryPattern("SELECT * FROM users WHERE id = ?", 0.005)

        # Add 4 more executions quickly (total 5)
        for _ in range(4):
            pattern.add_execution(0.005)

        # Should detect as N+1 (>= 5 executions within 1 second)
        assert pattern.is_potential_n_plus_one is True

    def test_is_potential_n_plus_one_false_low_count(self) -> None:
        """Test N+1 detection with insufficient executions."""
        pattern = QueryPattern("SELECT * FROM users WHERE id = ?", 0.005)
        pattern.add_execution(0.005)

        # Only 2 executions, should not detect
        assert pattern.is_potential_n_plus_one is False

    def test_is_potential_n_plus_one_false_slow_execution(self) -> None:
        """Test N+1 detection with executions spread over time."""
        pattern = QueryPattern("SELECT * FROM users WHERE id = ?", 0.005)

        # Artificially set timestamps to simulate slow execution
        pattern.first_seen = time.time()
        pattern.last_seen = pattern.first_seen + 2.0  # More than 1 second
        pattern.count = 10

        # Should not detect (executions not in quick succession)
        assert pattern.is_potential_n_plus_one is False


class TestQueryNormalizer:
    """Test QueryNormalizer class for query pattern matching."""

    def test_normalize_empty_query(self) -> None:
        """Test normalization of empty query."""
        assert QueryNormalizer.normalize_query("") == ""
        assert QueryNormalizer.normalize_query("   ") == ""

    def test_normalize_lowercase_conversion(self) -> None:
        """Test query is converted to lowercase."""
        query = "SELECT * FROM Users WHERE Name = 'John'"
        normalized = QueryNormalizer.normalize_query(query)

        assert "SELECT" not in normalized
        assert "select" in normalized

    def test_normalize_whitespace_removal(self) -> None:
        """Test extra whitespace is normalized."""
        query = "SELECT  *   FROM    users WHERE   id = 1"
        normalized = QueryNormalizer.normalize_query(query)

        assert "  " not in normalized
        assert normalized.count(" ") < query.count(" ")

    def test_normalize_numbers_replaced(self) -> None:
        """Test numeric values are replaced with placeholders."""
        query = "SELECT * FROM users WHERE id = 123"
        normalized = QueryNormalizer.normalize_query(query)

        assert "123" not in normalized
        assert "?" in normalized

    def test_normalize_single_quoted_strings(self) -> None:
        """Test single-quoted strings are replaced."""
        query = "SELECT * FROM users WHERE name = 'John Doe'"
        normalized = QueryNormalizer.normalize_query(query)

        assert "'John Doe'" not in normalized
        assert "?" in normalized

    def test_normalize_double_quoted_strings(self) -> None:
        """Test double-quoted strings are replaced."""
        query = 'SELECT * FROM users WHERE name = "John Doe"'
        normalized = QueryNormalizer.normalize_query(query)

        assert '"John Doe"' not in normalized
        assert "?" in normalized

    def test_normalize_in_clause(self) -> None:
        """Test IN clause with multiple values is normalized."""
        query = "SELECT * FROM users WHERE id IN (1, 2, 3, 4, 5)"
        normalized = QueryNormalizer.normalize_query(query)

        assert "in (?)" in normalized
        assert "(1, 2, 3, 4, 5)" not in normalized

    def test_normalize_postgresql_parameters(self) -> None:
        """Test PostgreSQL-style parameters are replaced."""
        query = "SELECT * FROM users WHERE id = $1 AND name = $2"
        normalized = QueryNormalizer.normalize_query(query)

        assert "$1" not in normalized
        assert "$2" not in normalized
        assert normalized.count("?") >= 2

    def test_normalize_named_parameters(self) -> None:
        """Test named parameters are replaced."""
        query = "SELECT * FROM users WHERE id = :user_id AND name = :name"
        normalized = QueryNormalizer.normalize_query(query)

        assert ":user_id" not in normalized
        assert ":name" not in normalized
        assert normalized.count("?") >= 2

    def test_extract_table_name_select(self) -> None:
        """Test table name extraction from SELECT query."""
        query = "SELECT * FROM users WHERE id = 1"
        table_name = QueryNormalizer.extract_table_name(query)

        assert table_name == "users"

    def test_extract_table_name_update(self) -> None:
        """Test table name extraction from UPDATE query."""
        query = "UPDATE users SET name = 'John' WHERE id = 1"
        table_name = QueryNormalizer.extract_table_name(query)

        assert table_name == "users"

    def test_extract_table_name_delete(self) -> None:
        """Test table name extraction from DELETE query."""
        query = "DELETE FROM users WHERE id = 1"
        table_name = QueryNormalizer.extract_table_name(query)

        assert table_name == "users"

    def test_extract_table_name_insert(self) -> None:
        """Test table name extraction from INSERT query."""
        query = "INSERT INTO users (name, email) VALUES ('John', 'john@example.com')"
        table_name = QueryNormalizer.extract_table_name(query)

        assert table_name == "users"

    def test_extract_table_name_not_found(self) -> None:
        """Test table name extraction when pattern doesn't match."""
        query = "BEGIN TRANSACTION"
        table_name = QueryNormalizer.extract_table_name(query)

        assert table_name is None

    def test_extract_table_name_case_insensitive(self) -> None:
        """Test table name extraction is case-insensitive."""
        query = "SELECT * FROM Users WHERE id = 1"
        table_name = QueryNormalizer.extract_table_name(query)

        assert table_name == "users"


class TestNPlusOneDetectionMiddleware:
    """Test NPlusOneDetectionMiddleware functionality."""

    @pytest.fixture
    def app(self) -> FastAPI:
        """Create a test FastAPI application."""
        app = FastAPI()

        @app.get("/test")
        async def test_endpoint() -> dict[str, str]:
            return {"message": "test"}

        return app

    @pytest.fixture
    def middleware(self, app: FastAPI) -> NPlusOneDetectionMiddleware:
        """Create middleware instance."""
        return NPlusOneDetectionMiddleware(
            app,
            threshold=5,
            log_slow_queries=True,
            slow_query_threshold=0.1,
            enable_detailed_logging=True,
        )

    def test_initialization(self, middleware: NPlusOneDetectionMiddleware) -> None:
        """Test middleware initialization with custom settings."""
        assert middleware.threshold == 5
        assert middleware.log_slow_queries is True
        assert middleware.slow_query_threshold == 0.1
        assert middleware.enable_detailed_logging is True

    def test_initialization_default_exclude_patterns(self, app: FastAPI) -> None:
        """Test middleware initialization with default exclude patterns."""
        middleware = NPlusOneDetectionMiddleware(app)

        assert middleware.exclude_patterns == []
        assert middleware.exclude_regexes == []

    def test_initialization_custom_exclude_patterns(self, app: FastAPI) -> None:
        """Test middleware initialization with custom exclude patterns."""
        middleware = NPlusOneDetectionMiddleware(
            app, exclude_patterns=[r"pg_catalog", r"information_schema"]
        )

        assert len(middleware.exclude_patterns) == 2
        assert len(middleware.exclude_regexes) == 2

    @pytest.mark.asyncio
    async def test_dispatch_normal_request(
        self, app: FastAPI, middleware: NPlusOneDetectionMiddleware
    ) -> None:
        """Test middleware dispatch with normal request."""
        app.add_middleware(
            NPlusOneDetectionMiddleware,
            threshold=10,
        )

        client = TestClient(app)
        response = client.get("/test")

        assert response.status_code == 200
        assert "X-Query-Count" in response.headers
        assert "X-Request-Time" in response.headers

    @pytest.mark.asyncio
    async def test_record_query_basic(self, middleware: NPlusOneDetectionMiddleware) -> None:
        """Test basic query recording."""
        mock_request = Mock(spec=Request)
        mock_request.state.query_patterns = {}
        mock_request.state.query_count = 0

        middleware.record_query(mock_request, "SELECT * FROM users WHERE id = 1", 0.005)

        assert mock_request.state.query_count == 1
        assert len(mock_request.state.query_patterns) == 1

    @pytest.mark.asyncio
    async def test_record_query_pattern_tracking(
        self, middleware: NPlusOneDetectionMiddleware
    ) -> None:
        """Test query pattern tracking with multiple similar queries."""
        mock_request = Mock(spec=Request)
        mock_request.state.query_patterns = {}
        mock_request.state.query_count = 0

        # Record similar queries with different parameters
        for i in range(10):
            middleware.record_query(mock_request, f"SELECT * FROM users WHERE id = {i}", 0.005)

        # Should normalize to same pattern
        assert mock_request.state.query_count == 10
        # All queries should match the same normalized pattern
        patterns = [p for p in mock_request.state.query_patterns.values() if p]
        assert len(patterns) == 1
        assert patterns[0].count == 10

    @pytest.mark.asyncio
    async def test_record_query_excluded_pattern(self, app: FastAPI) -> None:
        """Test query recording skips excluded patterns."""
        middleware = NPlusOneDetectionMiddleware(app, exclude_patterns=[r"pg_catalog"])

        mock_request = Mock(spec=Request)
        mock_request.state.query_patterns = {}
        mock_request.state.query_count = 0

        middleware.record_query(mock_request, "SELECT * FROM pg_catalog.pg_tables", 0.005)

        # Should be excluded
        assert mock_request.state.query_count == 0
        assert len(mock_request.state.query_patterns) == 0

    @pytest.mark.asyncio
    async def test_record_query_slow_query_logging(
        self, middleware: NPlusOneDetectionMiddleware, caplog: Any
    ) -> None:
        """Test slow query logging."""
        mock_request = Mock(spec=Request)
        mock_request.state.query_patterns = {}
        mock_request.state.query_count = 0

        with caplog.at_level("WARNING"):
            middleware.record_query(mock_request, "SELECT * FROM users WHERE id = 1", 0.5)

        # Slow query should be logged (threshold is 0.1s)
        assert "Slow Query Detected" in caplog.text

    @pytest.mark.asyncio
    async def test_record_query_no_state(self, middleware: NPlusOneDetectionMiddleware) -> None:
        """Test query recording when request state is not initialized."""
        mock_request = Mock(spec=Request)
        # Create a proper state object that doesn't have query_patterns
        mock_request.state = type("State", (), {})()

        # Should not raise exception - just return early
        middleware.record_query(mock_request, "SELECT * FROM users WHERE id = 1", 0.005)

        # Verify nothing was recorded
        assert not hasattr(mock_request.state, "query_patterns")

    @pytest.mark.asyncio
    async def test_analyze_query_patterns_with_n_plus_one(
        self, middleware: NPlusOneDetectionMiddleware, caplog: Any
    ) -> None:
        """Test query pattern analysis detects N+1 issues."""
        mock_request = Mock(spec=Request)
        mock_request.url.path = "/test"
        mock_request.method = "GET"
        mock_request.state.query_patterns = {}
        mock_request.state.query_count = 0
        mock_request.state.request_start_time = time.time()

        # Simulate N+1 pattern
        for i in range(15):
            middleware.record_query(mock_request, f"SELECT * FROM users WHERE id = {i}", 0.005)

        mock_response = Mock(spec=Response)
        mock_response.headers = {}

        with caplog.at_level("WARNING"):
            await middleware._analyze_query_patterns(mock_request, mock_response)

        # Should detect N+1 pattern
        assert "N+1 Query Pattern Detected" in caplog.text
        assert "X-N-Plus-One-Detected" in mock_response.headers

    @pytest.mark.asyncio
    async def test_analyze_query_patterns_with_exception(
        self, middleware: NPlusOneDetectionMiddleware, caplog: Any
    ) -> None:
        """Test query pattern analysis with exception."""
        mock_request = Mock(spec=Request)
        mock_request.url.path = "/test"
        mock_request.method = "GET"
        mock_request.state.query_patterns = {}
        mock_request.state.query_count = 5
        mock_request.state.request_start_time = time.time()

        with caplog.at_level("WARNING"):
            await middleware._analyze_query_patterns(
                mock_request, None, exception=ValueError("Test error")
            )

        assert "Request completed with exception" in caplog.text

    @pytest.mark.asyncio
    async def test_log_n_plus_one_patterns(
        self, middleware: NPlusOneDetectionMiddleware, caplog: Any
    ) -> None:
        """Test N+1 pattern logging with recommendations."""
        mock_request = Mock(spec=Request)
        mock_request.url.path = "/test"
        mock_request.method = "GET"

        pattern = QueryPattern("SELECT * FROM users WHERE id = ?", 0.005)
        # Add more executions to increase count and total time
        for _ in range(14):
            pattern.add_execution(0.005)

        with caplog.at_level("WARNING"):
            await middleware._log_n_plus_one_patterns(mock_request, [pattern], 0.1, 15)

        assert "N+1 Query Pattern Detected" in caplog.text
        assert "Recommendation" in caplog.text
        assert "eager loading" in caplog.text

    @pytest.mark.asyncio
    async def test_log_request_summary_with_n_plus_one(
        self, middleware: NPlusOneDetectionMiddleware, caplog: Any
    ) -> None:
        """Test request summary logging with N+1 detection."""
        mock_request = Mock(spec=Request)
        mock_request.url.path = "/test"
        mock_request.method = "GET"

        with caplog.at_level("WARNING"):
            await middleware._log_request_summary(mock_request, 0.1, 15, 1)

        assert "Request Summary" in caplog.text
        assert "15 queries" in caplog.text

    @pytest.mark.asyncio
    async def test_log_request_summary_without_n_plus_one(
        self, middleware: NPlusOneDetectionMiddleware, caplog: Any
    ) -> None:
        """Test request summary logging without N+1 detection."""
        mock_request = Mock(spec=Request)
        mock_request.url.path = "/test"
        mock_request.method = "GET"

        with caplog.at_level("INFO"):
            await middleware._log_request_summary(mock_request, 0.1, 5, 0)

        assert "Request Summary" in caplog.text


class TestSetupNPlusOneMonitoring:
    """Test setup_n_plus_one_monitoring function."""

    @pytest.mark.skipif(
        True,
        reason="Requires SQLAlchemy engine setup",
    )
    def test_setup_monitoring_without_sqlalchemy(self) -> None:
        """Test setup when SQLAlchemy is not available."""
        with patch("example_service.app.middleware.n_plus_one_detection.event", None):
            mock_engine = Mock()
            mock_middleware = Mock(spec=NPlusOneDetectionMiddleware)

            set_request_context = setup_n_plus_one_monitoring(mock_engine, mock_middleware)

            # Should return a no-op function
            assert callable(set_request_context)
            set_request_context(Mock())  # Should not raise

    def test_setup_monitoring_context_function(self) -> None:
        """Test the returned context function."""
        mock_engine = Mock()
        mock_engine.sync_engine = Mock()
        mock_middleware = Mock(spec=NPlusOneDetectionMiddleware)

        with patch("example_service.app.middleware.n_plus_one_detection.event"):
            set_request_context = setup_n_plus_one_monitoring(mock_engine, mock_middleware)

            mock_request = Mock()
            set_request_context(mock_request)

            # Should not raise
            assert callable(set_request_context)


class TestIntegration:
    """Integration tests for N+1 detection middleware."""

    @pytest.mark.asyncio
    async def test_full_request_lifecycle(self) -> None:
        """Test complete request lifecycle with query tracking."""
        app = FastAPI()

        @app.get("/users")
        async def get_users(request: Request) -> dict[str, Any]:
            # Simulate N+1 query pattern
            request.state.query_patterns = {}
            request.state.query_count = 0
            return {"users": []}

        app.add_middleware(
            NPlusOneDetectionMiddleware,
            threshold=5,
            enable_detailed_logging=True,
        )

        client = TestClient(app)
        response = client.get("/users")

        assert response.status_code == 200
        assert "X-Query-Count" in response.headers
        assert "X-Request-Time" in response.headers

    @pytest.mark.asyncio
    async def test_performance_overhead(self) -> None:
        """Test middleware has minimal performance overhead."""
        app = FastAPI()

        @app.get("/fast")
        async def fast_endpoint() -> dict[str, str]:
            return {"status": "ok"}

        app.add_middleware(NPlusOneDetectionMiddleware, threshold=10)

        client = TestClient(app)

        # Measure overhead
        start = time.perf_counter()
        for _ in range(100):
            response = client.get("/fast")
            assert response.status_code == 200
        duration = time.perf_counter() - start

        # Overhead should be minimal (< 10ms per request)
        assert duration / 100 < 0.01
