"""SQL identifier validation utilities.

Provides validation for SQL identifiers (table names, column names, schemas)
to prevent SQL injection when identifiers must be dynamically included in queries.

Example:
    from example_service.core.database.validation import (
        validate_identifier,
        safe_table_reference,
    )

    # Validate before using in raw SQL
    table = validate_identifier(user_input)  # Raises if invalid

    # Get safely quoted reference
    ref = safe_table_reference("users", schema="public")  # '"public"."users"'
"""

from __future__ import annotations

import re

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
    }
)


class IdentifierValidationError(ValueError):
    """Invalid SQL identifier."""

    pass


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
        raise IdentifierValidationError(f"Empty {identifier_type} name not allowed")

    if len(name) > MAX_IDENTIFIER_LENGTH:
        raise IdentifierValidationError(
            f"{identifier_type} name exceeds maximum length of {MAX_IDENTIFIER_LENGTH}"
        )

    if not VALID_IDENTIFIER.match(name):
        raise IdentifierValidationError(
            f"Invalid {identifier_type} name: must start with letter or underscore, "
            "contain only letters, digits, underscores, or dollar signs"
        )

    # Check for dangerous patterns that might indicate injection attempts
    dangerous_patterns = ["--", ";", "/*", "*/", "xp_", "sp_", "0x"]
    name_lower = name.lower()
    for pattern in dangerous_patterns:
        if pattern in name_lower:
            raise IdentifierValidationError(
                f"Dangerous pattern '{pattern}' detected in {identifier_type} name"
            )

    # Check reserved keywords
    if not allow_reserved and name_lower in RESERVED_KEYWORDS:
        raise IdentifierValidationError(
            f"'{name}' is a SQL reserved keyword and cannot be used as {identifier_type}"
        )

    return name


def safe_table_reference(
    table_name: str,
    *,
    schema: str | None = None,
) -> str:
    """Create a safely quoted table reference.

    Validates and quotes the table name (and optional schema) for safe
    use in SQL queries.

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


__all__ = [
    "IdentifierValidationError",
    "validate_identifier",
    "safe_table_reference",
]
