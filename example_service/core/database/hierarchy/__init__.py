"""Hierarchical data support using PostgreSQL ltree.

This package provides utilities for working with hierarchical (tree-structured)
data using PostgreSQL's ltree extension. Ltree stores paths as dot-separated
strings like "electronics.computers.laptops".

Components:
    - LtreePath: Python wrapper for path manipulation and navigation
    - HierarchicalMixin: Mixin for models with tree operations

The ltree extension provides efficient queries for:
    - Finding all ancestors or descendants
    - Pattern matching (e.g., "*.computers.*")
    - Subtree operations

Example:
    >>> from example_service.core.database import Base, IntegerPKMixin
    >>> from example_service.core.database.types import LtreeType
    >>> from example_service.core.database.hierarchy import HierarchicalMixin, LtreePath
    >>>
    >>> class Category(Base, IntegerPKMixin, HierarchicalMixin):
    ...     __tablename__ = "categories"
    ...     name: Mapped[str] = mapped_column(String(255))
    ...     path: Mapped[str] = mapped_column(LtreeType())
    >>>
    >>> # Python-side path manipulation
    >>> path = LtreePath("electronics.computers")
    >>> path.child("laptops")
    LtreePath("electronics.computers.laptops")
    >>>
    >>> # Database queries via mixin
    >>> cat = await session.get(Category, 1)
    >>> children = await cat.get_children(session)
    >>> ancestors = await cat.get_ancestors(session)

Note:
    - Requires PostgreSQL with ltree extension
    - Create extension: CREATE EXTENSION IF NOT EXISTS ltree
    - Add GiST index for performance: CREATE INDEX ... USING GIST (path)
"""

from example_service.core.database.hierarchy.ltree import (
    LABEL_PATTERN,
    LtreePath,
)
from example_service.core.database.hierarchy.mixins import (
    HierarchicalMixin,
)

__all__ = [
    "LABEL_PATTERN",
    "HierarchicalMixin",
    "LtreePath",
]
