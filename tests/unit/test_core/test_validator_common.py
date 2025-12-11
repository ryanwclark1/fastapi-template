"""Tests for optional validator helper."""

def test_optional_validator_handles_none():
    from example_service.core.validators.common import optional_validator

    def validator(value: str) -> str:
        return value.upper()

    optional = optional_validator(validator)
    assert optional(None) is None
    assert optional("abc") == "ABC"
