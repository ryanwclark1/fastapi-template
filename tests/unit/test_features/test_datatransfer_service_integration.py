"""Lightweight tests around DataTransferService export helpers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from example_service.features.datatransfer import service as dt_service
from example_service.features.datatransfer.schemas import ExportFormat, ExportRequest


class DummyExporter:
    file_extension = "csv"
    content_type = "text/csv"

    def __init__(self, *args, **kwargs):
        self.called_with = None

    def export(self, records, output_path):
        self.called_with = list(records)
        output_path.write_text("data")
        return len(records)

    def export_to_bytes(self, records):
        return b"bytes"


class DummySession:
    def __init__(self, records):
        self._records = records

    async def execute(self, stmt):
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: self._records))


@pytest.mark.asyncio
async def test_export_uses_exporter_and_returns_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    records = [SimpleNamespace(id=1)]
    session = DummySession(records)
    svc = dt_service.DataTransferService(session=session)

    monkeypatch.setattr(
        svc,
        "_get_entity_config",
        lambda *_: {"exportable": True, "fields": ["id"], "model_path": "x"},
    )
    monkeypatch.setattr(svc, "_import_model", lambda *_: SimpleNamespace(search_vector=None))
    monkeypatch.setattr(dt_service, "get_exporter", lambda *_, **__: DummyExporter())
    monkeypatch.setattr(dt_service, "ensure_export_dir", lambda: tmp_path)
    monkeypatch.setattr(dt_service, "select", lambda *_: None)

    result = await svc.export(ExportRequest(entity_type="any", format=ExportFormat.CSV))
    assert result.status.name == "COMPLETED"
    assert result.record_count == len(records)
    assert result.file_path


@pytest.mark.asyncio
async def test_export_to_bytes_success(monkeypatch: pytest.MonkeyPatch) -> None:
    records = [SimpleNamespace(id=1)]
    session = DummySession(records)
    svc = dt_service.DataTransferService(session=session)

    monkeypatch.setattr(
        svc,
        "_get_entity_config",
        lambda *_: {"exportable": True, "fields": ["id"], "model_path": "x"},
    )
    monkeypatch.setattr(svc, "_import_model", lambda *_: SimpleNamespace(search_vector=None))
    monkeypatch.setattr(dt_service, "get_exporter", lambda *_, **__: DummyExporter())
    monkeypatch.setattr(dt_service, "select", lambda *_: None)

    data, content_type, filename = await svc.export_to_bytes(
        ExportRequest(entity_type="any", format=ExportFormat.CSV),
    )
    assert data == b"bytes"
    assert content_type == "text/csv"
    assert filename.endswith(".csv")


@pytest.mark.asyncio
async def test_export_to_bytes_handles_not_exportable(monkeypatch: pytest.MonkeyPatch) -> None:
    session = DummySession([])
    svc = dt_service.DataTransferService(session=session)
    monkeypatch.setattr(
        svc, "_get_entity_config", lambda *_: {"exportable": False, "fields": [], "model_path": "x"},
    )

    req = ExportRequest(entity_type="any", format=ExportFormat.CSV)
    with pytest.raises(ValueError, match="is not exportable"):
        await svc.export_to_bytes(req)
