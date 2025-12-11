"""SQL identifier validation utilities.

Provides validation for SQL identifiers (table names, column names, schemas)
to prevent SQL injection when identifiers must be dynamically included in queries.

Example:
    from example_service.core.database.validation import (
        validate_identifier,
        safe_table_reference,
        safe_identifier_sql,
    )

    # Validate before using in raw SQL
    table = validate_identifier(user_input)  # Raises if invalid

    # Get safely quoted reference
    ref = safe_table_reference("users", schema="public")  # '"public"."users"'

    # Use SQLAlchemy's identifier preparer for dialect-specific quoting
    from sqlalchemy import create_engine
    engine = create_engine("postgresql://...")
    quoted = safe_identifier_sql("users", engine)  # Uses SQLAlchemy's preparer
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

# PostgreSQL identifier rules:
# - Max 63 characters
# - Start with letter or underscore
# - Contain letters, digits, underscores, dollar signs
VALID_IDENTIFIER = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_$]*$")
MAX_IDENTIFIER_LENGTH = 63

# SQL reserved keywords that should not be used as unquoted identifiers
# This is a subset of the most dangerous ones
RESERVED_KEYWORDS = frozenset(
    {
        "select",
        "insert",
        "update",
        "delete",
        "drop",
        "truncate",
        "create",
        "alter",
        "grant",
        "revoke",
        "union",
        "join",
        "where",
        "from",
        "table",
        "index",
        "database",
        "schema",
        "execute",
        "exec",
    },
)


class IdentifierValidationError(ValueError):
    """Invalid SQL identifier."""



def validate_identifier(
    name: str,
    *,
    identifier_type: str = "identifier",
    allow_reserved: bool = False,
) -> str:
    """Validate a SQL identifier against injection attacks.

    Ensures the identifier follows PostgreSQL naming rules and doesn't
    contain dangerous patterns.

    Args:
        name: The identifier to validate
        identifier_type: Type description for error messages (e.g., "table", "column")
        allow_reserved: If True, allow SQL reserved keywords

    Returns:
        The validated identifier (unchanged if valid)

    Raises:
        IdentifierValidationError: If the identifier is invalid

    Example:
        >>> validate_identifier("users")
        'users'
        >>> validate_identifier("my_table_123")
        'my_table_123'
        >>> validate_identifier("; DROP TABLE users; --")  # Raises
        IdentifierValidationError: Invalid identifier characters
    """
    if not name:
        msg = f"Empty {identifier_type} name not allowed"
        raise IdentifierValidationError(msg)

    if len(name) > MAX_IDENTIFIER_LENGTH:
        msg = f"{identifier_type} name exceeds maximum length of {MAX_IDENTIFIER_LENGTH}"
        raise IdentifierValidationError(
            msg,
        )

    if not VALID_IDENTIFIER.match(name):
        msg = (
            f"Invalid {identifier_type} name: must start with letter or underscore, "
            "contain only letters, digits, underscores, or dollar signs"
        )
        raise IdentifierValidationError(
            msg,
        )

    # Check for dangerous patterns that might indicate injection attempts
    dangerous_patterns = ["--", ";", "/*", "*/", "xp_", "sp_", "0x"]
    name_lower = name.lower()
    for pattern in dangerous_patterns:
        if pattern in name_lower:
            msg = f"Dangerous pattern '{pattern}' detected in {identifier_type} name"
            raise IdentifierValidationError(
                msg,
            )

    # Check reserved keywords
    if not allow_reserved and name_lower in RESERVED_KEYWORDS:
        msg = f"'{name}' is a SQL reserved keyword and cannot be used as {identifier_type}"
        raise IdentifierValidationError(
            msg,
        )

    return name


def safe_table_reference(
    table_name: str,
    *,
    schema: str | None = None,
) -> str:
    """Create a safely quoted table reference.

    Validates and quotes the table name (and optional schema) for safe
    use in SQL queries. Uses manual quoting for compatibility.

    Args:
        table_name: The table name to reference
        schema: Optional schema name

    Returns:
        Quoted table reference string (e.g., '"public"."users"')

    Raises:
        IdentifierValidationError: If table or schema name is invalid

    Example:
        >>> safe_table_reference("users")
        '"users"'
        >>> safe_table_reference("users", schema="public")
        '"public"."users"'
    """
    validated_table = validate_identifier(table_name, identifier_type="table")

    if schema:
        validated_schema = validate_identifier(schema, identifier_type="schema")
        return f'"{validated_schema}"."{validated_table}"'

    return f'"{validated_table}"'


def safe_identifier_sql(
    identifier: str,
    engine: Engine,
    *,
    identifier_type: str = "identifier",
) -> str:
    """Create a safely quoted SQL identifier using SQLAlchemy's preparer.

    This uses SQLAlchemy's dialect-specific identifier preparer to properly
    quote identifiers according to the database dialect rules. This is the
    recommended approach when you have access to an engine.

    Args:
        identifier: The identifier to quote (table name, column name, etc.)
        engine: SQLAlchemy engine (used to get dialect-specific preparer)
        identifier_type: Type description for validation error messages

    Returns:
        Properly quoted identifier string according to the dialect

    Raises:
        IdentifierValidationError: If identifier is invalid

    Example:
        >>> from sqlalchemy import create_engine
        >>> engine = create_engine("postgresql://...")
        >>> safe_identifier_sql("users", engine)
        '"users"'
    """
    # Validate first
    validated = validate_identifier(identifier, identifier_type=identifier_type)

    # Use SQLAlchemy's identifier preparer for dialect-specific quoting
    preparer = engine.dialect.identifier_preparer
    return preparer.quote(validated)


def safe_sql_text(
    sql_template: str,
    **validated_identifiers: str,
) -> str:
    """Construct SQL text with validated identifiers.

    This helper function constructs SQL strings using validated identifiers,
    making it clear that the identifiers have been checked for SQL injection.
    The identifiers are expected to already be quoted (via safe_table_reference
    or similar).

    Args:
        sql_template: SQL template string with {placeholder} format
        **validated_identifiers: Keyword arguments mapping placeholders to
            validated and quoted identifier strings

    Returns:
        SQL string with identifiers substituted

    Example:
        >>> table = safe_table_reference("users")
        >>> sql = safe_sql_text("SELECT COUNT(*) FROM {table}", table=table)
        >>> sql
        'SELECT COUNT(*) FROM "users"'
    """
    # All identifiers should already be validated and quoted
    return sql_template.format(**validated_identifiers)


__all__ = [
    "IdentifierValidationError",
    "safe_identifier_sql",
    "safe_table_reference",
    "validate_identifier",
]
