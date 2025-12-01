"""Schema management utilities for database operations.

This module provides utilities for inspecting, comparing, and managing database
schemas. These are complementary to the data export/import in cli/commands/data.py.

- `drop_all`: Drop all tables from the database
- `dump_schema`: Inspect and export schema information
- `truncate_all`: Clear all data while preserving schema
- `compare_schema`: Compare model metadata with actual database

Example:
    from example_service.infra.database import engine
    from example_service.infra.database.schema import drop_all, dump_schema

    # Get schema information
    schema_info = await dump_schema(engine)

    # Reset database for testing
    dropped = await drop_all(engine, cascade=True)

"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import MetaData, inspect, text
from sqlalchemy.schema import DropTable

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection
    from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


@dataclass
class SchemaDifference:
    """Represents a difference between model and database schema.

    Attributes:
        type: Type of difference
        table: Table name where difference was found
        column: Column name (if applicable)
        expected: What the model expects
        actual: What the database has
        message: Human-readable description
    """

    type: Literal[
        "missing_table",
        "extra_table",
        "missing_column",
        "extra_column",
        "type_mismatch",
        "nullable_mismatch",
        "default_mismatch",
    ]
    table: str
    column: str | None
    expected: str | None
    actual: str | None
    message: str


async def drop_all(
    engine: AsyncEngine,
    *,
    metadata: MetaData | None = None,
    include_alembic: bool = False,
    cascade: bool = False,
) -> list[str]:
    """Drop all tables from the database.

    This is a destructive operation intended for development/testing.
    By default, preserves the alembic_version table for migration tracking.

    Args:
        engine: SQLAlchemy async engine
        metadata: Optional MetaData to use (uses reflection if None)
        include_alembic: If True, also drops alembic_version table
        cascade: If True, use CASCADE (PostgreSQL) to drop dependent objects

    Returns:
        List of dropped table names

    Example:
            from example_service.infra.database import engine
        from example_service.infra.database.schema import drop_all

        # Drop all tables except alembic_version
        dropped = await drop_all(engine)
        print(f"Dropped: {dropped}")

        # Drop everything including migration tracking
        dropped = await drop_all(engine, include_alembic=True)

        # Force drop with CASCADE (PostgreSQL)
        dropped = await drop_all(engine, cascade=True)

    Warning:
        This operation cannot be undone. Use with caution!
    """
    dropped_tables: list[str] = []

    async with engine.begin() as conn:
        # Reflect current schema if no metadata provided
        if metadata is not None:
            tables_to_drop = list(metadata.sorted_tables)
        else:
            # Reflect all tables from database
            reflected = MetaData()
            await conn.run_sync(reflected.reflect)
            tables_to_drop = list(reflected.sorted_tables)

        # Filter out alembic_version if needed
        if not include_alembic:
            tables_to_drop = [t for t in tables_to_drop if t.name != "alembic_version"]

        # Drop in reverse order (respects foreign keys)
        for table in reversed(tables_to_drop):
            logger.info(f"Dropping table: {table.name}")
            try:
                if cascade:
                    # PostgreSQL-specific CASCADE
                    await conn.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))
                else:
                    await conn.execute(DropTable(table, if_exists=True))
                dropped_tables.append(table.name)
            except Exception as e:
                logger.error(f"Failed to drop table {table.name}: {e}")
                raise

    logger.info(f"Dropped {len(dropped_tables)} tables: {dropped_tables}")
    return dropped_tables


async def dump_schema(
    engine: AsyncEngine,
    *,
    include_columns: bool = True,
    include_indexes: bool = True,
    include_constraints: bool = True,
    include_row_counts: bool = False,
) -> dict[str, Any]:
    """Dump database schema information.

    Inspects the database and returns a dictionary describing all
    tables, columns, indexes, and constraints. This is for schema
    inspection, not data export (see cli/commands/data.py for data export).

    Args:
        engine: SQLAlchemy async engine
        include_columns: Include column definitions
        include_indexes: Include index information
        include_constraints: Include foreign keys and constraints
        include_row_counts: Include row count for each table (slower)

    Returns:
        Dictionary with schema information

    Example:
            from example_service.infra.database import engine
        from example_service.infra.database.schema import dump_schema
        import json

        schema = await dump_schema(engine)
        print(json.dumps(schema, indent=2))

        # With row counts (slower)
        schema = await dump_schema(engine, include_row_counts=True)
    """

    def _inspect(conn: Connection) -> dict[str, Any]:
        inspector = inspect(conn)
        result: dict[str, Any] = {"tables": {}, "dialect": conn.dialect.name}

        for table_name in inspector.get_table_names():
            table_info: dict[str, Any] = {}

            if include_columns:
                columns = []
                for col in inspector.get_columns(table_name):
                    columns.append(
                        {
                            "name": col["name"],
                            "type": str(col["type"]),
                            "nullable": col["nullable"],
                            "default": str(col.get("default")) if col.get("default") else None,
                            "autoincrement": col.get("autoincrement", False),
                        }
                    )
                table_info["columns"] = columns

            if include_indexes:
                indexes = []
                for idx in inspector.get_indexes(table_name):
                    indexes.append(
                        {
                            "name": idx["name"],
                            "columns": idx["column_names"],
                            "unique": idx["unique"],
                        }
                    )
                table_info["indexes"] = indexes

            if include_constraints:
                # Primary key
                pk = inspector.get_pk_constraint(table_name)
                if pk:
                    table_info["primary_key"] = {
                        "name": pk.get("name"),
                        "columns": pk.get("constrained_columns", []),
                    }

                # Foreign keys
                fks = []
                for fk in inspector.get_foreign_keys(table_name):
                    fks.append(
                        {
                            "name": fk.get("name"),
                            "columns": fk.get("constrained_columns", []),
                            "referred_table": fk.get("referred_table"),
                            "referred_columns": fk.get("referred_columns", []),
                            "ondelete": fk.get("options", {}).get("ondelete"),
                            "onupdate": fk.get("options", {}).get("onupdate"),
                        }
                    )
                table_info["foreign_keys"] = fks

                # Unique constraints
                uniques = []
                for uq in inspector.get_unique_constraints(table_name):
                    uniques.append(
                        {
                            "name": uq.get("name"),
                            "columns": uq.get("column_names", []),
                        }
                    )
                table_info["unique_constraints"] = uniques

                # Check constraints
                checks = []
                for ck in inspector.get_check_constraints(table_name):
                    checks.append(
                        {
                            "name": ck.get("name"),
                            "sqltext": str(ck.get("sqltext", "")),
                        }
                    )
                table_info["check_constraints"] = checks

            result["tables"][table_name] = table_info

        return result

    async with engine.connect() as conn:
        result = await conn.run_sync(_inspect)

        # Optionally add row counts (requires separate queries)
        if include_row_counts:
            for table_name in result["tables"]:
                count_result = await conn.execute(text(f'SELECT COUNT(*) FROM "{table_name}"'))
                result["tables"][table_name]["row_count"] = count_result.scalar()

    return result


async def truncate_all(
    engine: AsyncEngine,
    *,
    exclude_tables: list[str] | None = None,
    restart_identity: bool = True,
) -> list[str]:
    """Truncate all tables (delete data but keep schema).

    Faster than drop_all + recreate for resetting test data.
    Uses PostgreSQL TRUNCATE with CASCADE and optional RESTART IDENTITY.

    Args:
        engine: SQLAlchemy async engine
        exclude_tables: Tables to skip (default: ["alembic_version"])
        restart_identity: Reset auto-increment sequences (PostgreSQL only)

    Returns:
        List of truncated table names

    Example:
            from example_service.infra.database import engine
        from example_service.infra.database.schema import truncate_all

        # Truncate all tables except alembic_version
        truncated = await truncate_all(engine)

        # Keep specific tables
        truncated = await truncate_all(engine, exclude_tables=["users", "alembic_version"])
    """
    if exclude_tables is None:
        exclude_tables = ["alembic_version"]

    truncated: list[str] = []

    async with engine.begin() as conn:
        # Reflect tables
        reflected = MetaData()
        await conn.run_sync(reflected.reflect)

        tables = [t.name for t in reflected.sorted_tables if t.name not in exclude_tables]

        if not tables:
            logger.info("No tables to truncate")
            return truncated

        # Build TRUNCATE statement
        # PostgreSQL supports TRUNCATE multiple tables in one statement
        dialect = conn.dialect.name

        if dialect == "postgresql":
            table_list = ", ".join(f'"{t}"' for t in tables)
            identity_clause = " RESTART IDENTITY" if restart_identity else ""
            await conn.execute(text(f"TRUNCATE TABLE {table_list} CASCADE{identity_clause}"))
            truncated.extend(tables)
        else:
            # For other dialects, truncate one at a time
            for table_name in reversed(tables):  # Reverse to handle FK dependencies
                if dialect == "sqlite":
                    await conn.execute(text(f'DELETE FROM "{table_name}"'))
                    if restart_identity:
                        # SQLite: Reset autoincrement counter
                        await conn.execute(
                            text(
                                f"DELETE FROM sqlite_sequence WHERE name='{table_name}'"  # noqa: S608
                            )
                        )
                else:
                    await conn.execute(text(f'TRUNCATE TABLE "{table_name}"'))
                truncated.append(table_name)

    logger.info(f"Truncated {len(truncated)} tables: {truncated}")
    return truncated


async def compare_schema(
    engine: AsyncEngine,
    metadata: MetaData,
) -> list[SchemaDifference]:
    """Compare model metadata with actual database schema.

    Detects drift between SQLAlchemy model definitions and the actual
    database state. Useful for validating schema consistency.

    Args:
        engine: SQLAlchemy async engine
        metadata: SQLAlchemy MetaData from model definitions

    Returns:
        List of SchemaDifference objects describing each difference

    Example:
            from example_service.infra.database import engine
        from example_service.core.database import Base
        from example_service.infra.database.schema import compare_schema

        differences = await compare_schema(engine, Base.metadata)

        if differences:
            print("Schema drift detected:")
            for diff in differences:
                print(f"  [{diff.type}] {diff.table}: {diff.message}")
        else:
            print("Schema is in sync")
    """
    differences: list[SchemaDifference] = []

    def _compare(conn: Connection) -> list[SchemaDifference]:
        inspector = inspect(conn)
        diffs: list[SchemaDifference] = []

        # Get actual database tables
        db_tables = set(inspector.get_table_names())

        # Get model tables (exclude alembic_version from comparison)
        model_tables = {t.name for t in metadata.sorted_tables if t.name != "alembic_version"}

        # Find missing tables (in model but not in database)
        for table_name in model_tables - db_tables:
            diffs.append(
                SchemaDifference(
                    type="missing_table",
                    table=table_name,
                    column=None,
                    expected="exists",
                    actual="missing",
                    message=f"Table '{table_name}' defined in models but not in database",
                )
            )

        # Find extra tables (in database but not in model)
        for table_name in db_tables - model_tables - {"alembic_version"}:
            diffs.append(
                SchemaDifference(
                    type="extra_table",
                    table=table_name,
                    column=None,
                    expected="missing",
                    actual="exists",
                    message=f"Table '{table_name}' exists in database but not in models",
                )
            )

        # Compare columns for tables that exist in both
        for table_name in model_tables & db_tables:
            model_table = metadata.tables[table_name]
            db_columns = {col["name"]: col for col in inspector.get_columns(table_name)}
            model_columns = {col.name: col for col in model_table.columns}

            # Find missing columns
            for col_name in model_columns.keys() - db_columns.keys():
                diffs.append(
                    SchemaDifference(
                        type="missing_column",
                        table=table_name,
                        column=col_name,
                        expected="exists",
                        actual="missing",
                        message=f"Column '{col_name}' defined in model but not in database",
                    )
                )

            # Find extra columns
            for col_name in db_columns.keys() - model_columns.keys():
                diffs.append(
                    SchemaDifference(
                        type="extra_column",
                        table=table_name,
                        column=col_name,
                        expected="missing",
                        actual="exists",
                        message=f"Column '{col_name}' exists in database but not in model",
                    )
                )

            # Compare column properties for columns in both
            for col_name in model_columns.keys() & db_columns.keys():
                model_col = model_columns[col_name]
                db_col = db_columns[col_name]

                # Compare nullable
                model_nullable = model_col.nullable
                db_nullable = db_col["nullable"]
                if model_nullable != db_nullable:
                    diffs.append(
                        SchemaDifference(
                            type="nullable_mismatch",
                            table=table_name,
                            column=col_name,
                            expected=f"nullable={model_nullable}",
                            actual=f"nullable={db_nullable}",
                            message=f"Column '{col_name}' nullable mismatch",
                        )
                    )

                # Note: Type comparison is complex due to dialect differences
                # Alembic's compare_type handles this better in env.py

        return diffs

    async with engine.connect() as conn:
        differences = await conn.run_sync(_compare)

    return differences


@dataclass
class TableStats:
    """Statistics for a database table.

    Attributes:
        table_name: Name of the table
        row_count: Number of rows (approximate or exact)
        approximate: Whether row_count is an estimate or exact
        size_bytes: Total size in bytes (data + indexes), PostgreSQL only
        size_human: Human-readable size string (e.g., "1.2 MB")
    """

    table_name: str
    row_count: int
    approximate: bool
    size_bytes: int | None
    size_human: str | None


async def get_table_stats(
    engine: AsyncEngine,
    table_name: str,
    *,
    exact: bool = False,
) -> TableStats:
    """Get table statistics including row count and size.

    Uses PostgreSQL's pg_stat_user_tables for fast approximate counts,
    avoiding expensive full table scans. For exact counts, falls back
    to COUNT(*) which can be slow on large tables.

    Args:
        engine: SQLAlchemy async engine
        table_name: Name of the table to analyze
        exact: If True, use COUNT(*) for exact row count (slower)

    Returns:
        TableStats with row count, size, and whether count is approximate

    Example:
            from example_service.infra.database import engine
        from example_service.infra.database.schema import get_table_stats

        # Fast approximate count (default)
        stats = await get_table_stats(engine, "users")
        print(f"~{stats.row_count} rows, {stats.size_human}")

        # Exact count (slower for large tables)
        stats = await get_table_stats(engine, "users", exact=True)
        print(f"Exactly {stats.row_count} rows")

    Note:
        PostgreSQL approximate counts come from pg_stat_user_tables.n_live_tup,
        which is updated by VACUUM and ANALYZE. For recently modified tables,
        run ANALYZE first for accurate estimates.

        Size information is only available on PostgreSQL.
    """
    from example_service.core.database.validation import validate_identifier

    # Validate table name to prevent SQL injection
    validated_table = validate_identifier(table_name, identifier_type="table")

    async with engine.connect() as conn:
        dialect = conn.dialect.name
        row_count: int = 0
        approximate: bool = False
        size_bytes: int | None = None

        if dialect == "postgresql":
            if exact:
                # Exact count using COUNT(*)
                result = await conn.execute(text(f'SELECT COUNT(*) FROM "{validated_table}"'))
                row_count = result.scalar() or 0
                approximate = False
            else:
                # Fast approximate count from statistics
                stats_query = text("""
                    SELECT n_live_tup
                    FROM pg_stat_user_tables
                    WHERE relname = :table_name
                """)
                result = await conn.execute(stats_query, {"table_name": validated_table})
                row = result.first()
                if row:
                    row_count = row[0] or 0
                    approximate = True
                else:
                    # Table not in stats (maybe just created), fall back to count
                    result = await conn.execute(text(f'SELECT COUNT(*) FROM "{validated_table}"'))
                    row_count = result.scalar() or 0
                    approximate = False

            # Get table size (PostgreSQL specific)
            size_query = text("""
                SELECT pg_total_relation_size(:table_name) AS size_bytes
            """)
            size_result = await conn.execute(size_query, {"table_name": validated_table})
            size_row = size_result.first()
            if size_row:
                size_bytes = size_row[0]

        else:
            # Non-PostgreSQL: always use COUNT(*)
            result = await conn.execute(text(f'SELECT COUNT(*) FROM "{validated_table}"'))
            row_count = result.scalar() or 0
            approximate = False

        # Format human-readable size
        size_human: str | None = None
        if size_bytes is not None:
            if size_bytes < 1024:
                size_human = f"{size_bytes} B"
            elif size_bytes < 1024 * 1024:
                size_human = f"{size_bytes / 1024:.1f} KB"
            elif size_bytes < 1024 * 1024 * 1024:
                size_human = f"{size_bytes / (1024 * 1024):.1f} MB"
            else:
                size_human = f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

        return TableStats(
            table_name=validated_table,
            row_count=row_count,
            approximate=approximate,
            size_bytes=size_bytes,
            size_human=size_human,
        )


__all__ = [
    "SchemaDifference",
    "TableStats",
    "drop_all",
    "dump_schema",
    "truncate_all",
    "compare_schema",
    "get_table_stats",
]
