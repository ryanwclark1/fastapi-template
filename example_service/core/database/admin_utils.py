"""Database administration utility functions.

This module provides utilities for database maintenance and monitoring operations:
- Human-readable formatting (bytes, percentages)
- Security validation (table/index names, confirmation tokens)
- PostgreSQL statistics and health checks
- Query text sanitization

These functions are used by database admin features to perform safe,
auditable maintenance operations.

Example:
    from example_service.core.database.admin_utils import (
        format_bytes,
        generate_confirmation_token,
        verify_confirmation_token,
        calculate_cache_hit_ratio,
    )

    # Format storage sizes
    size = format_bytes(1536000)  # "1.5 MB"

    # Generate confirmation token for dangerous operations
    token = generate_confirmation_token("vacuum_full", "large_table")

    # Verify user provided correct token
    if verify_confirmation_token(token, "vacuum_full", "large_table"):
        # Proceed with operation
        pass

    # Check database health
    ratio, is_healthy = await calculate_cache_hit_ratio(session)
    if not is_healthy:
        print(f"Cache hit ratio is low: {ratio:.2f}%")
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# =============================================================================
# Formatting Functions
# =============================================================================


def format_bytes(bytes_value: int) -> str:
    """Convert bytes to human-readable format.

    Uses base-2 units (1 KiB = 1024 bytes) with proper IEC notation.
    Provides 2 decimal places for values >= 1 KB.

    Args:
        bytes_value: Size in bytes (integer)

    Returns:
        Human-readable string (e.g., "1.50 MiB", "512 B", "2.25 GiB")

    Example:
        >>> format_bytes(0)
        '0 B'
        >>> format_bytes(512)
        '512 B'
        >>> format_bytes(1024)
        '1.00 KiB'
        >>> format_bytes(1536)
        '1.50 KiB'
        >>> format_bytes(1048576)
        '1.00 MiB'
        >>> format_bytes(1572864000)
        '1.46 GiB'
        >>> format_bytes(1099511627776)
        '1.00 TiB'
    """
    if bytes_value < 0:
        msg = "Byte value cannot be negative"
        raise ValueError(msg)

    if bytes_value == 0:
        return "0 B"

    # Define size units (base-2, IEC standard)
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    unit_index = 0
    size = float(bytes_value)

    # Find appropriate unit
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1

    # Format with appropriate precision
    if unit_index == 0:
        # Bytes - no decimal places
        return f"{int(size)} {units[unit_index]}"

    # Larger units - 2 decimal places
    return f"{size:.2f} {units[unit_index]}"


# =============================================================================
# Security & Validation Functions
# =============================================================================


DEFAULT_CONFIRMATION_SALT = "db_admin_confirmation"


def generate_confirmation_token(
    operation: str,
    target: str,
    *,
    secret_salt: str = DEFAULT_CONFIRMATION_SALT,
) -> str:
    """Generate SHA256-based confirmation token for dangerous operations.

    Creates a deterministic but unpredictable token that users must provide
    to confirm they understand the operation they're about to perform.
    The token includes a timestamp to prevent replay attacks.

    Args:
        operation: Operation name (e.g., "vacuum_full", "drop_index")
        target: Target resource (e.g., table name, index name)
        secret_salt: Salt for token generation (default: "db_admin_confirmation")

    Returns:
        Hex-encoded SHA256 hash (8 characters)

    Example:
        >>> token = generate_confirmation_token("reindex", "users")
        >>> print(f"To confirm, provide token: {token}")
        To confirm, provide token: a1b2c3d4

    Security Notes:
        - Tokens are time-sensitive (2-minute window by default)
        - Tokens are operation and target specific
        - Not cryptographically secure for authentication, only confirmation
    """
    # Round timestamp to minute to allow for reasonable confirmation window
    timestamp_minute = int(time.time() / 60)

    # Create payload
    payload = f"{operation}:{target}:{timestamp_minute}:{secret_salt}"

    # Generate SHA256 hash
    hash_obj = hashlib.sha256(payload.encode("utf-8"))

    # Return first 8 characters of hex digest (32 bits of entropy)
    return hash_obj.hexdigest()[:8]


def verify_confirmation_token(
    token: str,
    operation: str,
    target: str,
    *,
    tolerance_minutes: int = 2,
    secret_salt: str = DEFAULT_CONFIRMATION_SALT,
) -> bool:
    """Verify confirmation token is valid and not expired.

    Checks if the provided token matches what would be generated for the
    given operation and target within the tolerance window.

    Args:
        token: Token provided by user
        operation: Operation name
        target: Target resource
        tolerance_minutes: How many minutes old token can be (default: 2)
        secret_salt: Salt used for token generation (must match generate_confirmation_token)

    Returns:
        True if token is valid and not expired, False otherwise

    Example:
        >>> token = generate_confirmation_token("vacuum", "posts")
        >>> verify_confirmation_token(token, "vacuum", "posts")
        True
        >>> verify_confirmation_token(token, "vacuum", "users")  # Wrong target
        False
        >>> verify_confirmation_token("invalid", "vacuum", "posts")
        False

    Security Notes:
        - Tokens expire after tolerance_minutes
        - Operation and target must match exactly
        - Case-sensitive comparison
    """
    if not token or len(token) != 8:
        return False

    current_minute = int(time.time() / 60)

    # Check token against current time and recent past
    for minutes_ago in range(tolerance_minutes + 1):
        check_minute = current_minute - minutes_ago

        # Generate expected token for this time window
        payload = f"{operation}:{target}:{check_minute}:{secret_salt}"
        hash_obj = hashlib.sha256(payload.encode("utf-8"))
        expected_token = hash_obj.hexdigest()[:8]

        if token == expected_token:
            return True

    return False


def validate_table_name(table_name: str, allowed_tables: set[str]) -> bool:
    """Validate table name against whitelist.

    Prevents SQL injection and ensures only approved tables can be operated on.
    Uses both whitelist checking and basic SQL injection pattern detection.

    Args:
        table_name: Table name to validate
        allowed_tables: Set of permitted table names

    Returns:
        True if table name is valid and allowed, False otherwise

    Example:
        >>> allowed = {"users", "posts", "comments"}
        >>> validate_table_name("users", allowed)
        True
        >>> validate_table_name("admin_users", allowed)
        False
        >>> validate_table_name("users; DROP TABLE users;", allowed)
        False

    Security Notes:
        - Only allows exact matches from whitelist
        - Rejects any SQL special characters
        - Case-sensitive comparison
    """
    if not table_name or not isinstance(table_name, str):
        return False

    # Check whitelist first
    if table_name not in allowed_tables:
        return False

    # Additional safety: ensure no SQL special characters
    # Valid table names: alphanumeric, underscore, hyphen
    if not re.match(r"^[a-zA-Z0-9_-]+$", table_name):
        logger.warning(
            "Table name contains invalid characters",
            extra={"table_name": table_name},
        )
        return False

    return True


def validate_index_name(index_name: str, allowed_indexes: set[str]) -> bool:
    """Validate index name against whitelist.

    Similar to validate_table_name but for index names. Prevents SQL injection
    and ensures only approved indexes can be operated on.

    Args:
        index_name: Index name to validate
        allowed_indexes: Set of permitted index names

    Returns:
        True if index name is valid and allowed, False otherwise

    Example:
        >>> allowed = {"ix_users_email", "ix_posts_created_at"}
        >>> validate_index_name("ix_users_email", allowed)
        True
        >>> validate_index_name("malicious_index", allowed)
        False
        >>> validate_index_name("ix_users_email; DROP INDEX;", allowed)
        False

    Security Notes:
        - Only allows exact matches from whitelist
        - Rejects any SQL special characters
        - Case-sensitive comparison
    """
    if not index_name or not isinstance(index_name, str):
        return False

    # Check whitelist first
    if index_name not in allowed_indexes:
        return False

    # Additional safety: ensure no SQL special characters
    # Valid index names: alphanumeric, underscore, hyphen
    if not re.match(r"^[a-zA-Z0-9_-]+$", index_name):
        logger.warning(
            "Index name contains invalid characters",
            extra={"index_name": index_name},
        )
        return False

    return True


def sanitize_query_text(query_text: str, max_length: int = 500) -> str:
    """Sanitize and truncate query text for safe display.

    Cleans up query text by removing sensitive information, normalizing
    whitespace, and truncating to a reasonable length for logging/display.

    Args:
        query_text: SQL query text to sanitize
        max_length: Maximum length of output (default: 500 characters)

    Returns:
        Sanitized query text, truncated if necessary

    Example:
        >>> query = "SELECT * FROM users WHERE password = 'secret123'"
        >>> sanitize_query_text(query)
        "SELECT * FROM users WHERE password = '[REDACTED]'"

        >>> long_query = "SELECT " + ", ".join([f"col{i}" for i in range(100)])
        >>> result = sanitize_query_text(long_query, max_length=50)
        >>> len(result) <= 53  # 50 + "..."
        True

    Security Notes:
        - Redacts password literals
        - Removes excessive whitespace
        - Truncates long queries
        - Safe for display in logs and UIs
    """
    if not query_text:
        return ""

    # Normalize whitespace (replace multiple spaces/newlines with single space)
    sanitized = re.sub(r"\s+", " ", query_text.strip())

    # Redact password literals (basic pattern matching)
    # Matches: password = 'value', PASSWORD='value', etc.
    sanitized = re.sub(
        r"(password\s*=\s*)['\"][^'\"]*['\"]",
        r"\1'[REDACTED]'",
        sanitized,
        flags=re.IGNORECASE,
    )

    # Redact other sensitive patterns
    # Matches: secret = 'value', api_key = 'value', etc.
    sanitized = re.sub(
        r"((?:secret|api_key|token)\s*=\s*)['\"][^'\"]*['\"]",
        r"\1'[REDACTED]'",
        sanitized,
        flags=re.IGNORECASE,
    )

    # Truncate if necessary
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length] + "..."

    return sanitized


# =============================================================================
# PostgreSQL Statistics Functions
# =============================================================================


async def calculate_cache_hit_ratio(session: AsyncSession) -> tuple[float, bool]:
    """Calculate PostgreSQL buffer cache hit ratio.

    Measures how often data is found in memory vs. read from disk.
    A healthy database should have >85% cache hit ratio.

    Args:
        session: Async database session

    Returns:
        Tuple of (ratio_percentage, is_healthy)
        - ratio_percentage: Cache hit ratio as percentage (0-100)
        - is_healthy: True if ratio >= 85%, False otherwise

    Example:
        >>> ratio, is_healthy = await calculate_cache_hit_ratio(session)
        >>> print(f"Cache hit ratio: {ratio:.2f}%")
        Cache hit ratio: 92.34%
        >>> if not is_healthy:
        ...     print("Consider increasing shared_buffers")

    Notes:
        - Queries pg_statio_user_tables for statistics
        - Returns (0.0, False) if no statistics available
        - Ratio of 0% on fresh database is normal (no data in cache yet)
    """
    query = text("""
        SELECT
            SUM(heap_blks_hit) as hits,
            SUM(heap_blks_read) as reads
        FROM pg_statio_user_tables
    """)

    result = await session.execute(query)
    row = result.fetchone()

    if not row or row.hits is None or row.reads is None:
        # No statistics available (empty database or stats not collected)
        logger.debug("No cache statistics available from pg_statio_user_tables")
        return (0.0, False)

    total_accesses = row.hits + row.reads

    if total_accesses == 0:
        # No accesses yet
        return (0.0, False)

    # Calculate hit ratio as percentage
    hit_ratio = (row.hits / total_accesses) * 100

    # Healthy threshold: 85%
    is_healthy = hit_ratio >= 85.0

    logger.debug(
        "Cache hit ratio calculated",
        extra={
            "hits": row.hits,
            "reads": row.reads,
            "ratio_pct": round(hit_ratio, 2),
            "is_healthy": is_healthy,
        },
    )

    return (round(hit_ratio, 2), is_healthy)


async def check_connection_limit(
    session: AsyncSession,
    *,
    critical_threshold: float = 90.0,
) -> tuple[bool, str]:
    """Check PostgreSQL connection pool utilization.

    Monitors how close the database is to max_connections limit.
    Warns when utilization exceeds the critical threshold.

    Args:
        session: Async database session
        critical_threshold: Percentage threshold for critical alert (default: 90%)

    Returns:
        Tuple of (is_critical, message)
        - is_critical: True if utilization >= critical_threshold
        - message: Human-readable status message

    Example:
        >>> is_critical, msg = await check_connection_limit(session)
        >>> print(msg)
        "Connection utilization: 45/100 (45.0%) - Healthy"
        >>> if is_critical:
        ...     print("WARNING: Connection pool near capacity!")

    Notes:
        - Queries pg_stat_activity and pg_settings
        - Includes all connections (active, idle, etc.)
        - Critical threshold typically 80-90%
    """
    query = text("""
        SELECT
            COUNT(*) as current_connections,
            (SELECT setting::int FROM pg_settings WHERE name = 'max_connections') as max_connections
        FROM pg_stat_activity
    """)

    result = await session.execute(query)
    row = result.fetchone()

    if not row or row.max_connections is None:
        error_msg = "Unable to retrieve connection statistics"
        logger.error(error_msg)
        return (False, error_msg)

    current = row.current_connections
    maximum = row.max_connections

    if maximum == 0:
        error_msg = "Invalid max_connections value: 0"
        logger.error(error_msg)
        return (False, error_msg)

    # Calculate utilization percentage
    utilization_pct = (current / maximum) * 100
    is_critical = utilization_pct >= critical_threshold

    # Generate status message
    status = "CRITICAL" if is_critical else "Healthy"
    message = (
        f"Connection utilization: {current}/{maximum} "
        f"({utilization_pct:.1f}%) - {status}"
    )

    logger.debug(
        "Connection limit check completed",
        extra={
            "current_connections": current,
            "max_connections": maximum,
            "utilization_pct": round(utilization_pct, 2),
            "is_critical": is_critical,
            "threshold_pct": critical_threshold,
        },
    )

    return (is_critical, message)


__all__ = [
    "calculate_cache_hit_ratio",
    "check_connection_limit",
    "format_bytes",
    "generate_confirmation_token",
    "sanitize_query_text",
    "validate_index_name",
    "validate_table_name",
    "verify_confirmation_token",
]
