"""Unit tests for recurrence rule handling."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

pytest.importorskip("dateutil.rrule", reason="Recurrence utilities require python-dateutil")

from example_service.features.reminders.recurrence import (
    BIWEEKLY,
    DAILY,
    MONTHLY,
    WEEKDAYS,
    WEEKLY,
    YEARLY,
    Frequency,
    RecurrenceRule,
    Weekday,
    describe_rrule,
    generate_occurrences,
    get_next_occurrence,
    validate_rrule,
)

# ──────────────────────────────────────────────────────────────
# Test RecurrenceRule
# ──────────────────────────────────────────────────────────────


class TestRecurrenceRule:
    """Tests for RecurrenceRule dataclass."""

    def test_simple_daily_rule(self):
        """Daily recurrence should generate correct RRULE."""
        rule = RecurrenceRule(frequency=Frequency.DAILY)

        rrule_str = rule.to_rrule_string()

        assert rrule_str == "FREQ=DAILY"

    def test_weekly_with_interval(self):
        """Weekly recurrence with interval should include INTERVAL."""
        rule = RecurrenceRule(frequency=Frequency.WEEKLY, interval=2)

        rrule_str = rule.to_rrule_string()

        assert rrule_str == "FREQ=WEEKLY;INTERVAL=2"

    def test_weekly_with_weekdays(self):
        """Weekly recurrence with days should include BYDAY."""
        rule = RecurrenceRule(
            frequency=Frequency.WEEKLY,
            weekdays=[Weekday.MONDAY, Weekday.WEDNESDAY, Weekday.FRIDAY],
        )

        rrule_str = rule.to_rrule_string()

        assert "FREQ=WEEKLY" in rrule_str
        assert "BYDAY=MO,WE,FR" in rrule_str

    def test_monthly_with_day(self):
        """Monthly recurrence with day should include BYMONTHDAY."""
        rule = RecurrenceRule(
            frequency=Frequency.MONTHLY,
            month_day=15,
        )

        rrule_str = rule.to_rrule_string()

        assert "FREQ=MONTHLY" in rrule_str
        assert "BYMONTHDAY=15" in rrule_str

    def test_rule_with_count(self):
        """Recurrence with count should include COUNT."""
        rule = RecurrenceRule(
            frequency=Frequency.DAILY,
            count=10,
        )

        rrule_str = rule.to_rrule_string()

        assert "FREQ=DAILY" in rrule_str
        assert "COUNT=10" in rrule_str

    def test_rule_with_until(self):
        """Recurrence with until should include UNTIL."""
        until = datetime(2025, 12, 31, 23, 59, 59)
        rule = RecurrenceRule(
            frequency=Frequency.WEEKLY,
            until=until,
        )

        rrule_str = rule.to_rrule_string()

        assert "FREQ=WEEKLY" in rrule_str
        assert "UNTIL=20251231T235959Z" in rrule_str

    def test_from_rrule_string_simple(self):
        """Should parse simple RRULE string."""
        rule = RecurrenceRule.from_rrule_string("FREQ=DAILY")

        assert rule.frequency == Frequency.DAILY
        assert rule.interval == 1

    def test_from_rrule_string_complex(self):
        """Should parse complex RRULE string."""
        rrule_str = "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE,FR;COUNT=10"
        rule = RecurrenceRule.from_rrule_string(rrule_str)

        assert rule.frequency == Frequency.WEEKLY
        assert rule.interval == 2
        assert rule.weekdays == [Weekday.MONDAY, Weekday.WEDNESDAY, Weekday.FRIDAY]
        assert rule.count == 10

    def test_roundtrip(self):
        """to_rrule_string and from_rrule_string should be inverses."""
        original = RecurrenceRule(
            frequency=Frequency.MONTHLY,
            interval=3,
            month_day=1,
            count=12,
        )

        rrule_str = original.to_rrule_string()
        parsed = RecurrenceRule.from_rrule_string(rrule_str)

        assert parsed.frequency == original.frequency
        assert parsed.interval == original.interval
        assert parsed.month_day == original.month_day
        assert parsed.count == original.count


# ──────────────────────────────────────────────────────────────
# Test generate_occurrences
# ──────────────────────────────────────────────────────────────


class TestGenerateOccurrences:
    """Tests for generate_occurrences function."""

    def test_daily_occurrences(self):
        """Daily recurrence should generate consecutive days."""
        start = datetime(2025, 1, 1, 9, 0, 0)
        occurrences = list(generate_occurrences(DAILY, start, count=5))

        assert len(occurrences) == 5
        assert occurrences[0] == start
        assert occurrences[1] == start + timedelta(days=1)
        assert occurrences[4] == start + timedelta(days=4)

    def test_weekly_occurrences(self):
        """Weekly recurrence should generate weekly intervals."""
        start = datetime(2025, 1, 1, 9, 0, 0)  # Wednesday
        occurrences = list(generate_occurrences(WEEKLY, start, count=3))

        assert len(occurrences) == 3
        assert occurrences[0] == start
        assert occurrences[1] == start + timedelta(weeks=1)
        assert occurrences[2] == start + timedelta(weeks=2)

    def test_weekdays_occurrences(self):
        """Weekday recurrence should skip weekends."""
        # Start on Monday, January 6, 2025
        start = datetime(2025, 1, 6, 9, 0, 0)
        occurrences = list(generate_occurrences(WEEKDAYS, start, count=7))

        assert len(occurrences) == 7
        # First week: Mon, Tue, Wed, Thu, Fri
        # Then skip weekend, next Mon, Tue
        weekdays = [dt.weekday() for dt in occurrences]
        # All should be weekdays (0-4)
        assert all(d < 5 for d in weekdays)

    def test_occurrences_with_after(self):
        """Should only return occurrences after specified date."""
        start = datetime(2025, 1, 1, 9, 0, 0)
        after = datetime(2025, 1, 5, 0, 0, 0)

        occurrences = list(generate_occurrences(DAILY, start, after=after, count=3))

        assert len(occurrences) == 3
        assert all(dt > after for dt in occurrences)

    def test_occurrences_with_before(self):
        """Should stop at before date."""
        start = datetime(2025, 1, 1, 9, 0, 0)
        before = datetime(2025, 1, 5, 0, 0, 0)

        occurrences = list(generate_occurrences(DAILY, start, before=before, count=100))

        assert len(occurrences) == 4  # Jan 1, 2, 3, 4
        assert all(dt < before for dt in occurrences)

    def test_biweekly_occurrences(self):
        """Biweekly recurrence should generate every 2 weeks."""
        start = datetime(2025, 1, 1, 9, 0, 0)
        occurrences = list(generate_occurrences(BIWEEKLY, start, count=3))

        assert len(occurrences) == 3
        assert occurrences[1] == start + timedelta(weeks=2)
        assert occurrences[2] == start + timedelta(weeks=4)

    def test_exclude_start(self):
        """include_start=False should skip the start date."""
        start = datetime(2025, 1, 1, 9, 0, 0)
        occurrences = list(generate_occurrences(DAILY, start, count=3, include_start=False))

        assert len(occurrences) == 3
        assert occurrences[0] == start + timedelta(days=1)


# ──────────────────────────────────────────────────────────────
# Test get_next_occurrence
# ──────────────────────────────────────────────────────────────


class TestGetNextOccurrence:
    """Tests for get_next_occurrence function."""

    def test_next_daily(self):
        """Should return next day for daily recurrence."""
        start = datetime(2025, 1, 1, 9, 0, 0)
        after = datetime(2025, 1, 3, 10, 0, 0)  # After Jan 3 morning

        next_occ = get_next_occurrence(DAILY, start, after)

        assert next_occ is not None
        assert next_occ == datetime(2025, 1, 4, 9, 0, 0)

    def test_next_weekly(self):
        """Should return next week for weekly recurrence."""
        start = datetime(2025, 1, 1, 9, 0, 0)  # Wednesday
        after = datetime(2025, 1, 1, 10, 0, 0)  # Same day, later

        next_occ = get_next_occurrence(WEEKLY, start, after)

        assert next_occ is not None
        assert next_occ == datetime(2025, 1, 8, 9, 0, 0)


# ──────────────────────────────────────────────────────────────
# Test validate_rrule
# ──────────────────────────────────────────────────────────────


class TestValidateRrule:
    """Tests for validate_rrule function."""

    def test_valid_rrule(self):
        """Valid RRULE should return True."""
        is_valid, error = validate_rrule("FREQ=DAILY;INTERVAL=2")

        assert is_valid is True
        assert error is None

    def test_invalid_frequency(self):
        """Invalid frequency should return False."""
        is_valid, error = validate_rrule("FREQ=INVALID")

        assert is_valid is False
        assert error is not None
        assert "frequency" in error.lower()

    def test_missing_freq(self):
        """Missing FREQ should return False."""
        is_valid, error = validate_rrule("INTERVAL=2")

        assert is_valid is False
        assert error is not None


# ──────────────────────────────────────────────────────────────
# Test describe_rrule
# ──────────────────────────────────────────────────────────────


class TestDescribeRrule:
    """Tests for describe_rrule function."""

    def test_describe_daily(self):
        """Daily rule should describe as 'Every day'."""
        description = describe_rrule("FREQ=DAILY")

        assert "Every day" in description

    def test_describe_weekly(self):
        """Weekly rule should describe as 'Every week'."""
        description = describe_rrule("FREQ=WEEKLY")

        assert "Every week" in description

    def test_describe_weekly_with_days(self):
        """Weekly with days should list the days."""
        description = describe_rrule("FREQ=WEEKLY;BYDAY=MO,WE,FR")

        assert "Monday" in description
        assert "Wednesday" in description
        assert "Friday" in description

    def test_describe_with_interval(self):
        """Rule with interval should include the number."""
        description = describe_rrule("FREQ=WEEKLY;INTERVAL=2")

        assert "2 weeks" in description

    def test_describe_monthly(self):
        """Monthly rule should describe frequency."""
        description = describe_rrule("FREQ=MONTHLY;BYMONTHDAY=15")

        assert "month" in description.lower()
        assert "15th" in description

    def test_describe_invalid(self):
        """Invalid rule should return error message."""
        description = describe_rrule("INVALID")

        assert "Invalid" in description


# ──────────────────────────────────────────────────────────────
# Test Presets
# ──────────────────────────────────────────────────────────────


class TestPresets:
    """Tests for predefined RRULE constants."""

    def test_daily_preset(self):
        """DAILY preset should be valid."""
        is_valid, _ = validate_rrule(DAILY)
        assert is_valid

    def test_weekly_preset(self):
        """WEEKLY preset should be valid."""
        is_valid, _ = validate_rrule(WEEKLY)
        assert is_valid

    def test_weekdays_preset(self):
        """WEEKDAYS preset should be valid."""
        is_valid, _ = validate_rrule(WEEKDAYS)
        assert is_valid

    def test_biweekly_preset(self):
        """BIWEEKLY preset should be valid."""
        is_valid, _ = validate_rrule(BIWEEKLY)
        assert is_valid

    def test_monthly_preset(self):
        """MONTHLY preset should be valid."""
        is_valid, _ = validate_rrule(MONTHLY)
        assert is_valid

    def test_yearly_preset(self):
        """YEARLY preset should be valid."""
        is_valid, _ = validate_rrule(YEARLY)
        assert is_valid
