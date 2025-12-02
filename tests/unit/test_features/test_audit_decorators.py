"""Tests for audit decorators."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import Request
from starlette.types import Scope

from example_service.features.audit import decorators
from example_service.features.audit.models import AuditAction


class DummyAsyncSessionCtx:
    """Simple async context manager to mimic DB session factory."""

    def __init__(self, session: Any):
        self.session = session

    async def __aenter__(self) -> Any:
        return self.session

    async def __aexit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - trivial
        return None


def _build_request() -> Request:
    scope: Scope = {
        "type": "http",
        "path": "/api/resource/123",
        "method": "POST",
        "headers": [(b"user-agent", b"pytest")],
        "client": ("127.0.0.1", 9000),
    }
    request = Request(scope)
    request.state.user_id = "user-1"
    request.state.user = SimpleNamespace(user_id="user-1")
    request.state.tenant_uuid = "tenant-1"
    request.state.request_id = "req-99"
    return request


@pytest.mark.asyncio
async def test_audited_decorator_logs_success(monkeypatch: pytest.MonkeyPatch) -> None:
    logged: list[dict[str, Any]] = []
    dummy_session = object()

    class StubAuditService:
        def __init__(self, session):
            assert session is dummy_session

        async def log(self, **kwargs):
            logged.append(kwargs)

    monkeypatch.setattr(
        "example_service.infra.database.session.get_async_session",
        lambda: DummyAsyncSessionCtx(dummy_session),
    )
    monkeypatch.setattr("example_service.features.audit.service.AuditService", StubAuditService)

    @decorators.audited("thing", capture_args=True)
    async def create_item(request: Request, id: str):
        return SimpleNamespace(id=id, value="ok")

    result = await create_item(_build_request(), id="123")
    assert result.value == "ok"

    assert logged
    assert logged[0]["action"] == AuditAction.CREATE
    assert logged[0]["entity_id"] == "123"
    assert logged[0]["user_id"] == "user-1"
    assert logged[0]["tenant_id"] == "tenant-1"
    assert logged[0]["metadata"]["function"] == "create_item"
    assert logged[0]["success"] is True
    assert logged[0]["duration_ms"] is not None
    assert logged[0]["new_values"]["id"] == "123"


@pytest.mark.asyncio
async def test_audited_decorator_handles_errors(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    logged: list[dict[str, Any]] = []

    class StubAuditService:
        def __init__(self, *_):
            pass

        async def log(self, **kwargs):
            logged.append(kwargs)

    monkeypatch.setattr(
        "example_service.infra.database.session.get_async_session",
        lambda: DummyAsyncSessionCtx(None),
    )
    monkeypatch.setattr("example_service.features.audit.service.AuditService", StubAuditService)

    @decorators.audited("thing")
    async def update_item():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await update_item()

    assert logged[0]["success"] is False
    assert "boom" in logged[0]["error_message"]


@pytest.mark.asyncio
async def test_audit_action_explicit_params(monkeypatch: pytest.MonkeyPatch) -> None:
    logged: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "example_service.infra.database.session.get_async_session",
        lambda: DummyAsyncSessionCtx(None),
    )

    class StubAuditService:
        def __init__(self, *_):
            pass

        async def log(self, **kwargs):
            logged.append(kwargs)

    monkeypatch.setattr("example_service.features.audit.service.AuditService", StubAuditService)

    @decorators.audit_action(
        action=AuditAction.UPDATE,
        entity_type="reminder",
        entity_id_param="reminder_id",
        old_values_param="old",
        new_values_param="new",
    )
    async def handler(reminder_id: int, old: dict, new: dict, request: Request | None = None):
        return {"ok": True}

    await handler(
        reminder_id=55,
        old={"name": "before"},
        new={"name": "after"},
        request=_build_request(),
    )

    assert logged
    assert logged[0]["action"] == AuditAction.UPDATE
    assert logged[0]["entity_id"] == "55"
    assert logged[0]["old_values"] == {"name": "before"}
    assert logged[0]["new_values"] == {"name": "after"}
    assert logged[0]["user_id"] == "user-1"
    assert logged[0]["tenant_id"] == "tenant-1"
