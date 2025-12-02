"""Mixin for adding full-text search capability to SQLAlchemy models.

The SearchableMixin adds a search_vector column and provides utilities
for building and updating the search vector from specified text fields.

Usage:
    class Article(Base, SearchableMixin):
        __tablename__ = "articles"
        __search_fields__ = ["title", "content", "author"]
        __search_config__ = "english"
        __search_weights__ = {"title": "A", "content": "B", "author": "C"}

        title: Mapped[str] = mapped_column(String(255))
        content: Mapped[str] = mapped_column(Text)
        author: Mapped[str] = mapped_column(String(100))

The search vector is updated via database triggers (recommended) or
application-level updates before insert/update.

Weight classes (A, B, C, D) affect ranking:
- A: Highest weight (e.g., title)
- B: High weight (e.g., subtitle)
- C: Normal weight (e.g., body)
- D: Low weight (e.g., metadata)

Multi-language support:
    class MultilingualArticle(Base, SearchableMixin):
        __tablename__ = "articles"
        __search_fields__ = ["title", "content"]
        __search_field_configs__ = {"title": "simple", "content": "english"}
        # Fields can have different text search configurations

Trigram indexing for fuzzy search:
    class Product(Base, SearchableMixin):
        __tablename__ = "products"
        __search_fields__ = ["name", "description"]
        __trigram_fields__ = ["name"]  # Add trigram index for fuzzy search on name
"""

from __future__ import annotations

from typing import Any, ClassVar, TYPE_CHECKING

