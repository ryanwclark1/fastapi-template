"""Automatic full-text search setup via SQLAlchemy event listeners.

This module provides convenience functions for automatic trigger and index
creation during table creation, similar to sqlalchemy-searchable's approach.

Two modes of operation:

1. **Development mode** (make_searchable):
   - Automatically creates triggers and indexes when tables are created
   - Zero-config for rapid prototyping
   - Not recommended for production (use explicit migrations)

2. **Production mode** (FTSMigrationHelper):
   - Explicit migration steps for full control
   - Auditable and reversible
   - Recommended for production deployments

Usage:
    # Development - automatic setup
    from example_service.core.database.search import make_searchable

    Base = declarative_base()
    make_searchable(Base.metadata)  # Register listeners

    class Article(Base, SearchableMixin):
        __tablename__ = "articles"
        __search_fields__ = ["title", "content"]
        # ... triggers created automatically on table create

    # Production - use FTSMigrationHelper in Alembic migrations
    from example_service.core.database.search import FTSMigrationHelper

    def upgrade():
        helper = FTSMigrationHelper(...)
        helper.add_fts(op)
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
import logging
from typing import TYPE_CHECKING, Any
import weakref

from sqlalchemy import event, text
from sqlalchemy.orm import Mapper

if TYPE_CHECKING:
    from sqlalchemy import MetaData, Table
    from sqlalchemy.engine import Connection

logger = logging.getLogger(__name__)


@dataclass
class SearchableConfig:
    """Configuration options for automatic search setup.

    Attributes:
        regconfig: PostgreSQL text search configuration (e.g., "english").
        auto_index: Whether to automatically create GIN indexes.
        auto_trigger: Whether to automatically create update triggers.
        trigger_name_template: Template for trigger names.
        function_name_template: Template for trigger function names.
    """

    regconfig: str = "english"
    auto_index: bool = True
    auto_trigger: bool = True
    trigger_name_template: str = "{table}_search_update"
    function_name_template: str = "{table}_search_vector_update"


@dataclass
class SearchManager:
    """Manages automatic full-text search setup for SQLAlchemy models.

    Registers event listeners on metadata and mappers to automatically
    create triggers and indexes when tables are created.

    This is primarily for development convenience. For production,
    use explicit Alembic migrations with FTSMigrationHelper.

    Example:
        manager = SearchManager()
        manager.configure(Base.metadata)

        # Or use the convenience function:
        make_searchable(Base.metadata)
    """

    config: SearchableConfig = field(default_factory=SearchableConfig)
    _processed_tables: set[str] = field(default_factory=set, repr=False)
    _listeners: list[tuple[Any, str, Any]] = field(default_factory=list, repr=False)
    _metadata_ref: Any = field(default=None, repr=False)

    def configure(
        self,
        metadata: MetaData,
        *,
        options: dict[str, Any] | None = None,
    ) -> None:
        """Configure automatic search setup for a metadata object.

        Registers event listeners that will create triggers and indexes
        when tables are created.

        Args:
            metadata: SQLAlchemy MetaData to configure.
            options: Optional configuration overrides.
        """
        if options:
            for key, value in options.items():
                if hasattr(self.config, key):
                    setattr(self.config, key, value)

        # Store weak reference to metadata
        self._metadata_ref = weakref.ref(metadata)

        # Register after_create listener on metadata
        self._add_listener(
            metadata,
            "after_create",
            self._on_table_create,
        )

        # Register mapper listener to discover searchable models
        self._add_listener(
            Mapper,
            "after_configured",
            self._on_mapper_configured,
        )

        logger.debug("SearchManager configured for metadata")

    def _add_listener(
        self,
        target: Any,
        event_name: str,
        callback: Any,
    ) -> None:
        """Add an event listener and track it for cleanup.

        Args:
            target: Event target (metadata, mapper, etc.)
            event_name: Name of the event.
            callback: Callback function.
        """
        event.listen(target, event_name, callback)
        self._listeners.append((target, event_name, callback))

    def remove_listeners(self) -> None:
        """Remove all registered event listeners.

        Call this to clean up listeners, e.g., between tests.
        """
        for target, event_name, callback in self._listeners:
            with contextlib.suppress(Exception):
                event.remove(target, event_name, callback)  # Listener may already be removed
        self._listeners.clear()
        self._processed_tables.clear()
        logger.debug("SearchManager listeners removed")

    def _on_mapper_configured(self) -> None:
        """Called after all mappers are configured.

        Discovers models with SearchableMixin and prepares for trigger creation.
        """
        # This is called once after all mappers are set up
        # We don't need to do anything here since we process tables on create

    def _on_table_create(
        self,
        target: Table,
        connection: Connection,
        **_kwargs: Any,
    ) -> None:
        """Called after a table is created.

        Creates triggers and indexes for searchable tables.

        Args:
            target: The created table.
            connection: Database connection.
            **kwargs: Additional event arguments.
        """
        table_name = target.name

        # Avoid processing the same table twice
        if table_name in self._processed_tables:
            return

        # Check if table has a search_vector column
        search_vector_col = None
        for column in target.columns:
            if column.name == "search_vector":
                search_vector_col = column
                break

        if search_vector_col is None:
            return

        # Get the model class to access search configuration
        model_class = self._get_model_for_table(target)
        if model_class is None:
            logger.warning("Could not find model class for table %s", table_name)
            return

        # Check if model has search fields defined
        search_fields = getattr(model_class, "__search_fields__", [])
        if not search_fields:
            return

        logger.info("Setting up full-text search for table: %s", table_name)

        try:
            if self.config.auto_trigger:
                self._create_trigger(connection, model_class, table_name)

            self._processed_tables.add(table_name)
            logger.info("Full-text search configured for %s", table_name)

        except Exception as e:
            logger.error("Failed to setup FTS for %s: %s", table_name, e)

    def _get_model_for_table(self, table: Table) -> Any:
        """Find the model class associated with a table.

        Args:
            table: SQLAlchemy Table object.

        Returns:
            Model class or None if not found.
        """
        metadata = self._metadata_ref() if self._metadata_ref else None
        if metadata is None:
            return None

        # Search through registry for matching table
        try:
            # Try to find via table's info or mapper
            # In SQLAlchemy 2.0, we access mappers through the registry
            if metadata and hasattr(metadata, "registry"):
                reg = metadata.registry
                for mapper in reg.mappers:
                    if mapper.persist_selectable is table:
                        return mapper.class_
            # Fallback: try to find via table's mapper attribute if available
            if hasattr(table, "_mapper"):
                return table._mapper.class_
        except Exception as e:
            logger.debug("Could not find model for table: %s", str(e), extra={"table": table.name})

        return None

    def _create_trigger(
        self,
        connection: Connection,
        model_class: Any,
        table_name: str,
    ) -> None:
        """Create the search vector update trigger.

        Args:
            connection: Database connection.
            model_class: Model class with search configuration.
            table_name: Name of the table.
        """
        # Get search configuration from model
        search_fields = getattr(model_class, "__search_fields__", [])
        search_config = getattr(model_class, "__search_config__", self.config.regconfig)
        search_weights = getattr(model_class, "__search_weights__", {})
        search_field_configs = getattr(model_class, "__search_field_configs__", {})

        # Build vector expression
        vector_parts = []
        for field_name in search_fields:
            config = search_field_configs.get(field_name, search_config)
            weight = search_weights.get(field_name, "D")
            vector_parts.append(
                f"setweight(to_tsvector('{config}', coalesce(NEW.{field_name}, '')), '{weight}')"
            )

        vector_expr = (
            " || ".join(vector_parts) if vector_parts else f"to_tsvector('{search_config}', '')"
        )

        # Build field change conditions for UPDATE optimization
        field_conditions = " OR ".join(
            f"OLD.{field_name} IS DISTINCT FROM NEW.{field_name}" for field_name in search_fields
        )

        function_name = self.config.function_name_template.format(table=table_name)
        trigger_name = self.config.trigger_name_template.format(table=table_name)

        # Create trigger function
        function_sql = f"""
