"""Tests for webhook validators."""

import pytest

from example_service.core.validators.webhooks import (
    RESERVED_WEBHOOK_HEADERS,
    validate_custom_headers,
    validate_custom_headers_optional,
    validate_event_types,
    validate_event_types_optional,
)


class TestValidateEventTypes:
    def test_strips_whitespace(self) -> None:
        result = validate_event_types(["  created ", "updated"])
        assert result == ["created", "updated"]

    def test_raises_on_empty_value(self) -> None:
        with pytest.raises(ValueError):
            validate_event_types(["valid", "   "])

    def test_optional_accepts_none(self) -> None:
        assert validate_event_types_optional(None) is None


class TestValidateCustomHeaders:
    def test_allows_non_reserved_headers(self) -> None:
        headers = {"X-Custom": "value", "x-trace-id": "123"}
        assert validate_custom_headers(headers) is headers

    def test_rejects_reserved_header(self) -> None:
        header = next(iter(RESERVED_WEBHOOK_HEADERS))
        with pytest.raises(ValueError):
            validate_custom_headers({header: "value"})

    def test_optional_accepts_none(self) -> None:
        assert validate_custom_headers_optional(None) is None
