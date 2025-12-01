"""Database management commands using programmatic Alembic API.

This module provides CLI commands for database operations using the
AlembicCommands class instead of subprocess calls. All commands are
async-compatible and use the project's infrastructure layer.

Example:bash
    # Apply all pending migrations
    example-service db upgrade

    # Create new migration
    example-service db migrate -m "Add user avatar"

    # Check migration status
    example-service db check

    # Rollback last migration
    example-service db downgrade

    # Drop all tables (development only!)
    example-service db drop-all --confirm
"""

import json
import sys

import click
from sqlalchemy import text

from example_service.cli.utils import coro, error, header, info, section, success, warning
from example_service.core.settings import get_app_settings


def get_alembic_commands():
    """Get AlembicCommands instance with lazy import.

    Lazy import avoids circular dependencies and ensures proper
    initialization order.

    Returns:
        Configured AlembicCommands instance
    """
    from example_service.infra.database.alembic import get_alembic_commands

    return get_alembic_commands()


@click.group(name="db")
def db() -> None:
    """Database management commands."""


# =============================================================================
# Connection & Status Commands
# =============================================================================


@db.command()
@coro
async def init() -> None:
    """Initialize database connection and verify connectivity."""
    info("Initializing database connection...")

    try:
        from example_service.infra.database import get_async_session

        settings = get_app_settings()
        db_settings = settings.database

        info(f"Connecting to: {db_settings.db_host}:{db_settings.db_port}/{db_settings.db_name}")

        async with get_async_session() as session:
            result = await session.execute(text("SELECT version()"))
            version = result.scalar_one()
            success("Database connected successfully!")
            info(f"PostgreSQL version: {version}")

            # Check if tables exist
            result = await session.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                """
                )
            )
            table_count = result.scalar_one()
            info(f"Tables in public schema: {table_count}")

    except Exception as e:
        error(f"Failed to connect to database: {e}")
        sys.exit(1)


@db.command()
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format",
)
@coro
async def info_cmd(output_format: str) -> None:
    """Show database connection info and statistics."""
    from example_service.infra.database import get_async_session

    header("Database Information")

    try:
        settings = get_app_settings()
        db_settings = settings.database

        if output_format == "json":
            info_dict = {
                "host": db_settings.db_host,
                "port": db_settings.db_port,
                "database": db_settings.db_name,
                "user": db_settings.db_user,
                "pool_size": db_settings.db_pool_size,
                "max_overflow": db_settings.db_max_overflow,
            }
            click.echo(json.dumps(info_dict, indent=2))
            return

        section("Connection Settings")
        click.echo(f"  Host:         {db_settings.db_host}")
        click.echo(f"  Port:         {db_settings.db_port}")
        click.echo(f"  Database:     {db_settings.db_name}")
        click.echo(f"  User:         {db_settings.db_user}")
        click.echo(f"  Pool Size:    {db_settings.db_pool_size}")
        click.echo(f"  Max Overflow: {db_settings.db_max_overflow}")

        # Try to connect and get version
        async with get_async_session() as session:
            result = await session.execute(text("SELECT version()"))
            version = result.scalar_one()

            result = await session.execute(
                text("SELECT pg_size_pretty(pg_database_size(current_database()))")
            )
            db_size = result.scalar_one()

            section("Server Information")
            click.echo(f"  Version:      {version.split(',')[0] if version else 'N/A'}")
            click.echo(f"  Size:         {db_size}")

            # Migration info using programmatic API
            section("Migration Status")
            commands = get_alembic_commands()
            current = await commands.get_current_revision()
            is_current = await commands.is_up_to_date()
            click.echo(f"  Current:      {current if current else '(none)'}")
            click.echo(f"  Up to date:   {'Yes' if is_current else 'No'}")

    except Exception as e:
        error(f"Failed to get database info: {e}")
        sys.exit(1)


# =============================================================================
# Migration Commands
# =============================================================================


@db.command()
@click.option(
    "-m",
    "--message",
    required=True,
    help="Migration message",
)
@click.option(
    "--autogenerate/--no-autogenerate",
    default=True,
    help="Auto-generate migration from models",
)
@coro
async def migrate(message: str, autogenerate: bool) -> None:
    """Create a new database migration."""
    info(f"Creating migration: {message}")

    try:
        commands = get_alembic_commands()
        output = await commands.revision(message, autogenerate=autogenerate)

        if output:
            click.echo(output)

        success("Migration created successfully!")
        info("Run 'example-service db upgrade' to apply the migration")

    except Exception as e:
        error(f"Failed to create migration: {e}")
        sys.exit(1)


@db.command()
@click.option(
    "--revision",
    default="head",
    help="Target revision (default: head)",
)
@click.option(
    "--sql/--no-sql",
    default=False,
    help="Output SQL without executing",
)
@coro
async def upgrade(revision: str, sql: bool) -> None:
    """Apply database migrations."""
    info(f"Upgrading database to: {revision}")

    try:
        commands = get_alembic_commands()
        output = await commands.upgrade(revision, sql=sql)

        if output:
            click.echo(output)

        if not sql:
            success("Database upgraded successfully!")

    except Exception as e:
        error(f"Failed to upgrade database: {e}")
        sys.exit(1)


@db.command()
@click.option(
    "--steps",
    default=1,
    type=int,
    help="Number of migrations to rollback",
)
@click.option(
    "--sql/--no-sql",
    default=False,
    help="Output SQL without executing",
)
@coro
async def downgrade(steps: int, sql: bool) -> None:
    """Rollback database migrations."""
    if not sql:
        warning(f"Rolling back {steps} migration(s)...")

        if not click.confirm("Are you sure you want to rollback migrations?"):
            info("Rollback cancelled")
            return

    try:
        commands = get_alembic_commands()
        target = f"-{steps}" if steps > 0 else "base"
        output = await commands.downgrade(target, sql=sql)

        if output:
            click.echo(output)

        if not sql:
            success("Database downgraded successfully!")

    except Exception as e:
        error(f"Failed to downgrade database: {e}")
        sys.exit(1)


@db.command()
@coro
async def history() -> None:
    """Show migration history."""
    info("Migration history:")

    try:
        commands = get_alembic_commands()
        output = await commands.history(verbose=True, indicate_current=True)

        if output:
            click.echo(output)
        else:
            info("No migrations found")

    except Exception as e:
        error(f"Failed to get migration history: {e}")
        sys.exit(1)


@db.command()
@coro
async def current() -> None:
    """Show current database revision."""
    info("Current database revision:")

    try:
        commands = get_alembic_commands()
        output = await commands.current(verbose=True)

        if output:
            click.echo(output)
        else:
            info("No migrations applied")

    except Exception as e:
        error(f"Failed to get current revision: {e}")
        sys.exit(1)


@db.command()
@coro
async def heads() -> None:
    """Show current revision heads."""
    info("Current revision heads:")

    try:
        commands = get_alembic_commands()
        output = await commands.heads(verbose=True)

        if output:
            click.echo(output)
        else:
            info("No heads found")

    except Exception as e:
        error(f"Failed to get heads: {e}")
        sys.exit(1)


@db.command()
@coro
async def branches() -> None:
    """Show branch points in migration history."""
    info("Migration branches:")

    try:
        commands = get_alembic_commands()
        output = await commands.branches(verbose=True)

        if output.strip():
            click.echo(output)
        else:
            info("No branch points found (linear history)")

    except Exception as e:
        error(f"Failed to get branches: {e}")
        sys.exit(1)


@db.command(name="show")
@click.argument("revision", default="head")
@coro
async def show_revision(revision: str) -> None:
    """Show details of a specific migration revision.

    REVISION is the revision identifier (default: head).
    """
    info(f"Showing revision: {revision}")

    try:
        commands = get_alembic_commands()
        output = await commands.show(revision)

        if output:
            click.echo(output)

    except Exception as e:
        error(f"Failed to show revision: {e}")
        sys.exit(1)


@db.command()
@click.argument("revision")
@click.option(
    "--purge",
    is_flag=True,
    help="Delete revision row from alembic_version",
)
@coro
async def stamp(revision: str, purge: bool) -> None:
    """Stamp the database with a specific revision without running migrations.

    This is useful for marking the database as being at a specific revision
    when you've applied migrations manually or are initializing a new database.

    REVISION is the revision to stamp (e.g., 'head', 'base', or a specific hash).
    """
    warning(f"Stamping database with revision: {revision}")

    if not click.confirm("This will modify alembic_version table. Continue?"):
        info("Stamp cancelled")
        return

    try:
        commands = get_alembic_commands()
        output = await commands.stamp(revision, purge=purge)

        if output:
            click.echo(output)

        success(f"Database stamped with revision: {revision}")

    except Exception as e:
        error(f"Failed to stamp database: {e}")
        sys.exit(1)


@db.command()
@click.argument("message", required=True)
@coro
async def merge(message: str) -> None:
    """Create a merge migration for multiple heads.

    MESSAGE is the description for the merge migration.

    This is used when you have multiple branch heads that need to be merged.
    """
    info(f"Creating merge migration: {message}")

    try:
        commands = get_alembic_commands()
        output = await commands.merge(message=message)

        if output:
            click.echo(output)

        success("Merge migration created successfully!")

    except Exception as e:
        error(f"Failed to create merge migration: {e}")
        sys.exit(1)


@db.command()
@coro
async def check() -> None:
    """Check if database migrations are up to date."""
    info("Checking migration status...")

    try:
        commands = get_alembic_commands()

        current = await commands.get_current_revision()
        head = await commands.get_head_revision()
        is_current = await commands.is_up_to_date()

        click.echo(f"  Current: {current if current else '(none)'}")
        click.echo(f"  Head:    {head if head else '(none)'}")

        if not current:
            warning("Database has no migrations applied")
            info("Run 'example-service db upgrade' to apply migrations")
        elif is_current:
            success("Database is up to date!")
        else:
            pending = await commands.get_pending_revisions()
            warning(f"Database has {len(pending)} pending migration(s)")
            for rev in pending:
                click.echo(f"    - {rev}")
            info("Run 'example-service db upgrade' to apply pending migrations")

    except Exception as e:
        error(f"Failed to check migrations: {e}")
        sys.exit(1)


@db.command()
@coro
async def pending() -> None:
    """List pending migrations that haven't been applied."""
    info("Checking for pending migrations...")

    try:
        commands = get_alembic_commands()

        pending = await commands.get_pending_revisions()

        if not pending:
            success("No pending migrations - database is up to date")
            return

        warning(f"Found {len(pending)} pending migration(s):")
        for rev in pending:
            click.echo(f"  - {rev}")

        info("\nRun 'example-service db upgrade' to apply pending migrations")

    except Exception as e:
        error(f"Failed to check pending migrations: {e}")
        sys.exit(1)


