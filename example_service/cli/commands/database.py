"""Database management commands."""

import subprocess
import sys
from pathlib import Path

import click
from sqlalchemy import text

from example_service.cli.utils import coro, error, info, success, warning
from example_service.core.settings import get_settings
from example_service.infra.database import get_session


@click.group(name="db")
def db() -> None:
    """Database management commands."""


@db.command()
@coro
async def init() -> None:
    """Initialize database connection and verify connectivity."""
    info("Initializing database connection...")

    try:
        settings = get_settings()
        db_settings = settings.database

        info(f"Connecting to: {db_settings.db_host}:{db_settings.db_port}/{db_settings.db_name}")

        async with get_session() as session:
            result = await session.execute(text("SELECT version()"))
            version = result.scalar_one()
            success(f"Database connected successfully!")
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
def migrate(message: str, autogenerate: bool) -> None:
    """Create a new database migration."""
    info(f"Creating migration: {message}")

    try:
        cmd = ["alembic", "revision"]
        if autogenerate:
            cmd.append("--autogenerate")
        cmd.extend(["-m", message])

        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        click.echo(result.stdout)

        success("Migration created successfully!")
        info("Run 'example-service db upgrade' to apply the migration")

    except subprocess.CalledProcessError as e:
        error(f"Failed to create migration: {e.stderr}")
        sys.exit(1)


@db.command()
@click.option(
    "--revision",
    default="head",
    help="Target revision (default: head)",
)
def upgrade(revision: str) -> None:
    """Apply database migrations."""
    info(f"Upgrading database to: {revision}")

    try:
        result = subprocess.run(
            ["alembic", "upgrade", revision],
            check=True,
            capture_output=True,
            text=True,
        )
        click.echo(result.stdout)
        success("Database upgraded successfully!")

    except subprocess.CalledProcessError as e:
        error(f"Failed to upgrade database: {e.stderr}")
        sys.exit(1)


@db.command()
@click.option(
    "--steps",
    default=1,
    type=int,
    help="Number of migrations to rollback",
)
def downgrade(steps: int) -> None:
    """Rollback database migrations."""
    warning(f"Rolling back {steps} migration(s)...")

    if not click.confirm("Are you sure you want to rollback migrations?"):
        info("Rollback cancelled")
        return

    try:
        target = f"-{steps}" if steps > 0 else "base"
        result = subprocess.run(
            ["alembic", "downgrade", target],
            check=True,
            capture_output=True,
            text=True,
        )
        click.echo(result.stdout)
        success("Database downgraded successfully!")

    except subprocess.CalledProcessError as e:
        error(f"Failed to downgrade database: {e.stderr}")
        sys.exit(1)


@db.command()
def history() -> None:
    """Show migration history."""
    info("Migration history:")

    try:
        result = subprocess.run(
            ["alembic", "history", "--verbose"],
            check=True,
            capture_output=True,
            text=True,
        )
        click.echo(result.stdout)

    except subprocess.CalledProcessError as e:
        error(f"Failed to get migration history: {e.stderr}")
        sys.exit(1)


@db.command()
def current() -> None:
    """Show current database revision."""
    info("Current database revision:")

    try:
        result = subprocess.run(
            ["alembic", "current", "--verbose"],
            check=True,
            capture_output=True,
            text=True,
        )
        click.echo(result.stdout)

    except subprocess.CalledProcessError as e:
        error(f"Failed to get current revision: {e.stderr}")
        sys.exit(1)


@db.command()
@coro
async def shell() -> None:
    """Open an interactive database shell (psql)."""
    info("Opening database shell...")

    try:
        settings = get_settings()
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
        import os

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

    warning("⚠ Seed command is not yet implemented")
    info("To implement: Add your seed data logic here")
    info("Example: Create sample users, products, or other entities")

    # Example implementation:
    # try:
    #     async with get_session() as session:
    #         for i in range(sample_size):
    #             # Create your sample records here
    #             pass
    #         await session.commit()
    #     success(f"Successfully seeded {sample_size} records!")
    # except Exception as e:
    #     error(f"Failed to seed database: {e}")
    #     sys.exit(1)


