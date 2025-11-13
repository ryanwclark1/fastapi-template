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
