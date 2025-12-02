"""Tests for PIIMasker utility in request logging middleware."""

from __future__ import annotations

from example_service.app.middleware.request_logging import PIIMasker


def test_masker_masks_common_pii_fields_and_strings():
    masker = PIIMasker()
    data = {
        "email": "user@example.com",
        "phone": "555-123-4567",
        "password": "secret123",
        "nested": {"token": "abcd1234efgh5678"},
        "list": [{"ssn": "123-45-6789"}, "4111-1111-1111-1111"],
        "note": "Call me at 555-000-1111 or email test@test.com",
    }

    masked = masker.mask_dict(data)

    assert masked["email"] != "user@example.com"
    assert masked["phone"].startswith("***-***")
    assert masked["password"] == "*" * 8
    assert masked["nested"]["token"] == "*" * 8
    assert masked["list"][0]["ssn"] == "*" * len("123-45-6789")
    assert "***@" in masked["note"]
    assert "***-***-1111" in masked["note"]


def test_masker_truncates_on_max_depth_and_custom_pattern():
    masker = PIIMasker(custom_patterns={"hex": PIIMasker.API_KEY_PATTERN})
    deep = {"a": {"b": {"c": {"d": {"e": "value"}}}}}
    masked = masker.mask_dict(deep, max_depth=2)
    assert masked["a"]["b"]["c"] == {"_truncated": "max_depth_exceeded"}

    api_key = "A" * 32
    masked_string = masker.mask_string(f"token {api_key}")
    assert "*" * 8 in masked_string
