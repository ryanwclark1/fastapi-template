"""Tests for FastAPI application lifespan management."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

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
    base_url: str = "http://consul.test"
    application_name: str = "example-service"
    driver: str = "psycopg"
    endpoint: str = "http://otel.test"
    debug: bool = False


@pytest.mark.asyncio
async def test_lifespan_runs_with_all_dependencies_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Minimal lifespan should complete without hitting external resources."""

    dummy = DummySettings()
    _patch_setting_getters(
        monkeypatch,
        app=dummy,
        log=dummy,
        consul=dummy,
        db=dummy,
        redis=dummy,
        rabbit=dummy,
        otel=dummy,
    )
    _patch_common_dependencies(monkeypatch)

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

    _patch_setting_getters(
        monkeypatch,
        app=app_settings,
        log=log_settings,
        db=db_settings,
        redis=redis_settings,
        rabbit=DummySettings(),
        otel=DummySettings(is_configured=False),
    )

    calls: list[str] = []

    async def record(name: str):
        calls.append(name)

    _patch_common_dependencies(monkeypatch)
    monkeypatch.setattr("example_service.app.lifespan.init_database", lambda: record("db_init"))
    monkeypatch.setattr("example_service.app.lifespan.close_database", lambda: record("db_close"))
    monkeypatch.setattr("example_service.app.lifespan.start_cache", lambda: record("cache_start"))
    monkeypatch.setattr("example_service.app.lifespan.stop_cache", lambda: record("cache_stop"))
    monkeypatch.setattr(
        "example_service.app.lifespan.start_tracker", lambda: record("tracker_start")
    )
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


@pytest.mark.asyncio
async def test_lifespan_starts_and_stops_service_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    """Consul discovery should start and stop when configured."""
    consul_settings = DummySettings(is_configured=True, base_url="http://consul")
    _patch_setting_getters(
        monkeypatch,
        app=DummySettings(),
        log=DummySettings(),
        consul=consul_settings,
    )
    start_calls: list[str] = []
    stop_calls: list[str] = []

    async def start_discovery() -> bool:
        start_calls.append("start")
        return True

    async def stop_discovery() -> None:
        stop_calls.append("stop")

    _patch_common_dependencies(
        monkeypatch,
        start_discovery=start_discovery,
        stop_discovery=stop_discovery,
    )

    async with lifespan(FastAPI()):
        pass

    assert start_calls == ["start"]
    assert stop_calls == ["stop"]


@pytest.mark.asyncio
async def test_lifespan_warns_when_database_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    """Optional database should log warning instead of aborting startup."""
    db_settings = DummySettings(is_configured=True, startup_require_db=False)
    _patch_setting_getters(
        monkeypatch,
        app=DummySettings(),
        log=DummySettings(),
        db=db_settings,
    )
    warnings: list[str] = []

    async def failing_init() -> None:
        raise RuntimeError("db down")

    async def close_db() -> None:
        warnings.append("close")

    monkeypatch.setattr(
        "example_service.app.lifespan.logger.warning", lambda msg, *_, **__: warnings.append(msg)
    )
    monkeypatch.setattr("example_service.app.lifespan.init_database", failing_init)
    monkeypatch.setattr("example_service.app.lifespan.close_database", close_db)
    _patch_common_dependencies(monkeypatch)

    async with lifespan(FastAPI()):
        pass

    assert any("Database unavailable" in message for message in warnings)
    assert "close" in warnings  # shutdown still runs


@pytest.mark.asyncio
async def test_lifespan_raises_when_database_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """Startup must fail when database is required and unavailable."""
    db_settings = DummySettings(is_configured=True, startup_require_db=True)
    _patch_setting_getters(
        monkeypatch,
        app=DummySettings(),
        log=DummySettings(),
        db=db_settings,
    )

    async def failing_init() -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr("example_service.app.lifespan.init_database", failing_init)
    _patch_common_dependencies(monkeypatch)

    with pytest.raises(RuntimeError):
        async with lifespan(FastAPI()):
            pass


