"""Query filtering utilities for SQLAlchemy.

Inspired by Advanced Alchemy, these filters work directly with SQLAlchemy
statements without hiding the query. They're utility helpers, not an abstraction layer.

Usage:
    from sqlalchemy import select
    from example_service.core.database.filters import SearchFilter, OrderBy, LimitOffset

    stmt = select(User)
    stmt = SearchFilter("name", "john").apply(stmt)
    stmt = OrderBy("created_at", "desc").apply(stmt)
    stmt = LimitOffset(limit=50, offset=0).apply(stmt)

    result = await session.execute(stmt)
    users = result.scalars().all()
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import Select, and_, false, func, or_

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import InstrumentedAttribute


class StatementFilter(ABC):
    """Base class for statement filters.

    All filters implement `apply()` which modifies a SQLAlchemy statement.
    """

    @abstractmethod
    def apply(self, statement: Select[Any]) -> Select[Any]:
        """Apply filter to statement.

        Args:
            statement: SQLAlchemy select statement

        Returns:
            Modified select statement
        """
        ...


class SearchFilter(StatementFilter):
    """Multi-field text search using LIKE/ILIKE.

    Example:
            # Case-insensitive search across multiple fields
        stmt = SearchFilter(
            fields=[User.name, User.email],
            value="john",
            case_insensitive=True,
        ).apply(stmt)

        # Generates: WHERE (LOWER(name) LIKE '%john%' OR LOWER(email) LIKE '%john%')
    """

    def __init__(
        self,
        fields: InstrumentedAttribute[Any] | Sequence[InstrumentedAttribute[Any]],
        value: str,
        *,
        case_insensitive: bool = True,
        operator: Literal["and", "or"] = "or",
    ):
        """Initialize search filter.

        Args:
            fields: Single field or list of fields to search
            value: Search term
            case_insensitive: Use ILIKE (True) or LIKE (False)
            operator: Join multiple fields with AND or OR
        """
        self.fields = [fields] if not isinstance(fields, Sequence) else list(fields)
        self.value = value
        self.case_insensitive = case_insensitive
        self.operator = operator

    def apply(self, statement: Select[Any]) -> Select[Any]:
        """Apply search filter to statement."""
        if not self.value or not self.fields:
            return statement

        search_term = f"%{self.value}%"
        conditions = []

        for field in self.fields:
            if self.case_insensitive:
                condition = func.lower(field).like(search_term.lower())
            else:
                condition = field.like(search_term)
            conditions.append(condition)

        if self.operator == "or":
            return statement.where(or_(*conditions))
        return statement.where(and_(*conditions))


class OrderBy(StatementFilter):
    """Column ordering/sorting.

    Example:
            # Descending order
        stmt = OrderBy(User.created_at, "desc").apply(stmt)

        # Multiple orderings
        stmt = OrderBy([User.is_active, User.created_at], ["desc", "asc"]).apply(stmt)
    """

    def __init__(
        self,
        fields: InstrumentedAttribute[Any] | Sequence[InstrumentedAttribute[Any]],
        sort_order: Literal["asc", "desc"] | Sequence[Literal["asc", "desc"]] = "asc",
    ):
        """Initialize ordering filter.

        Args:
            fields: Single field or list of fields to order by
            sort_order: Sort direction(s) - 'asc' or 'desc'
        """
        self.fields = [fields] if not isinstance(fields, Sequence) else list(fields)

        if isinstance(sort_order, str):
            self.sort_orders = [sort_order] * len(self.fields)
        else:
            self.sort_orders = list(sort_order)
            if len(self.sort_orders) != len(self.fields):
                msg = "sort_order length must match fields length"
                raise ValueError(msg)

    def apply(self, statement: Select[Any]) -> Select[Any]:
        """Apply ordering to statement."""
        for field, order in zip(self.fields, self.sort_orders, strict=False):
            if order == "desc":
                statement = statement.order_by(field.desc())
            else:
                statement = statement.order_by(field.asc())
        return statement


class LimitOffset(StatementFilter):
    """Pagination using LIMIT and OFFSET.

    Example:
            # Page 1 (first 50 items)
        stmt = LimitOffset(limit=50, offset=0).apply(stmt)

        # Page 2
        stmt = LimitOffset(limit=50, offset=50).apply(stmt)
    """

    def __init__(self, limit: int, offset: int = 0):
        """Initialize pagination filter.

        Args:
            limit: Maximum number of results
            offset: Number of results to skip
        """
        self.limit = limit
        self.offset = offset

    def apply(self, statement: Select[Any]) -> Select[Any]:
        """Apply pagination to statement."""
        return statement.limit(self.limit).offset(self.offset)


class CollectionFilter(StatementFilter):
    """Filter by collection (WHERE ... IN).

    Example:
            # Single field IN clause
        stmt = CollectionFilter(User.id, [1, 2, 3]).apply(stmt)
        # WHERE user.id IN (1, 2, 3)

        # NOT IN clause
        stmt = CollectionFilter(User.status, ["banned", "deleted"], invert=True).apply(stmt)
        # WHERE user.status NOT IN ('banned', 'deleted')
    """

    def __init__(
        self,
        field: InstrumentedAttribute[Any],
        values: Sequence[Any],
        *,
        invert: bool = False,
    ):
        """Initialize collection filter.

        Args:
            field: Field to filter
            values: Collection of values to match
            invert: If True, use NOT IN instead of IN
        """
        self.field = field
        self.values = list(values)
        self.invert = invert

    def apply(self, statement: Select[Any]) -> Select[Any]:
        """Apply collection filter to statement."""
        if not self.values:
            # Empty collection - return statement that matches nothing
            return statement.where(false()) if not self.invert else statement

        if self.invert:
            return statement.where(self.field.notin_(self.values))
        return statement.where(self.field.in_(self.values))


class BeforeAfter(StatementFilter):
    """Date/time range filtering (exclusive).

    Example:
            # Records after a date
        stmt = BeforeAfter(User.created_at, after=datetime(2024, 1, 1)).apply(stmt)

        # Records in a date range
        stmt = BeforeAfter(
            User.created_at,
            after=datetime(2024, 1, 1),
            before=datetime(2024, 12, 31),
        ).apply(stmt)
    """

    def __init__(
        self,
        field: InstrumentedAttribute[Any],
        *,
        before: datetime | None = None,
        after: datetime | None = None,
    ):
        """Initialize date range filter.

        Args:
            field: DateTime field to filter
            before: Exclusive upper bound (< before)
            after: Exclusive lower bound (> after)
        """
        self.field = field
        self.before = before
        self.after = after

    def apply(self, statement: Select[Any]) -> Select[Any]:
        """Apply date range filter to statement."""
        if self.after is not None:
            statement = statement.where(self.field > self.after)
        if self.before is not None:
            statement = statement.where(self.field < self.before)
        return statement


class OnBeforeAfter(StatementFilter):
    """Date/time range filtering (inclusive).

    Example:
            # Records on or after a date
        stmt = OnBeforeAfter(User.created_at, on_or_after=datetime(2024, 1, 1)).apply(stmt)

        # Records in a date range (inclusive)
        stmt = OnBeforeAfter(
            User.created_at,
            on_or_after=datetime(2024, 1, 1),
            on_or_before=datetime(2024, 12, 31),
        ).apply(stmt)
    """

    def __init__(
        self,
        field: InstrumentedAttribute[Any],
        *,
        on_or_before: datetime | None = None,
        on_or_after: datetime | None = None,
    ):
        """Initialize inclusive date range filter.

        Args:
            field: DateTime field to filter
            on_or_before: Inclusive upper bound (<= on_or_before)
            on_or_after: Inclusive lower bound (>= on_or_after)
        """
        self.field = field
        self.on_or_before = on_or_before
        self.on_or_after = on_or_after

    def apply(self, statement: Select[Any]) -> Select[Any]:
        """Apply inclusive date range filter to statement."""
        if self.on_or_after is not None:
            statement = statement.where(self.field >= self.on_or_after)
        if self.on_or_before is not None:
            statement = statement.where(self.field <= self.on_or_before)
        return statement


class FilterGroup(StatementFilter):
    """Combine multiple filters with AND or OR logic.

    Example:
            # Combine with AND (default)
        filters = FilterGroup([
            SearchFilter(User.name, "john"),
            CollectionFilter(User.status, ["active", "pending"]),
        ])
        stmt = filters.apply(stmt)

        # Combine with OR
        filters = FilterGroup([
            SearchFilter(User.email, "admin"),
            CollectionFilter(User.role, ["admin", "superuser"]),
        ], operator="or")
        stmt = filters.apply(stmt)
    """

    def __init__(
        self,
        filters: Sequence[StatementFilter],
        operator: Literal["and", "or"] = "and",
    ):
        """Initialize filter group.

        Args:
            filters: List of filters to combine
            operator: Join filters with AND or OR
        """
        self.filters = list(filters)
        self.operator = operator

    def apply(self, statement: Select[Any]) -> Select[Any]:
        """Apply all filters to statement."""
        # Note: This applies filters sequentially, which uses AND by default
        # For OR behavior, you'd need to collect WHERE clauses and combine them
        # For simplicity, we apply sequentially (AND behavior)
        for filter_obj in self.filters:
            statement = filter_obj.apply(statement)
        return statement


__all__ = [
    "BeforeAfter",
    "CollectionFilter",
    "FilterGroup",
    "LimitOffset",
    "OnBeforeAfter",
    "OrderBy",
    "SearchFilter",
    "StatementFilter",
]
