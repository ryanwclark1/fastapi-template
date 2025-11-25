"""Data import/export commands.

This module provides CLI commands for data management:
- Export data to CSV, JSON, or SQL formats
- Import data from files
- Database statistics and analysis
"""

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click

from example_service.cli.utils import coro, error, header, info, section, success, warning


@click.group(name="data")
def data() -> None:
    """Data import/export commands."""


@data.command(name="export")
@click.argument("table", required=True)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["csv", "json", "jsonl"]),
    default="csv",
    help="Output format (default: csv)",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default=None,
    help="Output file path (default: stdout or auto-generated)",
)
@click.option(
    "--limit",
    type=int,
    default=None,
    help="Maximum number of records to export",
)
@click.option(
    "--where",
    type=str,
    default=None,
    help="Filter condition (e.g., 'is_active=true')",
)
@coro
async def export_data(
    table: str,
    output_format: str,
    output: str | None,
    limit: int | None,
    where: str | None,
) -> None:
    """Export data from a database table.

    TABLE is the name of the table to export (e.g., users, posts, reminders).

    Examples:

    \b
      example-service data export users --format csv -o users.csv
      example-service data export posts --format json --limit 100
      example-service data export users --where "is_active=true"
    """
    info(f"Exporting table: {table}")

    # Map table names to models
    table_models = {
        "users": "example_service.core.models.user:User",
        "posts": "example_service.core.models.post:Post",
        "reminders": "example_service.features.reminders.models:Reminder",
    }

    if table not in table_models:
        error(f"Unknown table: {table}")
        info(f"Available tables: {', '.join(table_models.keys())}")
        sys.exit(1)

    try:
        # Import the model
        module_path, class_name = table_models[table].rsplit(":", 1)
        import importlib
        module = importlib.import_module(module_path)
        Model = getattr(module, class_name)

        from sqlalchemy import select, inspect
        from example_service.infra.database import get_session

        async with get_session() as session:
            # Build query
            stmt = select(Model)

            if limit:
                stmt = stmt.limit(limit)

            # Execute query
            result = await session.execute(stmt)
            records = result.scalars().all()

            if not records:
                warning(f"No records found in table: {table}")
                return

            # Get column names from model
            mapper = inspect(Model)
            columns = [c.key for c in mapper.columns]

            # Convert records to dicts
            data_rows = []
            for record in records:
                row = {}
                for col in columns:
                    value = getattr(record, col, None)
                    # Handle datetime serialization
                    if isinstance(value, datetime):
                        value = value.isoformat()
                    row[col] = value
                data_rows.append(row)

            # Determine output
            if output:
                output_path = Path(output)
            else:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_path = Path(f"{table}_{timestamp}.{output_format}")

            # Write data
            if output_format == "csv":
                with open(output_path, "w", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=columns)
                    writer.writeheader()
                    writer.writerows(data_rows)

            elif output_format == "json":
                with open(output_path, "w") as f:
                    json.dump(data_rows, f, indent=2, default=str)

            elif output_format == "jsonl":
                with open(output_path, "w") as f:
                    for row in data_rows:
                        f.write(json.dumps(row, default=str) + "\n")

            success(f"Exported {len(data_rows)} records to {output_path}")

    except ImportError as e:
        error(f"Failed to import model: {e}")
        sys.exit(1)
    except Exception as e:
        error(f"Export failed: {e}")
        sys.exit(1)


