"""Cursor filter for SQLAlchemy queries.

The CursorFilter implements the seek/keyset pagination method:
- Instead of OFFSET, we use WHERE conditions to seek directly to the cursor position
- This is O(1) instead of O(n) for OFFSET pagination
- Results are stable even when data changes between pages

How it works:
    For ORDER BY created_at DESC, id ASC with cursor at (t1, id1):
    WHERE (created_at < t1) OR (created_at = t1 AND id > id1)

This compound WHERE clause efficiently seeks to the correct position.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from sqlalchemy import Select, and_, or_

from example_service.core.database.filters import StatementFilter
from example_service.core.pagination.cursor import CursorCodec, CursorData

if TYPE_CHECKING:
    from sqlalchemy.orm import InstrumentedAttribute


class CursorFilter(StatementFilter):
    """Apply cursor-based pagination to a SQLAlchemy query.

    Uses the seek method (keyset pagination) for efficient pagination:
    - No OFFSET scanning - seeks directly to cursor position
    - Stable results even when data changes
    - Works with any combination of sort fields

    The filter builds a compound WHERE clause based on the cursor values
    and sort directions to efficiently seek to the correct position.

    Example:
        from example_service.core.pagination import CursorFilter

        # Apply cursor filter to query
        stmt = select(User).where(User.is_active == True)
        stmt = CursorFilter(
            cursor=request_cursor,
            order_by=[(User.created_at, "desc"), (User.id, "asc")],
        ).apply(stmt)

        # The filter adds:
        # 1. WHERE conditions to seek past the cursor
        # 2. ORDER BY clause for consistent ordering
        # 3. LIMIT clause for page size

    Attributes:
        cursor: Encoded cursor string (None for first page)
        order_by: List of (column, direction) tuples
        limit: Page size
        direction: "after" (forward) or "before" (backward)
    """

    def __init__(
        self,
        cursor: str | None,
        order_by: list[tuple[InstrumentedAttribute[Any], Literal["asc", "desc"]]],
        *,
        limit: int = 50,
        direction: Literal["after", "before"] = "after",
    ) -> None:
        """Initialize cursor filter.

        Args:
            cursor: Encoded cursor string (None for first page)
            order_by: List of (column, direction) tuples defining sort order
            limit: Maximum items to return (page size)
            direction: "after" (next page) or "before" (previous page)

        Example:
            CursorFilter(
                cursor="eyJ2Ijp7ImNyZWF...",
                order_by=[
                    (User.created_at, "desc"),
                    (User.id, "asc"),
                ],
                limit=50,
            )
        """
        self.cursor = cursor
        self.order_by = order_by
        self.limit = limit
        self.direction = direction

        # Decode cursor if provided
        self._cursor_data: CursorData | None = None
        if cursor:
            try:
                self._cursor_data = CursorCodec.decode(cursor)
            except ValueError:
                # Invalid cursor, treat as first page
                self._cursor_data = None

    def apply(self, statement: Select[Any]) -> Select[Any]:
        """Apply cursor pagination to statement.

        Adds:
        1. WHERE clause to seek past cursor (if cursor provided)
        2. ORDER BY clause for consistent ordering
        3. LIMIT clause for page size

        The WHERE clause uses compound conditions to correctly handle
        multi-column sorting. For example, with ORDER BY (a DESC, b ASC)
        and cursor at (a=5, b=10), the condition is:
            (a < 5) OR (a = 5 AND b > 10)
        """
        # Apply ORDER BY
        statement = self._apply_ordering(statement)

        # Apply cursor seek condition (if cursor provided)
        if self._cursor_data:
            statement = self._apply_seek_condition(statement)

        # Apply LIMIT (fetch one extra to detect has_more)
        return statement.limit(self.limit + 1)


    def _apply_ordering(self, statement: Select[Any]) -> Select[Any]:
        """Apply ORDER BY clause based on sort specification."""
        for column, direction in self.order_by:
            # Reverse direction for backward pagination
            effective_direction = direction
            if self.direction == "before":
                effective_direction = "asc" if direction == "desc" else "desc"

            if effective_direction == "desc":
                statement = statement.order_by(column.desc())
            else:
                statement = statement.order_by(column.asc())

        return statement

    def _apply_seek_condition(self, statement: Select[Any]) -> Select[Any]:
        """Apply WHERE condition to seek past cursor.

        Builds a compound OR condition for multi-column sorting.
        For columns (a, b, c) with cursor values (v1, v2, v3):
            (a op v1) OR
            (a = v1 AND b op v2) OR
            (a = v1 AND b = v2 AND c op v3)

        Where 'op' is > or < depending on sort direction and pagination direction.
        """
        if not self._cursor_data:
            return statement

        cursor_values = self._cursor_data.values
        or_conditions = []

        for i, (column, direction) in enumerate(self.order_by):
            field_name = column.key
            cursor_value = cursor_values.get(field_name)

            if cursor_value is None:
                continue

            # Convert cursor value to appropriate type
            cursor_value = self._convert_cursor_value(column, cursor_value)

            # Build equality conditions for preceding columns
            eq_conditions = []
            for j in range(i):
                prev_column, _ = self.order_by[j]
                prev_field = prev_column.key
                prev_value = cursor_values.get(prev_field)
                if prev_value is not None:
                    prev_value = self._convert_cursor_value(prev_column, prev_value)
                    eq_conditions.append(prev_column == prev_value)

            # Determine comparison operator
            # For "after" with "desc": we want rows that come after (less than)
            # For "after" with "asc": we want rows that come after (greater than)
            if self.direction == "after":
                if direction == "desc":
                    compare_cond = column < cursor_value
                else:
                    compare_cond = column > cursor_value
            elif direction == "desc":
                compare_cond = column > cursor_value
            else:
                compare_cond = column < cursor_value

            # Combine: (prev_cols = their_values) AND (this_col op cursor_value)
            if eq_conditions:
                or_conditions.append(and_(*eq_conditions, compare_cond))
            else:
                or_conditions.append(compare_cond)

        if or_conditions:
            statement = statement.where(or_(*or_conditions))

        return statement

    def _convert_cursor_value(
        self,
        column: InstrumentedAttribute[Any],
        value: Any,
    ) -> Any:
        """Convert cursor value to appropriate Python type.

        Handles datetime strings, UUIDs, etc. that were serialized
        when creating the cursor.
        """
        if value is None:
            return None

        # Get column type info
        column_type = getattr(column.type, "impl", column.type)
        type_name = type(column_type).__name__

        # Convert based on column type
        if type_name in ("DateTime", "TIMESTAMP"):
            if isinstance(value, str):
                # Parse ISO format datetime
                return datetime.fromisoformat(value)
            return value

        if type_name in ("Uuid", "UUID"):
            if isinstance(value, str):
                return UUID(value)
            return value

        return value

    @property
    def sort_fields(self) -> list[str]:
        """Get list of sort field names."""
        return [col.key for col, _ in self.order_by]


__all__ = ["CursorFilter"]
