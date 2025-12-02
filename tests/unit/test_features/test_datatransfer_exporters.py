"""Tests for data transfer exporters."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from example_service.features.datatransfer import exporters


def test_serialize_value_handles_common_types() -> None:
    now = datetime.now(UTC)
    uid = uuid4()
    obj = SimpleNamespace(foo="bar")

    assert exporters.serialize_value(None) is None
    assert exporters.serialize_value(now) == now.isoformat()
    assert exporters.serialize_value(uid) == str(uid)
    assert exporters.serialize_value(b"bytes") == "bytes"
    assert exporters.serialize_value(obj)["foo"] == "bar"


def test_base_exporter_extracts_and_filters_fields() -> None:
    record = SimpleNamespace(id=1, name="Alice", secret="ignore")
    base = exporters.CSVExporter(fields=["id", "name"])

    extracted = base._extract_fields(record)
    assert extracted == {"id": 1, "name": "Alice"}


def test_csv_exporter_writes_headers_and_rows(tmp_path: Path) -> None:
    records = [SimpleNamespace(id=1, name="Alice"), SimpleNamespace(id=2, name="Bob")]
    exporter = exporters.CSVExporter()
    output_file = tmp_path / "out.csv"

    count = exporter.export(records, output_file)

    content = output_file.read_text().splitlines()
    assert count == 2
    assert content[0] == "id,name"
    assert "1,Alice" in content[1]
    assert "2,Bob" in content[2]


def test_csv_exporter_to_bytes_respects_header_toggle() -> None:
    exporter = exporters.CSVExporter(include_headers=False)
    result = exporter.export_to_bytes([{"id": 1, "name": "Alice"}])
    assert b"id" not in result  # headers omitted
    assert b"Alice" in result


def test_json_exporter_produces_expected_payload(tmp_path: Path) -> None:
    exporter = exporters.JSONExporter(indent=0)
    output_file = tmp_path / "data.json"
    records = [SimpleNamespace(id=7, name="json")]

    count = exporter.export(records, output_file)
    payload = json.loads(output_file.read_text())

    assert count == 1
    assert payload["record_count"] == 1
    assert payload["records"][0]["name"] == "json"


def test_get_exporter_resolves_and_validates_format() -> None:
    assert isinstance(exporters.get_exporter("csv"), exporters.CSVExporter)
    assert isinstance(exporters.get_exporter("json"), exporters.JSONExporter)
    assert isinstance(exporters.get_exporter("excel"), exporters.ExcelExporter)

    with pytest.raises(ValueError, match="Unsupported export format"):
        exporters.get_exporter("unknown")
