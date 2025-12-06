"""Unit tests for task management schemas."""

from __future__ import annotations

from datetime import datetime, timedelta

from pydantic import ValidationError
import pytest

from example_service.features.tasks.schemas import (
    CancelTaskRequest,
    CancelTaskResponse,
    RunningTaskResponse,
    ScheduledJobListResponse,
    ScheduledJobResponse,
    TaskExecutionDetailResponse,
    TaskExecutionResponse,
    TaskName,
    TaskSearchParams,
    TaskSearchResponse,
    TaskStatsResponse,
    TaskStatus,
    TriggerTaskRequest,
    TriggerTaskResponse,
)


class TestTaskStatus:
    """Tests for TaskStatus enum."""

    def test_all_statuses_exist(self):
        """All expected statuses should be defined."""
        expected = {"pending", "running", "success", "failure", "cancelled"}
        actual = {s.value for s in TaskStatus}

        assert actual == expected

    def test_status_values(self):
        """Status values should match their names in lowercase."""
        assert TaskStatus.PENDING.value == "pending"
        assert TaskStatus.RUNNING.value == "running"
        assert TaskStatus.SUCCESS.value == "success"
        assert TaskStatus.FAILURE.value == "failure"
        assert TaskStatus.CANCELLED.value == "cancelled"


class TestTaskName:
    """Tests for TaskName enum."""

    def test_backup_tasks(self):
        """Backup tasks should be defined."""
        assert TaskName.backup_database.value == "backup_database"

    def test_notification_tasks(self):
        """Notification tasks should be defined."""
        assert TaskName.check_due_reminders.value == "check_due_reminders"

    def test_cache_tasks(self):
        """Cache tasks should be defined."""
        assert TaskName.warm_cache.value == "warm_cache"
        assert TaskName.invalidate_cache.value == "invalidate_cache"

    def test_export_tasks(self):
        """Export tasks should be defined."""
        assert TaskName.export_csv.value == "export_csv"
        assert TaskName.export_json.value == "export_json"

    def test_cleanup_tasks(self):
        """Cleanup tasks should be defined."""
        cleanup_tasks = [
            TaskName.cleanup_temp_files,
            TaskName.cleanup_old_backups,
            TaskName.cleanup_old_exports,
            TaskName.cleanup_expired_data,
            TaskName.run_all_cleanup,
        ]

        for task in cleanup_tasks:
            assert task.value.startswith("cleanup") or task.value == "run_all_cleanup"

    def test_total_task_count(self):
        """Should have expected number of triggerable tasks."""
        assert len(TaskName) == 11


class TestTaskExecutionResponse:
    """Tests for TaskExecutionResponse schema."""

    def test_minimal_response(self):
        """Response with only required fields should be valid."""
        response = TaskExecutionResponse(
            task_id="task-123",
            task_name="backup_database",
            status="success",
        )

        assert response.task_id == "task-123"
        assert response.task_name == "backup_database"
        assert response.status == "success"
        assert response.worker_id is None
        assert response.duration_ms is None

    def test_full_response(self):
        """Response with all fields should be valid."""
        response = TaskExecutionResponse(
            task_id="task-456",
            task_name="export_csv",
            status="running",
            worker_id="worker-1",
            started_at="2024-01-15T10:00:00",
            finished_at=None,
            duration_ms=5000,
        )

        assert response.worker_id == "worker-1"
        assert response.started_at == "2024-01-15T10:00:00"
        assert response.finished_at is None
        assert response.duration_ms == 5000


class TestTaskExecutionDetailResponse:
    """Tests for TaskExecutionDetailResponse schema."""

    def test_inherits_base_fields(self):
        """Should include all base response fields."""
        response = TaskExecutionDetailResponse(
            task_id="task-789",
            task_name="cleanup_temp_files",
            status="success",
            duration_ms=1500,
        )

        assert response.task_id == "task-789"
        assert response.task_name == "cleanup_temp_files"
        assert response.status == "success"

    def test_success_with_return_value(self):
        """Successful task should include return value."""
        response = TaskExecutionDetailResponse(
            task_id="task-1",
            task_name="export_csv",
            status="success",
            return_value={"path": "/exports/data.csv", "rows": 1000},
        )

        assert response.return_value == {"path": "/exports/data.csv", "rows": 1000}
        assert response.error_type is None
        assert response.error_message is None

    def test_failure_with_error_info(self):
        """Failed task should include error details."""
        response = TaskExecutionDetailResponse(
            task_id="task-2",
            task_name="backup_database",
            status="failure",
            error_type="ConnectionError",
            error_message="Database connection timeout",
            error_traceback="Traceback...",
        )

        assert response.error_type == "ConnectionError"
        assert response.error_message == "Database connection timeout"
        assert response.error_traceback == "Traceback..."

    def test_task_args_and_kwargs(self):
        """Should include task arguments."""
        response = TaskExecutionDetailResponse(
            task_id="task-3",
            task_name="export_csv",
            status="success",
            task_args=["reminders"],
            task_kwargs={"filters": {"status": "active"}},
        )

        assert response.task_args == ["reminders"]
        assert response.task_kwargs == {"filters": {"status": "active"}}

    def test_labels_and_metadata(self):
        """Should include labels and progress."""
        response = TaskExecutionDetailResponse(
            task_id="task-4",
            task_name="export_json",
            status="running",
            labels={"priority": "high", "tenant": "acme"},
            progress={"current": 50, "total": 100, "percent": 50},
        )

        assert response.labels == {"priority": "high", "tenant": "acme"}
        assert response.progress["percent"] == 50


