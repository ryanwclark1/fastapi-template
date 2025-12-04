"""Unit tests for task tracker factory utilities."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from example_service.infra.tasks.tracking import factory


@pytest.fixture(autouse=True)
def reset_tracker():
    """Ensure global tracker is reset between tests."""
    factory._tracker = None
    yield
    factory._tracker = None


@pytest.fixture
def redis_settings():
    return type("RedisSettings", (), {"url": "redis://localhost:6379/0"})


@pytest.fixture
def db_settings():
    return type("DBSettings", (), {"url": "postgresql+asyncpg://user:pass@localhost/db"})


def test_create_tracker_returns_redis(monkeypatch, redis_settings):
    """create_tracker should build Redis tracker when backend is redis."""
    settings = type("Settings", (), {"is_postgres_backend": False, "tracking_enabled": True,
                                     "redis_key_prefix": "task", "redis_result_ttl_seconds": 100,
                                     "redis_max_connections": 5})
    monkeypatch.setattr("example_service.infra.tasks.tracking.factory.get_task_settings", lambda: settings)
    monkeypatch.setattr("example_service.infra.tasks.tracking.factory.get_redis_settings", lambda: redis_settings)
    created_kwargs = {}

    class DummyRedisTracker:
        def __init__(self, **kwargs):
            created_kwargs.update(kwargs)

    monkeypatch.setattr(
        "example_service.infra.tasks.tracking.redis_tracker.RedisTaskTracker",
        DummyRedisTracker,
    )

    tracker_obj = factory.create_tracker()

    assert isinstance(tracker_obj, DummyRedisTracker)
    assert created_kwargs["redis_url"] == redis_settings.url
    assert created_kwargs["key_prefix"] == "task"


def test_create_tracker_returns_postgres(monkeypatch, db_settings):
    """create_tracker should build Postgres tracker when backend is postgres."""
    settings = type("Settings", (), {"is_postgres_backend": True, "tracking_enabled": True})
    monkeypatch.setattr("example_service.infra.tasks.tracking.factory.get_task_settings", lambda: settings)
    monkeypatch.setattr("example_service.infra.tasks.tracking.factory.get_db_settings", lambda: db_settings)

    class DummyPostgresTracker:
        def __init__(self, dsn: str, pool_size: int, max_overflow: int):
            self.dsn = dsn
            self.pool_size = pool_size
            self.max_overflow = max_overflow

    monkeypatch.setattr(
        "example_service.infra.tasks.tracking.postgres_tracker.PostgresTaskTracker",
        DummyPostgresTracker,
    )

    tracker_obj = factory.create_tracker()

    assert isinstance(tracker_obj, DummyPostgresTracker)
    assert tracker_obj.dsn == db_settings.url
    assert tracker_obj.pool_size == 5
    assert tracker_obj.max_overflow == 10


def test_get_tracker_returns_global(monkeypatch):
    """get_tracker should return previously set tracker instance."""
    dummy = object()
    factory._tracker = dummy

    assert factory.get_tracker() is dummy


@pytest.mark.asyncio
async def test_start_tracker_skips_when_disabled(monkeypatch):
    """start_tracker should no-op when tracking disabled."""
    settings = type("Settings", (), {"tracking_enabled": False, "result_backend": "redis"})
    monkeypatch.setattr("example_service.infra.tasks.tracking.factory.get_task_settings", lambda: settings)
    created = MagicMock()
    monkeypatch.setattr("example_service.infra.tasks.tracking.factory.create_tracker", created)

    await factory.start_tracker()

    created.assert_not_called()
    assert factory.get_tracker() is None


@pytest.mark.asyncio
async def test_start_tracker_initializes_global(monkeypatch):
    """start_tracker should create and connect tracker when enabled."""
    settings = type("Settings", (), {"tracking_enabled": True, "result_backend": "redis"})
    monkeypatch.setattr("example_service.infra.tasks.tracking.factory.get_task_settings", lambda: settings)
    tracker_mock = MagicMock()
    tracker_mock.connect = AsyncMock()
    monkeypatch.setattr("example_service.infra.tasks.tracking.factory.create_tracker", lambda: tracker_mock)

    await factory.start_tracker()

    tracker_mock.connect.assert_awaited_once()
    assert factory.get_tracker() is tracker_mock


@pytest.mark.asyncio
async def test_stop_tracker_disconnects(monkeypatch):
    """stop_tracker should disconnect and clear global tracker."""
    tracker_mock = MagicMock()
    tracker_mock.disconnect = AsyncMock()
    factory._tracker = tracker_mock

    await factory.stop_tracker()

    tracker_mock.disconnect.assert_awaited_once()
    assert factory.get_tracker() is None
