"""Full-text search utilities for migrations and runtime.

This module provides utilities for:
- Generating trigger functions and triggers for search vector updates
- Creating GIN indexes for efficient FTS queries
- Managing PostgreSQL extensions (pg_trgm for fuzzy search)
- Backfilling existing data with search vectors
- Generating tsvector SQL expressions

Usage in Alembic migrations:
    from example_service.core.database.search.utils import FTSMigrationHelper

    helper = FTSMigrationHelper(
        table_name="articles",
        search_fields=["title", "content", "summary"],
        weights={"title": "A", "summary": "B", "content": "C"},
        config="english",
    )

    def upgrade():
        # Add column, index, trigger, and backfill in one call
        helper.add_fts(op)

    def downgrade():
        helper.remove_fts(op)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from example_service.core.database.validation import safe_table_reference

if TYPE_CHECKING:
    from alembic.operations import Operations


@dataclass
class SearchFieldConfig:
    """Configuration for a searchable field.

    Attributes:
        name: Column name in the database
        weight: PostgreSQL weight class (A, B, C, D) - A is highest
        config: Text search configuration override (defaults to table config)
        boost: Additional multiplier for ranking (1.0 = normal)
    """

    name: str
    weight: str = "D"
    config: str | None = None
    boost: float = 1.0


@dataclass
class FTSMigrationHelper:
    """Helper for creating full-text search infrastructure in migrations.

    Provides methods to add/remove FTS capabilities from tables, including:
    - TSVECTOR column
    - GIN index for efficient searching
    - Trigger function for automatic updates
    - Trigger to call the function
    - Backfill of existing data

    Example:
        helper = FTSMigrationHelper(
            table_name="posts",
            search_fields=["title", "content"],
            weights={"title": "A", "content": "B"},
        )

        # In upgrade()
        helper.add_fts(op)

        # In downgrade()
        helper.remove_fts(op)
    """

    table_name: str
    search_fields: list[str]
    weights: dict[str, str] = field(default_factory=dict)
    config: str = "english"
    column_name: str = "search_vector"
    index_name: str | None = None
    trigger_name: str | None = None
    function_name: str | None = None

    def __post_init__(self) -> None:
        """Set default names based on table name."""
        if self.index_name is None:
            self.index_name = f"ix_{self.table_name}_{self.column_name}"
        if self.trigger_name is None:
            self.trigger_name = f"{self.table_name}_search_update"
        if self.function_name is None:
            self.function_name = f"{self.table_name}_search_vector_update"

    def _build_vector_expression(self, prefix: str = "") -> str:
        """Build the tsvector expression for the trigger.

        Args:
            prefix: Optional prefix for column names (e.g., "NEW.")

        Returns:
            SQL expression that combines weighted tsvectors
        """
        parts = []
        for field_name in self.search_fields:
            weight = self.weights.get(field_name, "D")
            col_ref = f"{prefix}{field_name}" if prefix else field_name
            part = f"setweight(to_tsvector('{self.config}', coalesce({col_ref}, '')), '{weight}')"
            parts.append(part)

        if not parts:
            return f"to_tsvector('{self.config}', '')"

        return " || ".join(parts)

    def get_trigger_function_sql(self) -> str:
        """Generate SQL for the trigger function.

        Returns:
            CREATE FUNCTION SQL statement
        """
        vector_expr = self._build_vector_expression(prefix="NEW.")

        return f"""
