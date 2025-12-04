"""Unit tests for PostgresTaskTracker."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from example_service.infra.results.models import TaskExecution
from example_service.infra.tasks.tracking.postgres_tracker import PostgresTaskTracker


class FakeScalarResult:
    """Mimic SQLAlchemy ScalarResult."""

    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def all(self):
        return list(self._values)


class FakeResult:
    """Mimic SQLAlchemy Result objects used in tracker."""

    def __init__(
        self,
        scalars_list: list[Any] | None = None,
        scalar_value: Any = None,
        scalar_one: Any = None,
        all_rows: list[Any] | None = None,
    ) -> None:
        self._scalars_list = scalars_list or []
        self._scalar_value = scalar_value
        self._scalar_one = scalar_one
        self._all_rows = all_rows

    def scalars(self):
        return FakeScalarResult(self._scalars_list)

    def scalar(self):
        return self._scalar_value

    def scalar_one(self):
        return self._scalar_one

    def scalar_one_or_none(self):
        return self._scalar_one

    def all(self):
        if self._all_rows is not None:
            return self._all_rows
        return self._scalars_list


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeSession:
    """Minimal async session used for tracker tests."""

    def __init__(self, results: list[FakeResult] | None = None) -> None:
        self.results = results or []
        self.executed: list[Any] = []
        self.added: list[Any] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def begin(self):
        return FakeTransaction()

    async def execute(self, stmt):
        self.executed.append(stmt)
        if self.results:
            return self.results.pop(0)
        return FakeResult()

    def add(self, obj: Any) -> None:
        self.added.append(obj)


@pytest.fixture
def tracker(monkeypatch):
    """Provide PostgresTaskTracker with patched engine/session maker."""
    engine = MagicMock()
    engine.dispose = AsyncMock()
    session = FakeSession([FakeResult()])

    def session_factory():
        return session

    monkeypatch.setattr(
        "example_service.infra.tasks.tracking.postgres_tracker.create_async_engine",
        lambda *args, **kwargs: engine,
    )
    monkeypatch.setattr(
        "example_service.infra.tasks.tracking.postgres_tracker.async_sessionmaker",
        lambda *args, **kwargs: session_factory,
    )

    tracker = PostgresTaskTracker(dsn="postgresql+asyncpg://user:pass@host/db")
    tracker._engine = engine
    tracker._session_factory = session_factory
    return tracker


@pytest.mark.asyncio
async def test_connect_and_disconnect(monkeypatch):
    """connect initializes engine and tests session; disconnect disposes."""
    engine = MagicMock()
    engine.dispose = AsyncMock()
    session = FakeSession([FakeResult()])

    def session_factory():
        return session

    monkeypatch.setattr(
        "example_service.infra.tasks.tracking.postgres_tracker.create_async_engine",
        lambda *args, **kwargs: engine,
    )
    monkeypatch.setattr(
        "example_service.infra.tasks.tracking.postgres_tracker.async_sessionmaker",
        lambda *args, **kwargs: session_factory,
    )

    tracker = PostgresTaskTracker(dsn="postgresql+asyncpg://user:pass@db/db")

    await tracker.connect()
    assert tracker.is_connected is True
    assert session.executed, "connect should run test query"

    await tracker.disconnect()
    engine.dispose.assert_awaited_once()
    assert tracker._session_factory is None


@pytest.mark.asyncio
async def test_on_task_start_creates_execution_record(tracker):
    """on_task_start should add TaskExecution with serialized args/kwargs."""
    session = FakeSession()
    tracker._session_factory = lambda: session

    await tracker.on_task_start(
        task_id="task-1",
        task_name="backup_database",
        worker_id="worker-1",
        queue_name="default",
        task_args=("a", 1),
        task_kwargs={"k": "v"},
        labels={"env": "test"},
    )

    assert len(session.added) == 1
    execution: TaskExecution = session.added[0]
    assert execution.task_id == "task-1"
    assert execution.task_name == "backup_database"
    assert execution.status == "running"
    assert execution.worker_id == "worker-1"
    assert execution.task_args == ["a", 1]
    assert execution.task_kwargs == {"k": "v"}
    assert execution.labels == {"env": "test"}


@pytest.mark.asyncio
async def test_on_task_finish_updates_record(tracker):
    """on_task_finish should issue update statement with result and error info."""
    session = FakeSession()
    tracker._session_factory = lambda: session

    await tracker.on_task_finish(
        task_id="task-1",
        status="failure",
        return_value={"ok": False},
        error=RuntimeError("boom"),
        duration_ms=1500,
    )

    assert session.executed, "update statement should be executed"
    stmt = session.executed[0]
    assert "task_executions" in str(stmt)
    assert "duration_ms" in str(stmt)


@pytest.mark.asyncio
async def test_get_running_tasks_queries_running(tracker):
    """get_running_tasks returns running tasks with runtime calculation."""
    now = datetime.now(UTC)
    executions = [
        TaskExecution(
            task_id="run-1",
            task_name="cleanup",
            status="running",
            worker_id="worker-1",
            created_at=now - timedelta(minutes=1),
            started_at=now - timedelta(seconds=10),
        )
    ]
    session = FakeSession(results=[FakeResult(scalars_list=executions)])
    tracker._session_factory = lambda: session

    tasks = await tracker.get_running_tasks()

    assert len(tasks) == 1
    assert tasks[0]["task_id"] == "run-1"
    assert tasks[0]["running_for_ms"] >= 0


@pytest.mark.asyncio
async def test_get_task_history_returns_list(tracker):
    """get_task_history should map TaskExecution rows to dicts."""
    now = datetime.now(UTC)
    executions = [
        TaskExecution(
            task_id="task-1",
            task_name="cleanup",
            status="success",
            worker_id="worker-1",
            created_at=now,
            started_at=now,
            finished_at=now,
            duration_ms=100,
        ),
        TaskExecution(
            task_id="task-2",
            task_name="cleanup",
            status="failure",
            worker_id="worker-2",
            created_at=now,
            started_at=now,
            finished_at=now,
            duration_ms=200,
        ),
    ]
    session = FakeSession(results=[FakeResult(scalars_list=executions)])
    tracker._session_factory = lambda: session

    history = await tracker.get_task_history(limit=2, offset=0, status="success")

    assert len(history) == 2
    assert {item["task_id"] for item in history} == {"task-1", "task-2"}
    assert history[0]["task_name"] == "cleanup"


@pytest.mark.asyncio
async def test_count_task_history(tracker):
    """count_task_history returns scalar count from query."""
    session = FakeSession(results=[FakeResult(scalar_one=5)])
    tracker._session_factory = lambda: session

    count = await tracker.count_task_history(status="running")

    assert count == 5


@pytest.mark.asyncio
async def test_get_task_details(tracker):
    """get_task_details returns mapped task details."""
    now = datetime.now(UTC)
    execution = TaskExecution(
        task_id="task-1",
        task_name="cleanup",
        status="failure",
        worker_id="worker-1",
        queue_name="default",
        created_at=now,
        started_at=now,
        finished_at=now,
        duration_ms=200,
        return_value={"ok": False},
        error_type="ValueError",
        error_message="boom",
        error_traceback="trace",
        task_args=["a"],
        task_kwargs={"k": "v"},
        labels={"env": "test"},
        retry_count=1,
        progress={"pct": 10},
    )
    session = FakeSession(results=[FakeResult(scalar_one=execution)])
    tracker._session_factory = lambda: session

    details = await tracker.get_task_details("task-1")

    assert details is not None
    assert details["task_id"] == "task-1"
    assert details["error_traceback"] == "trace"
    assert details["retry_count"] == 1
    assert details["progress"] == {"pct": 10}


@pytest.mark.asyncio
async def test_get_stats_aggregates_queries(tracker):
    """get_stats should aggregate counts and averages from queries."""
    session_results = [
        FakeResult(scalar_value=1),  # running
        FakeResult(scalar_value=5),  # success
        FakeResult(scalar_value=2),  # failure
        FakeResult(scalar_value=1),  # cancelled
        FakeResult(scalar_value=9),  # total
        FakeResult(all_rows=[("cleanup", 7), ("export", 2)]),  # by task name
        FakeResult(scalar_value=123.4),  # avg duration
    ]
    session = FakeSession(results=session_results)
    tracker._session_factory = lambda: session

    stats = await tracker.get_stats(hours=12)

    assert stats["running_count"] == 1
    assert stats["success_count"] == 5
    assert stats["failure_count"] == 2
    assert stats["cancelled_count"] == 1
    assert stats["total_count"] == 9
    assert stats["by_task_name"]["cleanup"] == 7
    assert stats["avg_duration_ms"] == 123.4


@pytest.mark.asyncio
async def test_cancel_task_behaviour(tracker):
    """cancel_task should update only when task is cancellable."""
    # Case 1: task not found
    session = FakeSession(results=[FakeResult(scalar_one=None)])
    tracker._session_factory = lambda: session
    assert await tracker.cancel_task("missing") is False

    # Case 2: task finished
    session = FakeSession(results=[FakeResult(scalar_one="success")])
    tracker._session_factory = lambda: session
    assert await tracker.cancel_task("done") is False

    # Case 3: running task
    session = FakeSession(results=[FakeResult(scalar_one="running"), FakeResult()])
    tracker._session_factory = lambda: session
    assert await tracker.cancel_task("running-task") is True
    assert session.executed, "update should be executed for running task"
