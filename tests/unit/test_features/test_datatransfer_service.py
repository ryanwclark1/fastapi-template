"""Tests for data transfer service utilities."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from example_service.features.datatransfer import service as dt_service
from example_service.features.datatransfer.schemas import ExportFormat, ExportRequest


def test_ensure_export_dir_uses_configured_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    custom_dir = tmp_path / "exports"
    monkeypatch.setattr(dt_service, "EXPORT_DIR", custom_dir)

    created = dt_service.ensure_export_dir()

    assert created == custom_dir
    assert created.exists()


def test_get_supported_entities_returns_registry_entries() -> None:
    svc = dt_service.DataTransferService(session=SimpleNamespace())
    entities = svc.get_supported_entities()
    names = {e.name for e in entities}
    assert "reminders" in names
    assert "files" in names


def test_get_entity_config_validates_known_entities() -> None:
    svc = dt_service.DataTransferService(session=SimpleNamespace())
    config = svc._get_entity_config("reminders")
    assert config["display_name"]

    with pytest.raises(ValueError, match="Unknown entity type"):
        svc._get_entity_config("unknown")


@pytest.mark.asyncio
async def test_export_rejects_non_exportable_entity(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = dt_service.DataTransferService(session=SimpleNamespace(execute=lambda *_: None))
    request = ExportRequest(entity_type="files", format=ExportFormat.CSV)

    monkeypatch.setattr(
        svc,
        "_get_entity_config",
        lambda *_: {"exportable": False, "fields": [], "model_path": "x"},
    )

    result = await svc.export(request)

    assert result.status.name == "FAILED"
    assert "not exportable" in (result.error_message or "")