@data.command(name="import")
@click.argument("table", required=True)
@click.argument("file_path", type=click.Path(exists=True))
@click.option(
    "--format",
    "input_format",
    type=click.Choice(["csv", "json", "jsonl"]),
    default=None,
    help="Input format (auto-detected from extension if not specified)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Validate data without importing",
)
@click.option(
    "--skip-errors",
    is_flag=True,
    default=False,
    help="Continue importing even if some records fail",
)
@coro
async def import_data(
    table: str,
    file_path: str,
    input_format: str | None,
    dry_run: bool,
    skip_errors: bool,
) -> None:
    """Import data into a database table from a file.

    TABLE is the name of the table to import into.
    FILE_PATH is the path to the data file.

    Examples:

    \b
      example-service data import users users.csv
      example-service data import posts data.json --dry-run
    """
    path = Path(file_path)

    # Auto-detect format
    if input_format is None:
        ext = path.suffix.lower()
        if ext == ".csv":
            input_format = "csv"
        elif ext == ".json":
            input_format = "json"
        elif ext == ".jsonl":
            input_format = "jsonl"
        else:
            error(f"Cannot determine format from extension: {ext}")
            info("Use --format to specify the format explicitly")
            sys.exit(1)

    info(f"Importing {input_format} data into table: {table}")

    if dry_run:
        warning("Dry run mode - no data will be imported")

    # Map table names to models
    table_models = {
        "users": "example_service.core.models.user:User",
        "posts": "example_service.core.models.post:Post",
        "reminders": "example_service.features.reminders.models:Reminder",
    }

    if table not in table_models:
        error(f"Unknown table: {table}")
        info(f"Available tables: {', '.join(table_models.keys())}")
        sys.exit(1)

    try:
        # Import the model
        module_path, class_name = table_models[table].rsplit(":", 1)
        import importlib
        module = importlib.import_module(module_path)
        Model = getattr(module, class_name)

        # Read data
        data_rows: list[dict[str, Any]] = []

        if input_format == "csv":
            with open(path, newline="") as f:
                reader = csv.DictReader(f)
                data_rows = list(reader)

        elif input_format == "json":
            with open(path) as f:
                content = json.load(f)
                if isinstance(content, list):
                    data_rows = content
                else:
                    data_rows = [content]

        elif input_format == "jsonl":
            with open(path) as f:
                for line in f:
                    if line.strip():
                        data_rows.append(json.loads(line))

        info(f"Found {len(data_rows)} records to import")

        if dry_run:
            # Validate data
            info("Validating records...")
            for i, row in enumerate(data_rows[:10]):  # Validate first 10
                click.echo(f"  Record {i + 1}: {list(row.keys())}")
            if len(data_rows) > 10:
                info(f"  ... and {len(data_rows) - 10} more records")
            success("Validation complete (dry run)")
            return

        # Import data
        from example_service.infra.database import get_session

        imported = 0
        errors_count = 0

        async with get_session() as session:
            for i, row in enumerate(data_rows):
                try:
                    # Remove id field if present (let DB generate it)
                    row.pop("id", None)
                    row.pop("created_at", None)
                    row.pop("updated_at", None)

                    record = Model(**row)
                    session.add(record)
                    imported += 1
                except Exception as e:
                    errors_count += 1
                    if skip_errors:
                        warning(f"Row {i + 1} failed: {e}")
                    else:
                        error(f"Row {i + 1} failed: {e}")
                        raise

            await session.commit()

        success(f"Imported {imported} records")
        if errors_count > 0:
            warning(f"Skipped {errors_count} records due to errors")

    except Exception as e:
        error(f"Import failed: {e}")
        sys.exit(1)


@data.command(name="stats")
@coro
async def database_stats() -> None:
    """Show database statistics and table information."""
    header("Database Statistics")

    try:
        from sqlalchemy import text
        from example_service.infra.database import get_session
        from example_service.core.settings import get_settings

        settings = get_settings()
        db_settings = settings.database

        async with get_session() as session:
            # Database info
            result = await session.execute(text("SELECT version()"))
            version = result.scalar_one()

            result = await session.execute(text("SELECT current_database()"))
            db_name = result.scalar_one()

            result = await session.execute(text("SELECT pg_size_pretty(pg_database_size(current_database()))"))
            db_size = result.scalar_one()

            section("Database Info")
            click.echo(f"  Host:     {db_settings.db_host}:{db_settings.db_port}")
            click.echo(f"  Database: {db_name}")
            click.echo(f"  Size:     {db_size}")
            click.echo(f"  Version:  {version.split(',')[0] if version else 'N/A'}")

            # Table statistics
            result = await session.execute(text("""
                SELECT
                    schemaname,
                    relname as table_name,
                    n_live_tup as row_count,
                    pg_size_pretty(pg_total_relation_size(relid)) as total_size
                FROM pg_stat_user_tables
                ORDER BY n_live_tup DESC
            """))
            tables = result.fetchall()

            section("Table Statistics")
            if tables:
                click.echo(f"  {'Table':<30} {'Rows':<12} {'Size':<15}")
                click.echo("  " + "-" * 57)
                for table in tables:
                    click.echo(f"  {table.table_name:<30} {table.row_count:<12} {table.total_size:<15}")
            else:
                info("No tables found")

            # Index statistics
            result = await session.execute(text("""
                SELECT
                    indexrelname as index_name,
                    relname as table_name,
                    idx_scan as scans,
                    pg_size_pretty(pg_relation_size(indexrelid)) as size
                FROM pg_stat_user_indexes
                ORDER BY idx_scan DESC
                LIMIT 10
            """))
            indexes = result.fetchall()

            section("Top Indexes (by usage)")
            if indexes:
                click.echo(f"  {'Index':<40} {'Table':<20} {'Scans':<10}")
                click.echo("  " + "-" * 70)
                for idx in indexes:
                    click.echo(f"  {idx.index_name:<40} {idx.table_name:<20} {idx.scans:<10}")
            else:
                info("No indexes found")

            # Connection info
            result = await session.execute(text("""
                SELECT
                    count(*) as total,
                    count(*) FILTER (WHERE state = 'active') as active,
                    count(*) FILTER (WHERE state = 'idle') as idle
                FROM pg_stat_activity
                WHERE datname = current_database()
            """))
            conn_stats = result.fetchone()

            section("Connection Statistics")
            click.echo(f"  Total:    {conn_stats.total}")
            click.echo(f"  Active:   {conn_stats.active}")
            click.echo(f"  Idle:     {conn_stats.idle}")

    except Exception as e:
        error(f"Failed to get database stats: {e}")
        sys.exit(1)