from sqlalchemy import Index, event, text
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from example_service.core.database.search.types import TSVECTOR

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SearchableMixin:
    """Mixin that adds full-text search capability to a model.

    Subclasses must define:
    - __search_fields__: List of field names to include in search

    Optional configuration:
    - __search_config__: Default PostgreSQL text search configuration
    - __search_weights__: Dict mapping fields to weight classes (A/B/C/D)
    - __search_field_configs__: Dict mapping fields to specific text search configs
    - __trigram_fields__: List of fields to add trigram indexes for fuzzy search
    - __search_vector_name__: Custom name for the search vector column

    The mixin adds:
    - search_vector column (TSVECTOR type)
    - GIN index on search_vector for fast searches

    Example:
        class Product(Base, SearchableMixin):
            __tablename__ = "products"
            __search_fields__ = ["name", "description", "sku"]
            __search_config__ = "english"
            __search_weights__ = {"name": "A", "description": "B", "sku": "C"}
            __trigram_fields__ = ["name"]  # Enable fuzzy search on name

            name: Mapped[str] = mapped_column(String(255))
            description: Mapped[str] = mapped_column(Text)
            sku: Mapped[str] = mapped_column(String(50))

        # The model now has:
        # - product.search_vector column
        # - GIN index ix_products_search_vector
        # - Trigram index ix_products_name_trgm (if extension enabled)
    """

    __allow_unmapped__ = True

    # Class variables to be overridden by subclasses
    __search_fields__: ClassVar[list[str]] = []
    __search_config__: ClassVar[str] = "english"
    __search_weights__: ClassVar[dict[str, str]] = {}  # field -> A/B/C/D
    __search_field_configs__: ClassVar[dict[str, str]] = {}  # field -> config (for multi-lang)
    __trigram_fields__: ClassVar[list[str]] = []  # fields with trigram indexes
    __search_vector_name__: ClassVar[str] = "search_vector"

    @declared_attr
    def search_vector(cls) -> Mapped[Any]:
        """Search vector column for full-text search.

        This column stores the preprocessed tsvector representation
        of the searchable fields. It's indexed with a GIN index for
        efficient full-text queries.
        """
        return mapped_column(
            TSVECTOR,
            nullable=True,
            comment="Full-text search vector",
        )

    @declared_attr  # type: ignore[arg-type]
    def __table_args__(cls) -> tuple[Any, ...]:
        """Add GIN index for search vector.

        GIN (Generalized Inverted Index) is optimized for TSVECTOR
        columns and provides fast full-text search.
        """
        # Get existing table args if any
        existing_args = getattr(cls, "__table_args_extra__", ())
        if not isinstance(existing_args, tuple):
            existing_args = (existing_args,)

        # Get tablename safely
        tablename = getattr(cls, "__tablename__", None)
        if tablename is None:
            return existing_args or ()

        indexes: list[Index] = []

        # Add GIN index for search vector
        gin_index = Index(
            f"ix_{tablename}_search_vector",
            cls.search_vector,
            postgresql_using="gin",
        )
        indexes.append(gin_index)

        return (*existing_args, *indexes)

    @classmethod
    def get_field_config(cls, field: str) -> str:
        """Get the text search configuration for a specific field.

        Args:
            field: Field name

        Returns:
            Text search configuration name
        """
        return cls.__search_field_configs__.get(field, cls.__search_config__)

    @classmethod
    def get_field_weight(cls, field: str) -> str:
        """Get the weight class for a specific field.

        Args:
            field: Field name

        Returns:
            Weight class (A, B, C, or D)
        """
        return cls.__search_weights__.get(field, "D")

    def build_search_vector_sql(self, prefix: str = "") -> str:
        """Build SQL expression for updating the search vector.

        Returns SQL that can be used in a trigger or UPDATE statement
        to rebuild the search vector from the search fields.

        Args:
            prefix: Optional prefix for column names (e.g., "NEW." for triggers)

        Returns:
            SQL expression string

        Example:
            # Returns something like:
            # setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
            # setweight(to_tsvector('english', coalesce(content, '')), 'B')
        """
        parts = []

        for field in self.__search_fields__:
            config = self.get_field_config(field)
            weight = self.get_field_weight(field)
            col_ref = f"{prefix}{field}" if prefix else field
            part = f"setweight(to_tsvector('{config}', coalesce({col_ref}, '')), '{weight}')"
            parts.append(part)

        if not parts:
            return f"to_tsvector('{self.__search_config__}', '')"

        return " || ".join(parts)

    @classmethod
    def get_search_trigger_sql(cls, table_name: str | None = None) -> str:
        """Generate SQL for creating a search vector update trigger.

        The trigger automatically updates the search_vector column
        whenever the searchable fields are modified.

        Args:
            table_name: Name of the table (uses __tablename__ if not provided)

        Returns:
            SQL statements to create the trigger function and trigger
        """
        table_name = table_name or getattr(cls, "__tablename__", None)
        if not table_name:
            raise ValueError("Table name is required")

        # Build the vector expression with NEW. prefix for trigger
        vector_parts = []
        for field in cls.__search_fields__:
            config = cls.get_field_config(field)
            weight = cls.get_field_weight(field)
            vector_parts.append(
                f"setweight(to_tsvector('{config}', coalesce(NEW.{field}, '')), '{weight}')"
            )

        vector_expr = (
            " || ".join(vector_parts)
            if vector_parts
            else f"to_tsvector('{cls.__search_config__}', '')"
        )

        # Build list of fields to watch for changes
        field_conditions = " OR ".join(
            f"OLD.{field} IS DISTINCT FROM NEW.{field}" for field in cls.__search_fields__
        )

        return f"""
-- Create trigger function for {table_name}
CREATE OR REPLACE FUNCTION {table_name}_search_vector_update() RETURNS trigger AS $$
BEGIN
    -- Only update if searchable fields changed (for UPDATE) or on INSERT
    IF TG_OP = 'INSERT' OR ({field_conditions}) THEN
        NEW.search_vector := {vector_expr};
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger
DROP TRIGGER IF EXISTS {table_name}_search_update ON {table_name};
CREATE TRIGGER {table_name}_search_update
    BEFORE INSERT OR UPDATE ON {table_name}
    FOR EACH ROW
    EXECUTE FUNCTION {table_name}_search_vector_update();
"""

    @classmethod
    def get_backfill_sql(cls, table_name: str | None = None) -> str:
        """Generate SQL to backfill search vectors for existing rows.

        Args:
            table_name: Name of the table

        Returns:
            UPDATE SQL statement
        """
        table_name = table_name or getattr(cls, "__tablename__", None)
        if not table_name:
            raise ValueError("Table name is required")

        # Build vector expression without prefix
        vector_parts = []
        for field in cls.__search_fields__:
            config = cls.get_field_config(field)
            weight = cls.get_field_weight(field)
            vector_parts.append(
                f"setweight(to_tsvector('{config}', coalesce({field}, '')), '{weight}')"
            )

        vector_expr = (
            " || ".join(vector_parts)
            if vector_parts
            else f"to_tsvector('{cls.__search_config__}', '')"
        )

        return f"UPDATE {table_name} SET search_vector = {vector_expr};"

    @classmethod
    def get_trigram_index_sql(cls, table_name: str | None = None) -> list[str]:
        """Generate SQL for creating trigram indexes on specified fields.

        Requires the pg_trgm extension to be installed.

        Args:
            table_name: Name of the table

        Returns:
            List of CREATE INDEX SQL statements
        """
        table_name = table_name or getattr(cls, "__tablename__", None)
        if not table_name:
            raise ValueError("Table name is required")

        statements = []
        for field in cls.__trigram_fields__:
            index_name = f"ix_{table_name}_{field}_trgm"
            statements.append(
                f"CREATE INDEX IF NOT EXISTS {index_name} "
                f"ON {table_name} USING gin ({field} gin_trgm_ops);"
            )
        return statements

    @classmethod
    def get_drop_trigger_sql(cls, table_name: str | None = None) -> str:
        """Generate SQL to drop the search trigger and function.

        Args:
            table_name: Name of the table

        Returns:
            SQL statements to drop trigger and function
        """
        table_name = table_name or getattr(cls, "__tablename__", None)
        if not table_name:
            raise ValueError("Table name is required")

        return f"""
DROP TRIGGER IF EXISTS {table_name}_search_update ON {table_name};
DROP FUNCTION IF EXISTS {table_name}_search_vector_update();
"""

    @classmethod
    async def rebuild_search_vectors(
        cls,
        session: "AsyncSession",
        batch_size: int = 1000,
    ) -> int:
        """Rebuild all search vectors for existing rows.

        This is useful when:
        - Search configuration changes
        - Search fields change
        - Initial data load without triggers

        Args:
            session: Database session
            batch_size: Number of rows to update per batch

        Returns:
            Number of rows updated
        """
        table_name = getattr(cls, "__tablename__", None)
        if not table_name:
            raise ValueError("Table name is required")

        sql = cls.get_backfill_sql(table_name)
        result = await session.execute(text(sql))
        await session.commit()
        return result.rowcount or 0

    def update_search_vector(self) -> None:
        """Update search vector from current field values.

        Note: This is a placeholder. For production, use database triggers
        which are more reliable and efficient. This method would require
        a database roundtrip to use PostgreSQL's to_tsvector function.
        """
        # Database triggers are the recommended approach
        pass

    @classmethod
    def get_search_stats_sql(cls, table_name: str | None = None) -> str:
        """Generate SQL to get search index statistics.

        Args:
            table_name: Name of the table

        Returns:
            SQL query for index statistics
        """
        table_name = table_name or getattr(cls, "__tablename__", None)
        if not table_name:
            raise ValueError("Table name is required")

        return f"""
SELECT
    relname AS index_name,
    pg_size_pretty(pg_relation_size(indexrelid)) AS index_size,
    idx_scan AS index_scans,
    idx_tup_read AS tuples_read,
    idx_tup_fetch AS tuples_fetched
FROM pg_stat_user_indexes
WHERE relname LIKE 'ix_{table_name}%'
ORDER BY pg_relation_size(indexrelid) DESC;
"""


