"""Unit tests for database administration utility functions.

This module tests all utility functions in admin_utils.py including:
- Byte formatting
- Token generation and verification
- Name validation
- Query sanitization
- Cache hit ratio calculation
- Connection limit checking
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text

from example_service.core.database.admin_utils import (
    DEFAULT_CONFIRMATION_SALT,
    calculate_cache_hit_ratio,
    check_connection_limit,
    format_bytes,
    generate_confirmation_token,
    sanitize_query_text,
    validate_index_name,
    validate_table_name,
    verify_confirmation_token,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# =============================================================================
# format_bytes() Tests
# =============================================================================


class TestFormatBytes:
    """Tests for format_bytes function."""

    def test_format_bytes_zero(self) -> None:
        """Test formatting zero bytes."""
        assert format_bytes(0) == "0 B"

    def test_format_bytes_negative_raises_error(self) -> None:
        """Test that negative values raise ValueError."""
        with pytest.raises(ValueError, match="cannot be negative"):
            format_bytes(-1)

    def test_format_bytes_under_1024(self) -> None:
        """Test formatting values under 1 KiB."""
        assert format_bytes(1) == "1 B"
        assert format_bytes(512) == "512 B"
        assert format_bytes(1023) == "1023 B"

    def test_format_bytes_exactly_1024(self) -> None:
        """Test formatting exactly 1 KiB."""
        assert format_bytes(1024) == "1.00 KiB"

    def test_format_bytes_kibibytes(self) -> None:
        """Test formatting values in KiB range."""
        assert format_bytes(1536) == "1.50 KiB"  # 1.5 KiB
        assert format_bytes(2048) == "2.00 KiB"  # 2 KiB
        assert format_bytes(10240) == "10.00 KiB"  # 10 KiB

    def test_format_bytes_mebibytes(self) -> None:
        """Test formatting values in MiB range."""
        assert format_bytes(1048576) == "1.00 MiB"  # 1 MiB
        assert format_bytes(1572864) == "1.50 MiB"  # 1.5 MiB
        assert format_bytes(10485760) == "10.00 MiB"  # 10 MiB

    def test_format_bytes_gibibytes(self) -> None:
        """Test formatting values in GiB range."""
        assert format_bytes(1073741824) == "1.00 GiB"  # 1 GiB
        assert format_bytes(2684354560) == "2.50 GiB"  # 2.5 GiB
        assert format_bytes(5368709120) == "5.00 GiB"  # 5 GiB

    def test_format_bytes_tebibytes(self) -> None:
        """Test formatting values in TiB range."""
        assert format_bytes(1099511627776) == "1.00 TiB"  # 1 TiB
        assert format_bytes(2199023255552) == "2.00 TiB"  # 2 TiB

    def test_format_bytes_pebibytes(self) -> None:
        """Test formatting values in PiB range."""
        assert format_bytes(1125899906842624) == "1.00 PiB"  # 1 PiB

    def test_format_bytes_large_value(self) -> None:
        """Test formatting very large values."""
        # Should cap at PiB and not exceed
        assert format_bytes(1125899906842624 * 10) == "10.00 PiB"


# =============================================================================
# Token Generation/Verification Tests
# =============================================================================


class TestTokenGeneration:
    """Tests for confirmation token generation."""

    def test_generate_confirmation_token_returns_8_chars(self) -> None:
        """Test that generated token is exactly 8 characters."""
        token = generate_confirmation_token("vacuum", "users")
        assert len(token) == 8
        assert token.isalnum()  # Should be hexadecimal

    def test_generate_confirmation_token_deterministic_within_minute(self) -> None:
        """Test that same operation/target generates same token within a minute."""
        token1 = generate_confirmation_token("vacuum", "users")
        token2 = generate_confirmation_token("vacuum", "users")
        assert token1 == token2

    def test_generate_confirmation_token_different_operations(self) -> None:
        """Test that different operations generate different tokens."""
        token1 = generate_confirmation_token("vacuum", "users")
        token2 = generate_confirmation_token("reindex", "users")
        assert token1 != token2

    def test_generate_confirmation_token_different_targets(self) -> None:
        """Test that different targets generate different tokens."""
        token1 = generate_confirmation_token("vacuum", "users")
        token2 = generate_confirmation_token("vacuum", "posts")
        assert token1 != token2

    def test_generate_confirmation_token_custom_salt(self) -> None:
        """Test that custom salt affects token generation."""
        token1 = generate_confirmation_token("vacuum", "users", secret_salt="salt1")
        token2 = generate_confirmation_token("vacuum", "users", secret_salt="salt2")
        assert token1 != token2


class TestTokenVerification:
    """Tests for confirmation token verification."""

    def test_verify_confirmation_token_valid(self) -> None:
        """Test verifying a valid token."""
        token = generate_confirmation_token("vacuum", "users")
        assert verify_confirmation_token(token, "vacuum", "users") is True

    def test_verify_confirmation_token_wrong_operation(self) -> None:
        """Test verifying token with wrong operation fails."""
        token = generate_confirmation_token("vacuum", "users")
        assert verify_confirmation_token(token, "reindex", "users") is False

    def test_verify_confirmation_token_wrong_target(self) -> None:
        """Test verifying token with wrong target fails."""
        token = generate_confirmation_token("vacuum", "users")
        assert verify_confirmation_token(token, "vacuum", "posts") is False

    def test_verify_confirmation_token_invalid_format(self) -> None:
        """Test verifying invalid token format."""
        assert verify_confirmation_token("invalid", "vacuum", "users") is False
        assert verify_confirmation_token("", "vacuum", "users") is False
        assert verify_confirmation_token("too_long_token", "vacuum", "users") is False

    def test_verify_confirmation_token_none(self) -> None:
        """Test verifying None token."""
        assert verify_confirmation_token(None, "vacuum", "users") is False  # type: ignore[arg-type]

    def test_verify_confirmation_token_custom_salt(self) -> None:
        """Test verifying token with custom salt."""
        token = generate_confirmation_token("vacuum", "users", secret_salt="custom")
        assert verify_confirmation_token(
            token,
            "vacuum",
            "users",
            secret_salt="custom",
        ) is True
        # Wrong salt should fail
        assert verify_confirmation_token(token, "vacuum", "users") is False

    @patch("example_service.core.database.admin_utils.time.time")
    def test_verify_confirmation_token_tolerance(self, mock_time: MagicMock) -> None:
        """Test token tolerance window."""
        # Generate token at time 0
        mock_time.return_value = 0
        token = generate_confirmation_token("vacuum", "users")

        # Verify within tolerance (2 minutes = 120 seconds)
        mock_time.return_value = 60  # 1 minute later
        assert verify_confirmation_token(token, "vacuum", "users") is True

        mock_time.return_value = 120  # 2 minutes later
        assert verify_confirmation_token(token, "vacuum", "users") is True

        # Beyond tolerance should fail
        mock_time.return_value = 180  # 3 minutes later
        assert verify_confirmation_token(token, "vacuum", "users") is False


# =============================================================================
# Name Validation Tests
# =============================================================================


class TestValidateTableName:
    """Tests for table name validation."""

    def test_validate_table_name_valid(self) -> None:
        """Test validating allowed table names."""
        allowed = {"users", "posts", "comments"}
        assert validate_table_name("users", allowed) is True
        assert validate_table_name("posts", allowed) is True
        assert validate_table_name("comments", allowed) is True

    def test_validate_table_name_not_in_whitelist(self) -> None:
        """Test rejecting table names not in whitelist."""
        allowed = {"users", "posts"}
        assert validate_table_name("comments", allowed) is False
        assert validate_table_name("admin", allowed) is False

    def test_validate_table_name_empty(self) -> None:
        """Test rejecting empty table names."""
        allowed = {"users"}
        assert validate_table_name("", allowed) is False

    def test_validate_table_name_none(self) -> None:
        """Test rejecting None table names."""
        allowed = {"users"}
        assert validate_table_name(None, allowed) is False  # type: ignore[arg-type]

    def test_validate_table_name_not_string(self) -> None:
        """Test rejecting non-string table names."""
        allowed = {"users"}
        assert validate_table_name(123, allowed) is False  # type: ignore[arg-type]

    def test_validate_table_name_sql_injection_attempts(self) -> None:
        """Test rejecting SQL injection attempts."""
        allowed = {"users; DROP TABLE users;"}
        # Even if in whitelist, special characters should be rejected
        assert validate_table_name("users; DROP TABLE users;", allowed) is False

    def test_validate_table_name_special_characters(self) -> None:
        """Test rejecting names with special characters."""
        allowed = {"users@admin", "users#1", "users'"}
        assert validate_table_name("users@admin", allowed) is False
        assert validate_table_name("users#1", allowed) is False
        assert validate_table_name("users'", allowed) is False

    def test_validate_table_name_with_underscore(self) -> None:
        """Test accepting names with underscores."""
        allowed = {"user_profiles", "post_comments"}
        assert validate_table_name("user_profiles", allowed) is True
        assert validate_table_name("post_comments", allowed) is True

    def test_validate_table_name_with_hyphen(self) -> None:
        """Test accepting names with hyphens."""
        allowed = {"user-profiles"}
        assert validate_table_name("user-profiles", allowed) is True

    def test_validate_table_name_case_sensitive(self) -> None:
        """Test that validation is case-sensitive."""
        allowed = {"users"}
        assert validate_table_name("USERS", allowed) is False
        assert validate_table_name("Users", allowed) is False


class TestValidateIndexName:
    """Tests for index name validation."""

    def test_validate_index_name_valid(self) -> None:
        """Test validating allowed index names."""
        allowed = {"ix_users_email", "ix_posts_created"}
        assert validate_index_name("ix_users_email", allowed) is True
        assert validate_index_name("ix_posts_created", allowed) is True

    def test_validate_index_name_not_in_whitelist(self) -> None:
        """Test rejecting index names not in whitelist."""
        allowed = {"ix_users_email"}
        assert validate_index_name("ix_users_name", allowed) is False

    def test_validate_index_name_empty(self) -> None:
        """Test rejecting empty index names."""
        allowed = {"ix_users_email"}
        assert validate_index_name("", allowed) is False

    def test_validate_index_name_sql_injection_attempts(self) -> None:
        """Test rejecting SQL injection attempts."""
        allowed = {"ix_users; DROP INDEX;"}
        assert validate_index_name("ix_users; DROP INDEX;", allowed) is False

    def test_validate_index_name_with_underscore_and_hyphen(self) -> None:
        """Test accepting names with underscores and hyphens."""
        allowed = {"idx_user_email-v2"}
        assert validate_index_name("idx_user_email-v2", allowed) is True


# =============================================================================
# Query Sanitization Tests
# =============================================================================


class TestSanitizeQueryText:
    """Tests for SQL query sanitization."""

    def test_sanitize_query_text_empty(self) -> None:
        """Test sanitizing empty query."""
        assert sanitize_query_text("") == ""

    def test_sanitize_query_text_none(self) -> None:
        """Test sanitizing None query."""
        assert sanitize_query_text(None) == ""  # type: ignore[arg-type]

    def test_sanitize_query_text_simple(self) -> None:
        """Test sanitizing simple query."""
        query = "SELECT * FROM users WHERE id = 1"
        assert sanitize_query_text(query) == query

    def test_sanitize_query_text_normalizes_whitespace(self) -> None:
        """Test that multiple spaces and newlines are normalized."""
        query = "SELECT  *\n  FROM   users\n\nWHERE  id = 1"
        expected = "SELECT * FROM users WHERE id = 1"
        assert sanitize_query_text(query) == expected

    def test_sanitize_query_text_redacts_password(self) -> None:
        """Test that password values are redacted."""
        query = "UPDATE users SET password = 'secret123' WHERE id = 1"
        result = sanitize_query_text(query)
        assert "[REDACTED]" in result
        assert "secret123" not in result

    def test_sanitize_query_text_redacts_password_case_insensitive(self) -> None:
        """Test password redaction is case-insensitive."""
        queries = [
            "UPDATE users SET PASSWORD = 'secret' WHERE id = 1",
            "UPDATE users SET Password = 'secret' WHERE id = 1",
            "UPDATE users SET password = 'secret' WHERE id = 1",
        ]
        for query in queries:
            result = sanitize_query_text(query)
            assert "[REDACTED]" in result
            assert "secret" not in result

    def test_sanitize_query_text_redacts_secret(self) -> None:
        """Test that secret values are redacted."""
        query = "UPDATE config SET secret = 'my_secret' WHERE id = 1"
        result = sanitize_query_text(query)
        assert "[REDACTED]" in result
        assert "my_secret" not in result

    def test_sanitize_query_text_redacts_api_key(self) -> None:
        """Test that api_key values are redacted."""
        query = "UPDATE config SET api_key = 'sk-12345' WHERE id = 1"
        result = sanitize_query_text(query)
        assert "[REDACTED]" in result
        assert "sk-12345" not in result

    def test_sanitize_query_text_redacts_token(self) -> None:
        """Test that token values are redacted."""
        query = "UPDATE sessions SET token = 'abc123' WHERE id = 1"
        result = sanitize_query_text(query)
        assert "[REDACTED]" in result
        assert "abc123" not in result

    def test_sanitize_query_text_truncates_long_queries(self) -> None:
        """Test that long queries are truncated."""
        long_query = "SELECT " + ", ".join([f"col{i}" for i in range(200)])
        result = sanitize_query_text(long_query, max_length=100)
        assert len(result) <= 103  # 100 + "..."
        assert result.endswith("...")

    def test_sanitize_query_text_default_max_length(self) -> None:
        """Test default max_length of 500."""
        long_query = "SELECT " + "x" * 600
        result = sanitize_query_text(long_query)
        assert len(result) <= 503  # 500 + "..."
        assert result.endswith("...")

    def test_sanitize_query_text_preserves_short_queries(self) -> None:
        """Test that short queries are not truncated."""
        query = "SELECT * FROM users"
        result = sanitize_query_text(query, max_length=100)
        assert result == query
        assert not result.endswith("...")


# =============================================================================
# Cache Hit Ratio Tests
# =============================================================================


class TestCalculateCacheHitRatio:
    """Tests for cache hit ratio calculation."""

    @pytest.mark.asyncio
    async def test_calculate_cache_hit_ratio_healthy(self) -> None:
        """Test calculating healthy cache hit ratio."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_row.hits = 95000
        mock_row.reads = 5000
        mock_result.fetchone.return_value = mock_row
        mock_session.execute.return_value = mock_result

        ratio, is_healthy = await calculate_cache_hit_ratio(mock_session)

        assert ratio == 95.0  # 95000 / (95000 + 5000) * 100
        assert is_healthy is True

    @pytest.mark.asyncio
    async def test_calculate_cache_hit_ratio_unhealthy(self) -> None:
        """Test calculating unhealthy cache hit ratio."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_row.hits = 80000
        mock_row.reads = 20000
        mock_result.fetchone.return_value = mock_row
        mock_session.execute.return_value = mock_result

        ratio, is_healthy = await calculate_cache_hit_ratio(mock_session)

        assert ratio == 80.0  # Below 85% threshold
        assert is_healthy is False

    @pytest.mark.asyncio
    async def test_calculate_cache_hit_ratio_threshold_exact(self) -> None:
        """Test cache hit ratio exactly at threshold."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_row.hits = 85000
        mock_row.reads = 15000
        mock_result.fetchone.return_value = mock_row
        mock_session.execute.return_value = mock_result

        ratio, is_healthy = await calculate_cache_hit_ratio(mock_session)

        assert ratio == 85.0
        assert is_healthy is True  # >= 85%

    @pytest.mark.asyncio
    async def test_calculate_cache_hit_ratio_no_data(self) -> None:
        """Test when no cache statistics are available."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_session.execute.return_value = mock_result

        ratio, is_healthy = await calculate_cache_hit_ratio(mock_session)

        assert ratio == 0.0
        assert is_healthy is False

    @pytest.mark.asyncio
    async def test_calculate_cache_hit_ratio_null_values(self) -> None:
        """Test when cache statistics contain null values."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_row.hits = None
        mock_row.reads = None
        mock_result.fetchone.return_value = mock_row
        mock_session.execute.return_value = mock_result

        ratio, is_healthy = await calculate_cache_hit_ratio(mock_session)

        assert ratio == 0.0
        assert is_healthy is False

    @pytest.mark.asyncio
    async def test_calculate_cache_hit_ratio_zero_accesses(self) -> None:
        """Test when there have been zero cache accesses."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_row.hits = 0
        mock_row.reads = 0
        mock_result.fetchone.return_value = mock_row
        mock_session.execute.return_value = mock_result

        ratio, is_healthy = await calculate_cache_hit_ratio(mock_session)

        assert ratio == 0.0
        assert is_healthy is False

    @pytest.mark.asyncio
    async def test_calculate_cache_hit_ratio_perfect(self) -> None:
        """Test perfect 100% cache hit ratio."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_row.hits = 100000
        mock_row.reads = 0
        mock_result.fetchone.return_value = mock_row
        mock_session.execute.return_value = mock_result

        ratio, is_healthy = await calculate_cache_hit_ratio(mock_session)

        assert ratio == 100.0
        assert is_healthy is True


