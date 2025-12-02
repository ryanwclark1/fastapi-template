"""Integration-style tests for tasks router."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from example_service.features.tasks.schemas import CancelTaskResponse, TaskName

tasks_router_module = importlib.import_module("example_service.features.tasks.router")


class MockTaskService:
    """Mock service used to drive router responses in integration tests."""

    def __init__(self) -> None:
        self.search_tasks = AsyncMock()
        self.get_running_tasks = AsyncMock()
        self.get_stats = AsyncMock()
        self.get_task_details = AsyncMock()
        self.trigger_task = AsyncMock()
        self.cancel_task = AsyncMock()
        self.get_scheduled_jobs = lambda: []  # Synchronous in service implementation
        self.get_scheduled_job = lambda _job_id: None
        self.pause_job = lambda _job_id: True
        self.resume_job = lambda _job_id: True


@pytest.fixture
async def tasks_client() -> AsyncClient:
    """Provide AsyncClient bound to FastAPI app with tasks router mounted at /api/v1."""
    app = FastAPI()
    service = MockTaskService()

    def get_service_override():
        return service

    app.dependency_overrides[tasks_router_module.get_service] = get_service_override
    app.include_router(tasks_router_module.router, prefix="/api/v1")

    # Ensure /tasks/{task_id} does not shadow scheduled job paths
    for idx, route in enumerate(list(app.router.routes)):
        if isinstance(route, APIRoute) and route.path.endswith("/tasks/{task_id}"):
            detail_route = app.router.routes.pop(idx)
            app.router.routes.append(detail_route)
            break

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.task_service = service  # type: ignore[attr-defined]
        yield client


@pytest.mark.asyncio
async def test_search_tasks_integration(tasks_client: AsyncClient):
    """Search endpoint returns paginated results under API prefix."""
    service: MockTaskService = tasks_client.task_service  # type: ignore[attr-defined]
    service.search_tasks.return_value = (
        [
            {
                "task_id": "task-1",
                "task_name": "backup_database",
                "status": "success",
                "worker_id": "worker-1",
                "started_at": "2024-01-01T00:00:00Z",
                "finished_at": "2024-01-01T00:02:00Z",
                "duration_ms": 120000,
            }
        ],
        1,
    )

    resp = await tasks_client.get("/api/v1/tasks", params={"limit": 10})

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["task_name"] == "backup_database"
    service.search_tasks.assert_awaited_once()


@pytest.mark.asyncio
async def test_trigger_and_details_flow(tasks_client: AsyncClient):
    """Trigger endpoint returns queued status and detail fetch handles 404."""
    service: MockTaskService = tasks_client.task_service  # type: ignore[attr-defined]
    service.trigger_task.return_value = {
        "task_id": "abc123",
        "task_name": TaskName.run_all_cleanup.value,
        "status": "queued",
        "message": "queued",
    }
    service.get_task_details.return_value = None

    trigger_resp = await tasks_client.post(
        "/api/v1/tasks/trigger",
        json={"task": TaskName.run_all_cleanup.value, "params": {}},
    )
    assert trigger_resp.status_code == 200
    assert trigger_resp.json()["task_id"] == "abc123"

    detail_resp = await tasks_client.get("/api/v1/tasks/abc123")
    assert detail_resp.status_code == 404
    service.trigger_task.assert_awaited_once()
    service.get_task_details.assert_awaited_once_with("abc123")


@pytest.mark.asyncio
async def test_cancel_and_stats(tasks_client: AsyncClient):
    """Cancel endpoint returns structured response; stats forwards hours param."""
    service: MockTaskService = tasks_client.task_service  # type: ignore[attr-defined]
    service.cancel_task.return_value = CancelTaskResponse(
        task_id="job-9",
        cancelled=True,
        message="cancelled",
        previous_status="running",
    )
    service.get_stats.return_value = {
        "total_count": 3,
        "success_count": 2,
        "failure_count": 1,
        "running_count": 0,
        "cancelled_count": 0,
        "avg_duration_ms": None,
        "by_task_name": {},
    }

    cancel_resp = await tasks_client.post("/api/v1/tasks/cancel", json={"task_id": "job-9"})
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["cancelled"] is True

    stats_resp = await tasks_client.get("/api/v1/tasks/stats", params={"hours": 12})
    assert stats_resp.status_code == 200
    assert stats_resp.json()["total_count"] == 3
    service.get_stats.assert_awaited_once_with(hours=12)


@pytest.mark.asyncio
async def test_scheduled_jobs_serialization(tasks_client: AsyncClient):
    """Scheduled jobs endpoint serializes datetime and counts correctly."""
    service: MockTaskService = tasks_client.task_service  # type: ignore[attr-defined]
    now = datetime.now(UTC)
    service.get_scheduled_jobs = lambda: [
        {
            "job_id": "job-1",
            "job_name": "cleanup",
            "next_run_time": now,
            "trigger_type": "cron",
            "trigger_description": "* * * * *",
            "is_paused": False,
            "misfire_grace_time": 5,
            "max_instances": 1,
        }
    ]

    resp = await tasks_client.get("/api/v1/tasks/scheduled")

    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["jobs"][0]["job_id"] == "job-1"
    assert "Z" in body["jobs"][0]["next_run_time"]