class TestRunningTaskResponse:
    """Tests for RunningTaskResponse schema."""

    def test_required_fields(self):
        """All required fields must be provided."""
        response = RunningTaskResponse(
            task_id="running-1",
            task_name="backup_database",
            started_at="2024-01-15T10:00:00",
            running_for_ms=30000,
        )

        assert response.task_id == "running-1"
        assert response.running_for_ms == 30000

    def test_with_worker_id(self):
        """Should include optional worker ID."""
        response = RunningTaskResponse(
            task_id="running-2",
            task_name="export_csv",
            started_at="2024-01-15T10:00:00",
            running_for_ms=5000,
            worker_id="worker-node-1",
        )

        assert response.worker_id == "worker-node-1"


class TestTaskSearchParams:
    """Tests for TaskSearchParams schema."""

    def test_default_values(self):
        """Default values should be set correctly."""
        params = TaskSearchParams()

        assert params.limit == 50
        assert params.offset == 0
        assert params.order_by == "created_at"
        assert params.order_dir == "desc"
        assert params.task_name is None
        assert params.status is None

    def test_with_filters(self):
        """Should accept various filter parameters."""
        params = TaskSearchParams(
            task_name="backup_database",
            status=TaskStatus.SUCCESS,
            worker_id="worker-1",
            error_type="TimeoutError",
            min_duration_ms=1000,
            max_duration_ms=60000,
        )

        assert params.task_name == "backup_database"
        assert params.status == TaskStatus.SUCCESS
        assert params.worker_id == "worker-1"
        assert params.min_duration_ms == 1000

    def test_date_range_filters(self):
        """Should accept date range filters."""
        now = datetime.now()
        yesterday = now - timedelta(days=1)

        params = TaskSearchParams(
            created_after=yesterday,
            created_before=now,
        )

        assert params.created_after == yesterday
        assert params.created_before == now

    def test_ordering_options(self):
        """Should accept valid ordering options."""
        for order_by in ["created_at", "duration_ms", "task_name", "status"]:
            for order_dir in ["asc", "desc"]:
                params = TaskSearchParams(order_by=order_by, order_dir=order_dir)
                assert params.order_by == order_by
                assert params.order_dir == order_dir

    def test_limit_bounds(self):
        """Limit should be within valid range."""
        # Valid limits
        TaskSearchParams(limit=1)
        TaskSearchParams(limit=200)

        # Invalid limits
        with pytest.raises(ValidationError):
            TaskSearchParams(limit=0)

        with pytest.raises(ValidationError):
            TaskSearchParams(limit=201)

    def test_offset_non_negative(self):
        """Offset must be non-negative."""
        TaskSearchParams(offset=0)
        TaskSearchParams(offset=100)

        with pytest.raises(ValidationError):
            TaskSearchParams(offset=-1)


class TestTaskSearchResponse:
    """Tests for TaskSearchResponse schema."""

    def test_empty_results(self):
        """Should handle empty results."""
        response = TaskSearchResponse(
            items=[],
            total=0,
            limit=50,
            offset=0,
        )

        assert len(response.items) == 0
        assert response.total == 0

    def test_with_results(self):
        """Should include task items."""
        items = [
            TaskExecutionResponse(
                task_id=f"task-{i}",
                task_name="backup_database",
                status="success",
            )
            for i in range(3)
        ]

        response = TaskSearchResponse(
            items=items,
            total=100,
            limit=50,
            offset=0,
        )

        assert len(response.items) == 3
        assert response.total == 100


class TestTaskStatsResponse:
    """Tests for TaskStatsResponse schema."""

    def test_default_values(self):
        """Should have sensible defaults."""
        stats = TaskStatsResponse(
            total_count=0,
            success_count=0,
            failure_count=0,
            running_count=0,
        )

        assert stats.cancelled_count == 0
        assert stats.avg_duration_ms is None
        assert stats.by_task_name == {}
        assert stats.by_status == {}

    def test_full_stats(self):
        """Should include all statistics."""
        stats = TaskStatsResponse(
            total_count=1000,
            success_count=950,
            failure_count=40,
            running_count=5,
            cancelled_count=5,
            avg_duration_ms=250.5,
            by_task_name={"backup_database": 100, "export_csv": 900},
            by_status={"success": 950, "failure": 40},
        )

        assert stats.total_count == 1000
        assert stats.avg_duration_ms == 250.5
        assert stats.by_task_name["backup_database"] == 100


