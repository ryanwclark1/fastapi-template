"""Tests for RRULE validators."""

import pytest

from example_service.core.validators.rrule import (
    validate_rrule_optional,
    validate_rrule_string,
)


class TestValidateRRule:
    def test_accepts_valid_rrule(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            "example_service.features.reminders.recurrence.validate_rrule",
            lambda value: (True, None),
        )

        assert validate_rrule_string("FREQ=DAILY") == "FREQ=DAILY"

    def test_raises_on_invalid_rrule(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            "example_service.features.reminders.recurrence.validate_rrule",
            lambda value: (False, "bad rule"),
        )

        with pytest.raises(ValueError) as exc:
            validate_rrule_string("invalid")

        assert "bad rule" in str(exc.value)

    def test_optional_accepts_none(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            "example_service.features.reminders.recurrence.validate_rrule",
            lambda value: (True, None),
        )

        assert validate_rrule_optional(None) is None
