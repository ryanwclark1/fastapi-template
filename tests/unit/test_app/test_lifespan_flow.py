"""Tests for lifespan startup/shutdown flow with toggled services."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
import pytest

from example_service.app.lifespan import lifespan


class DummySettings:
    """Dummy settings for testing lifespan behavior."""

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
        self.event_bridge_enabled = configured
        self.service_availability_enabled = False
        self.enable_pipeline_api = False
        self.bucket = "test"
        self.health_check_enabled = False
        self.pool_size = 5
        self.max_overflow = 10
        self.pool_timeout = 30
        self.pool_recycle = 3600


def _patch_settings(monkeypatch: pytest.MonkeyPatch, **overrides):
    """Patch all settings getters with provided overrides."""
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
        get_docs_url=lambda: "/docs",
        get_redoc_url=lambda: "/redoc",
        get_openapi_url=lambda: "/openapi.json",
        root_path="",
    )

    monkeypatch.setattr(
        "example_service.app.lifespan.get_app_settings",
        lambda: overrides.get("app", app_settings),
    )
    monkeypatch.setattr(
        "example_service.app.lifespan.get_auth_settings",
        lambda: overrides.get("auth", minimal),
    )
    monkeypatch.setattr(
        "example_service.app.lifespan.get_consul_settings",
        lambda: overrides.get("consul", minimal),
    )
    monkeypatch.setattr(
        "example_service.app.lifespan.get_db_settings",
        lambda: overrides.get("db", minimal),
    )
    monkeypatch.setattr(
        "example_service.app.lifespan.get_redis_settings",
        lambda: overrides.get("redis", minimal),
    )
    monkeypatch.setattr(
        "example_service.app.lifespan.get_storage_settings",
        lambda: overrides.get("storage", minimal),
    )
    monkeypatch.setattr(
        "example_service.app.lifespan.get_rabbit_settings",
        lambda: overrides.get("rabbit", minimal),
    )
    monkeypatch.setattr(
        "example_service.app.lifespan.get_otel_settings",
        lambda: overrides.get("otel", minimal),
    )
    monkeypatch.setattr(
        "example_service.app.lifespan.get_logging_settings",
        lambda: overrides.get("logging", minimal),
    )
    monkeypatch.setattr(
        "example_service.app.lifespan.get_mock_settings",
        lambda: overrides.get("mock", DummySettings(configured=False)),
        raising=False,
    )
    monkeypatch.setattr(
        "example_service.app.lifespan.get_task_settings",
        lambda: overrides.get("task", minimal),
    )
    monkeypatch.setattr(
        "example_service.app.lifespan.get_websocket_settings",
        lambda: overrides.get("websocket", minimal),
    )
    monkeypatch.setattr(
        "example_service.app.lifespan.get_health_settings",
        lambda: overrides.get("health", minimal),
    )
    monkeypatch.setattr(
        "example_service.app.lifespan.get_ai_settings",
        lambda: overrides.get("ai", minimal),
    )


def _patch_infrastructure(monkeypatch: pytest.MonkeyPatch, calls: list[str]):
    """Patch infrastructure modules to record calls."""

    async def record(name: str):
        calls.append(name)
        return True  # For functions that return bool

    # Core services
    monkeypatch.setattr(
        "example_service.app.lifespan.setup_logging",
        lambda **kwargs: calls.append("setup_logging"),
    )
    monkeypatch.setattr(
        "example_service.app.lifespan.setup_tracing",
        lambda: calls.append("setup_tracing"),
    )
    metric = type("Metric", (), {"set": lambda *_: None})
    monkeypatch.setattr(
        "example_service.app.lifespan.application_info",
        SimpleNamespace(labels=lambda **_: metric()),
    )
    monkeypatch.setattr(
        "example_service.app.lifespan.database_pool_size",
        SimpleNamespace(set=lambda v: None),
    )
    monkeypatch.setattr(
        "example_service.app.lifespan.database_pool_max_overflow",
        SimpleNamespace(set=lambda v: None),
    )

    # Discovery
    monkeypatch.setattr(
        "example_service.app.lifespan.start_discovery",
        lambda: record("start_discovery"),
    )
    monkeypatch.setattr(
        "example_service.app.lifespan.stop_discovery",
        lambda: record("stop_discovery"),
    )

    # Database
    monkeypatch.setattr(
        "example_service.infra.database.session.init_database",
        lambda: record("init_database"),
    )
    monkeypatch.setattr(
        "example_service.infra.database.session.close_database",
        lambda: record("close_database"),
    )

    # Cache
    monkeypatch.setattr(
        "example_service.infra.cache.redis.start_cache",
        lambda: record("start_cache"),
    )
    monkeypatch.setattr(
        "example_service.infra.cache.redis.stop_cache",
        lambda: record("stop_cache"),
    )

    # Messaging
    monkeypatch.setattr(
        "example_service.infra.messaging.broker.start_broker",
        lambda: record("start_broker"),
    )
    monkeypatch.setattr(
        "example_service.infra.messaging.broker.stop_broker",
        lambda: record("stop_broker"),
    )

    # Task tracking
    monkeypatch.setattr(
        "example_service.infra.tasks.tracking.start_tracker",
        lambda: record("start_tracker"),
    )
    monkeypatch.setattr(
        "example_service.infra.tasks.tracking.stop_tracker",
        lambda: record("stop_tracker"),
    )

    # Outbox processor
    monkeypatch.setattr(
        "example_service.infra.events.outbox.processor.start_outbox_processor",
        lambda: record("start_outbox_processor"),
    )
    monkeypatch.setattr(
        "example_service.infra.events.outbox.processor.stop_outbox_processor",
        lambda: record("stop_outbox_processor"),
    )

    # Taskiq/Scheduler - skip initialization
    async def _noop_async():
        return None

    monkeypatch.setattr(
        "example_service.app.lifespan._initialize_taskiq_and_scheduler",
        _noop_async,
    )


@pytest.mark.asyncio
async def test_lifespan_skips_services_when_not_configured(
    monkeypatch: pytest.MonkeyPatch,
):
    """When services are not configured, they should not be started."""
    calls: list[str] = []

    _patch_settings(monkeypatch)
    _patch_infrastructure(monkeypatch, calls)

    app = FastAPI()
    async with lifespan(app):
        # Core services always run
        assert "setup_logging" in calls
        # Infrastructure should not be started when not configured
        assert "init_database" not in calls
        assert "start_cache" not in calls
        assert "start_broker" not in calls


@pytest.mark.asyncio
async def test_lifespan_runs_services_when_configured(
    monkeypatch: pytest.MonkeyPatch,
):
    """When services are configured, they should be started and stopped."""
    calls: list[str] = []

    configured = DummySettings(configured=True)
    configured.startup_require_db = False
    configured.startup_require_cache = False
    configured.startup_require_storage = False
    configured.startup_require_rabbit = False

    task_settings = DummySettings(configured=True)
    task_settings.tracking_enabled = True

    _patch_settings(
        monkeypatch,
        db=configured,
        redis=configured,
        rabbit=configured,
        consul=configured,
        otel=configured,
        task=task_settings,
    )
    _patch_infrastructure(monkeypatch, calls)

    # Mock rate limiting infrastructure
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
        "example_service.features.health.providers.RateLimiterHealthProvider",
        lambda tracker: tracker,
    )
    monkeypatch.setattr(
        "example_service.features.health.providers.TaskTrackerHealthProvider",
        lambda: object(),
    )

    app = FastAPI()
    async with lifespan(app):
        # Verify startup calls
        assert "setup_logging" in calls
        assert "setup_tracing" in calls
        assert "start_discovery" in calls
        assert "init_database" in calls
        assert "start_cache" in calls
        assert "start_broker" in calls
        assert "start_tracker" in calls
        assert "start_outbox_processor" in calls

    # Verify shutdown calls (in reverse order)
    assert "stop_outbox_processor" in calls
    assert "stop_tracker" in calls
    assert "stop_broker" in calls
    assert "stop_cache" in calls
    assert "close_database" in calls
    assert "stop_discovery" in calls


@pytest.mark.asyncio
async def test_lifespan_startup_order(monkeypatch: pytest.MonkeyPatch):
    """Services should start in the correct dependency order."""
    calls: list[str] = []

    configured = DummySettings(configured=True)
    configured.startup_require_db = False
    configured.startup_require_cache = False
    configured.startup_require_rabbit = False

    task_settings = DummySettings(configured=True)
    task_settings.tracking_enabled = True

    _patch_settings(
        monkeypatch,
        db=configured,
        redis=configured,
        rabbit=configured,
        task=task_settings,
    )
    _patch_infrastructure(monkeypatch, calls)

    # Mock rate limiting infrastructure
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
        "example_service.features.health.providers.RateLimiterHealthProvider",
        lambda tracker: tracker,
    )
    monkeypatch.setattr(
        "example_service.features.health.providers.TaskTrackerHealthProvider",
        lambda: object(),
    )

    app = FastAPI()
    async with lifespan(app):
        pass

    # Verify correct startup order:
    # 1. Core (logging)
    # 2. Database
    # 3. Cache
    # 4. Messaging
    # 5. Task tracking (after database and cache)
    # 6. Outbox (after database and messaging)
    startup_calls = [c for c in calls if c.startswith(("setup", "init", "start"))]

    db_idx = startup_calls.index("init_database")
    cache_idx = startup_calls.index("start_cache")
    broker_idx = startup_calls.index("start_broker")
    tracker_idx = startup_calls.index("start_tracker")
    outbox_idx = startup_calls.index("start_outbox_processor")

    # Database and cache should start before task tracking
    assert db_idx < tracker_idx
    assert cache_idx < tracker_idx

    # Database and messaging should start before outbox
    assert db_idx < outbox_idx
    assert broker_idx < outbox_idx
