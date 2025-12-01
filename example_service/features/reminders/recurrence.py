"""Recurrence rule handling for repeating reminders.

This module provides utilities for working with iCalendar RRULE strings,
allowing reminders to repeat on various schedules (daily, weekly, monthly, etc.).

The implementation uses python-dateutil's rrule module which supports the full
iCalendar RRULE specification (RFC 5545).

Example RRULE strings:
    - "FREQ=DAILY" - Every day
    - "FREQ=WEEKLY;BYDAY=MO,WE,FR" - Monday, Wednesday, Friday
    - "FREQ=MONTHLY;BYMONTHDAY=1" - First of every month
    - "FREQ=YEARLY;BYMONTH=1;BYMONTHDAY=1" - Every January 1st
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING

from dateutil.rrule import (
    DAILY,
    FR,
    MO,
    MONTHLY,
    SA,
    SU,
    TH,
    TU,
    WE,
    WEEKLY,
    YEARLY,
    rrule,
    rrulestr,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


class Frequency(str, Enum):
    """Supported recurrence frequencies."""

    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    YEARLY = "YEARLY"


class Weekday(str, Enum):
    """Days of the week for weekly recurrence."""

    MONDAY = "MO"
    TUESDAY = "TU"
    WEDNESDAY = "WE"
    THURSDAY = "TH"
    FRIDAY = "FR"
    SATURDAY = "SA"
    SUNDAY = "SU"


# Mapping from Weekday enum to dateutil weekday constants
_WEEKDAY_MAP = {
    Weekday.MONDAY: MO,
    Weekday.TUESDAY: TU,
    Weekday.WEDNESDAY: WE,
    Weekday.THURSDAY: TH,
    Weekday.FRIDAY: FR,
    Weekday.SATURDAY: SA,
    Weekday.SUNDAY: SU,
}

# Mapping from Frequency enum to dateutil frequency constants
_FREQ_MAP = {
    Frequency.DAILY: DAILY,
    Frequency.WEEKLY: WEEKLY,
    Frequency.MONTHLY: MONTHLY,
    Frequency.YEARLY: YEARLY,
}


@dataclass
class RecurrenceRule:
    """Structured representation of a recurrence rule.

    This provides a more Pythonic interface than raw RRULE strings,
    while still supporting conversion to/from the standard format.
    """

    frequency: Frequency
    interval: int = 1
    weekdays: list[Weekday] | None = None
    month_day: int | None = None
    month: int | None = None
    count: int | None = None
    until: datetime | None = None

    def to_rrule_string(self) -> str:
        """Convert to iCalendar RRULE string format.

        Returns:
            RRULE string like "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE,FR"
        """
        parts = [f"FREQ={self.frequency.value}"]

        if self.interval != 1:
            parts.append(f"INTERVAL={self.interval}")

        if self.weekdays:
            days = ",".join(w.value for w in self.weekdays)
            parts.append(f"BYDAY={days}")

        if self.month_day is not None:
            parts.append(f"BYMONTHDAY={self.month_day}")

        if self.month is not None:
            parts.append(f"BYMONTH={self.month}")

        if self.count is not None:
            parts.append(f"COUNT={self.count}")

        if self.until is not None:
            # Format as UTC timestamp
            parts.append(f"UNTIL={self.until.strftime('%Y%m%dT%H%M%SZ')}")

        return ";".join(parts)

    @classmethod
    def from_rrule_string(cls, rrule_str: str) -> RecurrenceRule:
        """Parse an RRULE string into a RecurrenceRule.

        Args:
            rrule_str: iCalendar RRULE string

        Returns:
            RecurrenceRule instance

        Raises:
            ValueError: If the RRULE string is invalid
        """
        # Parse the RRULE string into components
        parts = {}
        for part in rrule_str.split(";"):
            if "=" in part:
                key, value = part.split("=", 1)
                parts[key.upper()] = value

        # Extract frequency (required)
        freq_str = parts.get("FREQ")
        if not freq_str:
            raise ValueError("RRULE must have FREQ component")

        try:
            frequency = Frequency(freq_str)
        except ValueError:
            raise ValueError(f"Unknown frequency: {freq_str}") from None

        # Extract optional components
        interval = int(parts.get("INTERVAL", 1))

        weekdays = None
        if "BYDAY" in parts:
            weekdays = [
                Weekday(day.strip()) for day in parts["BYDAY"].split(",")
            ]

        month_day = int(parts["BYMONTHDAY"]) if "BYMONTHDAY" in parts else None
        month = int(parts["BYMONTH"]) if "BYMONTH" in parts else None
        count = int(parts["COUNT"]) if "COUNT" in parts else None

        until = None
        if "UNTIL" in parts:
            until_str = parts["UNTIL"]
            # Parse various datetime formats
            if until_str.endswith("Z"):
                until = datetime.strptime(until_str, "%Y%m%dT%H%M%SZ")
            elif "T" in until_str:
                until = datetime.strptime(until_str, "%Y%m%dT%H%M%S")
            else:
                until = datetime.strptime(until_str, "%Y%m%d")

        return cls(
            frequency=frequency,
            interval=interval,
            weekdays=weekdays,
            month_day=month_day,
            month=month,
            count=count,
            until=until,
        )


def generate_occurrences(
    rrule_string: str,
    start: datetime,
    *,
    after: datetime | None = None,
    before: datetime | None = None,
    count: int | None = None,
    include_start: bool = True,
) -> Iterator[datetime]:
    """Generate occurrence datetimes from an RRULE string.

    Args:
        rrule_string: iCalendar RRULE string (e.g., "FREQ=DAILY;INTERVAL=2")
        start: The start datetime for the recurrence series
        after: Only return occurrences after this datetime
        before: Only return occurrences before this datetime
        count: Maximum number of occurrences to return
        include_start: Whether to include the start datetime if it matches

    Yields:
        datetime objects for each occurrence

    Example:
        >>> rule = "FREQ=WEEKLY;BYDAY=MO,WE,FR"
        >>> start = datetime(2025, 1, 1, 9, 0)
        >>> for dt in generate_occurrences(rule, start, count=5):
        ...     print(dt)
    """
    try:
        rule = rrulestr(rrule_string, dtstart=start)
    except ValueError as e:
        raise ValueError(f"Invalid RRULE string: {e}") from e

    # Determine the effective after/before bounds
    effective_after = after or (start if include_start else start - timedelta(seconds=1))
    effective_before = before

    # Generate occurrences
    generated = 0
    for dt in rule:
        # Check bounds
        if not include_start and dt == start:
            continue
        if effective_after and dt < effective_after:
            continue
        if effective_before and dt > effective_before:
            break

        yield dt
        generated += 1

        if count and generated >= count:
            break


def get_next_occurrence(
    rrule_string: str,
    start: datetime,
    after: datetime | None = None,
) -> datetime | None:
    """Get the next occurrence after a given datetime.

    Args:
        rrule_string: iCalendar RRULE string
        start: The start datetime for the recurrence series
        after: Get the occurrence after this datetime (defaults to now)

    Returns:
        The next occurrence datetime, or None if no more occurrences
    """
    after = after or datetime.now(start.tzinfo)

    for dt in generate_occurrences(rrule_string, start, after=after, count=1, include_start=False):
        return dt

    return None


def validate_rrule(rrule_string: str) -> tuple[bool, str | None]:
    """Validate an RRULE string.

    Args:
        rrule_string: The RRULE string to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        # Try to parse it
        RecurrenceRule.from_rrule_string(rrule_string)
        # Also validate with dateutil
        rrulestr(rrule_string, dtstart=datetime.now())
        return True, None
    except ValueError as e:
        return False, str(e)


