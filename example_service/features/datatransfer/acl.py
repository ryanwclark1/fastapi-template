"""Access control for datatransfer operations.

This module provides entity-level ACL permissions for data export and import:
- datatransfer.export.{entity_type} - Permission to export specific entity type
- datatransfer.import.{entity_type} - Permission to import specific entity type
- datatransfer.admin - Admin wildcard access to all datatransfer operations
- datatransfer.read.jobs - Permission to view own jobs

Key Functions:
    - check_export_permission(): Validate user can export entity type
    - check_import_permission(): Validate user can import entity type
    - check_job_access(): Validate user can access job (owner-or-admin pattern)

Permission Structure:
    Export permissions:
        - datatransfer.export.reminders
        - datatransfer.export.webhooks
        - datatransfer.export.files
        - datatransfer.admin (grants all export access)

    Import permissions:
        - datatransfer.import.reminders
        - datatransfer.import.webhooks
        - datatransfer.import.files
        - datatransfer.admin (grants all import access)

    Job permissions:
        - datatransfer.read.jobs (view own jobs)
        - datatransfer.admin (view all jobs)

Example Usage:
    ```python
    from example_service.core.dependencies.auth import AuthUserDep
    from example_service.features.datatransfer.acl import (
        check_export_permission,
        check_job_access,
    )

    @router.post("/export")
    async def export_data(
        request: ExportRequest,
        user: AuthUserDep,
    ):
        # Check entity-level permission
        if not check_export_permission(user, request.entity_type):
            raise HTTPException(
                403,
                f"Missing permission: datatransfer.export.{request.entity_type}"
            )

        # Proceed with export
        result = await service.export(request)
        return result

    @router.get("/jobs/{job_id}/download")
    async def download_job(
        job_id: str,
        user: AuthUserDep,
    ):
        job = await get_job(job_id)

        # Check job access (owner or admin)
        if not check_job_access(user, job):
            raise HTTPException(403, "Access denied to job")

        return stream_job_file(job)
    ```
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from example_service.core.schemas.auth import AuthUser

logger = logging.getLogger(__name__)


class DataTransferPermissions:
    """Permission constants for datatransfer operations.

    Permission structure uses entity-based granularity:
    - datatransfer.export.{entity_type}
    - datatransfer.import.{entity_type}
    - datatransfer.admin - wildcard access

    This allows fine-grained control over which entities users can export/import.
    """

    # Export permissions
    EXPORT_REMINDERS = "datatransfer.export.reminders"
    EXPORT_WEBHOOKS = "datatransfer.export.webhooks"
    EXPORT_FILES = "datatransfer.export.files"
    EXPORT_TAGS = "datatransfer.export.tags"
    EXPORT_FEATUREFLAGS = "datatransfer.export.featureflags"
    EXPORT_EMAILS = "datatransfer.export.emails"

    # Import permissions
    IMPORT_REMINDERS = "datatransfer.import.reminders"
    IMPORT_WEBHOOKS = "datatransfer.import.webhooks"
    IMPORT_FILES = "datatransfer.import.files"
    IMPORT_TAGS = "datatransfer.import.tags"
    IMPORT_FEATUREFLAGS = "datatransfer.import.featureflags"
    IMPORT_EMAILS = "datatransfer.import.emails"

    # Admin and job permissions
    ADMIN = "datatransfer.admin"
    READ_JOBS = "datatransfer.read.jobs"
    ADMIN_JOBS = "datatransfer.admin.jobs"

    @classmethod
    def export_permission(cls, entity_type: str) -> str:
        """Build export permission for entity type.

        Args:
            entity_type: Entity type (e.g., "reminders", "webhooks")

        Returns:
            Permission pattern (e.g., "datatransfer.export.reminders")
        """
        return f"datatransfer.export.{entity_type}"

    @classmethod
    def import_permission(cls, entity_type: str) -> str:
        """Build import permission for entity type.

        Args:
            entity_type: Entity type (e.g., "reminders", "webhooks")

        Returns:
            Permission pattern (e.g., "datatransfer.import.reminders")
        """
        return f"datatransfer.import.{entity_type}"


def check_export_permission(user: AuthUser, entity_type: str) -> bool:
    """Check if user has permission to export entity type.

    Grants access if user has:
    - datatransfer.export.{entity_type} (specific permission)
    - datatransfer.admin (admin wildcard)
    - datatransfer.export.# (export wildcard)
    - # (superuser)

    Args:
        user: Authenticated user from AuthUserDep
        entity_type: Entity type to export (e.g., "reminders", "webhooks")

    Returns:
        True if user has permission, False otherwise

    Example:
        if not check_export_permission(user, "reminders"):
            raise HTTPException(403, "Cannot export reminders")
    """
    if not user or not entity_type:
        return False

    # Build entity-specific permission
    required_permission = DataTransferPermissions.export_permission(entity_type)

    # Check permissions with fallback hierarchy
    has_permission = user.has_any_acl(
        required_permission,  # Specific: datatransfer.export.reminders
        DataTransferPermissions.ADMIN,  # Admin wildcard: datatransfer.admin
        "datatransfer.export.#",  # Export wildcard
        "#",  # Superuser
    )

    if not has_permission:
        logger.warning(
            "Export permission denied",
            extra={
                "user_id": user.user_id,
                "entity_type": entity_type,
                "required_permission": required_permission,
                "user_permissions": user.permissions,
            },
        )

    return has_permission


def check_import_permission(user: AuthUser, entity_type: str) -> bool:
    """Check if user has permission to import entity type.

    Grants access if user has:
    - datatransfer.import.{entity_type} (specific permission)
    - datatransfer.admin (admin wildcard)
    - datatransfer.import.# (import wildcard)
    - # (superuser)

    Args:
        user: Authenticated user from AuthUserDep
        entity_type: Entity type to import (e.g., "reminders", "webhooks")

    Returns:
        True if user has permission, False otherwise

    Example:
        if not check_import_permission(user, "reminders"):
            raise HTTPException(403, "Cannot import reminders")
    """
    if not user or not entity_type:
        return False

    # Build entity-specific permission
    required_permission = DataTransferPermissions.import_permission(entity_type)

    # Check permissions with fallback hierarchy
    has_permission = user.has_any_acl(
        required_permission,  # Specific: datatransfer.import.reminders
        DataTransferPermissions.ADMIN,  # Admin wildcard: datatransfer.admin
        "datatransfer.import.#",  # Import wildcard
        "#",  # Superuser
    )

    if not has_permission:
        logger.warning(
            "Import permission denied",
            extra={
                "user_id": user.user_id,
                "entity_type": entity_type,
                "required_permission": required_permission,
                "user_permissions": user.permissions,
            },
        )

    return has_permission


def check_job_access(user: AuthUser, job: Any) -> bool:
    """Check if user has access to job (owner-or-admin pattern).

    Grants access if:
    - User created the job (job.created_by == user.user_id)
    - User has tenant access (job.tenant_id == user.tenant_id)
    - User has admin access (datatransfer.admin or datatransfer.admin.jobs)
    - User is superuser (#)

    Args:
        user: Authenticated user from AuthUserDep
        job: Job object with created_by, tenant_id attributes

    Returns:
        True if user can access job, False otherwise

    Example:
        job = await get_job(job_id)
        if not check_job_access(user, job):
            raise HTTPException(403, "Access denied to job")
    """
    if not user or not job:
        return False

    # Check if user is job owner
    job_owner_id = getattr(job, "created_by", None) or getattr(job, "actor_id", None)
    if job_owner_id and user.user_id == job_owner_id:
        return True

    # Check if user has tenant access
    job_tenant_id = getattr(job, "tenant_id", None)
    user_tenant_id = user.tenant_id or user.metadata.get("tenant_uuid")
    if (
        job_tenant_id
        and user_tenant_id
        and job_tenant_id == user_tenant_id
        and user.has_any_acl(
            DataTransferPermissions.READ_JOBS,
            DataTransferPermissions.ADMIN,
            DataTransferPermissions.ADMIN_JOBS,
            "#",
        )
    ):
        return True

    # Check admin permissions
    has_admin = user.has_any_acl(
        DataTransferPermissions.ADMIN,
        DataTransferPermissions.ADMIN_JOBS,
        "#",
    )

    if not has_admin:
        logger.warning(
            "Job access denied",
            extra={
                "user_id": user.user_id,
                "job_id": getattr(job, "id", None),
                "job_owner": job_owner_id,
                "job_tenant": job_tenant_id,
                "user_tenant": user_tenant_id,
                "user_permissions": user.permissions,
            },
        )

    return has_admin


__all__ = [
    "DataTransferPermissions",
    "check_export_permission",
    "check_import_permission",
    "check_job_access",
]
