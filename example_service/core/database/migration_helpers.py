"""Migration helper utilities for PostgreSQL-specific features.

Provides helper functions for common migration patterns:
- PostgreSQL extensions (ltree, pg_trgm, etc.)
- GiST indexes for ltree and range columns
- Exclusion constraints for preventing overlapping ranges
- Specialized indexes (full-text search, partial indexes)

These utilities complement Alembic's operations by providing PostgreSQL-specific
patterns that aren't auto-generated.

Example:
    >>> from alembic import op
    >>> from example_service.core.database.migration_helpers import (
    ...     create_extension,
    ...     create_gist_index,
    ...     create_exclusion_constraint,
    ... )
    >>>
    >>> def upgrade() -> None:
    ...     # Enable ltree extension
    ...     create_extension("ltree")
    ...
    ...     # Create table with ltree column
    ...     op.create_table("categories", ...)
    ...
    ...     # Add GiST index for efficient hierarchy queries
    ...     create_gist_index("categories", "path")
    >>>
    >>> def downgrade() -> None:
    ...     drop_gist_index("categories", "path")
    ...     op.drop_table("categories")
    ...     # drop_extension("ltree")  # Only if nothing else uses it
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


# =============================================================================
# PostgreSQL Extension Helpers
# =============================================================================


def create_extension(name: str, *, schema: str | None = None) -> None:
    """Create a PostgreSQL extension if it doesn't exist.

    Common extensions:
    - ltree: Hierarchical data (materialized paths)
    - pg_trgm: Trigram similarity (fuzzy text search)
    - btree_gist: GiST for B-tree operators (required for some exclusion constraints)
    - uuid-ossp: UUID generation functions
    - pgcrypto: Cryptographic functions

    Args:
        name: Extension name (e.g., "ltree", "pg_trgm")
        schema: Optional schema to install extension into

    Example:
        >>> create_extension("ltree")
        >>> create_extension("pg_trgm", schema="public")
    """
    from alembic import op

    schema_clause = f" SCHEMA {schema}" if schema else ""
    op.execute(f"CREATE EXTENSION IF NOT EXISTS {name}{schema_clause}")


def drop_extension(name: str, *, cascade: bool = False) -> None:
    """Drop a PostgreSQL extension.

    Warning: Only drop extensions when you're certain no tables depend on them.

    Args:
        name: Extension name to drop
        cascade: If True, drop dependent objects (dangerous!)

    Example:
        >>> drop_extension("ltree")  # Safe drop
        >>> drop_extension("ltree", cascade=True)  # Force drop with deps
    """
    from alembic import op

    cascade_clause = " CASCADE" if cascade else ""
    op.execute(f"DROP EXTENSION IF EXISTS {name}{cascade_clause}")


# =============================================================================
# GiST Index Helpers
# =============================================================================


def create_gist_index(
    table: str,
    column: str,
    *,
    name: str | None = None,
    schema: str | None = None,
    unique: bool = False,
    where: str | None = None,
) -> None:
    """Create a GiST index on a column.

    GiST (Generalized Search Tree) indexes are required for efficient:
    - ltree ancestor/descendant queries (@>, <@)
    - Range type containment/overlap queries (&&, @>, <@)
    - Geometric operations
    - Full-text search (tsvector)

    Args:
        table: Table name
        column: Column to index
        name: Custom index name (default: ix_{table}_{column}_gist)
        schema: Table schema (default: public)
        unique: Create unique index
        where: Partial index condition (e.g., "deleted_at IS NULL")

    Example:
        >>> # Index for ltree hierarchy queries
        >>> create_gist_index("categories", "path")
        >>>
        >>> # Index for date range overlap checks
        >>> create_gist_index("bookings", "stay_period")
        >>>
        >>> # Partial index for active records only
        >>> create_gist_index(
        ...     "events",
        ...     "date_range",
        ...     where="status = 'active'"
        ... )
    """
    from alembic import op

    index_name = name or f"ix_{table}_{column}_gist"
    table_ref = f"{schema}.{table}" if schema else table
    unique_clause = "UNIQUE " if unique else ""
    where_clause = f" WHERE {where}" if where else ""

    op.execute(
        f"CREATE {unique_clause}INDEX {index_name} ON {table_ref} "
        f"USING GIST ({column}){where_clause}"
    )


def drop_gist_index(
    table: str,
    column: str,
    *,
    name: str | None = None,
    schema: str | None = None,
) -> None:
    """Drop a GiST index.

    Args:
        table: Table name (used for default index name)
        column: Column name (used for default index name)
        name: Custom index name if not using default naming
        schema: Schema containing the index
    """
    from alembic import op

    index_name = name or f"ix_{table}_{column}_gist"
    schema_clause = f"{schema}." if schema else ""

    op.execute(f"DROP INDEX IF EXISTS {schema_clause}{index_name}")


def create_gist_index_multi(
    table: str,
    columns: Sequence[str],
    *,
    name: str | None = None,
    schema: str | None = None,
) -> None:
    """Create a multi-column GiST index.

    Useful for composite exclusion constraints or queries filtering
    on multiple columns.

    Args:
        table: Table name
        columns: Columns to include in index
        name: Custom index name
        schema: Table schema

    Example:
        >>> # For exclusion constraint on (room_id, period)
        >>> create_gist_index_multi("bookings", ["room_id", "period"])
    """
    from alembic import op

    columns_str = ", ".join(columns)
    index_name = name or f"ix_{table}_{'_'.join(columns)}_gist"
    table_ref = f"{schema}.{table}" if schema else table

    op.execute(f"CREATE INDEX {index_name} ON {table_ref} USING GIST ({columns_str})")


# =============================================================================
# Exclusion Constraint Helpers
# =============================================================================


def create_exclusion_constraint(
    table: str,
    constraint_name: str,
    *,
    columns_with_operators: dict[str, str],
    using: str = "gist",
    where: str | None = None,
    schema: str | None = None,
) -> None:
    """Create an exclusion constraint to prevent overlapping values.

    Exclusion constraints are powerful for enforcing business rules like:
    - No overlapping date ranges for the same resource
    - No conflicting time slots
    - No duplicate IP ranges

    Args:
        table: Table name
        constraint_name: Name for the constraint
        columns_with_operators: Dict mapping column names to comparison operators
            Common operators:
            - "=" for equality (same resource)
            - "&&" for range overlap
            - "&>" for left overlap
        using: Index method (default: gist)
        where: Optional condition (partial exclusion)
        schema: Table schema

    Example:
        >>> # Prevent double-booking: same room, overlapping dates
        >>> create_exclusion_constraint(
        ...     "bookings",
        ...     "no_overlapping_bookings",
        ...     columns_with_operators={
        ...         "room_id": "=",      # Same room
        ...         "stay_period": "&&",  # Overlapping dates
        ...     },
        ... )
        >>>
        >>> # Prevent overlapping shifts for same employee (with condition)
        >>> create_exclusion_constraint(
        ...     "shifts",
        ...     "no_overlapping_shifts",
        ...     columns_with_operators={
        ...         "employee_id": "=",
        ...         "time_slot": "&&",
        ...     },
        ...     where="status != 'cancelled'",
        ... )

    Note:
        For exclusion constraints using "=" on non-range columns, you may need
        the btree_gist extension: CREATE EXTENSION btree_gist
    """
    from alembic import op

    table_ref = f"{schema}.{table}" if schema else table

    # Build the exclusion expression
    exclusion_parts = [f"{col} WITH {op}" for col, op in columns_with_operators.items()]
    exclusion_expr = ", ".join(exclusion_parts)

    where_clause = f" WHERE ({where})" if where else ""

    op.execute(
        f"ALTER TABLE {table_ref} ADD CONSTRAINT {constraint_name} "
        f"EXCLUDE USING {using} ({exclusion_expr}){where_clause}"
    )


def drop_exclusion_constraint(
    table: str,
    constraint_name: str,
    *,
    schema: str | None = None,
) -> None:
    """Drop an exclusion constraint.

    Args:
        table: Table name
        constraint_name: Name of constraint to drop
        schema: Table schema
    """
    from alembic import op

    table_ref = f"{schema}.{table}" if schema else table
    op.execute(f"ALTER TABLE {table_ref} DROP CONSTRAINT IF EXISTS {constraint_name}")


# =============================================================================
# Convenience Functions for Common Patterns
# =============================================================================


def create_no_overlap_constraint(
    table: str,
    range_column: str,
    *,
    partition_columns: Sequence[str] | None = None,
    constraint_name: str | None = None,
    where: str | None = None,
    schema: str | None = None,
) -> None:
    """Create a constraint preventing overlapping ranges within partitions.

    This is a convenience wrapper for the common pattern of preventing
    overlapping ranges for the same entity.

    Args:
        table: Table name
        range_column: Column containing the range (DATERANGE, TSTZRANGE, etc.)
        partition_columns: Columns that define partitions (e.g., ["room_id"])
            Overlaps are only prevented within the same partition.
        constraint_name: Custom constraint name
        where: Optional condition
        schema: Table schema

    Example:
        >>> # No overlapping periods for same room
        >>> create_no_overlap_constraint(
        ...     "bookings",
        ...     "stay_period",
        ...     partition_columns=["room_id"],
        ... )
        >>>
        >>> # No overlapping periods globally
        >>> create_no_overlap_constraint(
        ...     "maintenance_windows",
        ...     "window_period",
        ... )
    """
    columns_with_operators: dict[str, str] = {}

    # Add partition columns with equality
    if partition_columns:
        for col in partition_columns:
            columns_with_operators[col] = "="

    # Add range column with overlap
    columns_with_operators[range_column] = "&&"

    # Generate default constraint name
    if constraint_name is None:
        parts = list(partition_columns) if partition_columns else []
        parts.append(range_column)
        constraint_name = f"{table}_{'_'.join(parts)}_no_overlap"

    create_exclusion_constraint(
        table,
        constraint_name,
        columns_with_operators=columns_with_operators,
        where=where,
        schema=schema,
    )


def create_ltree_indexes(
    table: str,
    column: str = "path",
    *,
    schema: str | None = None,
    include_btree: bool = True,
) -> None:
    """Create recommended indexes for an ltree column.

    Creates:
    - GiST index for ancestor/descendant queries (@>, <@, ~)
    - Optional B-tree index for exact matches and sorting

    Args:
        table: Table name
        column: ltree column name (default: "path")
        schema: Table schema
        include_btree: Also create B-tree index for sorting (default: True)

    Example:
        >>> create_ltree_indexes("categories", "path")
    """
    from alembic import op

    # GiST index for hierarchy queries
    create_gist_index(table, column, schema=schema)

    # B-tree index for exact matches and ORDER BY
    if include_btree:
        index_name = f"ix_{table}_{column}_btree"
        table_ref = f"{schema}.{table}" if schema else table
        op.execute(f"CREATE INDEX {index_name} ON {table_ref} ({column})")


def drop_ltree_indexes(
    table: str,
    column: str = "path",
    *,
    schema: str | None = None,
    include_btree: bool = True,
) -> None:
    """Drop ltree indexes created by create_ltree_indexes.

    Args:
        table: Table name
        column: ltree column name (default: "path")
        schema: Table schema
        include_btree: Also drop B-tree index
    """
    from alembic import op

    drop_gist_index(table, column, schema=schema)

    if include_btree:
        index_name = f"ix_{table}_{column}_btree"
        schema_clause = f"{schema}." if schema else ""
        op.execute(f"DROP INDEX IF EXISTS {schema_clause}{index_name}")


# =============================================================================
# btree_gist Extension Helper
# =============================================================================


def ensure_btree_gist() -> None:
    """Ensure btree_gist extension is available.

    The btree_gist extension is required when using exclusion constraints
    that combine range types with non-range types (like integers or UUIDs).

    Without btree_gist, you'll get:
        ERROR: data type integer has no default operator class for access method "gist"

    Example:
        >>> def upgrade() -> None:
        ...     ensure_btree_gist()
        ...     create_exclusion_constraint(
        ...         "bookings",
        ...         "no_overlapping_bookings",
        ...         columns_with_operators={
        ...             "room_id": "=",       # Integer - needs btree_gist
        ...             "stay_period": "&&",  # DATERANGE - native GiST
        ...         },
        ...     )
    """
    create_extension("btree_gist")


__all__ = [
    # Extension helpers
    "create_extension",
    "drop_extension",
    # GiST index helpers
    "create_gist_index",
    "create_gist_index_multi",
    "drop_gist_index",
    # Exclusion constraint helpers
    "create_exclusion_constraint",
    "drop_exclusion_constraint",
    # Convenience functions
    "create_ltree_indexes",
    "create_no_overlap_constraint",
    "drop_ltree_indexes",
    "ensure_btree_gist",
]
