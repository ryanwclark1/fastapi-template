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


# ──────────────────────────────────────────────────────────────
# DLQ Tests
# ──────────────────────────────────────────────────────────────


class DLQMiddlewareStub:
    """Stub for DeadLetterQueueMiddleware."""

    def __init__(self, entries: list | None = None):
        self.entries = entries or []
        self.calls: dict = {}

    async def get_dlq_entries(self, limit: int = 50, offset: int = 0, status: str | None = None):
        self.calls["get_entries"] = {"limit": limit, "offset": offset, "status": status}
        return self.entries

    async def get_dlq_count(self):
        return len(self.entries)

    async def get_dlq_entry(self, task_id: str):
        self.calls["get_entry"] = task_id
        for entry in self.entries:
            if entry.get("task_id") == task_id:
                return entry
        return None

    async def update_dlq_status(self, task_id: str, status: str):
        self.calls["update_status"] = {"task_id": task_id, "status": status}
        return True


@pytest.mark.asyncio
async def test_get_dlq_entries_returns_empty_when_no_middleware(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test DLQ entries returns empty when middleware not available."""
    monkeypatch.setattr(task_service, "get_dlq_middleware", lambda: None)
    service = task_service.TaskManagementService(tracker=TrackerStub())

    result = await service.get_dlq_entries()

    assert result.items == []
    assert result.total == 0


@pytest.mark.asyncio
async def test_get_dlq_entries_returns_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test DLQ entries are returned properly."""
    dlq_stub = DLQMiddlewareStub(entries=[
        {
            "task_id": "dlq-1",
            "task_name": "failed_task",
            "error_message": "Test error",
            "error_type": "ValueError",
            "retry_count": "3",
            "failed_at": "2024-01-01T00:00:00Z",
            "status": "pending",
        }
    ])
    monkeypatch.setattr(task_service, "get_dlq_middleware", lambda: dlq_stub)
    service = task_service.TaskManagementService(tracker=TrackerStub())

    result = await service.get_dlq_entries()

    assert result.total == 1
    assert result.items[0].task_id == "dlq-1"
    assert result.items[0].task_name == "failed_task"


@pytest.mark.asyncio
async def test_get_dlq_entry_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test DLQ entry returns None when not found."""
    dlq_stub = DLQMiddlewareStub(entries=[])
    monkeypatch.setattr(task_service, "get_dlq_middleware", lambda: dlq_stub)
    service = task_service.TaskManagementService(tracker=TrackerStub())

    result = await service.get_dlq_entry("nonexistent")

    assert result is None


@pytest.mark.asyncio
async def test_discard_dlq_task_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test discarding a DLQ task."""
    dlq_stub = DLQMiddlewareStub(entries=[
        {"task_id": "dlq-1", "task_name": "test", "status": "pending"}
    ])
    monkeypatch.setattr(task_service, "get_dlq_middleware", lambda: dlq_stub)
    service = task_service.TaskManagementService(tracker=TrackerStub())

    result = await service.discard_dlq_task("dlq-1", reason="Test discard")

    assert result.discarded is True
    assert dlq_stub.calls.get("update_status") == {"task_id": "dlq-1", "status": "discarded"}


# ──────────────────────────────────────────────────────────────
# Bulk Operations Tests
# ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_cancel_tasks_partial_success() -> None:
    """Test bulk cancel with some successes and failures."""
    tracker = TrackerStub()
    service = task_service.TaskManagementService(tracker=tracker)

    result = await service.bulk_cancel_tasks(["task-1", "task-2"], reason="bulk test")

    assert result.total_requested == 2
    # Both should succeed with our stub
    assert result.successful == 2
    assert result.failed == 0
    assert len(result.results) == 2


@pytest.mark.asyncio
async def test_bulk_cancel_empty_list() -> None:
    """Test bulk cancel with empty list."""
    tracker = TrackerStub()
    service = task_service.TaskManagementService(tracker=tracker)

    result = await service.bulk_cancel_tasks([])

    assert result.total_requested == 0
    assert result.successful == 0
    assert result.failed == 0


# ──────────────────────────────────────────────────────────────
# Progress Tracking Tests
# ──────────────────────────────────────────────────────────────


class ProgressMiddlewareStub:
    """Stub for ProgressTrackingMiddleware."""

    def __init__(self, progress: dict | None = None):
        self.progress_data = progress

    async def get_progress(self, task_id: str):
        return self.progress_data


@pytest.mark.asyncio
async def test_get_task_progress_returns_none_when_no_middleware(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test progress returns None when middleware not available."""
    monkeypatch.setattr(task_service, "get_progress_middleware", lambda: None)
    service = task_service.TaskManagementService(tracker=TrackerStub())

    result = await service.get_task_progress("task-1")

    assert result is None


@pytest.mark.asyncio
async def test_get_task_progress_returns_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test progress is returned properly."""
    progress_stub = ProgressMiddlewareStub(progress={
        "task_id": "task-1",
        "percent": 50.0,
        "message": "Processing...",
        "current": 50,
        "total": 100,
        "updated_at": "2024-01-01T00:00:00Z",
    })
    monkeypatch.setattr(task_service, "get_progress_middleware", lambda: progress_stub)
    service = task_service.TaskManagementService(tracker=TrackerStub())

    result = await service.get_task_progress("task-1")

    assert result is not None
    assert result.percent == 50.0
    assert result.message == "Processing..."
    assert result.current == 50
    assert result.total == 100


@pytest.mark.asyncio
async def test_get_task_progress_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test progress returns None when task has no progress."""
    progress_stub = ProgressMiddlewareStub(progress=None)
    monkeypatch.setattr(task_service, "get_progress_middleware", lambda: progress_stub)
    service = task_service.TaskManagementService(tracker=TrackerStub())

    result = await service.get_task_progress("task-1")

    assert result is None
