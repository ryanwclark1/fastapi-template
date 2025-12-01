"""Tests for database session helpers."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from example_service.infra.database import session as session_module


@pytest.mark.asyncio
async def test_ensure_event_outbox_table_creates_table(monkeypatch):
    """_ensure_event_outbox_table should create the table when missing."""
    temp_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    monkeypatch.setattr(session_module, "engine", temp_engine)
    monkeypatch.setattr(session_module, "_outbox_table_initialized", False)

    await session_module._ensure_event_outbox_table()

    async with temp_engine.connect() as conn:
        result = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='event_outbox'")
        )
        assert result.scalar_one() == "event_outbox"

    assert session_module._outbox_table_initialized is True
    await temp_engine.dispose()


@pytest.mark.asyncio
async def test_ensure_event_outbox_table_is_idempotent(monkeypatch):
    """Subsequent calls should no-op once initialization has run."""
    temp_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    monkeypatch.setattr(session_module, "engine", temp_engine)
    monkeypatch.setattr(session_module, "_outbox_table_initialized", False)

    await session_module._ensure_event_outbox_table()

    from example_service.infra.events.outbox.models import EventOutbox

    def fail_if_called(*args, **kwargs):  # pragma: no cover - only used on failure
        raise AssertionError("EventOutbox table creation should not be invoked twice")

    monkeypatch.setattr(EventOutbox.__table__, "create", fail_if_called)

    await session_module._ensure_event_outbox_table()
    await temp_engine.dispose()
