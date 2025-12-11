"""Tests for FastAPI application lifespan management."""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib
import sys
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI
import pytest

from example_service.app.lifespan import lifespan

if TYPE_CHECKING:
    from collections.abc import Callable
else:  # pragma: no cover - runtime placeholder for typing-only import
    Callable = Any


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
    startup_require_storage: bool = False
    startup_require_rabbit: bool = False
    base_url: str = "http://consul.test"
    application_name: str = "example-service"
    driver: str = "psycopg"
    endpoint: str = "http://otel.test"
    debug: bool = False
    enabled: bool = False
    persona: str = "admin"
    health_checks_enabled: bool = False
    health_check_mode: Any = field(
        default_factory=lambda: SimpleNamespace(value="disabled"),
    )
    service_url: str | None = None
    rate_limit_failure_threshold: int = 1
    tracking_enabled: bool = False
    result_backend: str = "redis"
    is_redis_backend: bool = False
    is_postgres_backend: bool = False
    event_bridge_enabled: bool = False
    service_availability_enabled: bool = False
    enable_pipeline_api: bool = False
    api_prefix: str = "/api"
    docs_enabled: bool = False
    enable_rate_limiting: bool = False
    request_size_limit: int = 1
    max_retries: int = 3
    retry_delay: float = 0.05
    retry_timeout: float = 1.0
    enable_debug_middleware: bool = False
    strict_csp: bool = False
    pool_size: int = 5
    max_overflow: int = 10
    pool_timeout: int = 30
    pool_recycle: int = 3600
    pool_pre_ping: bool = False
    bucket: str = ""
    health_check_enabled: bool = False
    db: int = 0
    max_connections: int = 10
    socket_timeout: float = 5.0
    url: str = "redis://localhost:6379/0"
    queue_prefix: str = "example-service"
    exchange_name: str = "example-service"
    connection_timeout: float = 5.0
    graceful_timeout: float = 5.0
    broker_url: str = "amqp://guest:guest@localhost:5672/"
    echo: bool = False
    get_docs_url: Any = lambda: "/docs"
    get_redoc_url: Any = lambda: "/redoc"
    get_openapi_url: Any = lambda: "/openapi.json"
    root_path: str = ""

    def get_sqlalchemy_url(self) -> str:
        """Return a placeholder SQLAlchemy URL for database settings."""
        return self.__dict__.get(
            "_sqlalchemy_url",
            "postgresql+psycopg://user:pass@localhost:5432/example",
        )

    def get_psycopg_url(self) -> str:
        """Return a placeholder psycopg-compatible URL for database settings."""
        return self.__dict__.get(
            "_psycopg_url",
            "postgresql://user:pass@localhost:5432/example",
        )

    def sqlalchemy_engine_kwargs(self) -> dict[str, Any]:
        """Match the DatabaseSettings interface used during startup."""
        return {
            "pool_size": self.pool_size,
            "max_overflow": self.max_overflow,
            "pool_pre_ping": self.pool_pre_ping,
            "pool_timeout": self.pool_timeout,
            "pool_recycle": self.pool_recycle,
            "echo": self.echo,
        }

    def connection_pool_kwargs(self) -> dict[str, Any]:
        return {}

    def get_prefixed_queue(self, base_name: str) -> str:
        return f"{self.queue_prefix}.{base_name}"

    def get_url(self) -> str:
        url_value = self.__dict__.get("url")
        if isinstance(url_value, str) and url_value:
            return url_value
        broker_value = self.__dict__.get("broker_url")
        if isinstance(broker_value, str) and broker_value:
            return broker_value
        return "redis://localhost:6379/0"

    def to_logging_kwargs(self) -> dict[str, Any]:
        return {}

    def __getattr__(self, _: str) -> Any:  # pragma: no cover - test helper fallback
        return None


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
async def test_lifespan_initializes_database_and_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    monkeypatch.setattr(
        "example_service.infra.database.session.init_database",
        lambda: record("db_init"),
    )
    monkeypatch.setattr(
        "example_service.infra.database.session.close_database",
        lambda: record("db_close"),
    )
    monkeypatch.setattr(
        "example_service.infra.cache.redis.start_cache", lambda: record("cache_start"),
    )
    monkeypatch.setattr(
        "example_service.infra.cache.redis.stop_cache", lambda: record("cache_stop"),
    )
    monkeypatch.setattr(
        "example_service.infra.tasks.tracking.start_tracker",
        lambda: record("tracker_start"),
    )
    monkeypatch.setattr(
        "example_service.infra.tasks.tracking.stop_tracker",
        lambda: record("tracker_stop"),
    )

    task_settings = DummySettings(
        tracking_enabled=True,
        result_backend="redis",
        is_redis_backend=True,
        is_postgres_backend=False,
    )
    monkeypatch.setattr(
        "example_service.core.settings.get_task_settings", lambda: task_settings,
    )
    monkeypatch.setattr(
        "example_service.app.lifespan.get_task_settings", lambda: task_settings,
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
async def test_lifespan_starts_and_stops_service_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
async def test_lifespan_warns_when_database_optional(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        msg = "db down"
        raise RuntimeError(msg)

    async def close_db() -> None:
        warnings.append("close")

    monkeypatch.setattr(
        "example_service.app.lifespan.logger.warning",
        lambda msg, *_, **__: warnings.append(msg),
    )
    monkeypatch.setattr(
        "example_service.infra.database.session.init_database", failing_init,
    )
    monkeypatch.setattr(
        "example_service.infra.database.session.close_database", close_db,
    )
    _patch_common_dependencies(monkeypatch)

    async with lifespan(FastAPI()):
        pass

    assert any("Database unavailable" in message for message in warnings)
    assert "close" in warnings  # shutdown still runs


@pytest.mark.asyncio
async def test_lifespan_raises_when_database_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Startup must fail when database is required and unavailable."""
    db_settings = DummySettings(is_configured=True, startup_require_db=True)
    _patch_setting_getters(
        monkeypatch,
        app=DummySettings(),
        log=DummySettings(),
        db=db_settings,
    )

    async def failing_init() -> None:
        msg = "db down"
        raise RuntimeError(msg)

    monkeypatch.setattr(
        "example_service.infra.database.session.init_database", failing_init,
    )
    _patch_common_dependencies(monkeypatch)

    with pytest.raises(RuntimeError):
        async with lifespan(FastAPI()):
            pass


@pytest.mark.asyncio
async def test_lifespan_raises_when_cache_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Redis failures should abort when cache is marked as required."""
    redis_settings = DummySettings(is_configured=True, startup_require_cache=True)
    _patch_setting_getters(
        monkeypatch,
        app=DummySettings(),
        log=DummySettings(),
        redis=redis_settings,
    )

    async def failing_cache() -> None:
        msg = "redis down"
        raise RuntimeError(msg)

    _patch_common_dependencies(monkeypatch, start_cache=failing_cache)

    with pytest.raises(RuntimeError):
        async with lifespan(FastAPI()):
            pass


@pytest.mark.asyncio
async def test_lifespan_initializes_messaging_and_taskiq(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When messaging components are enabled all startup/shutdown hooks run."""
    calls: list[str] = []

    def _recorder(name: str):
        async def _run(*_: Any, **__: Any) -> None:
            calls.append(name)

        return _run

    rabbit = DummySettings(
        is_configured=True,
        url="amqp://guest:guest@localhost:5672/",
        broker_url="amqp://guest:guest@localhost:5672/",
    )
    redis = DummySettings(is_configured=True, url="redis://localhost:6379/0")
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

    async def _taskiq_initializer(*_: Any, **__: Any) -> tuple[Any, Any]:
        calls.append("taskiq_init")
        return taskiq_module, scheduler_module

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
        taskiq_initializer=_taskiq_initializer,
    )
    monkeypatch.setattr(
        "example_service.infra.tracing.opentelemetry.setup_tracing",
        lambda: calls.append("setup_tracing"),
    )
    monkeypatch.setattr(
        "example_service.app.lifespan.setup_tracing",
        lambda: calls.append("setup_tracing"),
    )
    # Patch task settings to enable tracking with redis backend (since redis is configured)
    task_settings = SimpleNamespace(
        tracking_enabled=True,
        result_backend="redis",
        is_redis_backend=True,
        is_postgres_backend=False,
    )
    monkeypatch.setattr(
        "example_service.core.settings.get_task_settings", lambda: task_settings,
    )
    monkeypatch.setattr(
        "example_service.app.lifespan.get_task_settings", lambda: task_settings,
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


def _patch_common_dependencies(
    monkeypatch: pytest.MonkeyPatch, **overrides: Any,
) -> None:
    """Patch dependencies that would otherwise perform I/O."""
    def _setattr(paths: tuple[str, ...], value: Any) -> None:
        for path in paths:
            monkeypatch.setattr(path, value)

    monkeypatch.setitem(
        sys.modules,
        "example_service.workers.tasks",
        ModuleType("example_service.workers.tasks"),
    )

    metric = type("Metric", (), {"set": lambda *_: None})

    metric_labels = SimpleNamespace(labels=lambda **_: metric())
    _setattr(
        (
            "example_service.infra.metrics.prometheus.application_info",
            "example_service.app.lifespan.application_info",
        ),
        metric_labels,
    )
    _setattr(
        (
            "example_service.infra.logging.config.setup_logging",
            "example_service.app.lifespan.setup_logging",
        ),
        lambda *_, **__: None,
    )
    _setattr(
        (
            "example_service.infra.tracing.opentelemetry.setup_tracing",
            "example_service.app.lifespan.setup_tracing",
        ),
        lambda: None,
    )
    async def _taskiq_stub(*_: Any, **__: Any) -> tuple[Any, Any]:
        return overrides.get("taskiq_result", (None, None))

    _setattr(
        (
            "example_service.app.lifespan._initialize_taskiq_and_scheduler",
        ),
        overrides.get("taskiq_initializer", _taskiq_stub),
    )
    monkeypatch.setattr(
        "example_service.infra.cache.redis.start_cache",
        overrides.get("start_cache", _async_stub(None)),
    )
    monkeypatch.setattr(
        "example_service.infra.cache.redis.stop_cache",
        overrides.get("stop_cache", _async_stub(None)),
    )
    monkeypatch.setattr(
        "example_service.infra.tasks.tracking.start_tracker",
        overrides.get("start_tracker", _async_stub(None)),
    )
    monkeypatch.setattr(
        "example_service.infra.tasks.tracking.stop_tracker",
        overrides.get("stop_tracker", _async_stub(None)),
    )
    monkeypatch.setattr(
        importlib.import_module("example_service.infra.messaging.broker"),
        "start_broker",
        overrides.get("start_broker", _async_stub(None)),
    )
    monkeypatch.setattr(
        importlib.import_module("example_service.infra.messaging.broker"),
        "stop_broker",
        overrides.get("stop_broker", _async_stub(None)),
    )
    start_discovery_impl = overrides.get("start_discovery", _async_stub(False))
    stop_discovery_impl = overrides.get("stop_discovery", _async_stub(None))
    _setattr(
        (
            "example_service.infra.discovery.start_discovery",
            "example_service.app.lifespan.start_discovery",
        ),
        start_discovery_impl,
    )
    _setattr(
        (
            "example_service.infra.discovery.stop_discovery",
            "example_service.app.lifespan.stop_discovery",
        ),
        stop_discovery_impl,
    )
    from example_service.features.health.aggregator import HealthAggregator

    aggregator = HealthAggregator()
    monkeypatch.setattr(
        "example_service.features.health.service.get_health_aggregator",
        lambda: aggregator,
    )
    monkeypatch.setattr(
        "example_service.features.health.aggregator.get_global_aggregator",
        lambda: aggregator,
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
    def _patch(name: str, value: DummySettings | None) -> None:
        provider = value or DummySettings()
        monkeypatch.setattr(
            f"example_service.core.settings.{name}",
            lambda provider=provider: provider,
            raising=False,
        )
        monkeypatch.setattr(
            f"example_service.app.lifespan.{name}",
            lambda provider=provider: provider,
            raising=False,
        )

    _patch("get_app_settings", app)
    _patch("get_logging_settings", log)
    _patch("get_consul_settings", consul)
    _patch("get_db_settings", db)
    _patch("get_redis_settings", redis)
    _patch("get_rabbit_settings", rabbit)
    _patch("get_otel_settings", otel)
    _patch("get_mock_settings", DummySettings(enabled=False, persona="admin"))
    _patch(
        "get_auth_settings",
        DummySettings(health_checks_enabled=False, service_url=None),
    )
    _patch("get_storage_settings", DummySettings())
    _patch(
        "get_task_settings",
        DummySettings(
            tracking_enabled=False,
            result_backend="redis",
            is_redis_backend=False,
            is_postgres_backend=False,
        ),
    )
    _patch(
        "get_websocket_settings",
        DummySettings(enabled=False, event_bridge_enabled=False),
    )
    _patch(
        "get_health_settings",
        DummySettings(service_availability_enabled=False),
    )
    _patch("get_ai_settings", DummySettings(enable_pipeline_api=False))
