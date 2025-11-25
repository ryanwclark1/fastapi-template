"""Tests for FastAPI application lifespan management."""
from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi import FastAPI

from example_service.app.lifespan import lifespan


@dataclass
class DummySettings:
    service_name: str = "example-service"
    environment: str = "test"
    version: str = "0.0.1"
    host: str = "0.0.0.0"
    port: int = 8000
    is_configured: bool = False
    startup_require_db: bool = False
    startup_require_cache: bool = False


@pytest.mark.asyncio
async def test_lifespan_runs_with_all_dependencies_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Minimal lifespan should complete without hitting external resources."""

    dummy = DummySettings()
    monkeypatch.setattr("example_service.app.lifespan.get_app_settings", lambda: dummy)
    monkeypatch.setattr("example_service.app.lifespan.get_logging_settings", lambda: dummy)
    monkeypatch.setattr("example_service.app.lifespan.get_db_settings", lambda: dummy)
    monkeypatch.setattr("example_service.app.lifespan.get_redis_settings", lambda: dummy)
    monkeypatch.setattr("example_service.app.lifespan.get_rabbit_settings", lambda: dummy)
    monkeypatch.setattr("example_service.app.lifespan.get_otel_settings", lambda: dummy)
    monkeypatch.setattr("example_service.app.lifespan.configure_logging", lambda **_: None)
    monkeypatch.setattr("example_service.app.lifespan.application_info", type("Obj", (), {"labels": staticmethod(lambda **_: type("Metric", (), {"set": lambda self, value: None})())}))

    app = FastAPI()
    async with lifespan(app):
        assert True  # context enters and exits cleanly


@pytest.mark.asyncio
async def test_lifespan_initializes_database_and_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """When services are configured, startup should call init and shutdown should close them."""

    db_settings = DummySettings(is_configured=True)
    redis_settings = DummySettings(is_configured=True)
    app_settings = DummySettings()
    log_settings = DummySettings()

    monkeypatch.setattr("example_service.app.lifespan.get_app_settings", lambda: app_settings)
    monkeypatch.setattr("example_service.app.lifespan.get_logging_settings", lambda: log_settings)
    monkeypatch.setattr("example_service.app.lifespan.get_db_settings", lambda: db_settings)
    monkeypatch.setattr("example_service.app.lifespan.get_redis_settings", lambda: redis_settings)
    monkeypatch.setattr("example_service.app.lifespan.get_rabbit_settings", lambda: DummySettings())
    monkeypatch.setattr("example_service.app.lifespan.get_otel_settings", lambda: DummySettings(is_configured=False))

    calls: list[str] = []

    async def record(name: str):
        calls.append(name)

    monkeypatch.setattr("example_service.app.lifespan.configure_logging", lambda **_: None)
    monkeypatch.setattr("example_service.app.lifespan.setup_tracing", lambda: None)
    monkeypatch.setattr("example_service.app.lifespan.application_info", type("Obj", (), {"labels": staticmethod(lambda **_: type("Metric", (), {"set": lambda self, value: None})())}))
    monkeypatch.setattr("example_service.app.lifespan.init_database", lambda: record("db_init"))
    monkeypatch.setattr("example_service.app.lifespan.close_database", lambda: record("db_close"))
    monkeypatch.setattr("example_service.app.lifespan.start_cache", lambda: record("cache_start"))
    monkeypatch.setattr("example_service.app.lifespan.stop_cache", lambda: record("cache_stop"))
    monkeypatch.setattr("example_service.app.lifespan.start_tracker", lambda: record("tracker_start"))
    monkeypatch.setattr("example_service.app.lifespan.stop_tracker", lambda: record("tracker_stop"))
    monkeypatch.setattr(
        "example_service.app.lifespan._initialize_taskiq_and_scheduler",
        lambda *_, **__: (None, None),
    )

    app = FastAPI()

    async with lifespan(app):
        pass

    assert calls == [
        "db_init",
        "cache_start",
        "tracker_start",
        "tracker_stop",
        "cache_stop",
        "db_close",
    ]
