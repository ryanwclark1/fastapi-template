"""Mixins for models with hierarchical (ltree) paths.

Provides convenient tree navigation methods for models that use LtreeType
columns. The mixin adds instance and class methods for traversing the
hierarchy without writing raw SQL.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from sqlalchemy import func, select

if TYPE_CHECKING:
    from typing import Self

    from sqlalchemy.ext.asyncio import AsyncSession


class HierarchicalMixin:
    """Mixin for models with ltree path column.

    Provides tree navigation methods and query helpers for models using
    PostgreSQL's ltree type. The model must have a `path` column of LtreeType.

    Methods use async SQLAlchemy sessions for database operations. All navigation
    methods perform actual database queries except where noted.

    Example:
        >>> from example_service.core.database import Base, IntegerPKMixin, TimestampMixin
        >>> from example_service.core.database.types import LtreeType
        >>>
        >>> class Category(Base, IntegerPKMixin, TimestampMixin, HierarchicalMixin):
        ...     __tablename__ = "categories"
        ...     name: Mapped[str] = mapped_column(String(255))
        ...     path: Mapped[str] = mapped_column(LtreeType())
        >>>
        >>> # Instance navigation
        >>> cat = await session.get(Category, 1)
        >>> parent = await cat.get_parent(session)
        >>> children = await cat.get_children(session)
        >>> ancestors = await cat.get_ancestors(session)
        >>> descendants = await cat.get_descendants(session)
        >>>
        >>> # Class-level queries
        >>> roots = await Category.get_roots(session)

    Note:
        - Requires PostgreSQL with ltree extension
        - Path column must be named 'path' by default (configurable via __path_column__)
        - All methods are async and require a session parameter
    """

    __allow_unmapped__ = True

    # Override in subclass to use different column name
    __path_column__: ClassVar[str] = "path"

    @property
    def hierarchy_depth(self) -> int:
        """Return depth of this node in hierarchy.

        This property does NOT query the database - it calculates depth
        from the current path value.

        Returns:
            Integer depth (1 for root nodes)

        Example:
            >>> category.path = "electronics.computers.laptops"
            >>> category.hierarchy_depth
            3
        """
        from example_service.core.database.hierarchy.ltree import LtreePath

        path_value = getattr(self, self.__path_column__)
        if not path_value:
            return 0
        return LtreePath(str(path_value)).depth

    @property
    def is_root(self) -> bool:
        """Check if this is a root node (depth 1).

        This property does NOT query the database.

        Returns:
            True if this node has no parent
        """
        return self.hierarchy_depth == 1

    @property
    def path_labels(self) -> list[str]:
        """Get list of path labels.

        This property does NOT query the database.

        Returns:
            List of labels from root to this node

        Example:
            >>> category.path = "electronics.computers.laptops"
            >>> category.path_labels
            ['electronics', 'computers', 'laptops']
        """
        from example_service.core.database.hierarchy.ltree import LtreePath

        path_value = getattr(self, self.__path_column__)
        if not path_value:
            return []
        return LtreePath(str(path_value)).labels

    async def get_parent(self, session: AsyncSession) -> Self | None:
        """Get parent node.

        Args:
            session: Async database session

        Returns:
            Parent instance or None if this is a root node
        """
        from example_service.core.database.hierarchy.ltree import LtreePath

        path_value = getattr(self, self.__path_column__)
        if not path_value:
            return None

        ltree_path = LtreePath(str(path_value))
        if ltree_path.parent is None:
            return None

        path_col = getattr(self.__class__, self.__path_column__)
        stmt = select(self.__class__).where(path_col == str(ltree_path.parent))
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_children(self, session: AsyncSession) -> list[Self]:
        """Get immediate children (direct descendants one level down).

        Uses lquery pattern matching to find nodes exactly one level below
        this node.

        Args:
            session: Async database session

        Returns:
            List of child instances, ordered by path
        """
        path_value = getattr(self, self.__path_column__)
        if not path_value:
            return []

        path_col = getattr(self.__class__, self.__path_column__)
        # Pattern matches exactly one more level: current.path.*{1}
        pattern = f"{path_value}.*{{1}}"

        stmt = select(self.__class__).where(path_col.match(pattern))
        stmt = stmt.order_by(path_col)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_siblings(self, session: AsyncSession, *, include_self: bool = False) -> list[Self]:
        """Get sibling nodes (same parent).

        Args:
            session: Async database session
            include_self: Include this node in results (default: False)

        Returns:
            List of sibling instances, ordered by path
        """
        from example_service.core.database.hierarchy.ltree import LtreePath

        path_value = getattr(self, self.__path_column__)
        if not path_value:
            return []

        ltree_path = LtreePath(str(path_value))
        if ltree_path.parent is None:
            # Root nodes: siblings are other roots
            return await self.__class__.get_roots(session, exclude_id=None if include_self else getattr(self, "id", None))

        path_col = getattr(self.__class__, self.__path_column__)
        # Pattern: parent.*{1} matches all children of parent
        pattern = f"{ltree_path.parent}.*{{1}}"

        stmt = select(self.__class__).where(path_col.match(pattern))
        if not include_self:
            stmt = stmt.where(path_col != str(path_value))
        stmt = stmt.order_by(path_col)

        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_ancestors(
        self,
        session: AsyncSession,
        *,
        include_self: bool = False,
    ) -> list[Self]:
        """Get all ancestor nodes (from root to parent).

        Args:
            session: Async database session
            include_self: Include this node at end of list (default: False)

        Returns:
            List of ancestor instances, ordered from root to parent (optionally self)
        """
        from example_service.core.database.hierarchy.ltree import LtreePath

        path_value = getattr(self, self.__path_column__)
        if not path_value:
            return []

        ltree_path = LtreePath(str(path_value))
        ancestor_paths = [str(a) for a in ltree_path.ancestors]

        if include_self:
            ancestor_paths.append(str(path_value))

        if not ancestor_paths:
            return []

        path_col = getattr(self.__class__, self.__path_column__)
        stmt = select(self.__class__).where(path_col.in_(ancestor_paths))
        # Order by depth (nlevel function)
        stmt = stmt.order_by(func.nlevel(path_col))

        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_descendants(
        self,
        session: AsyncSession,
        *,
        include_self: bool = False,
        max_depth: int | None = None,
    ) -> list[Self]:
        """Get all descendant nodes.

        Args:
            session: Async database session
            include_self: Include this node at start of list (default: False)
            max_depth: Maximum depth of descendants relative to this node
                      (None for unlimited)

        Returns:
            List of descendant instances, ordered by path
        """
        path_value = getattr(self, self.__path_column__)
        if not path_value:
            return []

        path_col = getattr(self.__class__, self.__path_column__)

        # Use <@ operator: descendant_of
        if include_self:
            # Includes self and all descendants
            stmt = select(self.__class__).where(path_col.descendant_of(str(path_value)))
        else:
            # Only descendants (not self)
            stmt = select(self.__class__).where(
                path_col.descendant_of(str(path_value)),
                path_col != str(path_value),
            )

        if max_depth is not None:
            current_depth = self.hierarchy_depth
            stmt = stmt.where(func.nlevel(path_col) <= current_depth + max_depth)

        stmt = stmt.order_by(path_col)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_subtree_count(self, session: AsyncSession, *, include_self: bool = False) -> int:
        """Get count of descendants.

        More efficient than len(await get_descendants()) as it uses COUNT.

        Args:
            session: Async database session
            include_self: Include this node in count (default: False)

        Returns:
            Number of descendant nodes
        """
        path_value = getattr(self, self.__path_column__)
        if not path_value:
            return 0

        path_col = getattr(self.__class__, self.__path_column__)

        if include_self:
            stmt = select(func.count()).select_from(self.__class__).where(
                path_col.descendant_of(str(path_value)),
            )
        else:
            stmt = select(func.count()).select_from(self.__class__).where(
                path_col.descendant_of(str(path_value)),
                path_col != str(path_value),
            )

        result = await session.execute(stmt)
        return result.scalar() or 0

    @classmethod
    async def get_roots(
        cls,
        session: AsyncSession,
        *,
        exclude_id: Any = None,
    ) -> list[Self]:
        """Get all root nodes (depth 1).

        Args:
            session: Async database session
            exclude_id: Optional ID to exclude from results

        Returns:
            List of root instances, ordered by path
        """
        path_col = getattr(cls, cls.__path_column__)
        stmt = select(cls).where(func.nlevel(path_col) == 1)

        if exclude_id is not None:
            id_col = getattr(cls, "id", None)
            if id_col is not None:
                stmt = stmt.where(id_col != exclude_id)

        stmt = stmt.order_by(path_col)

        result = await session.execute(stmt)
        return list(result.scalars().all())

    @classmethod
    async def get_by_path(cls, session: AsyncSession, path: str) -> Self | None:
        """Get node by exact path.

        Args:
            session: Async database session
            path: Exact path to match

        Returns:
            Instance or None if not found
        """
        path_col = getattr(cls, cls.__path_column__)
        stmt = select(cls).where(path_col == path)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @classmethod
    async def get_descendants_of(
        cls,
        session: AsyncSession,
        path: str,
        *,
        include_root: bool = False,
        max_depth: int | None = None,
    ) -> list[Self]:
        """Get all descendants of a path (class method version).

        Useful when you have a path string but not an instance.

        Args:
            session: Async database session
            path: Ancestor path
            include_root: Include the root path in results
            max_depth: Maximum depth relative to path (None for unlimited)

        Returns:
            List of descendant instances, ordered by path
        """
        from example_service.core.database.hierarchy.ltree import LtreePath

        path_col = getattr(cls, cls.__path_column__)
        root_path = LtreePath(path)

        if include_root:
            stmt = select(cls).where(path_col.descendant_of(str(path)))
        else:
            stmt = select(cls).where(
                path_col.descendant_of(str(path)),
                path_col != str(path),
            )

        if max_depth is not None:
            stmt = stmt.where(func.nlevel(path_col) <= root_path.depth + max_depth)

        stmt = stmt.order_by(path_col)
        result = await session.execute(stmt)
        return list(result.scalars().all())


__all__ = [
    "HierarchicalMixin",
]
