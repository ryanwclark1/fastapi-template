"""Unit tests for datatransfer ACL permissions."""

from __future__ import annotations

import pytest

from example_service.core.schemas.auth import AuthUser
from example_service.features.datatransfer.acl import (
    DataTransferPermissions,
    check_export_permission,
    check_import_permission,
    check_job_access,
)


class TestDataTransferPermissions:
    """Test DataTransferPermissions constants and helpers."""

    def test_permission_constants(self):
        """Test permission constant values."""
        assert DataTransferPermissions.EXPORT_REMINDERS == "datatransfer.export.reminders"
        assert DataTransferPermissions.IMPORT_WEBHOOKS == "datatransfer.import.webhooks"
        assert DataTransferPermissions.ADMIN == "datatransfer.admin"
        assert DataTransferPermissions.READ_JOBS == "datatransfer.read.jobs"

    def test_export_permission_builder(self):
        """Test export permission builder."""
        assert DataTransferPermissions.export_permission("reminders") == "datatransfer.export.reminders"
        assert DataTransferPermissions.export_permission("files") == "datatransfer.export.files"

    def test_import_permission_builder(self):
        """Test import permission builder."""
        assert DataTransferPermissions.import_permission("reminders") == "datatransfer.import.reminders"
        assert DataTransferPermissions.import_permission("tags") == "datatransfer.import.tags"


class TestCheckExportPermission:
    """Test check_export_permission function."""

    def test_with_specific_permission(self):
        """Test user with specific export permission."""
        user = AuthUser(
            user_id="user-123",
            permissions=["datatransfer.export.reminders"],
        )
        assert check_export_permission(user, "reminders") is True
        assert check_export_permission(user, "webhooks") is False

    def test_with_admin_permission(self):
        """Test user with admin wildcard."""
        user = AuthUser(
            user_id="admin-123",
            permissions=["datatransfer.admin"],
        )
        assert check_export_permission(user, "reminders") is True
        assert check_export_permission(user, "webhooks") is True
        assert check_export_permission(user, "files") is True

    def test_with_export_wildcard(self):
        """Test user with export wildcard."""
        user = AuthUser(
            user_id="exporter-123",
            permissions=["datatransfer.export.#"],
        )
        assert check_export_permission(user, "reminders") is True
        assert check_export_permission(user, "webhooks") is True

    def test_with_superuser(self):
        """Test superuser with # permission."""
        user = AuthUser(
            user_id="super-123",
            permissions=["#"],
        )
        assert check_export_permission(user, "reminders") is True
        assert check_export_permission(user, "anything") is True

    def test_without_permission(self):
        """Test user without export permission."""
        user = AuthUser(
            user_id="user-123",
            permissions=["datatransfer.import.reminders"],
        )
        assert check_export_permission(user, "reminders") is False

    def test_with_none_user(self):
        """Test with None user."""
        assert check_export_permission(None, "reminders") is False

    def test_with_empty_entity_type(self):
        """Test with empty entity type."""
        user = AuthUser(
            user_id="user-123",
            permissions=["datatransfer.export.reminders"],
        )
        assert check_export_permission(user, "") is False
        assert check_export_permission(user, None) is False


class TestCheckImportPermission:
    """Test check_import_permission function."""

    def test_with_specific_permission(self):
        """Test user with specific import permission."""
        user = AuthUser(
            user_id="user-123",
            permissions=["datatransfer.import.reminders"],
        )
        assert check_import_permission(user, "reminders") is True
        assert check_import_permission(user, "webhooks") is False

    def test_with_admin_permission(self):
        """Test user with admin wildcard."""
        user = AuthUser(
            user_id="admin-123",
            permissions=["datatransfer.admin"],
        )
        assert check_import_permission(user, "reminders") is True
        assert check_import_permission(user, "webhooks") is True

    def test_with_import_wildcard(self):
        """Test user with import wildcard."""
        user = AuthUser(
            user_id="importer-123",
            permissions=["datatransfer.import.#"],
        )
        assert check_import_permission(user, "reminders") is True
        assert check_import_permission(user, "files") is True

    def test_with_superuser(self):
        """Test superuser with # permission."""
        user = AuthUser(
            user_id="super-123",
            permissions=["#"],
        )
        assert check_import_permission(user, "reminders") is True

    def test_without_permission(self):
        """Test user without import permission."""
        user = AuthUser(
            user_id="user-123",
            permissions=["datatransfer.export.reminders"],
        )
        assert check_import_permission(user, "reminders") is False


class MockJob:
    """Mock job object for testing."""

    def __init__(
        self,
        job_id: str = "job-123",
        created_by: str | None = None,
        tenant_id: str | None = None,
    ):
        self.id = job_id
        self.created_by = created_by
        self.tenant_id = tenant_id