CREATE OR REPLACE FUNCTION {self.function_name}() RETURNS trigger AS $$
BEGIN
    NEW.{self.column_name} := {vector_expr};
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

    def get_trigger_sql(self) -> str:
        """Generate SQL for the trigger.

        Returns:
            CREATE TRIGGER SQL statement
        """
        return f"""
DROP TRIGGER IF EXISTS {self.trigger_name} ON {self.table_name};
CREATE TRIGGER {self.trigger_name}
    BEFORE INSERT OR UPDATE ON {self.table_name}
    FOR EACH ROW
    EXECUTE FUNCTION {self.function_name}();
"""

    def get_backfill_sql(self) -> str:
        """Generate SQL to backfill existing records.

        Returns:
            UPDATE SQL statement
        """
        vector_expr = self._build_vector_expression()
        # Validate and quote table name for safety
        safe_table = safe_table_reference(self.table_name)
        return f"""
UPDATE {safe_table} SET {self.column_name} = {vector_expr};
"""

    def get_drop_trigger_sql(self) -> str:
        """Generate SQL to drop the trigger.

        Returns:
            DROP TRIGGER SQL statement
        """
        return f"DROP TRIGGER IF EXISTS {self.trigger_name} ON {self.table_name};"

    def get_drop_function_sql(self) -> str:
        """Generate SQL to drop the trigger function.

        Returns:
            DROP FUNCTION SQL statement
        """
        return f"DROP FUNCTION IF EXISTS {self.function_name}();"

    def add_fts(self, op: Operations) -> None:
        """Add full-text search to a table.

        This is the main method to call in upgrade(). It:
        1. Adds the search_vector TSVECTOR column
        2. Creates a GIN index on the column
        3. Creates the trigger function
        4. Creates the trigger
        5. Backfills existing data

        Args:
            op: Alembic operations object
        """
        import sqlalchemy as sa
        from sqlalchemy.dialects.postgresql import TSVECTOR

        # 1. Add column
        op.add_column(
            self.table_name,
            sa.Column(self.column_name, TSVECTOR(), nullable=True),
        )

        # 2. Create GIN index
        op.create_index(
            self.index_name,
            self.table_name,
            [self.column_name],
            unique=False,
            postgresql_using="gin",
        )

        # 3. Create trigger function
        op.execute(self.get_trigger_function_sql())

        # 4. Create trigger
        op.execute(self.get_trigger_sql())

        # 5. Backfill existing data
        op.execute(self.get_backfill_sql())

    def remove_fts(self, op: Operations) -> None:
        """Remove full-text search from a table.

        This is the main method to call in downgrade(). It:
        1. Drops the trigger
        2. Drops the trigger function
        3. Drops the GIN index
        4. Drops the search_vector column

        Args:
            op: Alembic operations object
        """
        # 1. Drop trigger
        op.execute(self.get_drop_trigger_sql())

        # 2. Drop function
        op.execute(self.get_drop_function_sql())

        # 3. Drop index
        op.drop_index(self.index_name, table_name=self.table_name)  # type: ignore[arg-type]

        # 4. Drop column
        op.drop_column(self.table_name, self.column_name)


@dataclass
class TrigramMigrationHelper:
    """Helper for adding trigram (fuzzy search) support.

    PostgreSQL's pg_trgm extension enables similarity-based searching
    using trigrams (3-character substrings). This is useful for:
    - Typo-tolerant search
    - "Did you mean?" suggestions
    - Fuzzy matching

    Example:
        helper = TrigramMigrationHelper(
            table_name="products",
            field_name="name",
        )

        # In upgrade()
        helper.add_trigram_index(op)

        # In downgrade()
        helper.remove_trigram_index(op)
    """

    table_name: str
    field_name: str
    index_name: str | None = None
    index_type: str = "gin"  # gin or gist

    def __post_init__(self) -> None:
        """Set default index name."""
        if self.index_name is None:
            self.index_name = f"ix_{self.table_name}_{self.field_name}_trgm"

    @staticmethod
    def ensure_extension(op: Operations) -> None:
        """Ensure pg_trgm extension is installed.

        Args:
            op: Alembic operations object
        """
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")

    def get_index_sql(self) -> str:
        """Generate SQL for the trigram index.

        Returns:
            CREATE INDEX SQL statement
        """
        operator_class = "gin_trgm_ops" if self.index_type == "gin" else "gist_trgm_ops"
        return f"""
CREATE INDEX IF NOT EXISTS {self.index_name}
ON {self.table_name}
USING {self.index_type} ({self.field_name} {operator_class});
"""

    def add_trigram_index(self, op: Operations, ensure_extension: bool = True) -> None:
        """Add a trigram index to a column.

        Args:
            op: Alembic operations object
            ensure_extension: Whether to create the pg_trgm extension
        """
        if ensure_extension:
            self.ensure_extension(op)
        op.execute(self.get_index_sql())

    def remove_trigram_index(self, op: Operations) -> None:
        """Remove the trigram index.

        Args:
            op: Alembic operations object
        """
        op.execute(f"DROP INDEX IF EXISTS {self.index_name};")


