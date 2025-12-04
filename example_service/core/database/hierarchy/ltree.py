"""Python wrapper for PostgreSQL ltree paths with navigation utilities.

Provides a Pythonic interface for manipulating hierarchical paths including
navigation, validation, and path arithmetic. Works seamlessly with LtreeType.

The ltree extension stores paths as dot-separated labels like:
- "electronics.computers.laptops"
- "org.engineering.backend"

This wrapper provides Python-side operations for path manipulation without
requiring database queries.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import Self

# Valid ltree label pattern: alphanumeric and underscore, 1-256 chars
# PostgreSQL ltree labels must match: [A-Za-z0-9_]+
LABEL_PATTERN = re.compile(r"^[A-Za-z0-9_]{1,256}$")


class LtreePath:
    """Python wrapper for PostgreSQL ltree paths.

    Provides convenient methods for path manipulation, navigation,
    and validation. Can be used directly with SQLAlchemy LtreeType.

    Ltree paths are dot-separated strings representing hierarchical positions.
    For example, "electronics.computers.laptops" represents a laptop category
    nested under computers, which is nested under electronics.

    Example:
        >>> path = LtreePath("electronics.computers.laptops")
        >>> path.depth
        3
        >>> path.parent
        LtreePath("electronics.computers")
        >>> path.labels
        ['electronics', 'computers', 'laptops']
        >>> path.is_ancestor_of("electronics.computers.laptops.gaming")
        True
        >>> path / "gaming"
        LtreePath("electronics.computers.laptops.gaming")

    Note:
        - Labels must be alphanumeric with underscores (no dots, no spaces)
        - Maximum label length is 256 characters
        - Empty paths are represented as empty string
    """

    __slots__ = ("_labels", "_path")
    _path: str
    _labels: list[str]

    def __init__(self, path: str | LtreePath) -> None:
        """Initialize LtreePath from string or another LtreePath.

        Args:
            path: Dot-separated path string or existing LtreePath

        Raises:
            ValueError: If any label is invalid (contains invalid chars, too long)
        """
        if isinstance(path, LtreePath):
            self._path = path._path
            self._labels = path._labels
        else:
            self._path = str(path).strip()
            self._labels = self._path.split(".") if self._path else []
            self._validate()

    def _validate(self) -> None:
        """Validate all labels in path.

        Raises:
            ValueError: If any label is invalid
        """
        for label in self._labels:
            if not LABEL_PATTERN.match(label):
                raise ValueError(
                    f"Invalid ltree label: '{label}'. "
                    "Labels must be alphanumeric with underscores, 1-256 chars."
                )

    @property
    def depth(self) -> int:
        """Number of labels in path (nlevel in PostgreSQL).

        Returns:
            Integer depth (0 for empty path, 1 for root, etc.)

        Example:
            >>> LtreePath("a.b.c").depth
            3
        """
        return len(self._labels)

    @property
    def labels(self) -> list[str]:
        """List of path labels.

        Returns:
            Copy of labels list (modifications don't affect path)

        Example:
            >>> LtreePath("a.b.c").labels
            ['a', 'b', 'c']
        """
        return list(self._labels)

    @property
    def root(self) -> str:
        """First label in path (top of hierarchy).

        Returns:
            First label or empty string if path is empty

        Example:
            >>> LtreePath("org.dept.team").root
            'org'
        """
        return self._labels[0] if self._labels else ""

    @property
    def leaf(self) -> str:
        """Last label in path (current node).

        Returns:
            Last label or empty string if path is empty

        Example:
            >>> LtreePath("org.dept.team").leaf
            'team'
        """
        return self._labels[-1] if self._labels else ""

    @property
    def parent(self) -> LtreePath | None:
        """Parent path (one level up).

        Returns:
            Parent LtreePath or None for root/empty nodes

        Example:
            >>> LtreePath("a.b.c").parent
            LtreePath("a.b")
            >>> LtreePath("a").parent
            None
        """
        if self.depth <= 1:
            return None
        return LtreePath(".".join(self._labels[:-1]))

    @property
    def ancestors(self) -> list[LtreePath]:
        """All ancestor paths from root to parent.

        Returns:
            List of ancestor paths (excludes self), ordered root to parent

        Example:
            >>> [str(a) for a in LtreePath("a.b.c").ancestors]
            ['a', 'a.b']
        """
        result = []
        for i in range(1, self.depth):
            result.append(LtreePath(".".join(self._labels[:i])))
        return result

    def child(self, label: str) -> LtreePath:
        """Create child path by appending label.

        Args:
            label: Label to append

        Returns:
            New LtreePath with appended label

        Example:
            >>> LtreePath("a.b").child("c")
            LtreePath("a.b.c")
        """
        return LtreePath(f"{self._path}.{label}" if self._path else label)

    def sibling(self, label: str) -> LtreePath:
        """Create sibling path (same parent, different leaf).

        Args:
            label: New leaf label

        Returns:
            New LtreePath with same parent but different leaf

        Example:
            >>> LtreePath("a.b.c").sibling("d")
            LtreePath("a.b.d")
        """
        if self.parent is None:
            return LtreePath(label)
        return self.parent.child(label)

    def subpath(self, start: int, end: int | None = None) -> LtreePath:
        """Extract subpath from start to end indices.

        Args:
            start: Start index (0-based)
            end: End index (exclusive), None for end of path

        Returns:
            New LtreePath with extracted segment

        Example:
            >>> LtreePath("a.b.c.d").subpath(1, 3)
            LtreePath("b.c")
        """
        labels = self._labels[start:end]
        return LtreePath(".".join(labels)) if labels else LtreePath("")

    def is_ancestor_of(self, other: str | LtreePath) -> bool:
        """Check if this path is ancestor of other.

        An ancestor is a path that other descends from. For example,
        "a.b" is an ancestor of "a.b.c" and "a.b.c.d".

        Args:
            other: Path to check

        Returns:
            True if self is a proper ancestor of other

        Example:
            >>> LtreePath("a.b").is_ancestor_of("a.b.c")
            True
            >>> LtreePath("a.b").is_ancestor_of("a.b")
            False
        """
        other_path = LtreePath(other) if isinstance(other, str) else other
        if self.depth >= other_path.depth:
            return False
        return bool(other_path._labels[: self.depth] == self._labels)

    def is_descendant_of(self, other: str | LtreePath) -> bool:
        """Check if this path is descendant of other.

        A descendant is a path nested under another. For example,
        "a.b.c" is a descendant of "a" and "a.b".

        Args:
            other: Path to check

        Returns:
            True if self is a proper descendant of other

        Example:
            >>> LtreePath("a.b.c").is_descendant_of("a.b")
            True
            >>> LtreePath("a.b").is_descendant_of("a.b")
            False
        """
        other_path = LtreePath(other) if isinstance(other, str) else other
        if self.depth <= other_path.depth:
            return False
        return bool(self._labels[: other_path.depth] == other_path._labels)

    def is_sibling_of(self, other: str | LtreePath) -> bool:
        """Check if paths share same parent.

        Args:
            other: Path to check

        Returns:
            True if both paths have the same parent

        Example:
            >>> LtreePath("a.b.c").is_sibling_of("a.b.d")
            True
            >>> LtreePath("a.b.c").is_sibling_of("a.x.y")
            False
        """
        other_path = LtreePath(other) if isinstance(other, str) else other
        if self.depth != other_path.depth or self.depth == 0:
            return False
        return bool(self._labels[:-1] == other_path._labels[:-1])

    def common_ancestor(self, other: str | LtreePath) -> LtreePath | None:
        """Find lowest common ancestor with another path.

        The common ancestor is the longest shared prefix path.

        Args:
            other: Path to find common ancestor with

        Returns:
            Common ancestor LtreePath or None if no common ancestor

        Example:
            >>> LtreePath("a.b.c").common_ancestor("a.b.d")
            LtreePath("a.b")
            >>> LtreePath("x.y").common_ancestor("a.b")
            None
        """
        other_path = LtreePath(other) if isinstance(other, str) else other
        common: list[str] = []
        for a, b in zip(self._labels, other_path._labels, strict=False):
            if a != b:
                break
            common.append(a)
        return LtreePath(".".join(common)) if common else None

    def __truediv__(self, other: str) -> LtreePath:
        """Path concatenation using / operator.

        Args:
            other: Label to append

        Returns:
            New child path

        Example:
            >>> LtreePath("a") / "b" / "c"
            LtreePath("a.b.c")
        """
        return self.child(other)

    def __iter__(self) -> Iterator[str]:
        """Iterate over labels.

        Yields:
            Labels from root to leaf
        """
        return iter(self._labels)

    def __len__(self) -> int:
        """Return depth (number of labels)."""
        return self.depth

    def __str__(self) -> str:
        """Return string representation for database storage."""
        return str(self._path)

    def __repr__(self) -> str:
        """Return debug representation."""
        return f"LtreePath({self._path!r})"

    def __eq__(self, other: object) -> bool:
        """Check equality with another path or string."""
        if isinstance(other, LtreePath):
            return bool(self._path == other._path)
        if isinstance(other, str):
            return bool(self._path == other)
        return False

    def __hash__(self) -> int:
        """Return hash for use in sets/dicts."""
        return hash(self._path)

    def __bool__(self) -> bool:
        """Return True if path is not empty."""
        return bool(self._path)

    @classmethod
    def from_labels(cls, *labels: str) -> Self:
        """Create path from individual labels.

        Args:
            *labels: Labels to join into path

        Returns:
            New LtreePath

        Example:
            >>> LtreePath.from_labels("a", "b", "c")
            LtreePath("a.b.c")
        """
        return cls(".".join(labels))


__all__ = [
    "LABEL_PATTERN",
    "LtreePath",
]