# =============================================================================
# Connection Limit Tests
# =============================================================================


class TestCheckConnectionLimit:
    """Tests for connection limit checking."""

    @pytest.mark.asyncio
    async def test_check_connection_limit_healthy(self) -> None:
        """Test checking healthy connection usage."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_row.current_connections = 45
        mock_row.max_connections = 100
        mock_result.fetchone.return_value = mock_row
        mock_session.execute.return_value = mock_result

        is_critical, message = await check_connection_limit(mock_session)

        assert is_critical is False
        assert "45/100" in message
        assert "45.0%" in message
        assert "Healthy" in message

    @pytest.mark.asyncio
    async def test_check_connection_limit_critical(self) -> None:
        """Test checking critical connection usage."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_row.current_connections = 95
        mock_row.max_connections = 100
        mock_result.fetchone.return_value = mock_row
        mock_session.execute.return_value = mock_result

        is_critical, message = await check_connection_limit(mock_session)

        assert is_critical is True
        assert "95/100" in message
        assert "95.0%" in message
        assert "CRITICAL" in message

    @pytest.mark.asyncio
    async def test_check_connection_limit_at_threshold(self) -> None:
        """Test checking at exact threshold (90%)."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_row.current_connections = 90
        mock_row.max_connections = 100
        mock_result.fetchone.return_value = mock_row
        mock_session.execute.return_value = mock_result

        is_critical, message = await check_connection_limit(mock_session)

        assert is_critical is True  # >= 90%
        assert "90/100" in message

    @pytest.mark.asyncio
    async def test_check_connection_limit_custom_threshold(self) -> None:
        """Test checking with custom threshold."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_row.current_connections = 80
        mock_row.max_connections = 100
        mock_result.fetchone.return_value = mock_row
        mock_session.execute.return_value = mock_result

        is_critical, message = await check_connection_limit(
            mock_session,
            critical_threshold=75.0,
        )

        assert is_critical is True  # 80% >= 75%
        assert "80/100" in message

    @pytest.mark.asyncio
    async def test_check_connection_limit_no_data(self) -> None:
        """Test when no connection data is available."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_session.execute.return_value = mock_result

        is_critical, message = await check_connection_limit(mock_session)

        assert is_critical is False
        assert "Unable to retrieve" in message

    @pytest.mark.asyncio
    async def test_check_connection_limit_invalid_max(self) -> None:
        """Test when max_connections is 0 or invalid."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_row.current_connections = 50
        mock_row.max_connections = 0
        mock_result.fetchone.return_value = mock_row
        mock_session.execute.return_value = mock_result

        is_critical, message = await check_connection_limit(mock_session)

        assert is_critical is False
        assert "Invalid max_connections" in message

    @pytest.mark.asyncio
    async def test_check_connection_limit_zero_current(self) -> None:
        """Test when current connections is zero."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_row.current_connections = 0
        mock_row.max_connections = 100
        mock_result.fetchone.return_value = mock_row
        mock_session.execute.return_value = mock_result

        is_critical, message = await check_connection_limit(mock_session)

        assert is_critical is False
        assert "0/100" in message
        assert "0.0%" in message


__all__ = [
    "TestCalculateCacheHitRatio",
    "TestCheckConnectionLimit",
    "TestFormatBytes",
    "TestSanitizeQueryText",
    "TestTokenGeneration",
    "TestTokenVerification",
    "TestValidateIndexName",
    "TestValidateTableName",
]
