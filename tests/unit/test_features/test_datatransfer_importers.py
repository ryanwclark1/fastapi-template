"""Tests for data transfer importers."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import pytest

from example_service.features.datatransfer import importers


def test_get_importer_validates_format():
    assert isinstance(importers.get_importer("csv"), importers.CSVImporter)
    assert isinstance(importers.get_importer("json"), importers.JSONImporter)
    assert isinstance(importers.get_importer("xlsx"), importers.ExcelImporter)
    with pytest.raises(ValueError, match="Unsupported import format"):
        importers.get_importer("unknown")


def test_json_importer_handles_invalid_shape():
    importer = importers.JSONImporter()

    with pytest.raises(importers.DataImportError):
        importer.parse_bytes(b'"not an array"')

    # object with non-list records should raise
    with pytest.raises(importers.DataImportError):
        importer.parse_bytes(b'{"records": 123}')

    # object with wrong row type produces error record
    records = importer.parse_bytes(b'{"records": ["bad"]}')
    assert records[0].errors


class TestDateTimeTypeHandling:
    """Tests for datetime type conversion in importers."""

    def test_iso_format_datetime(self):
        """Test ISO format datetime parsing."""
        importer = importers.CSVImporter(
            field_types={"created_at": datetime}
        )
        record = importer.validate_record(
            {"created_at": "2024-01-15T10:30:00"},
            row_number=1,
        )
        assert not record.errors
        assert isinstance(record.data["created_at"], datetime)
        assert record.data["created_at"].year == 2024
        assert record.data["created_at"].month == 1

    def test_iso_format_with_z_suffix(self):
        """Test ISO format with Z timezone."""
        importer = importers.CSVImporter(
            field_types={"created_at": datetime}
        )
        record = importer.validate_record(
            {"created_at": "2024-01-15T10:30:00Z"},
            row_number=1,
        )
        assert not record.errors
        assert isinstance(record.data["created_at"], datetime)

    def test_common_date_formats(self):
        """Test common date format parsing."""
        importer = importers.CSVImporter(
            field_types={"date": datetime}
        )

        # YYYY-MM-DD
        record = importer.validate_record({"date": "2024-01-15"}, row_number=1)
        assert not record.errors

        # YYYY-MM-DD HH:MM:SS
        record = importer.validate_record({"date": "2024-01-15 10:30:00"}, row_number=1)
        assert not record.errors

    def test_invalid_datetime_format(self):
        """Test invalid datetime format produces error."""
        importer = importers.CSVImporter(
            field_types={"date": datetime}
        )
        record = importer.validate_record(
            {"date": "not-a-date"},
            row_number=1,
        )
        assert len(record.errors) == 1
        assert "datetime" in record.errors[0][1].lower()


class TestUUIDTypeHandling:
    """Tests for UUID type conversion in importers."""

    def test_valid_uuid_string(self):
        """Test valid UUID string parsing."""
        importer = importers.CSVImporter(
            field_types={"id": UUID}
        )
        record = importer.validate_record(
            {"id": "12345678-1234-5678-1234-567812345678"},
            row_number=1,
        )
        assert not record.errors
        assert isinstance(record.data["id"], UUID)

    def test_invalid_uuid_string(self):
        """Test invalid UUID string produces error."""
        importer = importers.CSVImporter(
            field_types={"id": UUID}
        )
        record = importer.validate_record(
            {"id": "not-a-uuid"},
            row_number=1,
        )
        assert len(record.errors) == 1
        assert "UUID" in record.errors[0][1]


class TestBooleanTypeHandling:
    """Tests for boolean type conversion."""

    def test_boolean_string_values(self):
        """Test various boolean string representations."""
        importer = importers.CSVImporter(
            field_types={"active": bool}
        )

        for true_val in ["true", "True", "1", "yes", "on"]:
            record = importer.validate_record({"active": true_val}, row_number=1)
            assert record.data["active"] is True

        for false_val in ["false", "False", "0", "no", "off"]:
            record = importer.validate_record({"active": false_val}, row_number=1)
            assert record.data["active"] is False


class TestRequiredFieldValidation:
    """Tests for required field validation."""

    def test_missing_required_field(self):
        """Test missing required field produces error."""
        importer = importers.CSVImporter(
            required_fields=["name", "email"]
        )
        record = importer.validate_record(
            {"name": "Test"},  # missing email
            row_number=1,
        )
        assert len(record.errors) == 1
        assert "email" in record.errors[0][1].lower()

    def test_empty_required_field(self):
        """Test empty required field produces error."""
        importer = importers.CSVImporter(
            required_fields=["name"]
        )
        record = importer.validate_record(
            {"name": ""},
            row_number=1,
        )
        assert len(record.errors) == 1
