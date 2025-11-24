"""Migration runner utilities with async support.

This module provides programmatic access to Alembic migrations,
allowing them to be run during application startup or in deployment scripts.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

logger = logging.getLogger(__name__)


def get_alembic_config() -> Config:
    """Get Alembic configuration.

    Returns:
        Alembic Config object configured for the project.
    """
    # Get the project root (where alembic.ini is located)
    project_root = Path(__file__).parent.parent.parent.parent
    alembic_ini_path = project_root / "alembic.ini"

    if not alembic_ini_path.exists():
        raise FileNotFoundError(f"alembic.ini not found at {alembic_ini_path}")

    config = Config(str(alembic_ini_path))
    return config


async def run_migrations(
    target: str = "head",
    *,
    dry_run: bool = False,
) -> None:
    """Run database migrations asynchronously.

    This function runs Alembic migrations in a background thread to avoid
    blocking the event loop. It's designed to be called during application
    startup or in deployment scripts.

    Args:
        target: Migration target revision (default: "head" for latest)
        dry_run: If True, show what would be done without applying changes

    Raises:
        Exception: If migration fails

    Example:
        ```python
        # In application startup
        await run_migrations()

        # In deployment script
        await run_migrations(target="head")
        ```
    """
    logger.info(f"Running migrations to target: {target}")

    try:
        config = get_alembic_config()

        # Run Alembic command in a thread pool to avoid blocking
        def _run():
            if dry_run:
                logger.info("DRY RUN: Would apply migrations")
                command.show(config, target)
            else:
                command.upgrade(config, target)

        await asyncio.to_thread(_run)

        logger.info(f"Migrations completed successfully to: {target}")

    except Exception as e:
        logger.exception(f"Failed to run migrations: {e}")
        raise


async def rollback_migrations(
    target: str = "-1",
    *,
    dry_run: bool = False,
) -> None:
    """Rollback database migrations asynchronously.

    Args:
        target: Migration target revision (default: "-1" for one step back)
        dry_run: If True, show what would be done without applying changes

    Raises:
        Exception: If rollback fails

    Example:
        ```python
        # Rollback one migration
        await rollback_migrations()

        # Rollback to specific revision
        await rollback_migrations(target="abc123")

        # Rollback all migrations
        await rollback_migrations(target="base")
        ```
    """
    logger.warning(f"Rolling back migrations to target: {target}")

    try:
        config = get_alembic_config()

        # Run Alembic command in a thread pool to avoid blocking
        def _run():
            if dry_run:
                logger.info("DRY RUN: Would rollback migrations")
                command.show(config, target)
            else:
                command.downgrade(config, target)

        await asyncio.to_thread(_run)

        logger.info(f"Rollback completed successfully to: {target}")

    except Exception as e:
        logger.exception(f"Failed to rollback migrations: {e}")
        raise


async def create_migration(
    message: str,
    *,
    autogenerate: bool = True,
) -> None:
    """Create a new migration revision.

    Args:
        message: Description of the migration
        autogenerate: If True, auto-generate migration from models (default)

    Raises:
        Exception: If migration creation fails

    Example:
        ```python
        # Create auto-generated migration
        await create_migration("Add user table")

        # Create empty migration
        await create_migration("Custom migration", autogenerate=False)
        ```
    """
    logger.info(f"Creating migration: {message}")

    try:
        config = get_alembic_config()

        # Run Alembic command in a thread pool to avoid blocking
        def _run():
            command.revision(
                config,
                message=message,
                autogenerate=autogenerate,
            )

        await asyncio.to_thread(_run)

        logger.info(f"Migration created successfully: {message}")

    except Exception as e:
        logger.exception(f"Failed to create migration: {e}")
        raise


def get_current_revision() -> str | None:
    """Get the current database revision.

    Returns:
        Current revision string or None if no migrations applied

    Example:
        ```python
        revision = get_current_revision()
        print(f"Current revision: {revision}")
        ```
    """
    try:
        config = get_alembic_config()

        # This is sync, but typically fast
        from alembic.script import ScriptDirectory
        from alembic.runtime.migration import MigrationContext
        from example_service.infra.database import engine

        script = ScriptDirectory.from_config(config)

        with engine.sync_engine.begin() as conn:
            context = MigrationContext.configure(conn)
            current = context.get_current_revision()
            return current

    except Exception as e:
        logger.exception(f"Failed to get current revision: {e}")
        return None


async def is_database_up_to_date() -> bool:
    """Check if database is up to date with latest migrations.

    Returns:
        True if database is at head revision, False otherwise

    Example:
        ```python
        if not await is_database_up_to_date():
            await run_migrations()
        ```
    """
    try:
        config = get_alembic_config()

        # Run in thread pool
        def _check():
            from alembic.script import ScriptDirectory
            from alembic.runtime.migration import MigrationContext
            from example_service.infra.database import engine

            script = ScriptDirectory.from_config(config)

            with engine.sync_engine.begin() as conn:
                context = MigrationContext.configure(conn)
                current = context.get_current_revision()
                head = script.get_current_head()
                return current == head

        return await asyncio.to_thread(_check)

    except Exception as e:
        logger.exception(f"Failed to check migration status: {e}")
        return False
