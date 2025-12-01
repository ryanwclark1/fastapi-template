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
"""

from __future__ import annotations

from typing import Any, ClassVar

from sqlalchemy import Index
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from example_service.core.database.search.types import TSVECTOR


class SearchableMixin:
    """Mixin that adds full-text search capability to a model.

    Subclasses must define:
    - __search_fields__: List of field names to include in search
    - __search_config__: PostgreSQL text search configuration (optional)
    - __search_weights__: Dict mapping fields to weight classes (optional)

    The mixin adds:
    - search_vector column (TSVECTOR type)
    - GIN index on search_vector for fast searches

    Example:
        class Product(Base, SearchableMixin):
            __tablename__ = "products"
            __search_fields__ = ["name", "description", "sku"]
            __search_config__ = "english"

            name: Mapped[str] = mapped_column(String(255))
            description: Mapped[str] = mapped_column(Text)
            sku: Mapped[str] = mapped_column(String(50))

        # The model now has:
        # - product.search_vector column
        # - GIN index ix_products_search_vector
    """

    __allow_unmapped__ = True

    # Class variables to be overridden by subclasses
    __search_fields__: ClassVar[list[str]] = []
    __search_config__: ClassVar[str] = "english"
    __search_weights__: ClassVar[dict[str, str]] = {}  # field -> A/B/C/D

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

    @declared_attr
    def __table_args__(cls) -> tuple:
        """Add GIN index for search vector.

        GIN (Generalized Inverted Index) is optimized for TSVECTOR
        columns and provides fast full-text search.
        """
        # Get existing table args if any
        existing_args = getattr(cls, "__table_args_extra__", ())
        if not isinstance(existing_args, tuple):
            existing_args = (existing_args,)

        # Add GIN index for search vector
        gin_index = Index(
            f"ix_{cls.__tablename__}_search_vector",
            cls.search_vector,
            postgresql_using="gin",
        )

        return (*existing_args, gin_index)

    def build_search_vector_sql(self) -> str:
        """Build SQL expression for updating the search vector.

        Returns SQL that can be used in a trigger or UPDATE statement
        to rebuild the search vector from the search fields.

        Returns:
            SQL expression string

        Example:
            # Returns something like:
            # setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
            # setweight(to_tsvector('english', coalesce(content, '')), 'B')
        """
        parts = []
        config = self.__search_config__

        for field in self.__search_fields__:
            weight = self.__search_weights__.get(field, "D")
            part = f"setweight(to_tsvector('{config}', coalesce({field}, '')), '{weight}')"
            parts.append(part)

        if not parts:
            return f"to_tsvector('{config}', '')"

        return " || ".join(parts)

    @classmethod
    def get_search_trigger_sql(cls, table_name: str) -> str:
        """Generate SQL for creating a search vector update trigger.

        The trigger automatically updates the search_vector column
        whenever the searchable fields are modified.

        Args:
            table_name: Name of the table

        Returns:
            SQL statements to create the trigger function and trigger
        """
        config = cls.__search_config__
        fields = cls.__search_fields__
        weights = cls.__search_weights__

        # Build the vector expression
        vector_parts = []
        for field in fields:
            weight = weights.get(field, "D")
            vector_parts.append(
                f"setweight(to_tsvector('{config}', coalesce(NEW.{field}, '')), '{weight}')"
            )

        vector_expr = " || ".join(vector_parts) if vector_parts else f"to_tsvector('{config}', '')"

        return f"""
-- Create trigger function
CREATE OR REPLACE FUNCTION {table_name}_search_vector_update() RETURNS trigger AS $$
BEGIN
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

    def update_search_vector(self) -> None:
        """Update search vector from current field values.

        Call this before committing if not using database triggers.
        Note: This is a Python-side update; for production, use
        database triggers for consistency.
        """
        # This would require a database call to use to_tsvector
        # For now, this is a placeholder - use triggers in production
        pass


__all__ = ["SearchableMixin"]