CREATE OR REPLACE FUNCTION {function_name}() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'INSERT' OR ({field_conditions}) THEN
        NEW.search_vector := {vector_expr};
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""
        connection.execute(text(function_sql))

        # Create trigger
        trigger_sql = f"""
DROP TRIGGER IF EXISTS {trigger_name} ON {table_name};
CREATE TRIGGER {trigger_name}
    BEFORE INSERT OR UPDATE ON {table_name}
    FOR EACH ROW
    EXECUTE FUNCTION {function_name}();
"""
        connection.execute(text(trigger_sql))

        logger.debug("Created trigger %s for %s", trigger_name, table_name)


# Global manager instance
_search_manager: SearchManager | None = None


def make_searchable(
    metadata: MetaData,
    *,
    options: dict[str, Any] | None = None,
) -> SearchManager:
    """Configure automatic full-text search setup for SQLAlchemy models.

    This is a convenience function that registers event listeners to
    automatically create triggers and indexes when tables are created.

    Best for development and testing. For production, use explicit
    Alembic migrations with FTSMigrationHelper.

    Args:
        metadata: SQLAlchemy MetaData object (usually Base.metadata).
        options: Optional configuration overrides:
            - regconfig: Text search configuration (default: "english")
            - auto_index: Create GIN indexes (default: True)
            - auto_trigger: Create update triggers (default: True)

    Returns:
        SearchManager instance for further configuration.

    Example:
        from sqlalchemy.orm import declarative_base
        from example_service.core.database.search import make_searchable, SearchableMixin

        Base = declarative_base()
        make_searchable(Base.metadata)

        class Article(Base, SearchableMixin):
            __tablename__ = "articles"
            __search_fields__ = ["title", "content"]
            __search_weights__ = {"title": "A", "content": "B"}

            id: Mapped[int] = mapped_column(primary_key=True)
            title: Mapped[str] = mapped_column(String(255))
            content: Mapped[str] = mapped_column(Text)

        # When Base.metadata.create_all() is called, triggers are auto-created
    """
    global _search_manager

    if _search_manager is not None:
        _search_manager.remove_listeners()

    _search_manager = SearchManager()
    _search_manager.configure(metadata, options=options)

    return _search_manager


def remove_searchable_listeners() -> None:
    """Remove all searchable event listeners.

    Call this to clean up listeners, useful between tests.

    Example:
        # In test teardown
        remove_searchable_listeners()
    """
    global _search_manager

    if _search_manager is not None:
        _search_manager.remove_listeners()
        _search_manager = None


def get_search_manager() -> SearchManager | None:
    """Get the current global SearchManager instance.

    Returns:
        SearchManager instance or None if not configured.
    """
    return _search_manager


__all__ = [
    "SearchManager",
    "SearchableConfig",
    "get_search_manager",
    "make_searchable",
    "remove_searchable_listeners",
]