class MultiLanguageSearchMixin(SearchableMixin):
    """Extended mixin with multi-language support.

    Adds a language column that determines the text search configuration
    to use for each row. This enables mixed-language content in the same table.

    Example:
        class Article(Base, MultiLanguageSearchMixin):
            __tablename__ = "articles"
            __search_fields__ = ["title", "content"]
            __language_column__ = "language"
            __language_configs__ = {
                "en": "english",
                "es": "spanish",
                "de": "german",
                "fr": "french",
            }

            language: Mapped[str] = mapped_column(String(10), default="en")
            title: Mapped[str] = mapped_column(String(255))
            content: Mapped[str] = mapped_column(Text)
    """

    __language_column__: ClassVar[str] = "language"
    __language_configs__: ClassVar[dict[str, str]] = {
        "en": "english",
        "es": "spanish",
        "de": "german",
        "fr": "french",
        "it": "italian",
        "pt": "portuguese",
        "nl": "dutch",
        "ru": "russian",
    }
    __default_language__: ClassVar[str] = "en"

    @classmethod
    def get_search_trigger_sql(cls, table_name: str | None = None) -> str:
        """Generate SQL for a language-aware search trigger.

        The trigger selects the text search configuration based on
        the language column value.

        Args:
            table_name: Name of the table

        Returns:
            SQL statements to create the trigger
        """
        table_name = table_name or getattr(cls, "__tablename__", None)
        if not table_name:
            raise ValueError("Table name is required")

        # Build CASE expression for language selection
        lang_cases = []
        for lang_code, config in cls.__language_configs__.items():
            lang_cases.append(f"WHEN '{lang_code}' THEN '{config}'")

        default_config = cls.__language_configs__.get(
            cls.__default_language__, cls.__search_config__
        )
        lang_cases.append(f"ELSE '{default_config}'")

        lang_case = f"CASE NEW.{cls.__language_column__} " + " ".join(lang_cases) + " END"

        # Build vector parts with dynamic config
        vector_parts = []
        for field in cls.__search_fields__:
            weight = cls.get_field_weight(field)
            vector_parts.append(
                f"setweight(to_tsvector({lang_case}, coalesce(NEW.{field}, '')), '{weight}')"
            )

        vector_expr = " || ".join(vector_parts) if vector_parts else f"to_tsvector({lang_case}, '')"

        return f"""
-- Create language-aware trigger function for {table_name}
CREATE OR REPLACE FUNCTION {table_name}_search_vector_update() RETURNS trigger AS $$
DECLARE
    search_config regconfig;
BEGIN
    -- Determine text search config based on language
    search_config := ({lang_case})::regconfig;

    NEW.search_vector := {vector_expr};
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger
DROP TRIGGER IF EXISTS {table_name}_search_update ON {table_name};
CREATE TRIGGER {table_name}_search_update
    BEFORE INSERT OR UPDATE ON {table_name}
    FOR EACH ROW
    EXECUTE FUNCTION {table_name}_search_vector_update();
"""


__all__ = ["SearchableMixin", "MultiLanguageSearchMixin"]
