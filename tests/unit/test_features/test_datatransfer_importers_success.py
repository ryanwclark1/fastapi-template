"""Success-path tests for data transfer importers."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from example_service.features.datatransfer import importers


def test_csv_importer_parses_rows(tmp_path: Path):
    csv_content = "name,age\nAlice,30\nBob,25\n"
    file_path = tmp_path / "data.csv"
    file_path.write_text(csv_content)

    imp = importers.CSVImporter(required_fields=["name"])
    records = imp.parse_file(file_path)

    assert len(records) == 2
    assert records[0].errors == []
    assert records[0].data["name"] == "Alice"


def test_excel_importer_parses_bytes():
    try:
        from openpyxl import Workbook
    except ImportError:  # pragma: no cover - dependency optional
        pytest.skip("openpyxl not installed")

    wb = Workbook()
    ws = wb.active
    ws.append(["name", "age"])
    ws.append(["Alice", 30])
    ws.append(["Bob", 25])
    buffer = io.BytesIO()
    wb.save(buffer)

    imp = importers.ExcelImporter(required_fields=["name"])
    records = imp.parse_bytes(buffer.getvalue())

    assert len(records) == 2
    assert records[1].data["name"] == "Bob"
