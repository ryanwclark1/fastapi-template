"""Tests for TaskManagementService."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from example_service.features.tasks import service as task_service
from example_service.features.tasks.schemas import TaskName, TaskSearchParams


class TrackerStub:
    def __init__(self, *, connected: bool = True):
        self.is_connected = connected
        self.calls = {}

    async def get_task_history(self, **kwargs):
        self.calls["history"] = kwargs
        return [{"task_id": "1", "task_name": "demo", "status": "success"}]

    async def count_task_history(self, **kwargs):
        self.calls["count"] = kwargs
        return 1

    async def get_task_details(self, task_id: str):
        self.calls["details"] = task_id
        return {"task_id": task_id, "task_name": "demo", "status": "success"}

    async def get_running_tasks(self):
        return [
            {
                "task_id": "1",
                "task_name": "demo",
                "started_at": "2024-01-01T00:00:00Z",
                "running_for_ms": 10,
            }
        ]

    async def get_stats(self, hours: int = 24):
        return {
            "total_count": 2,
            "success_count": 1,
            "failure_count": 1,
            "running_count": 0,
            "cancelled_count": 0,
        }

    async def cancel_task(self, task_id: str):
        self.calls["cancel"] = task_id
        return True


@pytest.mark.asyncio
async def test_search_tasks_handles_tracker_results(monkeypatch: pytest.MonkeyPatch) -> None:
    tracker = TrackerStub()
    service = task_service.TaskManagementService(tracker=tracker)
    params = TaskSearchParams(limit=10, offset=0, task_name=None, status=None)

    results, total = await service.search_tasks(params)

    assert total == 1
    assert results[0].task_id == "1"
    assert "history" in tracker.calls
    assert "count" in tracker.calls


@pytest.mark.asyncio
async def test_search_tasks_returns_empty_when_tracker_unavailable() -> None:
    service = task_service.TaskManagementService(tracker=TrackerStub(connected=False))
    params = TaskSearchParams(limit=5, offset=0, task_name=None, status=None)

    results, total = await service.search_tasks(params)

    assert results == []
    assert total == 0


@pytest.mark.asyncio
async def test_get_task_details_none_when_missing() -> None:
    class EmptyTracker(TrackerStub):
        async def get_task_details(self, task_id: str):
            return None

    service = task_service.TaskManagementService(tracker=EmptyTracker())
    assert await service.get_task_details("x") is None


@pytest.mark.asyncio
async def test_get_running_tasks_maps_response() -> None:
    service = task_service.TaskManagementService(tracker=TrackerStub())
    tasks = await service.get_running_tasks()
    assert tasks
    assert tasks[0].task_name == "demo"


@pytest.mark.asyncio
async def test_get_stats_defaults_when_tracker_missing() -> None:
    service = task_service.TaskManagementService(tracker=TrackerStub(connected=False))
    stats = await service.get_stats()
    assert stats.total_count == 0


@pytest.mark.asyncio
async def test_cancel_task_success_and_message() -> None:
    tracker = TrackerStub()
    service = task_service.TaskManagementService(tracker=tracker)
    result = await service.cancel_task("123", reason="test")
    assert result.cancelled is True
    assert "cancel" in tracker.calls


@pytest.mark.asyncio
async def test_trigger_task_requires_broker(monkeypatch: pytest.MonkeyPatch) -> None:
    service = task_service.TaskManagementService(tracker=TrackerStub())
    monkeypatch.setattr(task_service, "broker", None)

    with pytest.raises(task_service.BrokerNotConfiguredError):
        await service.trigger_task(TaskName.warm_cache)
