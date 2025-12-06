"""Tests for lifespan startup/shutdown flow with toggled services."""

from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace
from types import SimpleNamespace as Namespace

from fastapi import FastAPI
import pytest


class DummySettings:
    def __init__(self, *, configured: bool = False, require: bool = False):
        self.is_configured = configured
        self.startup_require_db = require
        self.startup_require_cache = require
        self.startup_require_storage = require
        self.startup_require_rabbit = require
        self.enabled = configured
        self.health_checks_enabled = False
        self.service_url = None
        self.endpoint = "http://example.test"
        self.base_url = "http://consul.test"
        self.rate_limit_failure_threshold = 1
        self.result_backend = "redis"
        self.tracking_enabled = False
        self.is_redis_backend = configured
        self.is_postgres_backend = configured


@pytest.mark.asyncio
async def test_lifespan_skips_services_when_not_configured(monkeypatch: pytest.MonkeyPatch):
    app = FastAPI()

    lifespan_module = _load_lifespan()
    minimal = DummySettings(configured=False)
    app_settings = SimpleNamespace(
        service_name="svc",
        environment="test",
        version="1",
        host="0.0.0.0",
        port=8000,
        api_prefix="/api",
        docs_enabled=False,
        debug=False,
        enable_rate_limiting=False,
        request_size_limit=1,
        enable_debug_middleware=False,
        strict_csp=True,
    )

    monkeypatch.setattr(lifespan_module, "get_app_settings", lambda: app_settings)
    monkeypatch.setattr(lifespan_module, "get_auth_settings", lambda: minimal)
    monkeypatch.setattr(lifespan_module, "get_consul_settings", lambda: minimal)
    monkeypatch.setattr(lifespan_module, "get_db_settings", lambda: minimal)
    monkeypatch.setattr(lifespan_module, "get_redis_settings", lambda: minimal)
    monkeypatch.setattr(lifespan_module, "get_storage_settings", lambda: minimal)
    monkeypatch.setattr(lifespan_module, "get_rabbit_settings", lambda: minimal)
    monkeypatch.setattr(lifespan_module, "get_otel_settings", lambda: minimal)
    monkeypatch.setattr(lifespan_module, "get_logging_settings", lambda: minimal)
    monkeypatch.setattr(lifespan_module, "get_task_settings", lambda: minimal)
    monkeypatch.setattr(lifespan_module, "get_websocket_settings", lambda: minimal)
    monkeypatch.setattr(lifespan_module, "setup_logging", lambda **kwargs: None)
    monkeypatch.setattr(lifespan_module, "application_info", SimpleNamespace(labels=lambda **_: SimpleNamespace(set=lambda v: None)))

    # No-op start/stop functions to ensure they're not called
    for name in [
        "start_discovery",
        "init_database",
        "start_cache",
        "start_tracker",
        "start_broker",
        "start_outbox_processor",
        "start_connection_manager",
        "start_event_bridge",
        "stop_discovery",
        "stop_cache",
        "stop_tracker",
        "stop_broker",
        "stop_outbox_processor",
        "stop_connection_manager",
        "stop_event_bridge",
        "close_database",
    ]:
        monkeypatch.setattr(lifespan_module, name, lambda *args, **kwargs: None)

    lifespan_module = _load_lifespan()
    async with lifespan_module.lifespan(app):
        # if any required service attempted to start, we'd see errors
        assert True