@pytest.mark.asyncio
async def test_lifespan_raises_when_cache_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redis failures should abort when cache is marked as required."""
    redis_settings = DummySettings(is_configured=True, startup_require_cache=True)
    _patch_setting_getters(
        monkeypatch,
        app=DummySettings(),
        log=DummySettings(),
        redis=redis_settings,
    )

    async def failing_cache() -> None:
        raise RuntimeError("redis down")

    _patch_common_dependencies(monkeypatch, start_cache=failing_cache)

    with pytest.raises(RuntimeError):
        async with lifespan(FastAPI()):
            pass


@pytest.mark.asyncio
async def test_lifespan_initializes_messaging_and_taskiq(monkeypatch: pytest.MonkeyPatch) -> None:
    """When messaging components are enabled all startup/shutdown hooks run."""
    calls: list[str] = []

    def _recorder(name: str):
        async def _run(*_: Any, **__: Any) -> None:
            calls.append(name)

        return _run

    rabbit = DummySettings(is_configured=True)
    redis = DummySettings(is_configured=True)
    otel = DummySettings(is_configured=True)
    consul = DummySettings(is_configured=True)

    _patch_setting_getters(
        monkeypatch,
        app=DummySettings(),
        log=DummySettings(),
        consul=consul,
        db=DummySettings(),
        redis=redis,
        rabbit=rabbit,
        otel=otel,
    )

    taskiq_module = SimpleNamespace(broker=True, stop_taskiq=_recorder("stop_taskiq"))
    scheduler_module = SimpleNamespace(stop_scheduler=_recorder("stop_scheduler"))

    _patch_common_dependencies(
        monkeypatch,
        start_cache=_recorder("start_cache"),
        stop_cache=_recorder("stop_cache"),
        start_tracker=_recorder("start_tracker"),
        stop_tracker=_recorder("stop_tracker"),
        start_broker=_recorder("start_broker"),
        stop_broker=_recorder("stop_broker"),
        start_discovery=_async_stub(True),
        stop_discovery=_recorder("stop_discovery"),
        taskiq_result=(taskiq_module, scheduler_module),
    )
    monkeypatch.setattr(
        "example_service.app.lifespan.setup_tracing", lambda: calls.append("setup_tracing")
    )
    # Patch task settings to enable tracking with redis backend (since redis is configured)
    task_settings = SimpleNamespace(
        tracking_enabled=True,
        result_backend="redis",
        is_redis_backend=True,
        is_postgres_backend=False,
    )
    monkeypatch.setattr(
        "example_service.app.lifespan.get_task_settings", lambda: task_settings
    )

    async with lifespan(FastAPI()):
        pass

    expected = {
        "start_cache",
        "start_tracker",
        "start_broker",
        "stop_broker",
        "stop_tracker",
        "stop_cache",
        "stop_taskiq",
        "stop_scheduler",
        "setup_tracing",
        "stop_discovery",
    }
    assert expected.issubset(calls)


def _patch_common_dependencies(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> None:
    """Patch dependencies that would otherwise perform I/O."""
    metric = type("Metric", (), {"set": lambda *_: None})
    monkeypatch.setattr(
        "example_service.app.lifespan.application_info",
        SimpleNamespace(labels=lambda **_: metric()),
    )
    monkeypatch.setattr("example_service.app.lifespan.setup_logging", lambda *_, **__: None)
    monkeypatch.setattr("example_service.app.lifespan.setup_tracing", lambda: None)
    monkeypatch.setattr(
        "example_service.app.lifespan._initialize_taskiq_and_scheduler",
        lambda *_, **__: overrides.get("taskiq_result", (None, None)),
    )
    monkeypatch.setattr(
        "example_service.app.lifespan.start_cache",
        overrides.get("start_cache", _async_stub(None)),
    )
    monkeypatch.setattr(
        "example_service.app.lifespan.stop_cache",
        overrides.get("stop_cache", _async_stub(None)),
    )
    monkeypatch.setattr(
        "example_service.app.lifespan.start_tracker",
        overrides.get("start_tracker", _async_stub(None)),
    )
    monkeypatch.setattr(
        "example_service.app.lifespan.stop_tracker",
        overrides.get("stop_tracker", _async_stub(None)),
    )
    monkeypatch.setattr(
        "example_service.app.lifespan.start_broker",
        overrides.get("start_broker", _async_stub(None)),
    )
    monkeypatch.setattr(
        "example_service.app.lifespan.stop_broker",
        overrides.get("stop_broker", _async_stub(None)),
    )
    monkeypatch.setattr(
        "example_service.app.lifespan.start_discovery",
        overrides.get("start_discovery", _async_stub(False)),
    )
    monkeypatch.setattr(
        "example_service.app.lifespan.stop_discovery",
        overrides.get("stop_discovery", _async_stub(None)),
    )


def _async_stub(result: Any) -> Callable[..., Any]:
    async def _runner(*_: Any, **__: Any) -> Any:
        return result

    return _runner


def _patch_setting_getters(
    monkeypatch: pytest.MonkeyPatch,
    *,
    app: DummySettings | None = None,
    log: DummySettings | None = None,
    consul: DummySettings | None = None,
    db: DummySettings | None = None,
    redis: DummySettings | None = None,
    rabbit: DummySettings | None = None,
    otel: DummySettings | None = None,
) -> None:
    """Override getter functions used by the lifespan manager."""
    monkeypatch.setattr(
        "example_service.app.lifespan.get_app_settings", lambda: app or DummySettings()
    )
    monkeypatch.setattr(
        "example_service.app.lifespan.get_logging_settings", lambda: log or DummySettings()
    )
    monkeypatch.setattr(
        "example_service.app.lifespan.get_consul_settings", lambda: consul or DummySettings()
    )
    monkeypatch.setattr(
        "example_service.app.lifespan.get_db_settings", lambda: db or DummySettings()
    )
    monkeypatch.setattr(
        "example_service.app.lifespan.get_redis_settings", lambda: redis or DummySettings()
    )
    monkeypatch.setattr(
        "example_service.app.lifespan.get_rabbit_settings", lambda: rabbit or DummySettings()
    )
    monkeypatch.setattr(
        "example_service.app.lifespan.get_otel_settings", lambda: otel or DummySettings()
    )