@db.command()
@coro
async def diff() -> None:
    """Show pending model changes that would be migrated.

    This checks if there are any model changes that haven't been captured
    in a migration yet.
    """
    info("Checking for model changes...")

    try:
        commands = get_alembic_commands()
        is_current, output = await commands.check()

        if is_current:
            success("No pending model changes detected")
        else:
            warning("Pending model changes detected:")
            if output:
                click.echo(output)
            info("Run 'example-service db migrate -m \"description\"' to create a migration")

    except Exception as e:
        error(f"Failed to check for changes: {e}")
        sys.exit(1)


@db.command(name="sql")
@click.option(
    "--to",
    "to_rev",
    default="head",
    help="Target revision (default: head)",
)
@coro
async def generate_sql(to_rev: str) -> None:
    """Generate SQL for migrations (offline mode).

    This outputs the SQL that would be executed without actually running it.
    Useful for reviewing changes or applying to production manually.
    """
    info(f"Generating SQL for migration to: {to_rev}")

    try:
        commands = get_alembic_commands()
        output = await commands.upgrade(to_rev, sql=True)

        if output:
            click.echo(output)

    except Exception as e:
        error(f"Failed to generate SQL: {e}")
        sys.exit(1)


# =============================================================================
# Schema Utility Commands
# =============================================================================


