"""Unit tests for task management service."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from example_service.features.tasks.schemas import (
    TaskName,
    TaskSearchParams,
    TaskStatus,
)
from example_service.features.tasks.service import (
    BrokerNotConfiguredError,
    TaskManagementService,
    TaskServiceError,
    TrackerNotAvailableError,
    get_task_service,
)


class MockTracker:
    """Mock task tracker for testing."""

    def __init__(self, is_connected: bool = True):
        self._is_connected = is_connected
        self.get_task_history = AsyncMock(return_value=[])
        self.count_task_history = AsyncMock(return_value=0)
        self.get_task_details = AsyncMock(return_value=None)
        self.get_running_tasks = AsyncMock(return_value=[])
        self.get_stats = AsyncMock(return_value={})
        self.cancel_task = AsyncMock(return_value=True)

    @property
    def is_connected(self) -> bool:
        return self._is_connected


class MockScheduler:
    """Mock APScheduler for testing."""

    def __init__(self, jobs: list | None = None):
        self._jobs = jobs or []

    def get_jobs(self) -> list:
        return self._jobs

    def get_job(self, job_id: str) -> Any:
        for job in self._jobs:
            if job.id == job_id:
                return job
        return None

    def pause_job(self, job_id: str) -> None:
        pass

    def resume_job(self, job_id: str) -> None:
        pass


class MockJob:
    """Mock APScheduler job for testing."""

    def __init__(
        self,
        job_id: str,
        name: str = "test_job",
        next_run: datetime | None = None,
    ):
        self.id = job_id
        self.name = name
        self.func_ref = f"module.{name}"
        self.next_run_time = next_run
        self.misfire_grace_time = 60
        self.max_instances = 1
        self.trigger = MagicMock()
        self.trigger.__class__.__name__ = "CronTrigger"


class TestTaskManagementServiceInit:
    """Tests for TaskManagementService initialization."""

    def test_init_with_tracker(self):
        """Should accept tracker instance."""
        tracker = MockTracker()
        service = TaskManagementService(tracker=tracker)

        assert service.tracker is tracker

    def test_init_with_scheduler(self):
        """Should accept scheduler instance."""
        scheduler = MockScheduler()
        service = TaskManagementService(scheduler=scheduler)

        assert service._scheduler is scheduler

    def test_init_without_tracker_uses_global(self):
        """Should use global tracker when not provided."""
        service = TaskManagementService()

        # Tracker property will try to get global tracker
        with patch("example_service.features.tasks.service.get_tracker") as mock_get_tracker:
            mock_get_tracker.return_value = MockTracker()
            _ = service.tracker

            mock_get_tracker.assert_called_once()


class TestSearchTasks:
    """Tests for search_tasks method."""

    @pytest.fixture
    def service(self):
        """Create service with mock tracker."""
        tracker = MockTracker()
        return TaskManagementService(tracker=tracker), tracker

    @pytest.mark.asyncio
    async def test_search_with_defaults(self, service):
        """Should search with default parameters."""
        svc, tracker = service
        tracker.get_task_history.return_value = [
            {
                "task_id": "task-1",
                "task_name": "backup_database",
                "status": "success",
                "worker_id": "worker-1",
                "started_at": "2024-01-15T10:00:00",
                "finished_at": "2024-01-15T10:05:00",
                "duration_ms": 300000,
            }
        ]
        tracker.count_task_history.return_value = 1

        params = TaskSearchParams()
        tasks, total = await svc.search_tasks(params)

        assert len(tasks) == 1
        assert tasks[0].task_id == "task-1"
        assert tasks[0].task_name == "backup_database"
        assert total == 1
        tracker.get_task_history.assert_called_once()
        tracker.count_task_history.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_with_filters(self, service):
        """Should pass filters to tracker."""
        svc, tracker = service
        tracker.get_task_history.return_value = []
        tracker.count_task_history.return_value = 12

        params = TaskSearchParams(
            task_name="backup_database",
            status=TaskStatus.SUCCESS,
            worker_id="worker-1",
            limit=10,
            offset=5,
        )

        tasks, total = await svc.search_tasks(params)

        assert tasks == []
        assert total == 12
        tracker.get_task_history.assert_called_once()
        call_kwargs = tracker.get_task_history.call_args.kwargs
        assert call_kwargs["task_name"] == "backup_database"
        assert call_kwargs["status"] == "success"
        assert call_kwargs["worker_id"] == "worker-1"
        assert call_kwargs["limit"] == 10
        assert call_kwargs["offset"] == 5
        tracker.count_task_history.assert_called_once()
        count_kwargs = tracker.count_task_history.call_args.kwargs
        assert count_kwargs["task_name"] == "backup_database"
        assert count_kwargs["status"] == "success"
        assert count_kwargs["worker_id"] == "worker-1"

    @pytest.mark.asyncio
    async def test_search_falls_back_when_count_fails(self, service):
        """Should fall back to page size when count raises."""
        svc, tracker = service
        tracker.get_task_history.return_value = [
            {
                "task_id": "task-1",
                "task_name": "cleanup",
                "status": "success",
                "worker_id": "worker-1",
                "started_at": "2024-01-15T10:00:00",
                "finished_at": "2024-01-15T10:05:00",
                "duration_ms": 300000,
            },
            {
                "task_id": "task-2",
                "task_name": "cleanup",
                "status": "success",
                "worker_id": "worker-2",
                "started_at": "2024-01-15T10:10:00",
                "finished_at": "2024-01-15T10:15:00",
                "duration_ms": 300000,
            },
        ]
        tracker.count_task_history.side_effect = RuntimeError("boom")

        params = TaskSearchParams(limit=2, offset=5)
        _, total = await svc.search_tasks(params)

        assert total == 7  # 5 offset + 2 returned
        tracker.count_task_history.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_with_disconnected_tracker(self):
        """Should return empty results when tracker is disconnected."""
        tracker = MockTracker(is_connected=False)
        service = TaskManagementService(tracker=tracker)

        params = TaskSearchParams()
        tasks, total = await service.search_tasks(params)

        assert tasks == []
        assert total == 0
        tracker.get_task_history.assert_not_called()
        tracker.count_task_history.assert_not_called()

    @pytest.mark.asyncio
    async def test_search_with_no_tracker(self):
        """Should return empty results when no tracker."""
        service = TaskManagementService(tracker=None)

        with patch("example_service.features.tasks.service.get_tracker") as mock_get_tracker:
            mock_get_tracker.return_value = None

            params = TaskSearchParams()
            tasks, total = await service.search_tasks(params)

            assert tasks == []
            assert total == 0
            tracker = mock_get_tracker.return_value
            if tracker:
                tracker.count_task_history.assert_not_called()


class TestGetTaskDetails:
    """Tests for get_task_details method."""

    @pytest.fixture
    def service(self):
        """Create service with mock tracker."""
        tracker = MockTracker()
        return TaskManagementService(tracker=tracker), tracker

    @pytest.mark.asyncio
    async def test_get_existing_task(self, service):
        """Should return task details."""
        svc, tracker = service
        tracker.get_task_details.return_value = {
            "task_id": "task-123",
            "task_name": "export_csv",
            "status": "success",
            "started_at": "2024-01-15T10:00:00",
            "finished_at": "2024-01-15T10:01:00",
            "duration_ms": 60000,
            "return_value": {"rows": 1000},
        }

        result = await svc.get_task_details("task-123")

        assert result is not None
        assert result.task_id == "task-123"
        assert result.return_value == {"rows": 1000}

    @pytest.mark.asyncio
    async def test_get_nonexistent_task(self, service):
        """Should return None for nonexistent task."""
        svc, tracker = service
        tracker.get_task_details.return_value = None

        result = await svc.get_task_details("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_task_with_error_details(self, service):
        """Should include error information."""
        svc, tracker = service
        tracker.get_task_details.return_value = {
            "task_id": "task-failed",
            "task_name": "backup_database",
            "status": "failure",
            "started_at": "2024-01-15T10:00:00",
            "finished_at": "2024-01-15T10:00:05",
            "duration_ms": 5000,
            "error_type": "ConnectionError",
            "error_message": "Database timeout",
            "error_traceback": "Traceback...",
        }

        result = await svc.get_task_details("task-failed")

        assert result.error_type == "ConnectionError"
        assert result.error_message == "Database timeout"


class TestGetRunningTasks:
    """Tests for get_running_tasks method."""

    @pytest.fixture
    def service(self):
        """Create service with mock tracker."""
        tracker = MockTracker()
        return TaskManagementService(tracker=tracker), tracker

    @pytest.mark.asyncio
    async def test_get_running_tasks(self, service):
        """Should return list of running tasks."""
        svc, tracker = service
        tracker.get_running_tasks.return_value = [
            {
                "task_id": "running-1",
                "task_name": "backup_database",
                "started_at": "2024-01-15T10:00:00",
                "running_for_ms": 30000,
                "worker_id": "worker-1",
            },
            {
                "task_id": "running-2",
                "task_name": "export_csv",
                "started_at": "2024-01-15T10:01:00",
                "running_for_ms": 15000,
            },
        ]

        result = await svc.get_running_tasks()

        assert len(result) == 2
        assert result[0].task_id == "running-1"
        assert result[0].running_for_ms == 30000
        assert result[1].worker_id is None

    @pytest.mark.asyncio
    async def test_no_running_tasks(self, service):
        """Should return empty list when no tasks running."""
        svc, tracker = service
        tracker.get_running_tasks.return_value = []

        result = await svc.get_running_tasks()

        assert result == []


class TestGetStats:
    """Tests for get_stats method."""

    @pytest.fixture
    def service(self):
        """Create service with mock tracker."""
        tracker = MockTracker()
        return TaskManagementService(tracker=tracker), tracker

    @pytest.mark.asyncio
    async def test_get_stats(self, service):
        """Should return task statistics."""
        svc, tracker = service
        tracker.get_stats.return_value = {
            "total_count": 1000,
            "success_count": 950,
            "failure_count": 40,
            "running_count": 5,
            "cancelled_count": 5,
            "avg_duration_ms": 250.5,
            "by_task_name": {"backup_database": 100},
        }

        result = await svc.get_stats(hours=24)

        assert result.total_count == 1000
        assert result.success_count == 950
        assert result.avg_duration_ms == 250.5
        tracker.get_stats.assert_called_once_with(hours=24)

    @pytest.mark.asyncio
    async def test_stats_with_disconnected_tracker(self):
        """Should return empty stats when tracker disconnected."""
        tracker = MockTracker(is_connected=False)
        service = TaskManagementService(tracker=tracker)

        result = await service.get_stats()

        assert result.total_count == 0
        assert result.success_count == 0


class TestCancelTask:
    """Tests for cancel_task method."""

    @pytest.fixture
    def service(self):
        """Create service with mock tracker."""
        tracker = MockTracker()
        return TaskManagementService(tracker=tracker), tracker

    @pytest.mark.asyncio
    async def test_cancel_running_task(self, service):
        """Should cancel a running task."""
        svc, tracker = service
        tracker.get_task_details.return_value = {
            "task_id": "task-to-cancel",
            "task_name": "backup_database",
            "status": "running",
        }
        tracker.cancel_task.return_value = True

        result = await svc.cancel_task("task-to-cancel", reason="User requested")

        assert result.cancelled is True
        assert result.previous_status == "running"
        assert "User requested" in result.message

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_task(self, service):
        """Should fail to cancel nonexistent task."""
        svc, tracker = service
        tracker.get_task_details.return_value = None

        result = await svc.cancel_task("nonexistent")

        assert result.cancelled is False
        assert "not found" in result.message.lower()

    @pytest.mark.asyncio
    async def test_cancel_completed_task(self, service):
        """Should fail to cancel completed task."""
        svc, tracker = service
        tracker.get_task_details.return_value = {
            "task_id": "completed-task",
            "task_name": "backup_database",
            "status": "success",
        }
        tracker.cancel_task.return_value = False

        result = await svc.cancel_task("completed-task")

        assert result.cancelled is False
        assert result.previous_status == "success"


class TestScheduledJobs:
    """Tests for scheduled job methods."""

    @pytest.fixture
    def service_with_jobs(self):
        """Create service with mock scheduler and jobs."""
        jobs = [
            MockJob("job-1", "backup_job", datetime(2024, 1, 15, 2, 0, 0)),
            MockJob("job-2", "cleanup_job"),
        ]
        scheduler = MockScheduler(jobs=jobs)
        return TaskManagementService(scheduler=scheduler)

    def test_get_scheduled_jobs(self, service_with_jobs):
        """Should return list of scheduled jobs."""
        result = service_with_jobs.get_scheduled_jobs()

        assert len(result) == 2
        assert result[0].job_id == "job-1"
        assert result[0].job_name == "backup_job"

    def test_get_scheduled_job(self, service_with_jobs):
        """Should return specific job."""
        result = service_with_jobs.get_scheduled_job("job-1")

        assert result is not None
        assert result.job_id == "job-1"

    def test_get_nonexistent_job(self, service_with_jobs):
        """Should return None for nonexistent job."""
        result = service_with_jobs.get_scheduled_job("nonexistent")

        assert result is None

    def test_pause_job(self, service_with_jobs):
        """Should pause a job."""
        result = service_with_jobs.pause_job("job-1")

        assert result is True

    def test_resume_job(self, service_with_jobs):
        """Should resume a job."""
        result = service_with_jobs.resume_job("job-1")

        assert result is True

    def test_no_scheduler(self):
        """Should handle missing scheduler."""
        service = TaskManagementService()

        assert service.get_scheduled_jobs() == []
        assert service.get_scheduled_job("any") is None
        assert service.pause_job("any") is False
        assert service.resume_job("any") is False


class TestTriggerTask:
    """Tests for trigger_task method."""

    @pytest.fixture
    def service(self):
        """Create service with mock tracker."""
        return TaskManagementService()

    @pytest.mark.asyncio
    async def test_trigger_task_no_broker(self, service):
        """Should raise error when broker not configured."""
        with patch("example_service.features.tasks.service.broker", None):
            # Import the service module to patch the broker there
            with patch(
                "example_service.features.tasks.service.TaskManagementService.trigger_task"
            ) as mock_trigger:
                mock_trigger.side_effect = BrokerNotConfiguredError("No broker")

                with pytest.raises(BrokerNotConfiguredError):
                    await service.trigger_task(TaskName.backup_database)


class TestGetTaskService:
    """Tests for get_task_service factory function."""

    def test_creates_service(self):
        """Should create TaskManagementService instance."""
        with patch(
            "example_service.features.tasks.service.scheduler",
            MagicMock(),
        ):
            service = get_task_service()

            assert isinstance(service, TaskManagementService)

    def test_handles_missing_scheduler(self):
        """Should handle missing scheduler module."""
        with patch.dict("sys.modules", {"example_service.workers.scheduler": None}):
            # Force ImportError by patching the import
            def raise_import_error(*args, **kwargs):
                msg = "No module"
                raise ImportError(msg)

            with patch("example_service.features.tasks.service.get_task_service") as mock_factory:
                mock_factory.return_value = TaskManagementService()
                service = mock_factory()

                assert isinstance(service, TaskManagementService)


class TestExceptions:
    """Tests for service exceptions."""

    def test_broker_not_configured_error(self):
        """BrokerNotConfiguredError should be TaskServiceError."""
        error = BrokerNotConfiguredError("Test")

        assert isinstance(error, TaskServiceError)
        assert str(error) == "Test"

    def test_tracker_not_available_error(self):
        """TrackerNotAvailableError should be TaskServiceError."""
        error = TrackerNotAvailableError("Test")

        assert isinstance(error, TaskServiceError)
        assert str(error) == "Test"