class TestScheduledJobResponse:
    """Tests for ScheduledJobResponse schema."""

    def test_minimal_job(self):
        """Should handle job with minimal data."""
        job = ScheduledJobResponse(
            job_id="job-1",
            job_name="backup_job",
            trigger_type="cron",
            trigger_description="cron[hour='2']",
        )

        assert job.job_id == "job-1"
        assert job.is_paused is False
        assert job.next_run_time is None

    def test_full_job(self):
        """Should include all job details."""
        next_run = datetime.now() + timedelta(hours=1)

        job = ScheduledJobResponse(
            job_id="job-2",
            job_name="cleanup_job",
            next_run_time=next_run,
            trigger_type="interval",
            trigger_description="interval[0:01:00]",
            is_paused=True,
            misfire_grace_time=60,
            max_instances=1,
        )

        assert job.is_paused is True
        assert job.misfire_grace_time == 60
        assert job.max_instances == 1


class TestScheduledJobListResponse:
    """Tests for ScheduledJobListResponse schema."""

    def test_empty_list(self):
        """Should handle empty job list."""
        response = ScheduledJobListResponse(jobs=[], count=0)

        assert len(response.jobs) == 0
        assert response.count == 0

    def test_with_jobs(self):
        """Should include job list."""
        jobs = [
            ScheduledJobResponse(
                job_id=f"job-{i}",
                job_name=f"job_{i}",
                trigger_type="cron",
                trigger_description="cron[...]",
            )
            for i in range(5)
        ]

        response = ScheduledJobListResponse(jobs=jobs, count=5)

        assert len(response.jobs) == 5
        assert response.count == 5


class TestTriggerTaskRequest:
    """Tests for TriggerTaskRequest schema."""

    def test_minimal_request(self):
        """Should accept task name only."""
        request = TriggerTaskRequest(task=TaskName.backup_database)

        assert request.task == TaskName.backup_database
        assert request.params is None

    def test_with_params(self):
        """Should accept task-specific parameters."""
        request = TriggerTaskRequest(
            task=TaskName.export_csv,
            params={"model": "reminders", "filters": {"status": "active"}},
        )

        assert request.task == TaskName.export_csv
        assert request.params["model"] == "reminders"

    def test_all_task_names_valid(self):
        """All TaskName values should be valid."""
        for task_name in TaskName:
            request = TriggerTaskRequest(task=task_name)
            assert request.task == task_name

    def test_invalid_task_name(self):
        """Invalid task name should raise error."""
        with pytest.raises(ValidationError):
            TriggerTaskRequest(task="invalid_task")


class TestTriggerTaskResponse:
    """Tests for TriggerTaskResponse schema."""

    def test_response_fields(self):
        """Should include all response fields."""
        response = TriggerTaskResponse(
            task_id="triggered-123",
            task_name="backup_database",
            status="queued",
            message="Task queued successfully",
        )

        assert response.task_id == "triggered-123"
        assert response.task_name == "backup_database"
        assert response.status == "queued"
        assert "queued" in response.message.lower()


class TestCancelTaskRequest:
    """Tests for CancelTaskRequest schema."""

    def test_minimal_request(self):
        """Should accept task ID only."""
        request = CancelTaskRequest(task_id="task-to-cancel")

        assert request.task_id == "task-to-cancel"
        assert request.reason is None

    def test_with_reason(self):
        """Should accept cancellation reason."""
        request = CancelTaskRequest(
            task_id="task-123",
            reason="User requested cancellation",
        )

        assert request.reason == "User requested cancellation"

    def test_reason_max_length(self):
        """Reason should respect max length."""
        # Valid length
        CancelTaskRequest(task_id="t", reason="x" * 500)

        # Too long
        with pytest.raises(ValidationError):
            CancelTaskRequest(task_id="t", reason="x" * 501)


class TestCancelTaskResponse:
    """Tests for CancelTaskResponse schema."""

    def test_successful_cancellation(self):
        """Should indicate successful cancellation."""
        response = CancelTaskResponse(
            task_id="task-123",
            cancelled=True,
            message="Task cancelled successfully",
            previous_status="running",
        )

        assert response.cancelled is True
        assert response.previous_status == "running"

    def test_failed_cancellation(self):
        """Should indicate failed cancellation."""
        response = CancelTaskResponse(
            task_id="task-456",
            cancelled=False,
            message="Cannot cancel completed task",
            previous_status="success",
        )

        assert response.cancelled is False
        assert response.previous_status == "success"
