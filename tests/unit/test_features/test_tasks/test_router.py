"""Router tests for task management endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
import importlib
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
import pytest

from example_service.app.exception_handlers import configure_exception_handlers
from example_service.features.tasks.schemas import (
    CancelTaskResponse,
    TaskName,
    TaskStatus,
)
from example_service.features.tasks.service import (
    BrokerNotConfiguredError,
    TaskServiceError,
)

tasks_router_module = importlib.import_module("example_service.features.tasks.router")


class MockTaskService:
    """Mock implementation of TaskManagementService for router tests."""

    def __init__(self) -> None:
        self.search_tasks = AsyncMock()
        self.get_running_tasks = AsyncMock()
        self.get_stats = AsyncMock()
        self.get_task_details = AsyncMock()
        self.trigger_task = AsyncMock()
        self.cancel_task = AsyncMock()
        self.get_scheduled_jobs = MagicMock(return_value=[])
        self.get_scheduled_job = MagicMock(return_value=None)
        self.pause_job = MagicMock(return_value=True)
        self.resume_job = MagicMock(return_value=True)


@pytest.fixture
def app_and_service():
    """Create FastAPI app with tasks router and mocked service dependency."""
    app = FastAPI()
    configure_exception_handlers(app)  # Register RFC 7807 exception handlers
    service = MockTaskService()

    def get_service_override():
        return service

    app.dependency_overrides[tasks_router_module.get_service] = get_service_override
    app.include_router(tasks_router_module.router)

    # Move catch-all task_id route to the end so static routes win in tests
    for idx, route in enumerate(list(app.router.routes)):
        if isinstance(route, APIRoute) and route.path == "/tasks/{task_id}":
            detail_route = app.router.routes.pop(idx)
            app.router.routes.append(detail_route)
            break

    try:
        yield app, service
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
async def client_and_service(app_and_service):
    """Provide httpx AsyncClient bound to FastAPI app plus service mock."""
    app, service = app_and_service
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, service


@pytest.mark.asyncio
async def test_search_tasks_with_filters(client_and_service):
    """GET /tasks should map query params into TaskSearchParams and return data."""
    client, service = client_and_service
    service.search_tasks.return_value = (
        [
            {
                "task_id": "task-1",
                "task_name": "backup_database",
                "status": "success",
                "worker_id": "worker-1",
                "started_at": "2024-01-01T00:00:00Z",
                "finished_at": "2024-01-01T00:05:00Z",
                "duration_ms": 300000,
            }
        ],
        12,
    )

    response = await client.get(
        "/tasks",
        params={
            "task_name": "backup_database",
            "status": TaskStatus.SUCCESS.value,
            "worker_id": "worker-1",
            "limit": 5,
            "offset": 1,
            "order_by": "created_at",
            "order_dir": "asc",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 12
    assert payload["limit"] == 5
    assert payload["offset"] == 1
    assert payload["items"][0]["task_name"] == "backup_database"

    params_obj = service.search_tasks.call_args.args[0]
    assert params_obj.task_name == "backup_database"
    assert params_obj.status == TaskStatus.SUCCESS
    assert params_obj.worker_id == "worker-1"
    assert params_obj.limit == 5
    assert params_obj.offset == 1
    assert params_obj.order_dir == "asc"


@pytest.mark.asyncio
async def test_search_tasks_invalid_params(client_and_service):
    """GET /tasks should validate query params (e.g., limit range)."""
    client, _ = client_and_service

    response = await client.get("/tasks", params={"limit": 0})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_running_tasks(client_and_service):
    """GET /tasks/running returns running tasks list."""
    client, service = client_and_service
    service.get_running_tasks.return_value = [
        {
            "task_id": "task-1",
            "task_name": "backup_database",
            "started_at": "2024-01-01T00:00:00Z",
            "running_for_ms": 120000,
            "worker_id": "worker-1",
        }
    ]

    response = await client.get("/tasks/running")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["task_id"] == "task-1"
    service.get_running_tasks.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_running_tasks_empty(client_and_service):
    """GET /tasks/running returns empty list when none running."""
    client, service = client_and_service
    service.get_running_tasks.return_value = []

    response = await client.get("/tasks/running")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_task_stats_with_hours(client_and_service):
    """GET /tasks/stats forwards hours param and returns stats."""
    client, service = client_and_service
    service.get_stats.return_value = {
        "total_count": 5,
        "success_count": 4,
        "failure_count": 1,
        "running_count": 0,
        "cancelled_count": 0,
        "avg_duration_ms": 1200.5,
        "by_task_name": {"backup_database": 3},
    }

    response = await client.get("/tasks/stats", params={"hours": 12})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_count"] == 5
    service.get_stats.assert_awaited_once_with(hours=12)


@pytest.mark.asyncio
async def test_get_task_details_found(client_and_service):
    """GET /tasks/{task_id} returns task details when found."""
    client, service = client_and_service
    service.get_task_details.return_value = {
        "task_id": "task-1",
        "task_name": "backup_database",
        "status": "success",
        "started_at": "2024-01-01T00:00:00Z",
        "finished_at": "2024-01-01T00:05:00Z",
        "duration_ms": 300000,
    }

    response = await client.get("/tasks/task-1")

    assert response.status_code == 200
    assert response.json()["task_id"] == "task-1"
    service.get_task_details.assert_awaited_once_with("task-1")


@pytest.mark.asyncio
async def test_get_task_details_not_found(client_and_service):
    """GET /tasks/{task_id} returns 404 when missing."""
    client, service = client_and_service
    service.get_task_details.return_value = None

    response = await client.get("/tasks/missing-task")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_trigger_task_success(client_and_service):
    """POST /tasks/trigger triggers task and returns queued status."""
    client, service = client_and_service
    service.trigger_task.return_value = {
        "task_id": "abc123",
        "task_name": TaskName.backup_database.value,
        "status": "queued",
        "message": "queued",
    }

    response = await client.post(
        "/tasks/trigger",
        json={"task": TaskName.backup_database.value, "params": {"foo": "bar"}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["task_id"] == "abc123"
    service.trigger_task.assert_awaited_once()


@pytest.mark.asyncio
async def test_trigger_task_broker_unavailable(client_and_service):
    """POST /tasks/trigger returns 503 when broker missing."""
    client, service = client_and_service
    service.trigger_task.side_effect = BrokerNotConfiguredError("no broker")

    response = await client.post(
        "/tasks/trigger",
        json={"task": TaskName.run_all_cleanup.value, "params": {}},
    )

    assert response.status_code == 503
    assert "no broker" in response.json()["detail"]


@pytest.mark.asyncio
async def test_trigger_task_invalid_name(client_and_service):
    """POST /tasks/trigger converts service errors to 500."""
    client, service = client_and_service
    service.trigger_task.side_effect = TaskServiceError("invalid task name")

    response = await client.post(
        "/tasks/trigger",
        json={"task": TaskName.run_all_cleanup.value, "params": {"invalid": True}},
    )

    assert response.status_code == 500
    assert "invalid task name" in response.json()["detail"]


@pytest.mark.asyncio
async def test_cancel_task_success(client_and_service):
    """POST /tasks/cancel returns cancellation result."""
    client, service = client_and_service
    service.cancel_task.return_value = CancelTaskResponse(
        task_id="task-1",
        cancelled=True,
        message="Task cancelled successfully",
        previous_status="running",
    )

    response = await client.post("/tasks/cancel", json={"task_id": "task-1"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["cancelled"] is True
    assert payload["previous_status"] == "running"
    service.cancel_task.assert_awaited_once_with("task-1", None)


@pytest.mark.asyncio
async def test_cancel_task_not_cancellable(client_and_service):
    """POST /tasks/cancel surfaces not-found/finished responses."""
    client, service = client_and_service
    service.cancel_task.return_value = CancelTaskResponse(
        task_id="task-2",
        cancelled=False,
        message="Cannot cancel task with status 'success'",
        previous_status="success",
    )

    response = await client.post("/tasks/cancel", json={"task_id": "task-2"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["cancelled"] is False
    assert payload["previous_status"] == "success"


@pytest.mark.asyncio
async def test_list_scheduled_jobs(client_and_service):
    """GET /tasks/scheduled returns jobs and count."""
    client, service = client_and_service
    now = datetime.now(UTC)
    service.get_scheduled_jobs.return_value = [
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

    response = await client.get("/tasks/scheduled")

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["jobs"][0]["job_id"] == "job-1"
    service.get_scheduled_jobs.assert_called_once()


@pytest.mark.asyncio
async def test_list_scheduled_jobs_empty(client_and_service):
    """GET /tasks/scheduled returns zero count when no jobs."""
    client, service = client_and_service
    service.get_scheduled_jobs.return_value = []

    response = await client.get("/tasks/scheduled")

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 0
    assert payload["jobs"] == []


@pytest.mark.asyncio
async def test_get_scheduled_job_found(client_and_service):
    """GET /tasks/scheduled/{job_id} returns job details."""
    client, service = client_and_service
    now = datetime.now(UTC)
    service.get_scheduled_job.return_value = {
        "job_id": "job-1",
        "job_name": "cleanup",
        "next_run_time": now,
        "trigger_type": "cron",
        "trigger_description": "* * * * *",
        "is_paused": False,
        "misfire_grace_time": 5,
        "max_instances": 1,
    }

    response = await client.get("/tasks/scheduled/job-1")

    assert response.status_code == 200
    assert response.json()["job_id"] == "job-1"
    service.get_scheduled_job.assert_called_once_with("job-1")


@pytest.mark.asyncio
async def test_get_scheduled_job_not_found(client_and_service):
    """GET /tasks/scheduled/{job_id} returns 404 when missing."""
    client, service = client_and_service
    service.get_scheduled_job.return_value = None

    response = await client.get("/tasks/scheduled/unknown")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_pause_scheduled_job_success(client_and_service):
    """POST /tasks/scheduled/{job_id}/pause pauses job."""
    client, service = client_and_service
    service.pause_job.return_value = True

    response = await client.post("/tasks/scheduled/job-1/pause")

    assert response.status_code == 200
    assert response.json()["paused"] is True
    service.pause_job.assert_called_once_with("job-1")


@pytest.mark.asyncio
async def test_pause_scheduled_job_not_found(client_and_service):
    """POST /tasks/scheduled/{job_id}/pause returns 404 when pause fails."""
    client, service = client_and_service
    service.pause_job.return_value = False

    response = await client.post("/tasks/scheduled/missing/pause")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_resume_scheduled_job_success(client_and_service):
    """POST /tasks/scheduled/{job_id}/resume resumes job."""
    client, service = client_and_service
    service.resume_job.return_value = True

    response = await client.post("/tasks/scheduled/job-1/resume")

    assert response.status_code == 200
    assert response.json()["resumed"] is True
    service.resume_job.assert_called_once_with("job-1")


@pytest.mark.asyncio
async def test_resume_scheduled_job_not_found(client_and_service):
    """POST /tasks/scheduled/{job_id}/resume returns 404 when resume fails."""
    client, service = client_and_service
    service.resume_job.return_value = False

    response = await client.post("/tasks/scheduled/missing/resume")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"]