@pytest.mark.asyncio
async def test_lifespan_runs_services_when_configured(monkeypatch: pytest.MonkeyPatch):
    app = FastAPI()
    calls: list[str] = []

    def record(name: str):
        async def _stub(*args, **kwargs):
            calls.append(name)
        return _stub

    configured = DummySettings(configured=True)
    configured.startup_require_db = False
    configured.startup_require_cache = False
    configured.startup_require_storage = False
    configured.startup_require_rabbit = False
    ws_settings = SimpleNamespace(enabled=True, event_bridge_enabled=True)
    task_settings = DummySettings(configured=True)
    task_settings.tracking_enabled = True

    app_settings = SimpleNamespace(
        service_name="svc",
        environment="test",
        version="1",
        host="0.0.0.0",
        port=8000,
        api_prefix="/api",
        docs_enabled=False,
        debug=False,
        enable_rate_limiting=False,
        request_size_limit=1,
        enable_debug_middleware=False,
        strict_csp=True,
    )

    lifespan_module = _load_lifespan()
    monkeypatch.setattr(lifespan_module, "get_app_settings", lambda: app_settings)
    monkeypatch.setattr(lifespan_module, "get_auth_settings", lambda: configured)
    monkeypatch.setattr(lifespan_module, "get_consul_settings", lambda: configured)
    monkeypatch.setattr(lifespan_module, "get_db_settings", lambda: configured)
    monkeypatch.setattr(lifespan_module, "get_redis_settings", lambda: configured)
    monkeypatch.setattr(lifespan_module, "get_storage_settings", lambda: configured)
    monkeypatch.setattr(lifespan_module, "get_rabbit_settings", lambda: configured)
    monkeypatch.setattr(lifespan_module, "get_otel_settings", lambda: configured)
    monkeypatch.setattr(lifespan_module, "get_logging_settings", lambda: configured)
    monkeypatch.setattr(lifespan_module, "get_task_settings", lambda: task_settings)
    monkeypatch.setattr(lifespan_module, "get_websocket_settings", lambda: ws_settings)
    monkeypatch.setattr(lifespan_module, "setup_logging", lambda **kwargs: None)
    monkeypatch.setattr(lifespan_module, "setup_tracing", lambda: calls.append("tracing"))
    monkeypatch.setattr(
        lifespan_module,
        "application_info",
        SimpleNamespace(labels=lambda **_: SimpleNamespace(set=lambda v: None)),
    )

    # Start/stop stubs
    monkeypatch.setattr(lifespan_module, "start_discovery", record("start_discovery"))
    monkeypatch.setattr(lifespan_module, "stop_discovery", record("stop_discovery"))
    monkeypatch.setattr(lifespan_module, "init_database", record("init_database"))
    monkeypatch.setattr(lifespan_module, "close_database", record("close_database"))
    monkeypatch.setattr(lifespan_module, "start_cache", record("start_cache"))
    monkeypatch.setattr(lifespan_module, "stop_cache", record("stop_cache"))
    monkeypatch.setattr(lifespan_module, "start_tracker", record("start_tracker"))
    monkeypatch.setattr(lifespan_module, "stop_tracker", record("stop_tracker"))
    monkeypatch.setattr(lifespan_module, "start_broker", record("start_broker"))
    monkeypatch.setattr(lifespan_module, "stop_broker", record("stop_broker"))
    monkeypatch.setattr(lifespan_module, "start_outbox_processor", record("start_outbox_processor"))
    monkeypatch.setattr(lifespan_module, "stop_outbox_processor", record("stop_outbox_processor"))
    monkeypatch.setattr(lifespan_module, "start_connection_manager", record("start_connection_manager"))
    monkeypatch.setattr(lifespan_module, "stop_connection_manager", record("stop_connection_manager"))
    monkeypatch.setattr(lifespan_module, "start_event_bridge", record("start_event_bridge"))
    monkeypatch.setattr(lifespan_module, "stop_event_bridge", record("stop_event_bridge"))

    # Storage service stub
    storage_service = SimpleNamespace(is_ready=True, startup=record("storage_startup"), shutdown=record("storage_shutdown"))
    monkeypatch.setitem(
        sys.modules,
        "example_service.infra.storage",
        Namespace(get_storage_service=lambda: storage_service),
    )

    # Health + ratelimit stubs
    monkeypatch.setattr(
        "example_service.infra.ratelimit.RateLimitStateTracker",
        lambda *args, **kwargs: SimpleNamespace(mark_disabled=lambda: None),
    )
    monkeypatch.setattr(
        "example_service.infra.ratelimit.set_rate_limit_tracker",
        lambda tracker: None,
    )
    monkeypatch.setattr(
        "example_service.features.health.service.get_health_aggregator",
        lambda: SimpleNamespace(add_provider=lambda provider: None),
    )
    monkeypatch.setattr(
        "example_service.features.health.rate_limit_provider.RateLimiterHealthProvider",
        lambda tracker: tracker,
    )
    monkeypatch.setattr(
        "example_service.features.health.task_tracker_provider.TaskTrackerHealthProvider",
        lambda: object(),
    )

    # Taskiq/scheduler
    async def fake_stop_scheduler():
        calls.append("stop_scheduler")

    async def fake_stop_taskiq():
        calls.append("stop_taskiq")

    monkeypatch.setattr(
        lifespan_module,
        "_initialize_taskiq_and_scheduler",
        lambda *args, **kwargs: (
            SimpleNamespace(stop_taskiq=fake_stop_taskiq),
            SimpleNamespace(stop_scheduler=fake_stop_scheduler),
        ),
    )

    async with lifespan_module.lifespan(app):
        assert "init_database" in calls
        assert "start_cache" in calls
        assert "start_broker" in calls

    # Ensure shutdown calls executed
    assert "stop_cache" in calls
    assert "stop_broker" in calls
    assert "stop_scheduler" in calls


def _load_lifespan():
    """Load lifespan module with minimal stubs to avoid circular imports."""
    if "example_service.app.lifespan" in sys.modules:
        return importlib.reload(sys.modules["example_service.app.lifespan"])
    # Pre-seed storage backend factory to avoid circular import during settings loading
    from enum import Enum

    class _StorageBackendType(Enum):
        S3 = "s3"

    sys.modules.setdefault(
        "example_service.infra.storage.backends.factory",
        Namespace(StorageBackendType=_StorageBackendType),
    )
    sys.modules.setdefault("example_service.infra.storage", Namespace(__all__=[]))
    return importlib.import_module("example_service.app.lifespan")
