"""Tests for data transfer importers."""

from __future__ import annotations

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

    with pytest.raises(importers.ImportError):
        importer.parse_bytes(b'"not an array"')

    # object with non-list records should raise
    with pytest.raises(importers.ImportError):
        importer.parse_bytes(b'{"records": 123}')

    # object with wrong row type produces error record
    records = importer.parse_bytes(b'{"records": ["bad"]}')
    assert records[0].errors