@db.command()
@coro
async def reset() -> None:
    """Reset database (drop all tables and re-run migrations)."""
    warning("⚠ This will DELETE ALL DATA in the database!")

    if not click.confirm("Are you sure you want to reset the database?"):
        info("Reset cancelled")
        return

    if not click.confirm("Type 'yes' to confirm", default=False):
        info("Reset cancelled")
        return

    info("Resetting database...")

    try:
        # Downgrade to base
        info("Dropping all tables...")
        subprocess.run(
            ["alembic", "downgrade", "base"],
            check=True,
            capture_output=True,
            text=True,
        )

        # Upgrade to head
        info("Re-running migrations...")
        subprocess.run(
            ["alembic", "upgrade", "head"],
            check=True,
            capture_output=True,
            text=True,
        )

        success("Database reset successfully!")

    except subprocess.CalledProcessError as e:
        error(f"Failed to reset database: {e.stderr}")
        sys.exit(1)


@db.command()
def heads() -> None:
    """Show current revision heads."""
    info("Current revision heads:")

    try:
        result = subprocess.run(
            ["alembic", "heads", "--verbose"],
            check=True,
            capture_output=True,
            text=True,
        )
        click.echo(result.stdout)

    except subprocess.CalledProcessError as e:
        error(f"Failed to get heads: {e.stderr}")
        sys.exit(1)


@db.command()
def branches() -> None:
    """Show branch points in migration history."""
    info("Migration branches:")

    try:
        result = subprocess.run(
            ["alembic", "branches", "--verbose"],
            check=True,
            capture_output=True,
            text=True,
        )
        if result.stdout.strip():
            click.echo(result.stdout)
        else:
            info("No branch points found (linear history)")

    except subprocess.CalledProcessError as e:
        error(f"Failed to get branches: {e.stderr}")
        sys.exit(1)


@db.command(name="show")
@click.argument("revision", default="head")
def show_revision(revision: str) -> None:
    """Show details of a specific migration revision.

    REVISION is the revision identifier (default: head).
    """
    info(f"Showing revision: {revision}")

    try:
        result = subprocess.run(
            ["alembic", "show", revision],
            check=True,
            capture_output=True,
            text=True,
        )
        click.echo(result.stdout)

    except subprocess.CalledProcessError as e:
        error(f"Failed to show revision: {e.stderr}")
        sys.exit(1)


@db.command()
@click.argument("revision")
@click.option(
    "--purge",
    is_flag=True,
    help="Delete revision row from alembic_version",
)
def stamp(revision: str, purge: bool) -> None:
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
        cmd = ["alembic", "stamp", revision]
        if purge:
            cmd.append("--purge")

        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
        )
        click.echo(result.stdout)
        success(f"Database stamped with revision: {revision}")

    except subprocess.CalledProcessError as e:
        error(f"Failed to stamp database: {e.stderr}")
        sys.exit(1)


@db.command()
@coro
async def check() -> None:
    """Check if database migrations are up to date."""
    info("Checking migration status...")

    try:
        # Get current revision
        current_result = subprocess.run(
            ["alembic", "current"],
            check=True,
            capture_output=True,
            text=True,
        )
        current = current_result.stdout.strip()

        # Get head revision
        head_result = subprocess.run(
            ["alembic", "heads"],
            check=True,
            capture_output=True,
            text=True,
        )
        head = head_result.stdout.strip()

        click.echo(f"  Current: {current if current else '(none)'}")
        click.echo(f"  Head:    {head if head else '(none)'}")

        # Check if up to date
        if not current:
            warning("Database has no migrations applied")
            info("Run 'example-service db upgrade' to apply migrations")
        elif "(head)" in current:
            success("Database is up to date!")
        else:
            warning("Database is not at head revision")
            info("Run 'example-service db upgrade' to apply pending migrations")

    except subprocess.CalledProcessError as e:
        error(f"Failed to check migrations: {e.stderr}")
        sys.exit(1)