class TestCheckJobAccess:
    """Test check_job_access function."""

    def test_job_owner_access(self):
        """Test job owner has access."""
        user = AuthUser(
            user_id="user-123",
            permissions=[],
        )
        job = MockJob(created_by="user-123")

        assert check_job_access(user, job) is True

    def test_tenant_user_with_read_permission(self):
        """Test tenant user with read permission."""
        user = AuthUser(
            user_id="user-456",
            permissions=["datatransfer.read.jobs"],
            metadata={"tenant_uuid": "tenant-123"},
        )
        job = MockJob(
            created_by="user-789",
            tenant_id="tenant-123",
        )

        assert check_job_access(user, job) is True

    def test_tenant_user_without_read_permission(self):
        """Test tenant user without read permission."""
        user = AuthUser(
            user_id="user-456",
            permissions=[],
            metadata={"tenant_uuid": "tenant-123"},
        )
        job = MockJob(
            created_by="user-789",
            tenant_id="tenant-123",
        )

        assert check_job_access(user, job) is False

    def test_different_tenant_user(self):
        """Test user from different tenant."""
        user = AuthUser(
            user_id="user-456",
            permissions=["datatransfer.read.jobs"],
            metadata={"tenant_uuid": "tenant-456"},
        )
        job = MockJob(
            created_by="user-789",
            tenant_id="tenant-123",
        )

        assert check_job_access(user, job) is False

    def test_admin_access(self):
        """Test admin can access any job."""
        user = AuthUser(
            user_id="admin-123",
            permissions=["datatransfer.admin"],
        )
        job = MockJob(
            created_by="user-789",
            tenant_id="tenant-456",
        )

        assert check_job_access(user, job) is True

    def test_admin_jobs_permission(self):
        """Test datatransfer.admin.jobs permission."""
        user = AuthUser(
            user_id="admin-123",
            permissions=["datatransfer.admin.jobs"],
        )
        job = MockJob(
            created_by="user-789",
            tenant_id="tenant-456",
        )

        assert check_job_access(user, job) is True

    def test_superuser_access(self):
        """Test superuser can access any job."""
        user = AuthUser(
            user_id="super-123",
            permissions=["#"],
        )
        job = MockJob(
            created_by="user-789",
            tenant_id="tenant-456",
        )

        assert check_job_access(user, job) is True

    def test_no_access_different_user(self):
        """Test user cannot access other user's job without admin."""
        user = AuthUser(
            user_id="user-456",
            permissions=[],
        )
        job = MockJob(
            created_by="user-789",
            tenant_id="tenant-123",
        )

        assert check_job_access(user, job) is False

    def test_with_none_user(self):
        """Test with None user."""
        job = MockJob()
        assert check_job_access(None, job) is False

    def test_with_none_job(self):
        """Test with None job."""
        user = AuthUser(user_id="user-123", permissions=[])
        assert check_job_access(user, None) is False

    def test_job_with_actor_id(self):
        """Test job with actor_id instead of created_by."""
        class JobWithActorId:
            def __init__(self):
                self.id = "job-123"
                self.actor_id = "user-123"
                self.tenant_id = None

        user = AuthUser(user_id="user-123", permissions=[])
        job = JobWithActorId()

        assert check_job_access(user, job) is True


class TestPermissionHierarchy:
    """Test permission hierarchy and fallback."""

    def test_multiple_permissions(self):
        """Test user with multiple permission levels."""
        user = AuthUser(
            user_id="user-123",
            permissions=[
                "datatransfer.export.reminders",
                "datatransfer.export.files",
                "datatransfer.import.tags",
            ],
        )

        # Has specific permissions
        assert check_export_permission(user, "reminders") is True
        assert check_export_permission(user, "files") is True
        assert check_import_permission(user, "tags") is True

        # Lacks other permissions
        assert check_export_permission(user, "tags") is False
        assert check_import_permission(user, "reminders") is False

    def test_admin_overrides_specific(self):
        """Test admin permission overrides specific permissions."""
        user = AuthUser(
            user_id="admin-123",
            permissions=["datatransfer.admin"],  # Admin only
        )

        # Admin has access to everything
        assert check_export_permission(user, "reminders") is True
        assert check_export_permission(user, "webhooks") is True
        assert check_import_permission(user, "reminders") is True
        assert check_import_permission(user, "files") is True

    def test_wildcard_patterns(self):
        """Test wildcard permission patterns."""
        # Export wildcard
        export_user = AuthUser(
            user_id="exporter-123",
            permissions=["datatransfer.export.#"],
        )
        assert check_export_permission(export_user, "any_entity") is True
        assert check_import_permission(export_user, "any_entity") is False

        # Import wildcard
        import_user = AuthUser(
            user_id="importer-123",
            permissions=["datatransfer.import.#"],
        )
        assert check_import_permission(import_user, "any_entity") is True
        assert check_export_permission(import_user, "any_entity") is False