@db.command(name="drop-all")
@click.option("--include-alembic", is_flag=True, help="Also drop alembic_version table")
@click.option("--cascade", is_flag=True, help="Use CASCADE (PostgreSQL)")
@click.option("--confirm", is_flag=True, help="Skip confirmation prompt")
@coro
async def drop_all_cmd(include_alembic: bool, cascade: bool, confirm: bool) -> None:
    """Drop all database tables.

    WARNING: This is a destructive operation that cannot be undone!
    """
    warning("This will DELETE ALL TABLES in the database!")

    if not confirm:
        if not click.confirm("Are you sure you want to drop all tables?"):
            info("Drop cancelled")
            return
        if not click.confirm("This action cannot be undone. Type 'yes' to confirm"):
            info("Drop cancelled")
            return

    try:
        from example_service.infra.database import engine
        from example_service.infra.database.schema import drop_all

        dropped = await drop_all(
            engine,
            include_alembic=include_alembic,
            cascade=cascade,
        )

        success(f"Dropped {len(dropped)} tables:")
        for table in dropped:
            click.echo(f"  - {table}")

    except Exception as e:
        error(f"Failed to drop tables: {e}")
        sys.exit(1)


@db.command(name="truncate")
@click.option("--exclude", multiple=True, help="Tables to exclude")
@click.option("--confirm", is_flag=True, help="Skip confirmation prompt")
@coro
async def truncate_cmd(exclude: tuple[str, ...], confirm: bool) -> None:
    """Truncate all tables (keep schema, delete data).

    Faster than drop + recreate for resetting test data.
    """
    warning("This will DELETE ALL DATA in the database!")

    if not confirm and not click.confirm("Are you sure you want to truncate all tables?"):
        info("Truncate cancelled")
        return

    try:
        from example_service.infra.database import engine
        from example_service.infra.database.schema import truncate_all

        exclude_list = list(exclude) + ["alembic_version"]
        truncated = await truncate_all(engine, exclude_tables=exclude_list)

        success(f"Truncated {len(truncated)} tables:")
        for table in truncated:
            click.echo(f"  - {table}")

    except Exception as e:
        error(f"Failed to truncate tables: {e}")
        sys.exit(1)