@db.command()
def diff() -> None:
    """Show pending model changes that would be migrated.

    This checks if there are any model changes that haven't been captured
    in a migration yet.
    """
    info("Checking for model changes...")

    try:
        # Use alembic check to see if there are pending changes
        result = subprocess.run(
            ["alembic", "check"],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            success("No pending model changes detected")
        else:
            warning("Pending model changes detected:")
            if result.stdout:
                click.echo(result.stdout)
            if result.stderr:
                click.echo(result.stderr)
            info("Run 'example-service db migrate -m \"description\"' to create a migration")

    except FileNotFoundError:
        error("alembic command not found")
        sys.exit(1)


@db.command(name="sql")
@click.option(
    "--to",
    "to_rev",
    default="head",
    help="Target revision (default: head)",
)
def generate_sql(to_rev: str) -> None:
    """Generate SQL for migrations (offline mode).

    This outputs the SQL that would be executed without actually running it.
    Useful for reviewing changes or applying to production manually.
    """
    info(f"Generating SQL for migration to: {to_rev}")

    try:
        result = subprocess.run(
            ["alembic", "upgrade", to_rev, "--sql"],
            check=True,
            capture_output=True,
            text=True,
        )
        click.echo(result.stdout)

    except subprocess.CalledProcessError as e:
        error(f"Failed to generate SQL: {e.stderr}")
        sys.exit(1)


@db.command()
@coro
async def pending() -> None:
    """List pending migrations that haven't been applied."""
    info("Checking for pending migrations...")

    try:
        # Get current revision
        current_result = subprocess.run(
            ["alembic", "current"],
            check=True,
            capture_output=True,
            text=True,
        )

        # Get full history
        history_result = subprocess.run(
            ["alembic", "history", "--verbose"],
            check=True,
            capture_output=True,
            text=True,
        )

        current = current_result.stdout.strip()

        if "(head)" in current:
            success("No pending migrations - database is up to date")
            return

        click.echo("\nMigration history:")
        click.echo(history_result.stdout)

        info("\nRun 'example-service db upgrade' to apply pending migrations")

    except subprocess.CalledProcessError as e:
        error(f"Failed to check pending migrations: {e.stderr}")
        sys.exit(1)


@db.command()
@click.argument("message", required=True)
def merge(message: str) -> None:
    """Create a merge migration for multiple heads.

    MESSAGE is the description for the merge migration.

    This is used when you have multiple branch heads that need to be merged.
    """
    info(f"Creating merge migration: {message}")

    try:
        result = subprocess.run(
            ["alembic", "merge", "-m", message, "heads"],
            check=True,
            capture_output=True,
            text=True,
        )
        click.echo(result.stdout)
        success("Merge migration created successfully!")

    except subprocess.CalledProcessError as e:
        error(f"Failed to create merge migration: {e.stderr}")
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
    from example_service.cli.utils import header, section

    header("Database Information")

    try:
        settings = get_settings()
        db_settings = settings.database

        if output_format == "json":
            import json
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
        async with get_session() as session:
            result = await session.execute(text("SELECT version()"))
            version = result.scalar_one()

            result = await session.execute(
                text("SELECT pg_size_pretty(pg_database_size(current_database()))")
            )
            db_size = result.scalar_one()

            section("Server Information")
            click.echo(f"  Version:      {version.split(',')[0] if version else 'N/A'}")
            click.echo(f"  Size:         {db_size}")

            # Migration info
            section("Migration Status")
            current_result = subprocess.run(
                ["alembic", "current"],
                capture_output=True,
                text=True,
            )
            current = current_result.stdout.strip() if current_result.returncode == 0 else "Unknown"
            click.echo(f"  Current:      {current if current else '(none)'}")

    except Exception as e:
        error(f"Failed to get database info: {e}")
        sys.exit(1)
