"""Database infrastructure package.

This package provides database session management and utilities:

- **Session Management**: Async SQLAlchemy engine and session factory
- **Alembic Commands**: Programmatic migration API
- **Schema Utilities**: Schema inspection, comparison, and management

Example:
    from example_service.infra.database import (
        engine,
        get_async_session,
        get_alembic_commands,
        drop_all,
        dump_schema,
    )

    # Use database session
    async with get_async_session() as session:
        result = await session.execute(...)

    # Run migrations programmatically
    commands = get_alembic_commands()
    await commands.upgrade("head")

    # Schema operations
    schema_info = await dump_schema(engine)
"""

# Alembic commands - programmatic migration API
from .alembic import (
    AlembicCommandConfig,
    AlembicCommands,
    get_alembic_commands,
)

# Schema utilities
from .schema import (
    SchemaDifference,
    compare_schema,
    drop_all,
    dump_schema,
    truncate_all,
)
from .session import (
    AsyncSessionLocal,
    close_database,
    engine,
    get_async_session,
    init_database,
)

__all__ = [
    # Alembic commands
    "AlembicCommandConfig",
    "AlembicCommands",
    "AsyncSessionLocal",
    # Schema utilities
    "SchemaDifference",
    "close_database",
    "compare_schema",
    "drop_all",
    "dump_schema",
    # Session management
    "engine",
    "get_alembic_commands",
    "get_async_session",
    "init_database",
    "truncate_all",
]
