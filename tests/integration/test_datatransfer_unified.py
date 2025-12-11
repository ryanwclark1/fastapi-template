"""Integration tests for unified DataTransfer system with JobManager.

This module tests the complete Option D implementation:
- Execution modes (sync, async, auto)
- ACL permission enforcement
- JobManager persistence
- Worker integration
- Job access patterns
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import inspect
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

from fastapi import status
import pytest
from sqlalchemy import select

from example_service.core.schemas.auth import AuthUser
from example_service.features.datatransfer.schemas import (
    ExportFormat,
    ExportRequest,
    ExportStatus,
)
from example_service.features.reminders.models import Reminder
from example_service.infra.tasks.jobs.manager import JobManager
from example_service.infra.tasks.jobs.models import Job, JobStatus
from example_service.workers.export.tasks import export_data_csv

if TYPE_CHECKING:
    from httpx import AsyncClient, Response
    from sqlalchemy.ext.asyncio import AsyncSession
else:
    Response = Any


def _assert_status(response: Response, expected_status: int) -> None:
    """Assert response status with helpful error message."""
    if response.status_code != expected_status:
        try:
            body = response.json()
        except ValueError:
            body = response.text
        error_msg = f"Expected {expected_status}, got {response.status_code}: {body}"
        raise AssertionError(error_msg)


@pytest.fixture
async def test_reminders(db_session: AsyncSession, test_tenant_id: str) -> list[Reminder]:
    """Create test reminders for export testing."""
    reminders = []
    for i in range(15):  # Create 15 reminders
        reminder = Reminder(
            id=uuid4(),
            tenant_id=test_tenant_id,
            title=f"Test Reminder {i + 1}",
            description=f"Description for reminder {i + 1}",
            due_date=datetime.now(UTC),
            is_completed=(i % 2 == 0),  # Half completed, half not
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        reminders.append(reminder)
        db_session.add(reminder)

    await db_session.commit()
    return reminders


@pytest.fixture
def user_with_export_permission() -> AuthUser:
    """User with export permission for reminders."""
    return AuthUser(
        user_id="user-with-permission",
        permissions=["datatransfer.export.reminders"],
        metadata={
            "tenant_uuid": "tenant-integration",
            "tenant_slug": "tenant-integration-slug",
        },
    )


@pytest.fixture
def user_without_export_permission() -> AuthUser:
    """User without export permission."""
    return AuthUser(
        user_id="user-without-permission",
        permissions=["some.other.permission"],
        metadata={
            "tenant_uuid": "tenant-integration",
            "tenant_slug": "tenant-integration-slug",
        },
    )


@pytest.fixture
def admin_user() -> AuthUser:
    """Admin user with full access."""
    return AuthUser(
        user_id="admin-user",
        permissions=["#"],  # Superuser
        metadata={
            "tenant_uuid": "tenant-integration",
            "tenant_slug": "tenant-integration-slug",
        },
    )


@pytest.mark.asyncio
class TestUnifiedDataTransferExecution:
    """Test execution modes (sync, async, auto) with JobManager integration."""

    async def test_export_sync_mode_default(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        test_reminders: list[Reminder],
    ) -> None:
        """Test sync mode export (default behavior) - backward compatible."""
        response = await async_client.post(
            "/api/v1/data-transfer/export",
            json={
                "entity_type": "reminders",
                "format": "csv",
                "filters": {"is_completed": False},
            },
            headers=auth_headers,
        )

        _assert_status(response, status.HTTP_200_OK)
        data = response.json()

        # Sync mode returns immediate results
        assert data["status"] == "completed"
        assert data["file_path"] is not None
        assert data["record_count"] > 0
        assert "job_id" not in data or data["job_id"] is None

        # Verify file exists
        assert Path(data["file_path"]).exists()

    async def test_export_async_mode_creates_job(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        test_reminders: list[Reminder],
    ) -> None:
        """Test async mode creates persistent job via JobManager."""
        with patch(
            "example_service.workers.export.tasks.export_data_csv.kiq",
        ) as mock_kiq:
            mock_kiq.return_value = AsyncMock()

            response = await async_client.post(
                "/api/v1/data-transfer/export?execution_mode=async",
                json={
                    "entity_type": "reminders",
                    "format": "csv",
                },
                headers=auth_headers,
            )

            _assert_status(response, status.HTTP_202_ACCEPTED)
            data = response.json()

            # Async mode returns job_id for polling
            assert data["status"] == "pending"
            assert data["job_id"] is not None
            assert data["poll_url"] is not None

            # Verify job exists in JobManager
            job_manager = JobManager(db_session)
            job = await job_manager.get(UUID(data["job_id"]))

            assert job is not None
            assert job.status == JobStatus.PENDING
            assert job.labels["feature"] == "datatransfer"
            assert job.labels["operation"] == "export"
            assert job.labels["entity"] == "reminders"

            # Verify worker was enqueued
            mock_kiq.assert_called_once()

    async def test_export_auto_mode_small_dataset_uses_sync(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
    ) -> None:
        """Test auto mode uses sync for small datasets (<10k records)."""
        # Create only 5 reminders (well below threshold)
        for i in range(5):
            reminder = Reminder(
                id=uuid4(),
                tenant_id="tenant-integration",
                title=f"Small Dataset {i}",
                due_date=datetime.now(UTC),
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            db_session.add(reminder)
        await db_session.commit()

        response = await async_client.post(
            "/api/v1/data-transfer/export?execution_mode=auto",
            json={
                "entity_type": "reminders",
                "format": "csv",
            },
            headers=auth_headers,
        )

        _assert_status(response, status.HTTP_200_OK)
        data = response.json()

        # Auto mode chose sync for small dataset
        assert data["status"] == "completed"
        assert data["file_path"] is not None

    async def test_export_auto_mode_large_dataset_uses_async(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
    ) -> None:
        """Test auto mode uses async for large datasets (>10k records)."""
        # Mock the count query to return >10k
        with patch(
            "example_service.features.datatransfer.service.DataTransferService._get_export_count",
        ) as mock_count:
            mock_count.return_value = 15000  # Above threshold

            with patch(
                "example_service.workers.export.tasks.export_data_csv.kiq",
            ) as mock_kiq:
                mock_kiq.return_value = AsyncMock()

                response = await async_client.post(
                    "/api/v1/data-transfer/export?execution_mode=auto",
                    json={
                        "entity_type": "reminders",
                        "format": "csv",
                    },
                    headers=auth_headers,
                )

                _assert_status(response, status.HTTP_202_ACCEPTED)
                data = response.json()

                # Auto mode chose async for large dataset
                assert data["status"] == "pending"
                assert data["job_id"] is not None


@pytest.mark.asyncio
class TestACLPermissions:
    """Test ACL permission enforcement for exports."""

    async def test_export_with_required_permission_succeeds(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        user_with_export_permission: AuthUser,
        test_reminders: list[Reminder],
    ) -> None:
        """Test export succeeds when user has required permission."""
        from example_service.core.dependencies.auth import get_current_user

        # Override with user who has permission
        async def _override_auth():
            return user_with_export_permission

        async_client.app.dependency_overrides[get_current_user] = _override_auth

        try:
            response = await async_client.post(
                "/api/v1/data-transfer/export",
                json={
                    "entity_type": "reminders",
                    "format": "csv",
                },
                headers=auth_headers,
            )

            _assert_status(response, status.HTTP_200_OK)
            assert response.json()["status"] == "completed"

        finally:
            async_client.app.dependency_overrides.clear()

    async def test_export_without_permission_denied(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        user_without_export_permission: AuthUser,
    ) -> None:
        """Test export fails when user lacks required permission."""
        from example_service.core.dependencies.auth import get_current_user

        # Override with user who lacks permission
        async def _override_auth():
            return user_without_export_permission

        async_client.app.dependency_overrides[get_current_user] = _override_auth

        try:
            response = await async_client.post(
                "/api/v1/data-transfer/export",
                json={
                    "entity_type": "reminders",
                    "format": "csv",
                },
                headers=auth_headers,
            )

            _assert_status(response, status.HTTP_403_FORBIDDEN)
            assert "permission" in response.json()["detail"].lower()

        finally:
            async_client.app.dependency_overrides.clear()

    async def test_admin_user_can_export_any_entity(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        admin_user: AuthUser,
        test_reminders: list[Reminder],
    ) -> None:
        """Test admin user (#) can export any entity."""
        from example_service.core.dependencies.auth import get_current_user

        async def _override_auth():
            return admin_user

        async_client.app.dependency_overrides[get_current_user] = _override_auth

        try:
            # Admin can export without specific entity permission
            response = await async_client.post(
                "/api/v1/data-transfer/export",
                json={
                    "entity_type": "reminders",
                    "format": "csv",
                },
                headers=auth_headers,
            )

            _assert_status(response, status.HTTP_200_OK)

        finally:
            async_client.app.dependency_overrides.clear()


@pytest.mark.asyncio
class TestJobAccessPatterns:
    """Test owner-or-admin job access patterns."""

    async def test_job_owner_can_download(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        user_with_export_permission: AuthUser,
        tmp_path: Path,
    ) -> None:
        """Test job owner can download their export."""
        job_manager = JobManager(db_session)

        # Create completed job owned by user
        job = await job_manager.submit(
            tenant_id="tenant-integration",
            task_name="datatransfer.export.csv",
            args={},
            labels={
                "feature": "datatransfer",
                "operation": "export",
                "entity": "reminders",
                "user_id": user_with_export_permission.user_id,
            },
            actor_id=user_with_export_permission.user_id,
        )

        # Mark job completed with file
        export_file = tmp_path / "test_export.csv"
        export_file.write_text("id,title\n1,Test")

        await job_manager.mark_completed(
            job.id,
            result_data={
                "file_path": str(export_file),
                "file_name": "test_export.csv",
                "record_count": 1,
            },
        )

        from example_service.core.dependencies.auth import get_current_user

        async def _override_auth():
            return user_with_export_permission

        async_client.app.dependency_overrides[get_current_user] = _override_auth

        try:
            response = await async_client.get(
                f"/api/v1/data-transfer/jobs/{job.id}/download",
                headers=auth_headers,
            )

            _assert_status(response, status.HTTP_200_OK)
            assert response.headers["content-type"] == "text/csv; charset=utf-8"

        finally:
            async_client.app.dependency_overrides.clear()
            export_file.unlink(missing_ok=True)

    async def test_non_owner_cannot_download(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        user_with_export_permission: AuthUser,
        user_without_export_permission: AuthUser,
        tmp_path: Path,
    ) -> None:
        """Test non-owner cannot download someone else's export."""
        job_manager = JobManager(db_session)

        # Create job owned by different user
        job = await job_manager.submit(
            tenant_id="tenant-integration",
            task_name="datatransfer.export.csv",
            args={},
            labels={
                "feature": "datatransfer",
                "operation": "export",
                "user_id": "different-user-id",  # Different owner
            },
            actor_id="different-user-id",
        )

        await job_manager.mark_completed(
            job.id,
            result_data={"file_path": str(tmp_path / "unauthorized.csv")},
        )

        from example_service.core.dependencies.auth import get_current_user

        # Try to download as user without permission
        async def _override_auth():
            return user_without_export_permission

        async_client.app.dependency_overrides[get_current_user] = _override_auth

        try:
            response = await async_client.get(
                f"/api/v1/data-transfer/jobs/{job.id}/download",
                headers=auth_headers,
            )

            _assert_status(response, status.HTTP_403_FORBIDDEN)

        finally:
            async_client.app.dependency_overrides.clear()

    async def test_admin_can_download_any_job(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        admin_user: AuthUser,
        tmp_path: Path,
    ) -> None:
        """Test admin user can download any job regardless of owner."""
        job_manager = JobManager(db_session)

        # Create job owned by different user
        job = await job_manager.submit(
            tenant_id="tenant-integration",
            task_name="datatransfer.export.csv",
            args={},
            labels={
                "feature": "datatransfer",
                "operation": "export",
                "user_id": "other-user",
            },
            actor_id="other-user",
        )

        export_file = tmp_path / "admin_test.csv"
        export_file.write_text("id,title\n1,Test")

        await job_manager.mark_completed(
            job.id,
            result_data={
                "file_path": str(export_file),
                "file_name": "admin_test.csv",
            },
        )

        from example_service.core.dependencies.auth import get_current_user

        async def _override_auth():
            return admin_user

        async_client.app.dependency_overrides[get_current_user] = _override_auth

        try:
            # Admin can download any job
            response = await async_client.get(
                f"/api/v1/data-transfer/jobs/{job.id}/download",
                headers=auth_headers,
            )

            _assert_status(response, status.HTTP_200_OK)

        finally:
            async_client.app.dependency_overrides.clear()
            export_file.unlink(missing_ok=True)


@pytest.mark.asyncio
class TestJobPersistence:
    """Test JobManager persistence survives restarts."""

    async def test_job_persists_across_sessions(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
    ) -> None:
        """Test jobs are persisted in database, not in-memory."""
        with patch("example_service.workers.export.tasks.export_data_csv.kiq") as mock_kiq:
            mock_kiq.return_value = AsyncMock()

            # Create async export
            response = await async_client.post(
                "/api/v1/data-transfer/export?execution_mode=async",
                json={
                    "entity_type": "reminders",
                    "format": "csv",
                },
                headers=auth_headers,
            )

            _assert_status(response, status.HTTP_202_ACCEPTED)
            job_id = UUID(response.json()["job_id"])

        # Close and reopen session (simulate restart)
        await db_session.close()

        # Create new session and JobManager
        from example_service.infra.database.session import get_async_session

        async with get_async_session() as new_session:
            new_job_manager = JobManager(new_session)

            # Job should still exist
            job = await new_job_manager.get(job_id)

            assert job is not None
            assert job.id == job_id
            assert job.labels["feature"] == "datatransfer"

    async def test_job_progress_tracking(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
    ) -> None:
        """Test job progress is tracked via JobManager."""
        job_manager = JobManager(db_session)

        # Create job
        job = await job_manager.submit(
            tenant_id="tenant-integration",
            task_name="datatransfer.export.csv",
            args={},
            labels={"feature": "datatransfer", "operation": "export"},
        )

        # Update progress
        await job_manager.update_progress(
            job.id,
            percentage=50,
            current_item=500,
            total_items=1000,
            message="Exported 500/1000 records",
        )

        # Verify progress persisted
        progress_list = await job_manager.get_progress(job.id)

        assert len(progress_list) > 0
        latest_progress = progress_list[-1]
        assert latest_progress.percentage == 50
        assert latest_progress.message == "Exported 500/1000 records"


@pytest.mark.asyncio
class TestConcurrentExports:
    """Test multiple concurrent exports."""

    async def test_multiple_users_concurrent_exports(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        test_reminders: list[Reminder],
    ) -> None:
        """Test multiple users can export simultaneously."""
        # Create 3 concurrent export requests
        tasks = []
        for i in range(3):
            task = async_client.post(
                "/api/v1/data-transfer/export",
                json={
                    "entity_type": "reminders",
                    "format": "csv",
                    "filters": {"is_completed": i % 2 == 0},
                },
                headers=auth_headers,
            )
            tasks.append(task)

        # Execute concurrently
        responses = await asyncio.gather(*tasks)

        # All should succeed
        for response in responses:
            _assert_status(response, status.HTTP_200_OK)
            assert response.json()["status"] == "completed"

        # All should have unique file paths
        file_paths = [r.json()["file_path"] for r in responses]
        assert len(file_paths) == len(set(file_paths))  # All unique


@pytest.mark.asyncio
class TestTenantIsolation:
    """Test tenant isolation in exports."""

    async def test_export_only_returns_tenant_data(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        test_tenant_id: str,
    ) -> None:
        """Test exports only include data from user's tenant."""
        # Create reminders for different tenant
        other_tenant_reminder = Reminder(
            id=uuid4(),
            tenant_id="other-tenant",
            title="Other Tenant Reminder",
            due_date=datetime.now(UTC),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db_session.add(other_tenant_reminder)

        # Create reminder for test tenant
        test_tenant_reminder = Reminder(
            id=uuid4(),
            tenant_id=test_tenant_id,
            title="Test Tenant Reminder",
            due_date=datetime.now(UTC),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db_session.add(test_tenant_reminder)
        await db_session.commit()

        response = await async_client.post(
            "/api/v1/data-transfer/export",
            json={
                "entity_type": "reminders",
                "format": "csv",
            },
            headers=auth_headers,
        )

        _assert_status(response, status.HTTP_200_OK)
        data = response.json()

        # Verify only test tenant's data exported
        export_file = Path(data["file_path"])
        content = export_file.read_text()

        assert "Test Tenant Reminder" in content
        assert "Other Tenant Reminder" not in content


@pytest.mark.asyncio
class TestWorkerIntegration:
    """Test worker task integration with DataTransferService."""

    async def test_worker_uses_datatransfer_service(
        self,
        db_session: AsyncSession,
        test_reminders: list[Reminder],
    ) -> None:
        """Test worker tasks call DataTransferService (not hardcoded logic)."""
        # Create job for tracking
        job_manager = JobManager(db_session)
        job = await job_manager.submit(
            tenant_id="tenant-integration",
            task_name="datatransfer.export.csv",
            args={},
            labels={"feature": "datatransfer", "operation": "export"},
        )

        # Execute worker task
        result = await export_data_csv(
            entity_type="reminders",  # Generic, not hardcoded!
            job_id=str(job.id),
        )

        # Verify success
        assert result["status"] == "success"
        assert result["entity_type"] == "reminders"
        assert result["record_count"] > 0
        assert Path(result["filepath"]).exists()

        # Verify job updated
        updated_job = await job_manager.get(job.id)
        assert updated_job.status == JobStatus.COMPLETED
        assert updated_job.result_data["record_count"] > 0

    async def test_worker_supports_all_entities(
        self,
        db_session: AsyncSession,
    ) -> None:
        """Test worker now supports all entities from ENTITY_REGISTRY."""
        # Worker should support any entity (not just reminders)
        # This tests the refactoring from hardcoded to generic

        # Note: Would need to create test data for other entities
        # For now, verify function signature accepts entity_type parameter
        sig = inspect.signature(export_data_csv)
        params = list(sig.parameters.keys())

        assert "entity_type" in params
        assert "model_name" not in params or params[0] != "model_name"  # Deprecated
