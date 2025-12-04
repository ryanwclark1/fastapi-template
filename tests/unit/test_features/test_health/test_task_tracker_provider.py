"""Unit tests for TaskTrackerHealthProvider."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from example_service.core.schemas.common import HealthStatus
from example_service.features.health.providers import ProviderConfig
from example_service.features.health.task_tracker_provider import TaskTrackerHealthProvider


class FakeTracker:
    """Simple fake tracker with configurable responses."""

    def __init__(
        self,
        *,
        is_connected: bool = True,
        stats: dict | None = None,
        running_tasks: list[dict] | None = None,
        delay: float = 0.0,
        error: Exception | None = None,
    ) -> None:
        self.is_connected = is_connected
        self._stats = stats or {
            "total_count": 2,
            "success_count": 1,
            "failure_count": 1,
            "running_count": 0,
            "cancelled_count": 0,
        }
        self._running_tasks = running_tasks or []
        self._delay = delay
        self._error = error

    async def get_stats(self, hours: int = 24):
        if self._error:
            raise self._error
        if self._delay:
            await asyncio.sleep(self._delay)
        return self._stats

    async def get_running_tasks(self):
        if self._error:
            raise self._error
        if self._delay:
            await asyncio.sleep(self._delay)
        return self._running_tasks


@pytest.fixture
def settings(monkeypatch):
    """Patch task settings for tests."""

    class Settings:
        def __init__(self) -> None:
            self.tracking_enabled = True
            self.result_backend = "redis"

    settings_obj = Settings()
    monkeypatch.setattr(
        "example_service.core.settings.get_task_settings",
        lambda: settings_obj,
    )
    return settings_obj


def _patch_get_tracker(monkeypatch, tracker):
    monkeypatch.setattr(
        "example_service.infra.tasks.tracking.get_tracker",
        lambda: tracker,
        raising=False,
    )


@pytest.mark.asyncio
async def test_tracker_connected_fast_response_is_healthy(monkeypatch, settings):
    """Connected tracker with quick response should be healthy."""
    tracker = FakeTracker()
    _patch_get_tracker(monkeypatch, tracker)
    provider = TaskTrackerHealthProvider()

    result = await provider.check_health()

    assert result.status == HealthStatus.HEALTHY
    assert "operational" in result.message
    assert result.metadata["backend"] == "redis"
    assert result.metadata["is_connected"] is True


@pytest.mark.asyncio
async def test_high_latency_results_in_degraded(monkeypatch, settings):
    """High latency beyond threshold returns DEGRADED."""
    tracker = FakeTracker(delay=0.05)
    _patch_get_tracker(monkeypatch, tracker)
    provider = TaskTrackerHealthProvider(
        config=ProviderConfig(timeout=1.0, degraded_threshold_ms=1.0),
    )

    result = await provider.check_health()

    assert result.status == HealthStatus.DEGRADED
    assert "High latency" in result.message
    assert result.metadata["running_tasks"] == 0


@pytest.mark.asyncio
async def test_tracker_not_initialized(monkeypatch, settings):
    """Missing tracker yields UNHEALTHY with message."""
    _patch_get_tracker(monkeypatch, None)
    provider = TaskTrackerHealthProvider()

    result = await provider.check_health()

    assert result.status == HealthStatus.UNHEALTHY
    assert "not initialized" in result.message
    assert result.metadata["is_connected"] is False


@pytest.mark.asyncio
async def test_tracker_disconnected(monkeypatch, settings):
    """Disconnected tracker yields UNHEALTHY."""
    tracker = FakeTracker(is_connected=False)
    _patch_get_tracker(monkeypatch, tracker)
    provider = TaskTrackerHealthProvider()

    result = await provider.check_health()

    assert result.status == HealthStatus.UNHEALTHY
    assert "not connected" in result.message
    assert result.metadata["is_connected"] is False


@pytest.mark.asyncio
async def test_tracking_disabled_in_settings(monkeypatch, settings):
    """Disabled tracking returns DEGRADED with message."""
    settings.tracking_enabled = False
    tracker = FakeTracker()
    _patch_get_tracker(monkeypatch, tracker)
    provider = TaskTrackerHealthProvider()

    result = await provider.check_health()

    assert result.status == HealthStatus.DEGRADED
    assert "disabled" in result.message
    assert result.metadata["tracking_enabled"] is False


@pytest.mark.asyncio
async def test_query_timeout_returns_unhealthy(monkeypatch, settings):
    """Timeout from tracker should surface as UNHEALTHY with timeout metadata."""
    tracker = FakeTracker()
    tracker.get_stats = AsyncMock(side_effect=TimeoutError("boom"))
    tracker.get_running_tasks = AsyncMock(return_value=[])
    _patch_get_tracker(monkeypatch, tracker)
    provider = TaskTrackerHealthProvider(config=ProviderConfig(timeout=0.1))

    result = await provider.check_health()

    assert result.status == HealthStatus.UNHEALTHY
    assert "Timeout" in result.message
    assert result.metadata["error"] == "timeout"


@pytest.mark.asyncio
async def test_query_exception_returns_unhealthy(monkeypatch, settings):
    """Unexpected tracker error returns UNHEALTHY with error details."""
    tracker = FakeTracker(error=ValueError("db down"))
    _patch_get_tracker(monkeypatch, tracker)
    provider = TaskTrackerHealthProvider()

    result = await provider.check_health()

    assert result.status == HealthStatus.UNHEALTHY
    assert "Query failed" in result.message
    assert result.metadata["error"] == "db down"
    assert result.metadata["error_type"] == "ValueError"


@pytest.mark.asyncio
async def test_metadata_includes_stats(monkeypatch, settings):
    """Health metadata should include stats and running task count."""
    tracker = FakeTracker(
        stats={
            "total_count": 10,
            "success_count": 8,
            "failure_count": 2,
            "running_count": 1,
        },
        running_tasks=[{"task_id": "a"}],
    )
    _patch_get_tracker(monkeypatch, tracker)
    provider = TaskTrackerHealthProvider()

    result = await provider.check_health()

    assert result.metadata["running_tasks"] == 1
    assert result.metadata["total_24h"] == 10
    assert result.metadata["success_24h"] == 8
    assert result.metadata["failure_24h"] == 2
