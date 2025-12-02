"""Alembic migration environment with async psycopg3 support and advanced features.

Enhanced with:
- compare_type support for detecting column type changes
- Batch mode auto-detection for SQLite compatibility
- Custom type registration for EncryptedString/EncryptedText
- Object filtering to exclude system tables
- Empty migration detection to skip no-op revisions
- Configurable via AlembicCommandConfig attributes

When using programmatic API (AlembicCommands), configuration is passed via
config.attributes. When using CLI, defaults are used.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import TYPE_CHECKING, Any

from sqlalchemy import Column, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Import the models package so Base.metadata is aware of all mapped classes.
# The package handles recursively loading feature-level models.
from example_service.core import models
from example_service.core.database.base import Base

# Import custom types for comparison and rendering
from example_service.core.database.types import EncryptedString, EncryptedText
from example_service.core.settings import get_db_settings

if TYPE_CHECKING:
    from collections.abc import Iterable

    from alembic.autogenerate.api import AutogenContext
    from alembic.operations.ops import MigrationScript
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy.engine import Connection
    from sqlalchemy.sql.type_api import TypeEngine

# Alembic Config object
config = context.config

# Setup Python logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for autogenerate
target_metadata = Base.metadata

# Override URL from settings (CLI usage)
db_settings = get_db_settings()
if db_settings.is_configured:
    config.set_main_option("sqlalchemy.url", db_settings.get_sqlalchemy_url())


# =============================================================================
# Configuration Helpers
# =============================================================================


def get_config_value(key: str, default: Any = None) -> Any:
    """Get configuration value from AlembicCommandConfig or default.

    When using programmatic API, values are passed via config.attributes.
    When using CLI, defaults are used.

    Args:
        key: Configuration key name
        default: Default value if not set

    Returns:
        Configuration value or default
    """
    return config.attributes.get(key, default)


# Feature flags (can be overridden by AlembicCommandConfig)
COMPARE_TYPE = get_config_value("compare_type", True)
COMPARE_SERVER_DEFAULT = get_config_value("compare_server_default", False)
RENDER_AS_BATCH = get_config_value("render_as_batch", False)
INCLUDE_SCHEMAS = get_config_value("include_schemas", False)
USER_MODULE_PREFIX = get_config_value("user_module_prefix", "example_service.core.database.types.")


# =============================================================================
# Custom Type Comparison
# =============================================================================


def compare_type(
    context: MigrationContext,
    inspected_column: Column[Any],
    metadata_column: Column[Any],
    inspected_type: TypeEngine[Any],
    metadata_type: TypeEngine[Any],
) -> bool | None:
    """Compare column types including custom types.

    Handles EncryptedString and EncryptedText by comparing their
    underlying String/Text types.

    Args:
        context: Migration context
        inspected_column: Column from database reflection
        metadata_column: Column from model metadata
        inspected_type: Type from database
        metadata_type: Type from model

    Returns:
        True if types are different (should generate migration)
        False if types are the same
        None to use default comparison
    """
    _ = context, inspected_column, metadata_column
    from sqlalchemy import String, Text

    # Handle EncryptedString - compare underlying String type
    if isinstance(metadata_type, EncryptedString):
        # Encrypted values are longer than originals, so don't compare lengths:
        # compatibility depends solely on whether the source column is String.
        return not isinstance(inspected_type, String)

    # Handle EncryptedText - compare underlying Text type
    if isinstance(metadata_type, EncryptedText):
        return not isinstance(inspected_type, Text)

    # Fall back to default comparison
    return None


# =============================================================================
# Object Inclusion Filter
# =============================================================================


def include_object(
    obj: Any,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: Any,
) -> bool:
    """Control which objects are included in autogenerate.

    Filters out system tables and internal schemas that shouldn't
    be managed by migrations.

    Args:
        obj: The SQLAlchemy object
        name: Object name
        type_: Object type ("table", "column", "index", "unique_constraint", etc.)
        reflected: True if object was reflected from database
        compare_to: The model object being compared to (if any)

    Returns:
        True to include object in migration, False to skip
    """
    # Skip alembic's own table
    if type_ == "table" and name == "alembic_version":
        return False

    # Skip PostGIS system tables if using spatial
    if type_ == "table" and name is not None and name.startswith("spatial_ref"):
        return False

    _ = reflected, compare_to
    # Skip PostgreSQL system schemas
    return not (hasattr(obj, "schema") and obj.schema in ("pg_catalog", "information_schema"))


# =============================================================================
# Custom Type Rendering
# =============================================================================


def render_item(type_: str, obj: Any, autogen_context: AutogenContext) -> str | bool:
    """Custom rendering for special types in migrations.

    Handles EncryptedString and EncryptedText by adding proper imports
    and rendering the type with its parameters.

    Args:
        type_: Type of item being rendered ("type", "server_default", etc.)
        obj: The object to render
        autogen_context: Alembic autogenerate context

    Returns:
        String representation or False to use default
    """
    if type_ == "type":
        # Render EncryptedString with import
        if isinstance(obj, EncryptedString):
            autogen_context.imports.add(
                "from example_service.core.database.types import EncryptedString"
            )
            max_length = getattr(obj, "max_length", 255)
            return f"EncryptedString(max_length={max_length})"

        # Render EncryptedText with import
        if isinstance(obj, EncryptedText):
            autogen_context.imports.add(
                "from example_service.core.database.types import EncryptedText"
            )
            return "EncryptedText()"

    # Fall back to default rendering
    return False


# =============================================================================
# Process Revision Directives
# =============================================================================


def process_revision_directives(
    context: MigrationContext,
    revision: str | tuple[str, ...] | Iterable[str | None] | Iterable[str],
    directives: list[MigrationScript],
) -> None:
    """Hook to modify revision before writing.

    Used to skip empty migrations when autogenerate detects no changes.

    Args:
        context: Migration context
        revision: Revision tuple
        directives: List of migration scripts to process
    """
    _ = context, revision
    if getattr(config.cmd_opts, "autogenerate", False) and directives:
        script = directives[0]
        if script.upgrade_ops is not None and script.upgrade_ops.is_empty():
            # Skip creating empty migration
            directives[:] = []
            print("No changes detected, skipping migration creation")


# =============================================================================
# Migration Runners
# =============================================================================


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generate SQL only).

    This configures the context with just a URL and not an Engine,
    so we don't need a DBAPI to be available. Calls to context.execute()
    emit the given string to the script output.
    """
    url = config.get_main_option("sqlalchemy.url")

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=compare_type if COMPARE_TYPE else None,
        compare_server_default=COMPARE_SERVER_DEFAULT,
        include_object=include_object,
        render_item=render_item,
        include_schemas=INCLUDE_SCHEMAS,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Configure and run migrations with connection.

    Handles both programmatic API (with engine in attributes) and
    CLI usage. Auto-detects SQLite for batch mode.

    Args:
        connection: SQLAlchemy connection
    """
    # Auto-detect SQLite for batch mode
    is_sqlite = connection.dialect.name == "sqlite"
    use_batch_mode = is_sqlite or RENDER_AS_BATCH

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=compare_type if COMPARE_TYPE else None,
        compare_server_default=COMPARE_SERVER_DEFAULT,
        include_object=include_object,
        render_item=render_item,
        render_as_batch=use_batch_mode,
        include_schemas=INCLUDE_SCHEMAS,
        process_revision_directives=process_revision_directives,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations with async engine.

    Checks if engine is provided via AlembicCommandConfig (programmatic API)
    or creates one from config (CLI usage).
    """
    # Check if engine is provided via AlembicCommandConfig
    engine = get_config_value("engine")

    if engine is not None:
        # Use provided engine (programmatic API)
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    else:
        # Create engine from config (CLI usage)
        connectable = async_engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )

        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)

        await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