@dataclass
class UnaccentMigrationHelper:
    """Helper for adding unaccented search support.

    PostgreSQL's unaccent extension removes accents from text,
    enabling accent-insensitive searching (e.g., "café" matches "cafe").

    This creates a custom text search configuration that applies
    unaccent before stemming.

    Example:
        helper = UnaccentMigrationHelper(
            config_name="english_unaccent",
            base_config="english",
        )

        # In upgrade()
        helper.add_unaccent_config(op)

        # In downgrade()
        helper.remove_unaccent_config(op)
    """

    config_name: str = "english_unaccent"
    base_config: str = "english"

    @staticmethod
    def ensure_extension(op: Operations) -> None:
        """Ensure unaccent extension is installed.

        Args:
            op: Alembic operations object
        """
        op.execute("CREATE EXTENSION IF NOT EXISTS unaccent;")

    def get_config_sql(self) -> str:
        """Generate SQL for the unaccented text search configuration.

        Returns:
            SQL statements to create the configuration
        """
        return f"""
-- Create text search configuration based on existing one
DROP TEXT SEARCH CONFIGURATION IF EXISTS {self.config_name} CASCADE;
CREATE TEXT SEARCH CONFIGURATION {self.config_name} (COPY = {self.base_config});

-- Add unaccent filter before stemming
ALTER TEXT SEARCH CONFIGURATION {self.config_name}
    ALTER MAPPING FOR hword, hword_part, word
    WITH unaccent, {self.base_config}_stem;
"""

    def add_unaccent_config(self, op: Operations, ensure_extension: bool = True) -> None:
        """Add unaccented search configuration.

        Args:
            op: Alembic operations object
            ensure_extension: Whether to create the unaccent extension
        """
        if ensure_extension:
            self.ensure_extension(op)
        op.execute(self.get_config_sql())

    def remove_unaccent_config(self, op: Operations) -> None:
        """Remove unaccented search configuration.

        Args:
            op: Alembic operations object
        """
        op.execute(f"DROP TEXT SEARCH CONFIGURATION IF EXISTS {self.config_name} CASCADE;")


def generate_search_vector_sql(
    fields: list[str],
    weights: dict[str, str] | None = None,
    config: str = "english",
    prefix: str = "",
) -> str:
    """Generate SQL expression for building a search vector.

    This is a standalone utility function for generating tsvector
    SQL expressions without using the helper classes.

    Args:
        fields: List of column names to include
        weights: Optional dict mapping field names to weights (A/B/C/D)
        config: PostgreSQL text search configuration
        prefix: Optional prefix for column names (e.g., "NEW." for triggers)

    Returns:
        SQL expression string

    Example:
        sql = generate_search_vector_sql(
            fields=["title", "content"],
            weights={"title": "A", "content": "B"},
            config="english",
        )
        # Returns: setweight(to_tsvector('english', coalesce(title, '')), 'A') || ...
    """
    weights = weights or {}
    parts = []

    for field_name in fields:
        weight = weights.get(field_name, "D")
        col_ref = f"{prefix}{field_name}" if prefix else field_name
        part = f"setweight(to_tsvector('{config}', coalesce({col_ref}, '')), '{weight}')"
        parts.append(part)

    if not parts:
        return f"to_tsvector('{config}', '')"

    return " || ".join(parts)


def build_ts_query_sql(
    query: str,
    config: str = "english",
    query_type: str = "websearch",
) -> str:
    """Generate SQL for building a tsquery from user input.

    Args:
        query: User's search query
        config: PostgreSQL text search configuration
        query_type: Query parsing mode:
            - "plain": plainto_tsquery (AND all words)
            - "phrase": phraseto_tsquery (exact phrase)
            - "websearch": websearch_to_tsquery (Google-like syntax)

    Returns:
        SQL expression string

    Example:
        sql = build_ts_query_sql("python web framework", query_type="websearch")
        # Returns: websearch_to_tsquery('english', 'python web framework')
    """
    if query_type == "phrase":
        return f"phraseto_tsquery('{config}', $${query}$$)"
    if query_type == "plain":
        return f"plainto_tsquery('{config}', $${query}$$)"
    # websearch
    return f"websearch_to_tsquery('{config}', $${query}$$)"


__all__ = [
    "FTSMigrationHelper",
    "SearchFieldConfig",
    "TrigramMigrationHelper",
    "UnaccentMigrationHelper",
    "build_ts_query_sql",
    "generate_search_vector_sql",
]
