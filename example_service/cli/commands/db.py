"""Database management commands."""
from __future__ import annotations

import asyncio

import click


@click.group()
def db() -> None:
    """Database management commands."""
    pass


@db.command()
def init() -> None:
    """Initialize database (create all tables).

    Creates all tables defined in SQLAlchemy models.

    Example:
        example-service db init
    """
    click.echo("Initializing database...")

    async def _init() -> None:
        from example_service.infra.database.base import Base
        from example_service.infra.database.session import get_engine

        # Import all models to register them
        from example_service.core.models import item  # noqa: F401

        engine = get_engine()

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        click.echo("✓ Database tables created successfully")

    try:
        asyncio.run(_init())
    except Exception as e:
        click.echo(f"❌ Failed to initialize database: {e}", err=True)
        raise click.Abort()


@db.command()
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Skip confirmation prompt",
)
def drop() -> None:
    """Drop all database tables.

    WARNING: This will delete all data!

    Example:
        example-service db drop --yes
    """
    if not click.confirm("⚠️  This will DELETE ALL DATA. Continue?"):
        click.echo("Aborted.")
        return

    click.echo("Dropping all tables...")

    async def _drop() -> None:
        from example_service.infra.database.base import Base
        from example_service.infra.database.session import get_engine

        # Import all models
        from example_service.core.models import item  # noqa: F401

        engine = get_engine()

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

        click.echo("✓ All tables dropped")

    try:
        asyncio.run(_drop())
    except Exception as e:
        click.echo(f"❌ Failed to drop tables: {e}", err=True)
        raise click.Abort()


@db.command()
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Skip confirmation prompt",
)
def reset() -> None:
    """Reset database (drop and recreate all tables).

    WARNING: This will delete all data!

    Example:
        example-service db reset --yes
    """
    if not click.confirm("⚠️  This will DELETE ALL DATA and recreate tables. Continue?"):
        click.echo("Aborted.")
        return

    click.echo("Resetting database...")

    async def _reset() -> None:
        from example_service.infra.database.base import Base
        from example_service.infra.database.session import get_engine

        # Import all models
        from example_service.core.models import item  # noqa: F401

        engine = get_engine()

        async with engine.begin() as conn:
            # Drop all
            await conn.run_sync(Base.metadata.drop_all)
            click.echo("✓ Dropped all tables")

            # Create all
            await conn.run_sync(Base.metadata.create_all)
            click.echo("✓ Created all tables")

        click.echo("✓ Database reset complete")

    try:
        asyncio.run(_reset())
    except Exception as e:
        click.echo(f"❌ Failed to reset database: {e}", err=True)
        raise click.Abort()


@db.command()
def check() -> None:
    """Check database connection.

    Example:
        example-service db check
    """
    click.echo("Checking database connection...")

    async def _check() -> None:
        from sqlalchemy import text

        from example_service.infra.database.session import get_engine

        engine = get_engine()

        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            click.echo("✓ Database connection successful")

            # Show database info
            db_url = str(engine.url)
            # Hide password
            if "@" in db_url:
                parts = db_url.split("@")
                user_part = parts[0].split("://")[1].split(":")[0]
                db_url = f"{parts[0].split('://')[0]}://{user_part}:***@{parts[1]}"

            click.echo(f"  URL: {db_url}")

        except Exception as e:
            click.echo(f"❌ Database connection failed: {e}", err=True)
            raise

    try:
        asyncio.run(_check())
    except Exception:
        raise click.Abort()


@db.command()
def shell() -> None:
    """Open database shell (psql for PostgreSQL).

    Example:
        example-service db shell
    """
    import os
    import subprocess

    from example_service.core.settings import get_db_settings

    settings = get_db_settings()

    if not settings.is_configured:
        click.echo("❌ Database not configured", err=True)
        raise click.Abort()

    db_url = str(settings.database_url)

    if "postgresql" in db_url:
        click.echo("Opening PostgreSQL shell...")
        # Use psql if available
        try:
            subprocess.run(["psql", db_url], check=False)
        except FileNotFoundError:
            click.echo("❌ psql not found. Install PostgreSQL client.", err=True)
            raise click.Abort()
    elif "sqlite" in db_url:
        click.echo("Opening SQLite shell...")
        db_file = db_url.split("///")[1] if "///" in db_url else "test.db"
        try:
            subprocess.run(["sqlite3", db_file], check=False)
        except FileNotFoundError:
            click.echo("❌ sqlite3 not found. Install SQLite.", err=True)
            raise click.Abort()
    else:
        click.echo(f"❌ Unsupported database type: {db_url.split(':')[0]}", err=True)
        raise click.Abort()
