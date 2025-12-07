"""PostgreSQL native range types for scheduling, price tiers, and versioning.

Provides Python wrappers for PostgreSQL's native range types:
- DATERANGE: Date ranges
- TSTZRANGE: Timestamp with timezone ranges
- INT4RANGE/INT8RANGE: Integer ranges
- NUMRANGE: Numeric/decimal ranges

Range types support efficient operations:
- Containment: Does range contain a value or another range?
- Overlap: Do two ranges overlap?
- Adjacent: Are two ranges adjacent (no gap, no overlap)?
- Exclusion constraints: Prevent overlapping ranges in database

Example:
    >>> from example_service.core.database.ranges import Range, DateRangeType
    >>>
    >>> class Booking(Base, IntegerPKMixin):
    ...     __tablename__ = "bookings"
    ...     room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"))
    ...     stay_period: Mapped[Range[date]] = mapped_column(DateRangeType())
    >>>
    >>> # Query bookings that contain a date
    >>> stmt = select(Booking).where(Booking.stay_period.op("@>")(target_date))
    >>>
    >>> # Query overlapping bookings
    >>> stmt = select(Booking).where(Booking.stay_period.op("&&")(other_range))

Note:
    - PostgreSQL only: Other databases will store as TEXT
    - Add GiST index for performance: CREATE INDEX ... USING GIST (column)
    - Use exclusion constraints to prevent overlaps
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, TypeVar

from sqlalchemy import types
from sqlalchemy.dialects.postgresql import (
    DATERANGE,
    INT4RANGE,
    INT8RANGE,
    NUMRANGE,
    TSRANGE,
    TSTZRANGE,
)

if TYPE_CHECKING:
    from collections.abc import Callable

T = TypeVar("T", date, datetime, int, Decimal)


@dataclass(frozen=True, slots=True)
class Range[T: (date, datetime, int, Decimal)]:
    """Python representation of a PostgreSQL range.

    Represents a range with configurable bounds inclusivity.
    PostgreSQL uses [) bounds by default (lower-inclusive, upper-exclusive).

    Attributes:
        lower: Lower bound (None for unbounded)
        upper: Upper bound (None for unbounded)
        bounds: Bound specification string:
            - "[)" - lower inclusive, upper exclusive (PostgreSQL default)
            - "[]" - both inclusive
            - "()" - both exclusive
            - "(]" - lower exclusive, upper inclusive

    Example:
        >>> # Date range: January 2024 (inclusive start, exclusive end)
        >>> r = Range(date(2024, 1, 1), date(2024, 2, 1), bounds="[)")
        >>>
        >>> # Check containment
        >>> date(2024, 1, 15) in r  # True
        >>> date(2024, 2, 1) in r  # False (exclusive upper)
        >>>
        >>> # Integer range: 1-10 inclusive
        >>> r = Range(1, 10, bounds="[]")
        >>> 5 in r  # True
        >>> 10 in r  # True (inclusive upper)

    Note:
        - Immutable (frozen dataclass)
        - Empty ranges have lower == upper with exclusive bounds
        - Unbounded ranges use None for lower/upper
    """

    lower: T | None
    upper: T | None
    bounds: str = "[)"  # PostgreSQL default: lower-inclusive, upper-exclusive

    def __post_init__(self) -> None:
        """Validate bounds specification and range consistency."""
        if self.bounds not in ("[]", "[)", "(]", "()"):
            raise ValueError(f"Invalid bounds: {self.bounds}. Use [], [), (], or ()")

        if (
            self.lower is not None
            and self.upper is not None
            and self.lower > self.upper
        ):
            msg = "Lower bound cannot be greater than upper bound"
            raise ValueError(msg)

    @property
    def lower_inc(self) -> bool:
        """Is lower bound inclusive?"""
        return self.bounds[0] == "["

    @property
    def upper_inc(self) -> bool:
        """Is upper bound inclusive?"""
        return self.bounds[1] == "]"

    @property
    def is_empty(self) -> bool:
        """Is this an empty range?

        A range is empty if:
        - Both bounds are equal and at least one is exclusive
        - Example: (1, 1) or [1, 1) are empty
        """
        if self.lower is None or self.upper is None:
            return False
        if self.lower == self.upper:
            return not (self.lower_inc and self.upper_inc)
        return False

    @property
    def is_unbounded_lower(self) -> bool:
        """Is lower bound unbounded (extends to -infinity)?"""
        return self.lower is None

    @property
    def is_unbounded_upper(self) -> bool:
        """Is upper bound unbounded (extends to +infinity)?"""
        return self.upper is None

    @property
    def is_bounded(self) -> bool:
        """Are both bounds defined?"""
        return self.lower is not None and self.upper is not None

    def __contains__(self, value: T) -> bool:
        """Check if value is contained in range.

        Args:
            value: Value to check

        Returns:
            True if value is within the range bounds
        """
        if value is None:
            return False

        if self.lower is not None:
            if self.lower_inc:
                if value < self.lower:
                    return False
            elif value <= self.lower:
                return False

        if self.upper is not None:
            if self.upper_inc:
                if value > self.upper:
                    return False
            elif value >= self.upper:
                return False

        return True

    def overlaps(self, other: Range[T]) -> bool:
        """Check if this range overlaps with another.

        Args:
            other: Range to check against

        Returns:
            True if ranges share any points
        """
        if self.is_empty or other.is_empty:
            return False

        # Check if ranges are disjoint
        if self.upper is not None and other.lower is not None:
            if self.upper < other.lower:
                return False
            if self.upper == other.lower and not (self.upper_inc and other.lower_inc):
                return False

        if other.upper is not None and self.lower is not None:
            if other.upper < self.lower:
                return False
            if other.upper == self.lower and not (other.upper_inc and self.lower_inc):
                return False

        return True

    def contains_range(self, other: Range[T]) -> bool:
        """Check if this range fully contains another range.

        Args:
            other: Range to check

        Returns:
            True if other is completely within this range
        """
        if other.is_empty:
            return True
        if self.is_empty:
            return False

        # Check lower bound
        if self.lower is not None:
            if other.lower is None:
                return False
            if other.lower < self.lower:
                return False
            if other.lower == self.lower and other.lower_inc and not self.lower_inc:
                return False

        # Check upper bound
        if self.upper is not None:
            if other.upper is None:
                return False
            if other.upper > self.upper:
                return False
            if other.upper == self.upper and other.upper_inc and not self.upper_inc:
                return False

        return True

    def adjacent_to(self, other: Range[T]) -> bool:
        """Check if this range is adjacent to another (no gap, no overlap).

        Adjacent ranges share a boundary point where one is exclusive
        and the other is inclusive.

        Args:
            other: Range to check

        Returns:
            True if ranges are adjacent
        """
        if self.is_empty or other.is_empty:
            return False

        # Check if self.upper is adjacent to other.lower
        if (
            self.upper is not None
            and other.lower is not None
            and self.upper == other.lower
            and self.upper_inc != other.lower_inc
        ):
            return True

        # Check if other.upper is adjacent to self.lower
        return (
            other.upper is not None
            and self.lower is not None
            and other.upper == self.lower
            and other.upper_inc != self.lower_inc
        )

    def to_tuple(self) -> tuple[T | None, T | None, str]:
        """Convert to tuple for serialization.

        Returns:
            Tuple of (lower, upper, bounds)
        """
        return (self.lower, self.upper, self.bounds)

    @classmethod
    def from_tuple(cls, t: tuple[T | None, T | None, str]) -> Range[T]:
        """Create Range from tuple.

        Args:
            t: Tuple of (lower, upper, bounds)

        Returns:
            New Range instance
        """
        return cls(t[0], t[1], t[2])

    @classmethod
    def empty(cls) -> Range[T]:
        """Create an empty range.

        Returns:
            Empty range with exclusive bounds
        """
        return cls(None, None, "()")

    @classmethod
    def unbounded(cls) -> Range[T]:
        """Create an unbounded range (contains all values).

        Returns:
            Range with both bounds as None
        """
        return cls(None, None, "[)")

    def __str__(self) -> str:
        """Return PostgreSQL-compatible string representation."""
        lower_str = "" if self.lower is None else str(self.lower)
        upper_str = "" if self.upper is None else str(self.upper)
        return f"{self.bounds[0]}{lower_str},{upper_str}{self.bounds[1]}"

    def __repr__(self) -> str:
        """Return debug representation."""
        return f"Range({self.lower!r}, {self.upper!r}, bounds={self.bounds!r})"


# =============================================================================
# Range Type Base Class
# =============================================================================


class BaseRangeType(types.UserDefinedType[Range[T]]):
    """Base class for PostgreSQL range types.

    Provides common functionality for all range types. Subclasses
    specify the PostgreSQL type and Python element type.
    """

    cache_ok = True
    pg_type: type  # Set by subclasses
    python_type: type  # Set by subclasses

    def get_col_spec(self, **kw: Any) -> str:
        """Return PostgreSQL column type specification."""
        raise NotImplementedError

    def bind_processor(self, _dialect: Any) -> Callable[[Any], Any] | None:
        """Process value before sending to database."""

        def process(value: Any) -> Any:
            if value is None:
                return None

            if isinstance(value, Range):
                # psycopg3 handles Range objects via adaptation
                # Return as psycopg3 Range type
                try:
                    from psycopg.types.range import Range as PsycopgRange

                    return PsycopgRange(
                        value.lower,
                        value.upper,
                        bounds=value.bounds,
                    )
                except ImportError:
                    # Fallback: return as string for older drivers
                    return self._to_pg_string(value)

            return value

        return process

    def result_processor(
        self, dialect: Any, coltype: Any
    ) -> Callable[[Any], Any] | None:
        """Process value received from database."""
        _ = dialect, coltype

        def process(value: Any) -> Any:
            if value is None:
                return None

            # psycopg3 returns Range objects
            if hasattr(value, "lower") and hasattr(value, "upper"):
                bounds = ""
                bounds += "[" if getattr(value, "lower_inc", True) else "("
                bounds += "]" if getattr(value, "upper_inc", False) else ")"
                return Range(value.lower, value.upper, bounds)

            return value

        return process

    def _to_pg_string(self, r: Range[T]) -> str:
        """Convert Range to PostgreSQL string representation."""
        lower = "" if r.lower is None else str(r.lower)
        upper = "" if r.upper is None else str(r.upper)
        return f"{r.bounds[0]}{lower},{upper}{r.bounds[1]}"


# =============================================================================
# Concrete Range Types
# =============================================================================


class DateRangeType(BaseRangeType[date]):
    """PostgreSQL DATERANGE type.

    Stores date ranges with configurable bounds. Useful for:
    - Booking periods (hotel stays, rentals)
    - Subscription periods
    - Date-based versioning

    Example:
        >>> class Event(Base, IntegerPKMixin):
        ...     __tablename__ = "events"
        ...     active_period: Mapped[Range[date] | None] = mapped_column(
        ...         DateRangeType(),
        ...         nullable=True,
        ...     )
        >>>
        >>> # Query events active on a specific date
        >>> stmt = select(Event).where(Event.active_period.op("@>")(date(2024, 6, 15)))
        >>>
        >>> # Query events that overlap a date range
        >>> stmt = select(Event).where(
        ...     Event.active_period.op("&&")(Range(date(2024, 1, 1), date(2024, 12, 31)))
        ... )
    """

    pg_type = DATERANGE
    python_type = date

    def get_col_spec(self, **kw: Any) -> str:
        """Return PostgreSQL column type specification."""
        _ = kw
        return "DATERANGE"


class DateTimeRangeType(BaseRangeType[datetime]):
    """PostgreSQL TSTZRANGE type (timestamp with timezone).

    Stores datetime ranges with configurable bounds. Useful for:
    - Time slot booking (meetings, appointments)
    - Shift schedules
    - Temporal validity periods

    Example:
        >>> class Booking(Base, IntegerPKMixin):
        ...     __tablename__ = "bookings"
        ...     time_slot: Mapped[Range[datetime] | None] = mapped_column(
        ...         DateTimeRangeType(),
        ...         nullable=True,
        ...     )
        >>>
        >>> # Find overlapping bookings
        >>> stmt = select(Booking).where(
        ...     Booking.time_slot.op("&&")(
        ...         Range(datetime(2024, 1, 1, 9, 0), datetime(2024, 1, 1, 10, 0))
        ...     )
        ... )

    Note:
        Default is TSTZRANGE (with timezone). Set timezone=False for TSRANGE.
    """

    pg_type: type = TSTZRANGE
    python_type = datetime

    def __init__(self, timezone: bool = True) -> None:
        """Initialize DateTimeRangeType.

        Args:
            timezone: Use TSTZRANGE (default) or TSRANGE
        """
        self._timezone = timezone
        self.pg_type = TSTZRANGE if timezone else TSRANGE

    def get_col_spec(self, **kw: Any) -> str:
        """Return PostgreSQL column type specification."""
        _ = kw
        return "TSTZRANGE" if self._timezone else "TSRANGE"


class IntRangeType(BaseRangeType[int]):
    """PostgreSQL INT4RANGE or INT8RANGE type.

    Stores integer ranges with configurable bounds. Useful for:
    - Version ranges (version 1-5)
    - Quantity ranges (order 10-100 items)
    - ID ranges for batch processing

    Example:
        >>> class PriceTier(Base, IntegerPKMixin):
        ...     __tablename__ = "price_tiers"
        ...     quantity_range: Mapped[Range[int] | None] = mapped_column(
        ...         IntRangeType(),
        ...         nullable=True,
        ...     )
        ...     price: Mapped[Decimal]
        >>>
        >>> # Find tier for quantity
        >>> stmt = select(PriceTier).where(PriceTier.quantity_range.op("@>")(50))
    """

    pg_type: type = INT4RANGE
    python_type = int

    def __init__(self, big: bool = False) -> None:
        """Initialize IntRangeType.

        Args:
            big: Use INT8RANGE for 64-bit integers (default: INT4RANGE)
        """
        self._big = big
        self.pg_type = INT8RANGE if big else INT4RANGE

    def get_col_spec(self, **kw: Any) -> str:
        """Return PostgreSQL column type specification."""
        _ = kw
        return "INT8RANGE" if self._big else "INT4RANGE"


class NumericRangeType(BaseRangeType[Decimal]):
    """PostgreSQL NUMRANGE type for decimal ranges.

    Stores decimal/numeric ranges with configurable bounds. Useful for:
    - Price ranges
    - Measurement tolerances
    - Financial thresholds

    Example:
        >>> class SalaryBand(Base, IntegerPKMixin):
        ...     __tablename__ = "salary_bands"
        ...     salary_range: Mapped[Range[Decimal] | None] = mapped_column(
        ...         NumericRangeType(),
        ...         nullable=True,
        ...     )
        ...     level: Mapped[str]
    """

    pg_type = NUMRANGE
    python_type = Decimal

    def get_col_spec(self, **kw: Any) -> str:
        """Return PostgreSQL column type specification."""
        _ = kw
        return "NUMRANGE"


# =============================================================================
# Query Helper Functions
# =============================================================================


def range_contains(column: Any, value: Any) -> Any:
    """Check if range column contains a value.

    SQL: column @> value

    Args:
        column: SQLAlchemy column of range type
        value: Value to check for containment

    Returns:
        SQLAlchemy column expression
    """
    return column.op("@>")(value)


def range_contained_by(column: Any, range_val: Range[Any]) -> Any:
    """Check if range column is contained by another range.

    SQL: column <@ range

    Args:
        column: SQLAlchemy column of range type
        range_val: Range to check containment by

    Returns:
        SQLAlchemy column expression
    """
    return column.op("<@")(range_val)


def range_overlaps(column: Any, range_val: Range[Any]) -> Any:
    """Check if range column overlaps with another range.

    SQL: column && range

    Args:
        column: SQLAlchemy column of range type
        range_val: Range to check overlap with

    Returns:
        SQLAlchemy column expression
    """
    return column.op("&&")(range_val)


def range_adjacent(column: Any, range_val: Range[Any]) -> Any:
    """Check if range column is adjacent to another range.

    SQL: column -|- range

    Args:
        column: SQLAlchemy column of range type
        range_val: Range to check adjacency with

    Returns:
        SQLAlchemy column expression
    """
    return column.op("-|-")(range_val)


def range_left_of(column: Any, range_val: Range[Any]) -> Any:
    """Check if range column is strictly left of another range.

    SQL: column << range

    Args:
        column: SQLAlchemy column of range type
        range_val: Range to check position against

    Returns:
        SQLAlchemy column expression
    """
    return column.op("<<")(range_val)


def range_right_of(column: Any, range_val: Range[Any]) -> Any:
    """Check if range column is strictly right of another range.

    SQL: column >> range

    Args:
        column: SQLAlchemy column of range type
        range_val: Range to check position against

    Returns:
        SQLAlchemy column expression
    """
    return column.op(">>")(range_val)


# =============================================================================
# Convenience Aliases
# =============================================================================

DateRange = DateRangeType
TimestampRange = DateTimeRangeType
IntRange = IntRangeType
DecimalRange = NumericRangeType


__all__ = [
    # Range types
    "BaseRangeType",
    "DateRange",
    "DateRangeType",
    "DateTimeRangeType",
    "DecimalRange",
    "IntRange",
    "IntRangeType",
    "NumericRangeType",
    # Core dataclass
    "Range",
    "TimestampRange",
    # Query helpers
    "range_adjacent",
    "range_contained_by",
    "range_contains",
    "range_left_of",
    "range_overlaps",
    "range_right_of",
]