@db.command(name="dump-schema")
@click.option("--format", "output_format", type=click.Choice(["json", "yaml"]), default="json")
@click.option("--include-counts", is_flag=True, help="Include row counts (slower)")
@coro
async def dump_schema_cmd(output_format: str, include_counts: bool) -> None:
    """Dump database schema information."""
    try:
        from example_service.infra.database import engine
        from example_service.infra.database.schema import dump_schema

        schema = await dump_schema(engine, include_row_counts=include_counts)

        if output_format == "json":
            click.echo(json.dumps(schema, indent=2, default=str))
        else:
            import yaml

            click.echo(yaml.dump(schema, default_flow_style=False))

    except Exception as e:
        error(f"Failed to dump schema: {e}")
        sys.exit(1)


@db.command(name="validate")
@coro
async def validate_cmd() -> None:
    """Validate database schema matches models."""
    info("Validating schema against models...")

    try:
        from example_service.core.database import Base
        from example_service.infra.database import engine
        from example_service.infra.database.schema import compare_schema

        differences = await compare_schema(engine, Base.metadata)

        if not differences:
            success("Schema is valid - database matches models")
        else:
            warning(f"Found {len(differences)} difference(s):")
            for diff in differences:
                click.echo(f"  [{diff.type}] {diff.table}")
                if diff.column:
                    click.echo(f"    Column: {diff.column}")
                click.echo(f"    {diff.message}")

            info("\nRun 'example-service db migrate -m \"description\"' to create migration")

    except Exception as e:
        error(f"Failed to validate schema: {e}")
        sys.exit(1)


# =============================================================================
# Other Commands
# =============================================================================


@db.command()
@coro
async def shell() -> None:
    """Open an interactive database shell (psql)."""
    import os
    import subprocess

    info("Opening database shell...")

    try:
        settings = get_app_settings()
        db_settings = settings.database

        # Build psql connection string
        psql_cmd = [
            "psql",
            "-h",
            db_settings.db_host,
            "-p",
            str(db_settings.db_port),
            "-U",
            db_settings.db_user,
            "-d",
            db_settings.db_name,
        ]

        # Set password environment variable
        env = os.environ.copy()
        env["PGPASSWORD"] = db_settings.db_password.get_secret_value()

        # Run psql interactively
        subprocess.run(psql_cmd, env=env)

    except FileNotFoundError:
        error("psql command not found. Please install PostgreSQL client tools.")
        sys.exit(1)
    except Exception as e:
        error(f"Failed to open database shell: {e}")
        sys.exit(1)


@db.command()
@click.option(
    "--sample-size",
    default=10,
    type=int,
    help="Number of sample records to create",
)
@coro
async def seed(sample_size: int) -> None:
    """Seed the database with sample data."""
    info(f"Seeding database with {sample_size} sample records...")

    warning("Seed command is not yet implemented")
    info("To implement: Add your seed data logic here")
    info("Example: Create sample users, products, or other entities")


@db.command()
@click.option("--confirm", is_flag=True, help="Skip confirmation prompts")
@coro
async def reset(confirm: bool) -> None:
    """Reset database (drop all tables and re-run migrations)."""
    warning("This will DELETE ALL DATA in the database!")

    if not confirm:
        if not click.confirm("Are you sure you want to reset the database?"):
            info("Reset cancelled")
            return

        if not click.confirm("Type 'yes' to confirm", default=False):
            info("Reset cancelled")
            return

    info("Resetting database...")

    try:
        commands = get_alembic_commands()

        # Downgrade to base
        info("Dropping all tables...")
        await commands.downgrade("base")

        # Upgrade to head
        info("Re-running migrations...")
        await commands.upgrade("head")

        success("Database reset successfully!")

    except Exception as e:
        error(f"Failed to reset database: {e}")
        sys.exit(1)
