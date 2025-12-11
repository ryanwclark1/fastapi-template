"""Unit tests for RedisTaskTracker."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from example_service.infra.tasks.tracking.redis_tracker import RedisTaskTracker


class FakePipeline:
    """Minimal pipeline that applies operations immediately."""

    def __init__(self, client: FakeRedis) -> None:
        self.client = client

    def hset(self, key: str, mapping: dict[str, Any]) -> FakePipeline:
        self.client._hset_sync(key, mapping)
        return self

    def expire(self, key: str, ttl: int) -> FakePipeline:
        self.client._expire_sync(key, ttl)
        return self

    def set(self, key: str, value: str, ex: int | None = None) -> FakePipeline:
        self.client._set_sync(key, value, ex)
        return self

    def zadd(self, key: str, mapping: dict[str, float]) -> FakePipeline:
        self.client._zadd_sync(key, mapping)
        return self

    def delete(self, key: str) -> FakePipeline:
        self.client._delete_sync(key)
        return self

    def zrem(self, key: str, member: str) -> FakePipeline:
        self.client._zrem_sync(key, member)
        return self

    async def execute(self):
        return []


class FakeRedis:
    """Very small in-memory Redis replacement for tracker tests."""

    def __init__(self, connection_pool: Any | None = None) -> None:
        self.connection_pool = connection_pool
        self.hashes: dict[str, dict[str, str]] = {}
        self.sorted_sets: dict[str, dict[str, float]] = {}
        self.strings: dict[str, str] = {}
        self.expirations: dict[str, int] = {}
        self.closed = False

    # Sync helpers used by pipeline
    def _hset_sync(self, key: str, mapping: dict[str, Any]) -> None:
        existing = self.hashes.setdefault(key, {})
        for k, v in mapping.items():
            existing[k] = str(v)

    def _expire_sync(self, key: str, ttl: int) -> None:
        self.expirations[key] = ttl

    def _set_sync(self, key: str, value: str, ex: int | None = None) -> None:
        self.strings[key] = value
        if ex:
            self.expirations[key] = ex

    def _zadd_sync(self, key: str, mapping: dict[str, float]) -> None:
        zset = self.sorted_sets.setdefault(key, {})
        for member, score in mapping.items():
            zset[member] = score

    def _delete_sync(self, key: str) -> None:
        self.strings.pop(key, None)
        self.hashes.pop(key, None)

    def _zrem_sync(self, key: str, member: str) -> None:
        if key in self.sorted_sets:
            self.sorted_sets[key].pop(member, None)

    # Async API used by tracker
    async def ping(self):
        return True

    async def close(self):
        self.closed = True

    async def hset(self, key: str, mapping: dict[str, Any]):
        self._hset_sync(key, mapping)

    async def expire(self, key: str, ttl: int):
        self._expire_sync(key, ttl)

    async def set(self, key: str, value: str, ex: int | None = None):
        self._set_sync(key, value, ex)

    async def zadd(self, key: str, mapping: dict[str, float]):
        self._zadd_sync(key, mapping)

    async def zrevrange(self, key: str, start: int, stop: int):
        items = self.sorted_sets.get(key, {})
        sorted_members = [k for k, _ in sorted(items.items(), key=lambda item: item[1], reverse=True)]
        slice_end = None if stop == -1 else stop + 1
        return sorted_members[start:slice_end]

    async def zcard(self, key: str):
        return len(self.sorted_sets.get(key, {}))

    async def zrem(self, key: str, member: str):
        self._zrem_sync(key, member)

    async def delete(self, key: str):
        self._delete_sync(key)

    async def hgetall(self, key: str):
        return dict(self.hashes.get(key, {}))

    async def hget(self, key: str, field: str):
        return self.hashes.get(key, {}).get(field)

    async def scan_iter(self, match: str):
        prefix = match.replace("*", "")
        for key in list(self.sorted_sets.keys()):
            if key.startswith(prefix):
                yield key

    def pipeline(self):
        return FakePipeline(self)

    async def disconnect(self):
        self.closed = True


@pytest.fixture
def tracker(monkeypatch):
    """Provide RedisTaskTracker wired to FakeRedis client."""

    class FakePool:
        async def disconnect(self):
            return None

    fake_pool = FakePool()
    # Avoid hitting real Redis during connect
    monkeypatch.setattr(
        "example_service.infra.tasks.tracking.redis_tracker.ConnectionPool.from_url",
        lambda *args, **kwargs: fake_pool,
    )
    monkeypatch.setattr(
        "example_service.infra.tasks.tracking.redis_tracker.Redis",
        FakeRedis,
    )
    return RedisTaskTracker(redis_url="redis://test", key_prefix="task", ttl_seconds=3600)


@pytest.mark.asyncio
async def test_connect_and_disconnect(tracker):
    """connect() initializes client and disconnect() cleans up."""
    await tracker.connect()
    assert tracker.is_connected is True
    assert tracker._client is not None
    assert tracker._pool is not None

    await tracker.disconnect()
    assert tracker.is_connected is False
    assert tracker._client is None
    assert tracker._pool is None


@pytest.mark.asyncio
async def test_on_task_start_records_execution(tracker):
    """on_task_start should create hash, running marker, and indices."""
    tracker._client = FakeRedis()
    task_id = "task-123"

    await tracker.on_task_start(
        task_id=task_id,
        task_name="backup_database",
        worker_id="worker-1",
        queue_name="default",
        task_args=("a", 1),
        task_kwargs={"k": "v"},
        labels={"env": "test"},
    )

    exec_data = tracker.client.hashes[tracker._exec_key(task_id)]
    assert exec_data["task_id"] == task_id
    assert exec_data["task_name"] == "backup_database"
    assert exec_data["status"] == "running"
    assert exec_data["worker_id"] == "worker-1"
    assert tracker.client.strings[tracker._running_key(task_id)]

    assert task_id in tracker.client.sorted_sets[tracker._index_all_key()]
    assert task_id in tracker.client.sorted_sets[tracker._index_name_key("backup_database")]
    assert task_id in tracker.client.sorted_sets[tracker._index_status_key("running")]


@pytest.mark.asyncio
async def test_on_task_finish_updates_status_and_indices(tracker):
    """on_task_finish should update hash fields and move status indices."""
    tracker._client = FakeRedis()
    task_id = "task-1"
    await tracker.on_task_start(task_id, "cleanup")

    await tracker.on_task_finish(
        task_id=task_id,
        status="success",
        return_value={"ok": True},
        error=None,
        duration_ms=1500,
    )

    exec_data = tracker.client.hashes[tracker._exec_key(task_id)]
    assert exec_data["status"] == "success"
    assert exec_data["duration_ms"] == "1500"
    assert exec_data["return_value"] == '{"ok": true}'
    assert tracker._running_key(task_id) not in tracker.client.strings
    assert task_id not in tracker.client.sorted_sets[tracker._index_status_key("running")]
    assert task_id in tracker.client.sorted_sets[tracker._index_status_key("success")]


@pytest.mark.asyncio
async def test_get_running_tasks_reports_elapsed(tracker):
    """get_running_tasks returns running task with calculated runtime."""
    tracker._client = FakeRedis()
    await tracker.on_task_start("task-run", "cleanup")

    tasks = await tracker.get_running_tasks()

    assert len(tasks) == 1
    assert tasks[0]["task_id"] == "task-run"
    assert tasks[0]["running_for_ms"] >= 0


@pytest.mark.asyncio
async def test_get_task_history_filters_and_paginates(tracker):
    """get_task_history should respect status filter and pagination."""
    tracker._client = FakeRedis()
    await tracker.on_task_start("task-a", "cleanup")
    await asyncio.sleep(0.001)
    await tracker.on_task_finish("task-a", "success", None, None, 100)

    await tracker.on_task_start("task-b", "cleanup")
    await asyncio.sleep(0.001)
    await tracker.on_task_finish("task-b", "success", None, None, 200)

    await tracker.on_task_start("task-c", "cleanup")
    await asyncio.sleep(0.001)
    await tracker.on_task_finish("task-c", "failure", None, RuntimeError("x"), 50)

    results = await tracker.get_task_history(limit=1, offset=1, status="success")

    assert len(results) == 1
    assert results[0]["status"] == "success"
    assert results[0]["task_id"] in {"task-a", "task-b"}


@pytest.mark.asyncio
async def test_get_task_details_parses_fields(tracker):
    """get_task_details should parse JSON fields and numeric values."""
    tracker._client = FakeRedis()
    task_id = "task-detail"
    await tracker.on_task_start(task_id, "backup_database", task_args=("x",), task_kwargs={"a": 1})
    await tracker.on_task_finish(
        task_id,
        status="failure",
        return_value={"data": 1},
        error=ValueError("boom"),
        duration_ms=250,
    )

    details = await tracker.get_task_details(task_id)

    assert details is not None
    assert details["duration_ms"] == 250
    assert details["return_value"] == {"data": 1}
    assert details["error_type"] == "ValueError"
    assert details["task_args"] == ["x"]
    assert details["task_kwargs"] == {"a": 1}


@pytest.mark.asyncio
async def test_get_stats_aggregates_counts(tracker):
    """get_stats should aggregate totals, status counts, and averages."""
    tracker._client = FakeRedis()
    await tracker.on_task_start("task-success-1", "cleanup")
    await tracker.on_task_finish("task-success-1", "success", None, None, 100)
    await tracker.on_task_start("task-success-2", "cleanup")
    await tracker.on_task_finish("task-success-2", "success", None, None, 300)
    await tracker.on_task_start("task-failure", "cleanup")
    await tracker.on_task_finish("task-failure", "failure", None, RuntimeError("x"), 200)
    await tracker.on_task_start("task-running", "cleanup")

    stats = await tracker.get_stats()

    assert stats["total_count"] == 4
    assert stats["success_count"] == 2
    assert stats["failure_count"] == 1
    assert stats["running_count"] == 1
    assert stats["by_task_name"]["cleanup"] == 4
    assert 190 <= stats["avg_duration_ms"] <= 210


@pytest.mark.asyncio
async def test_cancel_task_handles_status(tracker):
    """cancel_task should cancel running/pending but not completed tasks."""
    tracker._client = FakeRedis()
    await tracker.on_task_start("task-running", "cleanup")
    await tracker.on_task_start("task-finished", "cleanup")
    await tracker.on_task_finish("task-finished", "success", None, None, 10)

    cancelled_running = await tracker.cancel_task("task-running")
    cancelled_finished = await tracker.cancel_task("task-finished")

    assert cancelled_running is True
    assert tracker.client.hashes[tracker._exec_key("task-running")]["status"] == "cancelled"
    assert cancelled_finished is False


@pytest.mark.asyncio
async def test_returns_empty_when_not_connected():
    """Tracker should return empty results when not connected."""
    tracker = RedisTaskTracker(redis_url="redis://test")
    assert await tracker.get_running_tasks() == []
    assert await tracker.get_task_history() == []
    assert await tracker.get_stats() == {
        "total_count": 0,
        "success_count": 0,
        "failure_count": 0,
        "running_count": 0,
        "cancelled_count": 0,
        "by_task_name": {},
        "avg_duration_ms": None,
    }
