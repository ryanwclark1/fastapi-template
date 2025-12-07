"""Programmatic Alembic command interface with async support.

This module provides a clean Python API for Alembic migration operations,
replacing subprocess calls with direct use of the Alembic library.
Inspired by advanced-alchemy's AlembicCommands pattern.

Example:
    from example_service.infra.database.alembic import AlembicCommands, AlembicCommandConfig

    # Get configured commands instance
    commands = get_alembic_commands()

    # Run migrations
    output = await commands.upgrade("head")

    # Check status
    is_current = await commands.is_up_to_date()

    # Create new migration
    output = await commands.revision("Add user avatar column")
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import io
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from alembic import command

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


@dataclass
class AlembicCommandConfig:
    """Configuration for Alembic commands.

    Attributes:
        engine: SQLAlchemy async engine for database operations
        script_location: Path to alembic scripts directory (default: "alembic")
        version_table_name: Table name for version tracking (default: "alembic_version")
        render_as_batch: Enable batch mode for migrations (required for SQLite)
        compare_type: Enable type comparison in autogenerate
        compare_server_default: Compare server defaults in autogenerate
        user_module_prefix: Prefix for custom types in migrations
        include_schemas: Include schema names in operations

    Example:
            config = AlembicCommandConfig(
            engine=engine,
            compare_type=True,
            render_as_batch=False,
        )
        commands = AlembicCommands(config)
    """

    engine: AsyncEngine
    script_location: str = "alembic"
    version_table_name: str = "alembic_version"
    render_as_batch: bool = False
    compare_type: bool = True
    compare_server_default: bool = False
    user_module_prefix: str | None = "example_service.core.database.types."
    include_schemas: bool = False

    # Internal cached config
    _config: Config | None = field(default=None, init=False, repr=False)

    def get_alembic_config(self, output_buffer: io.StringIO | None = None) -> Config:
        """Get or create Alembic configuration.

        Args:
            output_buffer: Optional StringIO to capture command output

        Returns:
            Configured Alembic Config object
        """
        project_root = Path(__file__).parent.parent.parent.parent
        alembic_ini_path = project_root / "alembic.ini"

        if not alembic_ini_path.exists():
            raise FileNotFoundError(f"alembic.ini not found at {alembic_ini_path}")

        config = Config(str(alembic_ini_path), stdout=output_buffer or io.StringIO())
        config.set_main_option("script_location", self.script_location)

        # Set the database URL from engine (overrides alembic.ini placeholder)
        # Use render_as_string to include the password (str() masks it)
        config.set_main_option(
            "sqlalchemy.url", self.engine.url.render_as_string(hide_password=False)
        )

        # Store attributes for env.py access via config.attributes
        config.attributes["engine"] = self.engine
        config.attributes["render_as_batch"] = self.render_as_batch
        config.attributes["compare_type"] = self.compare_type
        config.attributes["compare_server_default"] = self.compare_server_default
        config.attributes["user_module_prefix"] = self.user_module_prefix
        config.attributes["include_schemas"] = self.include_schemas
        config.attributes["version_table_name"] = self.version_table_name

        return config


class AlembicCommands:
    """Programmatic interface for Alembic migration operations.

    Provides a clean Python API for all Alembic commands without subprocess calls.
    All methods run operations in a thread pool to avoid blocking the async event loop.

    Example:
            from example_service.infra.database import engine
        from example_service.infra.database.alembic import AlembicCommands, AlembicCommandConfig

        config = AlembicCommandConfig(engine=engine)
        commands = AlembicCommands(config)

        # Run migrations
        output = await commands.upgrade("head")
        print(output)

        # Check current revision
        revision = await commands.get_current_revision()

        # Generate migration
        output = await commands.revision("Add users table", autogenerate=True)
    """

    def __init__(self, config: AlembicCommandConfig) -> None:
        """Initialize AlembicCommands.

        Args:
            config: AlembicCommandConfig with engine and settings
        """
        self.config = config

    # =========================================================================
    # Migration Commands
    # =========================================================================

    async def upgrade(
        self,
        revision: str = "head",
        *,
        sql: bool = False,
        tag: str | None = None,
    ) -> str:
        """Upgrade database to a specified revision.

        Args:
            revision: Target revision (default: "head" for latest)
            sql: If True, output SQL without executing
            tag: Optional tag for the revision

        Returns:
            Output from the upgrade operation

        Example:
                    # Upgrade to latest
            output = await commands.upgrade()

            # Upgrade to specific revision
            output = await commands.upgrade("abc123")

            # Generate SQL without executing
            sql = await commands.upgrade(sql=True)
        """
        logger.info(f"Upgrading database to revision: {revision}")
        output = io.StringIO()
        alembic_config = self.config.get_alembic_config(output)

        def _run() -> None:
            command.upgrade(alembic_config, revision, sql=sql, tag=tag)

        await asyncio.to_thread(_run)
        result = output.getvalue()
        logger.info(f"Upgrade completed to: {revision}")
        return result

    async def downgrade(
        self,
        revision: str = "-1",
        *,
        sql: bool = False,
        tag: str | None = None,
    ) -> str:
        """Downgrade database to a specified revision.

        Args:
            revision: Target revision (default: "-1" for one step back)
            sql: If True, output SQL without executing
            tag: Optional tag for the revision

        Returns:
            Output from the downgrade operation

        Example:
                    # Downgrade one step
            output = await commands.downgrade()

            # Downgrade to specific revision
            output = await commands.downgrade("abc123")

            # Rollback all migrations
            output = await commands.downgrade("base")
        """
        logger.warning(f"Downgrading database to revision: {revision}")
        output = io.StringIO()
        alembic_config = self.config.get_alembic_config(output)

        def _run() -> None:
            command.downgrade(alembic_config, revision, sql=sql, tag=tag)

        await asyncio.to_thread(_run)
        result = output.getvalue()
        logger.info(f"Downgrade completed to: {revision}")
        return result

    async def revision(
        self,
        message: str,
        *,
        autogenerate: bool = True,
        sql: bool = False,
        head: str = "head",
        splice: bool = False,
        branch_label: str | None = None,
        version_path: str | None = None,
        rev_id: str | None = None,
        depends_on: str | None = None,
    ) -> str:
        """Create a new revision file.

        Args:
            message: Revision message/description
            autogenerate: Auto-detect schema changes from models (default: True)
            sql: Output SQL for offline mode
            head: Head revision to build from
            splice: Allow non-head revisions
            branch_label: Label for branch
            version_path: Custom path for version file
            rev_id: Explicit revision ID
            depends_on: Revision dependencies

        Returns:
            Output including path to new revision file

        Example:
                    # Create auto-generated migration
            output = await commands.revision("Add user table")

            # Create empty migration
            output = await commands.revision("Custom migration", autogenerate=False)
        """
        logger.info(f"Creating migration: {message}")
        output = io.StringIO()
        alembic_config = self.config.get_alembic_config(output)

        def _run() -> None:
            command.revision(
                alembic_config,
                message=message,
                autogenerate=autogenerate,
                sql=sql,
                head=head,
                splice=splice,
                branch_label=branch_label,
                version_path=version_path,
                rev_id=rev_id,
                depends_on=depends_on,
            )

        await asyncio.to_thread(_run)
        result = output.getvalue()
        logger.info(f"Migration created: {message}")
        return result

    # =========================================================================
    # Information Commands
    # =========================================================================

    async def current(self, *, verbose: bool = False) -> str:
        """Show current database revision.

        Args:
            verbose: Include additional details

        Returns:
            Current revision information
        """
        output = io.StringIO()
        alembic_config = self.config.get_alembic_config(output)

        def _run() -> None:
            command.current(alembic_config, verbose=verbose)

        await asyncio.to_thread(_run)
        return output.getvalue()

    async def history(
        self,
        *,
        rev_range: str | None = None,
        verbose: bool = False,
        indicate_current: bool = False,
    ) -> str:
        """Show migration history.

        Args:
            rev_range: Range of revisions (e.g., "base:head")
            verbose: Include additional details
            indicate_current: Mark current revision in output

        Returns:
            Migration history
        """
        output = io.StringIO()
        alembic_config = self.config.get_alembic_config(output)

        def _run() -> None:
            command.history(
                alembic_config,
                rev_range=rev_range,
                verbose=verbose,
                indicate_current=indicate_current,
            )

        await asyncio.to_thread(_run)
        return output.getvalue()

    async def heads(self, *, verbose: bool = False, resolve_dependencies: bool = False) -> str:
        """Show available migration heads.

        Args:
            verbose: Include additional details
            resolve_dependencies: Resolve dependencies in output

        Returns:
            List of head revisions
        """
        output = io.StringIO()
        alembic_config = self.config.get_alembic_config(output)

        def _run() -> None:
            command.heads(
                alembic_config, verbose=verbose, resolve_dependencies=resolve_dependencies
            )

        await asyncio.to_thread(_run)
        return output.getvalue()

    async def branches(self, *, verbose: bool = False) -> str:
        """Show branch points in migration history.

        Args:
            verbose: Include additional details

        Returns:
            Branch points information
        """
        output = io.StringIO()
        alembic_config = self.config.get_alembic_config(output)

        def _run() -> None:
            command.branches(alembic_config, verbose=verbose)

        await asyncio.to_thread(_run)
        return output.getvalue()

    async def show(self, revision: str = "head") -> str:
        """Show details of a specific revision.

        Args:
            revision: Revision identifier (default: "head")

        Returns:
            Revision details
        """
        output = io.StringIO()
        alembic_config = self.config.get_alembic_config(output)

        def _run() -> None:
            command.show(alembic_config, revision)

        await asyncio.to_thread(_run)
        return output.getvalue()

    # =========================================================================
    # Control Commands
    # =========================================================================

    async def stamp(
        self,
        revision: str,
        *,
        sql: bool = False,
        tag: str | None = None,
        purge: bool = False,
    ) -> str:
        """Stamp database with revision without running migrations.

        Args:
            revision: Revision to stamp (e.g., "head", "base", revision ID)
            sql: Output SQL without executing
            tag: Optional tag for the stamp
            purge: Delete existing version rows before stamping

        Returns:
            Output from stamp operation

        Example:
                    # Mark database as being at head
            await commands.stamp("head")

            # Clear and re-stamp
            await commands.stamp("head", purge=True)
        """
        logger.info(f"Stamping database with revision: {revision}")
        output = io.StringIO()
        alembic_config = self.config.get_alembic_config(output)

        def _run() -> None:
            command.stamp(alembic_config, revision, sql=sql, tag=tag, purge=purge)

        await asyncio.to_thread(_run)
        result = output.getvalue()
        logger.info(f"Database stamped with: {revision}")
        return result

    async def merge(
        self,
        revisions: str = "heads",
        *,
        message: str | None = None,
        branch_label: str | None = None,
        rev_id: str | None = None,
    ) -> str:
        """Create a merge migration for multiple heads.

        Args:
            revisions: Revisions to merge (default: "heads")
            message: Merge migration message
            branch_label: Label for the merge revision
            rev_id: Explicit revision ID

        Returns:
            Output including path to merge revision file
        """
        logger.info(f"Creating merge migration for: {revisions}")
        output = io.StringIO()
        alembic_config = self.config.get_alembic_config(output)

        def _run() -> None:
            command.merge(
                alembic_config,
                revisions,
                message=message,
                branch_label=branch_label,
                rev_id=rev_id,
            )

        await asyncio.to_thread(_run)
        result = output.getvalue()
        logger.info("Merge migration created")
        return result

    async def check(self) -> tuple[bool, str]:
        """Check if there are pending migrations or model changes.

        Returns:
            Tuple of (is_up_to_date: bool, output: str)

        Example:
                    is_current, output = await commands.check()
            if not is_current:
                print("Pending changes detected:")
                print(output)
        """
        output = io.StringIO()
        alembic_config = self.config.get_alembic_config(output)

        def _run() -> bool:
            try:
                command.check(alembic_config)
                return True
            except SystemExit:
                # Alembic check exits with non-zero if there are changes
                return False

        is_up_to_date = await asyncio.to_thread(_run)
        return is_up_to_date, output.getvalue()

    # =========================================================================
    # Utility Methods
    # =========================================================================

    async def get_current_revision(self) -> str | None:
        """Get current revision hash.

        Returns:
            Current revision string or None if no migrations applied

        Example:
                    revision = await commands.get_current_revision()
            if revision is None:
                print("No migrations applied")
            else:
                print(f"Current revision: {revision}")
        """

        def _get() -> str | None:
            from sqlalchemy import create_engine

            # Create a fresh sync engine to avoid async context issues
            # psycopg3 supports both async and sync operations with the same URL
            alembic_config = self.config.get_alembic_config()
            url = alembic_config.get_main_option("sqlalchemy.url")
            if url is None:
                msg = "sqlalchemy.url is not configured"
                raise ValueError(msg)
            sync_engine = create_engine(url)

            try:
                with sync_engine.begin() as conn:
                    context = MigrationContext.configure(conn)
                    return context.get_current_revision()
            finally:
                sync_engine.dispose()

        return await asyncio.to_thread(_get)

    async def get_head_revision(self) -> str | None:
        """Get head revision hash.

        Returns:
            Head revision string or None if no migrations exist
        """

        def _get() -> str | None:
            alembic_config = self.config.get_alembic_config()
            script = ScriptDirectory.from_config(alembic_config)
            return script.get_current_head()

        return await asyncio.to_thread(_get)

    async def is_up_to_date(self) -> bool:
        """Check if database is at head revision.

        Returns:
            True if database is at head, False otherwise

        Example:
                    if not await commands.is_up_to_date():
                await commands.upgrade("head")
        """
        current = await self.get_current_revision()
        head = await self.get_head_revision()
        return current == head

    async def get_pending_revisions(self) -> list[str]:
        """Get list of pending revision IDs.

        Returns:
            List of revision IDs that haven't been applied

        Example:
                    pending = await commands.get_pending_revisions()
            if pending:
                print(f"Pending migrations: {pending}")
        """

        def _get() -> list[str]:
            from sqlalchemy import create_engine

            alembic_config = self.config.get_alembic_config()
            script = ScriptDirectory.from_config(alembic_config)

            # Create a fresh sync engine to avoid async context issues
            # psycopg3 supports both async and sync operations with the same URL
            url = alembic_config.get_main_option("sqlalchemy.url")
            if url is None:
                msg = "sqlalchemy.url is not configured"
                raise ValueError(msg)
            sync_engine = create_engine(url)

            try:
                with sync_engine.begin() as conn:
                    context = MigrationContext.configure(conn)
                    current = context.get_current_revision()

                    pending = []
                    for rev in script.iterate_revisions("head", current):
                        if rev.revision != current:
                            pending.append(rev.revision)
                    return list(reversed(pending))
            finally:
                sync_engine.dispose()

        return await asyncio.to_thread(_get)


def get_alembic_commands(
    engine: AsyncEngine | None = None,
    *,
    compare_type: bool = True,
    render_as_batch: bool = False,
) -> AlembicCommands:
    """Factory function to get configured AlembicCommands instance.

    Args:
        engine: SQLAlchemy async engine (uses default if None)
        compare_type: Enable type comparison in autogenerate
        render_as_batch: Enable batch mode for SQLite

    Returns:
        Configured AlembicCommands instance

    Example:
            # Use default engine
        commands = get_alembic_commands()

        # Use custom engine
        commands = get_alembic_commands(engine=my_engine)

        # Enable SQLite batch mode
        commands = get_alembic_commands(render_as_batch=True)
    """
    if engine is None:
        from example_service.infra.database import engine as default_engine

        engine = default_engine

    config = AlembicCommandConfig(
        engine=engine,
        compare_type=compare_type,
        render_as_batch=render_as_batch,
    )
    return AlembicCommands(config)


__all__ = [
    "AlembicCommandConfig",
    "AlembicCommands",
    "get_alembic_commands",
]