def describe_rrule(rrule_string: str) -> str:
    """Generate a human-readable description of an RRULE.

    Args:
        rrule_string: iCalendar RRULE string

    Returns:
        Human-readable description like "Every 2 weeks on Monday, Wednesday"
    """
    try:
        rule = RecurrenceRule.from_rrule_string(rrule_string)
    except ValueError:
        return "Invalid recurrence rule"

    # Build description
    if rule.interval == 1:
        freq_text = {
            Frequency.DAILY: "Every day",
            Frequency.WEEKLY: "Every week",
            Frequency.MONTHLY: "Every month",
            Frequency.YEARLY: "Every year",
        }[rule.frequency]
    else:
        freq_text = {
            Frequency.DAILY: f"Every {rule.interval} days",
            Frequency.WEEKLY: f"Every {rule.interval} weeks",
            Frequency.MONTHLY: f"Every {rule.interval} months",
            Frequency.YEARLY: f"Every {rule.interval} years",
        }[rule.frequency]

    parts = [freq_text]

    # Add weekday info
    if rule.weekdays:
        day_names = {
            Weekday.MONDAY: "Monday",
            Weekday.TUESDAY: "Tuesday",
            Weekday.WEDNESDAY: "Wednesday",
            Weekday.THURSDAY: "Thursday",
            Weekday.FRIDAY: "Friday",
            Weekday.SATURDAY: "Saturday",
            Weekday.SUNDAY: "Sunday",
        }
        days = [day_names[d] for d in rule.weekdays]
        if len(days) == 1:
            parts.append(f"on {days[0]}")
        else:
            parts.append(f"on {', '.join(days[:-1])} and {days[-1]}")

    # Add month day info
    if rule.month_day is not None:
        ordinal = _ordinal(rule.month_day)
        parts.append(f"on the {ordinal}")

    # Add month info
    if rule.month is not None:
        month_names = [
            "", "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December"
        ]
        parts.append(f"in {month_names[rule.month]}")

    # Add count/until
    if rule.count is not None:
        parts.append(f"({rule.count} times)")
    elif rule.until is not None:
        parts.append(f"until {rule.until.strftime('%B %d, %Y')}")

    return " ".join(parts)


def _ordinal(n: int) -> str:
    """Convert number to ordinal string (1 -> 1st, 2 -> 2nd, etc.)."""
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# Common recurrence presets for convenience
DAILY = "FREQ=DAILY"
WEEKDAYS = "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"
WEEKLY = "FREQ=WEEKLY"
BIWEEKLY = "FREQ=WEEKLY;INTERVAL=2"
MONTHLY = "FREQ=MONTHLY"
YEARLY = "FREQ=YEARLY"


__all__ = [
    "Frequency",
    "Weekday",
    "RecurrenceRule",
    "generate_occurrences",
    "get_next_occurrence",
    "validate_rrule",
    "describe_rrule",
    "DAILY",
    "WEEKDAYS",
    "WEEKLY",
    "BIWEEKLY",
    "MONTHLY",
    "YEARLY",
]
