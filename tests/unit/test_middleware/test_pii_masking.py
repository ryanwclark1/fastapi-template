"""Unit tests for PIIMasker."""
from __future__ import annotations

import re

import pytest

from example_service.app.middleware.request_logging import PIIMasker


class TestPIIMasker:
    """Test suite for PIIMasker utility class."""

    @pytest.fixture
    def masker(self) -> PIIMasker:
        """Create a PIIMasker instance with default settings.

        Returns:
            PIIMasker instance.
        """
        return PIIMasker()

    def test_mask_email_preserves_domain(self, masker: PIIMasker):
        """Test that email masking preserves domain by default."""
        email = "john.doe@example.com"
        masked = masker.mask_email(email)

        assert "@example.com" in masked
        assert "john.doe" not in masked
        assert masked.startswith("j")  # First character preserved

    def test_mask_email_without_domain_preservation(self):
        """Test email masking without domain preservation."""
        masker = PIIMasker(preserve_domain=False)
        email = "john.doe@example.com"
        masked = masker.mask_email(email)

        assert masked == "***@***.com"
        assert "example" not in masked

    def test_mask_email_short_local_part(self, masker: PIIMasker):
        """Test email masking with short local part."""
        email = "a@example.com"
        masked = masker.mask_email(email)

        assert "@example.com" in masked
        assert len(masked) > 1

    def test_mask_email_invalid_format(self, masker: PIIMasker):
        """Test email masking with invalid format (no @)."""
        email = "notanemail"
        masked = masker.mask_email(email)

        # Should mask entire string
        assert masked == "*" * len(email)

    def test_mask_phone_preserves_last_4(self, masker: PIIMasker):
        """Test that phone masking preserves last 4 digits."""
        phone = "555-123-4567"
        masked = masker.mask_phone(phone)

        assert "4567" in masked
        assert "555" not in masked
        assert "123" not in masked
        # Should preserve formatting
        assert masked.count("-") == 2

    def test_mask_phone_without_last_4_preservation(self):
        """Test phone masking without preserving last 4."""
        masker = PIIMasker(preserve_last_4=False)
        phone = "555-123-4567"
        masked = masker.mask_phone(phone)

        assert "4567" not in masked
        assert all(c in ["*", "-"] for c in masked)

    def test_mask_phone_various_formats(self, masker: PIIMasker):
        """Test phone masking with various formats."""
        test_cases = [
            ("5551234567", "******4567"),
            ("555.123.4567", "***.***.4567"),
            ("(555) 123-4567", "(***) ***-4567"),
            ("555 123 4567", "*** *** 4567"),
        ]

        for phone, expected_pattern in test_cases:
            masked = masker.mask_phone(phone)
            # Check last 4 digits preserved
            assert "4567" in masked

    def test_mask_credit_card_preserves_last_4(self, masker: PIIMasker):
        """Test that credit card masking preserves last 4 digits."""
        card = "4532-1234-5678-9010"
        masked = masker.mask_credit_card(card)

        assert "9010" in masked
        assert "4532" not in masked
        assert "1234" not in masked
        # Should preserve formatting
        assert masked.count("-") == 3

    def test_mask_credit_card_without_separators(self, masker: PIIMasker):
        """Test credit card masking without separators."""
        card = "4532123456789010"
        masked = masker.mask_credit_card(card)

        assert masked.endswith("9010")
        assert len(masked) == len(card)

    def test_mask_string_with_email(self, masker: PIIMasker):
        """Test string masking that contains email."""
        text = "Contact us at support@example.com for help"
        masked = masker.mask_string(text)

        assert "support@example.com" not in masked
        assert "@example.com" in masked or "@" in masked

    def test_mask_string_with_phone(self, masker: PIIMasker):
        """Test string masking that contains phone number."""
        text = "Call 555-123-4567 for more information"
        masked = masker.mask_string(text)

        assert "555-123-4567" not in masked
        assert "4567" in masked  # Last 4 preserved

    def test_mask_string_with_credit_card(self, masker: PIIMasker):
        """Test string masking that contains credit card."""
        text = "Card number: 4532-1234-5678-9010"
        masked = masker.mask_string(text)

        assert "4532-1234-5678-9010" not in masked
        assert "9010" in masked  # Last 4 preserved

    def test_mask_string_with_ssn(self, masker: PIIMasker):
        """Test string masking that contains SSN."""
        text = "SSN: 123-45-6789"
        masked = masker.mask_string(text)

        assert "123-45-6789" not in masked
        assert "123" not in masked
        assert "6789" not in masked

    def test_mask_string_with_multiple_patterns(self, masker: PIIMasker):
        """Test string masking with multiple PII patterns."""
        text = "Email: user@example.com, Phone: 555-123-4567, SSN: 123-45-6789"
        masked = masker.mask_string(text)

        # All PII should be masked
        assert "user@example.com" not in masked
        assert "555-123-4567" not in masked
        assert "123-45-6789" not in masked

    def test_mask_dict_sensitive_fields(self, masker: PIIMasker):
        """Test that sensitive field names are completely masked."""
        data = {
            "username": "john_doe",
            "password": "secret123",
            "email": "john@example.com",
            "api_key": "sk_live_1234567890",
        }

        masked = masker.mask_dict(data)

        # Password and api_key should be completely masked
        assert masked["password"] == "********"
        assert masked["api_key"] == "********"
        # Username should not be masked
        assert masked["username"] == "john_doe"
        # Email should be partially masked
        assert "@example.com" in masked["email"]

    def test_mask_dict_nested_structure(self, masker: PIIMasker):
        """Test masking nested dictionary structures."""
        data = {
            "user": {
                "name": "John Doe",
                "email": "john@example.com",
                "credentials": {"password": "secret123", "api_key": "key_123"},
            }
        }

        masked = masker.mask_dict(data)

        # Check nested masking
        assert masked["user"]["name"] == "John Doe"
        assert "@example.com" in masked["user"]["email"]
        assert masked["user"]["credentials"]["password"] == "********"
        assert masked["user"]["credentials"]["api_key"] == "********"

    def test_mask_dict_with_lists(self, masker: PIIMasker):
        """Test masking dictionary with list values."""
        data = {
            "emails": ["user1@example.com", "user2@example.com"],
            "phones": ["555-123-4567", "555-987-6543"],
        }

        masked = masker.mask_dict(data)

        # Check list items are masked
        for email in masked["emails"]:
            assert "@example.com" in email
            assert "user" not in email

        for phone in masked["phones"]:
            assert "555" not in phone

    def test_mask_dict_max_depth_limit(self, masker: PIIMasker):
        """Test that deeply nested structures respect max_depth."""
        # Create deeply nested structure
        data = {"level1": {"level2": {"level3": {"level4": {"password": "secret"}}}}}

        # Mask with low max_depth
        masked = masker.mask_dict(data, max_depth=2)

        # Should truncate at max_depth
        assert "_truncated" in str(masked)

    def test_mask_dict_preserves_non_string_values(self, masker: PIIMasker):
        """Test that non-string values are preserved."""
        data = {
            "count": 42,
            "active": True,
            "ratio": 3.14,
            "items": None,
        }

        masked = masker.mask_dict(data)

        assert masked["count"] == 42
        assert masked["active"] is True
        assert masked["ratio"] == 3.14
        assert masked["items"] is None

    def test_custom_mask_character(self):
        """Test using custom mask character."""
        masker = PIIMasker(mask_char="X")
        email = "user@example.com"
        masked = masker.mask_email(email)

        assert "X" in masked
        assert "*" not in masked

    def test_custom_sensitive_fields(self):
        """Test adding custom sensitive field names."""
        masker = PIIMasker(custom_fields={"user_id", "session_token"})

        data = {
            "user_id": "12345",
            "session_token": "abc123xyz",
            "name": "John Doe",
        }

        masked = masker.mask_dict(data)

        assert masked["user_id"] == "********"
        assert masked["session_token"] == "********"
        assert masked["name"] == "John Doe"

    def test_custom_patterns(self):
        """Test using custom regex patterns for masking."""
        # Pattern to match IP addresses
        ip_pattern = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
        masker = PIIMasker(custom_patterns={"ip_address": ip_pattern})

        text = "Server IP: 192.168.1.1"
        masked = masker.mask_string(text)

        assert "192.168.1.1" not in masked
        assert "********" in masked

    def test_case_insensitive_field_matching(self, masker: PIIMasker):
        """Test that sensitive field matching is case-insensitive."""
        data = {
            "Password": "secret123",
            "API_KEY": "key_123",
            "ApiKey": "key_456",
        }

        masked = masker.mask_dict(data)

        # All should be masked regardless of case
        assert masked["Password"] == "********"
        assert masked["API_KEY"] == "********"
        assert masked["ApiKey"] == "********"

    def test_empty_values(self, masker: PIIMasker):
        """Test masking empty or None values."""
        data = {
            "email": "",
            "password": None,
            "phone": "",
        }

        # Should not raise exception
        masked = masker.mask_dict(data)

        assert masked["email"] == ""
        assert masked["password"] is None
        assert masked["phone"] == ""

    def test_mask_authorization_headers(self, masker: PIIMasker):
        """Test masking common authorization header patterns."""
        data = {
            "headers": {
                "authorization": "Bearer secret_token_123",
                "x-api-key": "key_abc123",
                "cookie": "session=xyz789",
            }
        }

        masked = masker.mask_dict(data)

        # Authorization-related headers should be masked
        assert masked["headers"]["authorization"] == "********"
        assert masked["headers"]["x-api-key"] == "********"
        assert masked["headers"]["cookie"] == "********"

    def test_complex_real_world_data(self, masker: PIIMasker):
        """Test masking complex real-world request data."""
        data = {
            "user": {
                "username": "john_doe",
                "email": "john.doe@example.com",
                "phone": "555-123-4567",
                "address": {
                    "street": "123 Main St",
                    "city": "Springfield",
                },
            },
            "payment": {
                "card_number": "4532-1234-5678-9010",
                "cvv": "123",
                "ssn": "123-45-6789",
            },
            "metadata": {
                "ip_address": "192.168.1.1",
                "timestamp": "2024-01-01T00:00:00Z",
            },
        }

        masked = masker.mask_dict(data)

        # Verify PII is masked
        assert "@example.com" in masked["user"]["email"]
        assert "4567" in masked["user"]["phone"]
        assert "9010" in masked["payment"]["card_number"]
        assert masked["payment"]["cvv"] == "********"  # Sensitive field

        # Verify non-PII is preserved
        assert masked["user"]["username"] == "john_doe"
        assert masked["user"]["address"]["city"] == "Springfield"
        assert masked["metadata"]["timestamp"] == "2024-01-01T00:00:00Z"

    def test_list_of_dicts(self, masker: PIIMasker):
        """Test masking list of dictionaries."""
        data = {
            "users": [
                {"email": "user1@example.com", "password": "pass1"},
                {"email": "user2@example.com", "password": "pass2"},
            ]
        }

        masked = masker.mask_dict(data)

        for user in masked["users"]:
            assert "@example.com" in user["email"]
            assert user["password"] == "********"

    def test_mixed_list_types(self, masker: PIIMasker):
        """Test masking list with mixed types (strings, dicts, numbers)."""
        data = {"mixed": ["user@example.com", {"password": "secret"}, 42, None]}

        masked = masker.mask_dict(data)

        # String should be masked
        assert "@example.com" in masked["mixed"][0]
        # Dict should be masked
        assert masked["mixed"][1]["password"] == "********"
        # Number preserved
        assert masked["mixed"][2] == 42
        # None preserved
        assert masked["mixed"][3] is None

    def test_performance_with_large_data(self, masker: PIIMasker):
        """Test performance with large data structures."""
        import time

        # Create large data structure
        data = {
            "users": [
                {
                    "email": f"user{i}@example.com",
                    "phone": f"555-123-{i:04d}",
                    "password": f"secret{i}",
                }
                for i in range(100)
            ]
        }

        start = time.perf_counter()
        masked = masker.mask_dict(data)
        elapsed = time.perf_counter() - start

        # Should complete in reasonable time (< 100ms)
        assert elapsed < 0.1, f"Masking took {elapsed:.3f}s, performance issue"

        # Verify masking worked
        assert len(masked["users"]) == 100
        assert all(u["password"] == "********" for u in masked["users"])