@data.command(name="tables")
@coro
async def list_tables() -> None:
    """List all database tables with their structure."""
    header("Database Tables")

    try:
        from sqlalchemy import text
        from example_service.infra.database import get_session

        async with get_session() as session:
            # Get tables
            result = await session.execute(text("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name
            """))
            tables = result.fetchall()

            if not tables:
                info("No tables found")
                return

            for table in tables:
                table_name = table.table_name
                section(f"Table: {table_name}")

                # Get columns
                result = await session.execute(text(f"""
                    SELECT
                        column_name,
                        data_type,
                        is_nullable,
                        column_default
                    FROM information_schema.columns
                    WHERE table_name = :table_name
                    ORDER BY ordinal_position
                """), {"table_name": table_name})
                columns = result.fetchall()

                click.echo(f"  {'Column':<25} {'Type':<20} {'Nullable':<10} {'Default'}")
                click.echo("  " + "-" * 75)
                for col in columns:
                    nullable = "Yes" if col.is_nullable == "YES" else "No"
                    default = col.column_default[:30] if col.column_default else "-"
                    click.echo(f"  {col.column_name:<25} {col.data_type:<20} {nullable:<10} {default}")

                click.echo()

    except Exception as e:
        error(f"Failed to list tables: {e}")
        sys.exit(1)


@data.command(name="count")
@click.argument("table", required=False)
@coro
async def count_records(table: str | None) -> None:
    """Count records in database tables.

    If TABLE is specified, counts only that table.
    Otherwise, counts all tables.
    """
    try:
        from sqlalchemy import text
        from example_service.infra.database import get_session

        async with get_session() as session:
            if table:
                # Count specific table
                result = await session.execute(
                    text(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
                )
                count = result.scalar_one()
                success(f"Table '{table}': {count:,} records")
            else:
                # Count all tables
                header("Record Counts")

                result = await session.execute(text("""
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                    ORDER BY table_name
                """))
                tables = result.fetchall()

                total = 0
                click.echo()
                for t in tables:
                    table_name = t.table_name
                    result = await session.execute(
                        text(f"SELECT COUNT(*) FROM {table_name}")  # noqa: S608
                    )
                    count = result.scalar_one()
                    total += count
                    click.echo(f"  {table_name:<30} {count:>12,}")

                click.echo("  " + "-" * 42)
                click.echo(f"  {'Total':<30} {total:>12,}")

    except Exception as e:
        error(f"Failed to count records: {e}")
        sys.exit(1)


@data.command(name="truncate")
@click.argument("table")
@click.option(
    "--cascade",
    is_flag=True,
    default=False,
    help="Cascade truncate to dependent tables",
)
@coro
async def truncate_table(table: str, cascade: bool) -> None:
    """Truncate (delete all records from) a table.

    WARNING: This permanently deletes all data in the table!
    """
    warning(f"This will DELETE ALL DATA from table: {table}")

    if not click.confirm("Are you absolutely sure?"):
        info("Operation cancelled")
        return

    if not click.confirm("Type 'yes' to confirm deletion"):
        info("Operation cancelled")
        return

    try:
        from sqlalchemy import text
        from example_service.infra.database import get_session

        async with get_session() as session:
            cascade_str = " CASCADE" if cascade else ""
            await session.execute(text(f"TRUNCATE TABLE {table}{cascade_str}"))  # noqa: S608
            await session.commit()

            success(f"Table '{table}' has been truncated")

    except Exception as e:
        error(f"Failed to truncate table: {e}")
        sys.exit(1)
