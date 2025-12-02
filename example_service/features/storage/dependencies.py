"""Dependencies for storage management endpoints."""

from typing import Annotated

from fastapi import Depends

from example_service.core.dependencies.auth import require_role
from example_service.core.dependencies.tenant import TenantContextDep
from example_service.core.schemas.auth import AuthUser
from example_service.infra.storage.service import StorageService, get_storage_service

# Storage service dependency
StorageServiceDep = Annotated[StorageService, Depends(get_storage_service)]

# Admin authentication - only admins can manage storage
# You can adjust this based on your permission model
AdminUser = Annotated[AuthUser, Depends(require_role("admin"))]

# Tenant context dependency - re-exported for convenience
__all__ = ["AdminUser", "StorageServiceDep", "TenantContextDep"]

# Alternative: Use permission-based auth
# from example_service.core.dependencies.auth import require_permission
# AdminUser = Annotated[AuthUser, Depends(require_permission("storage:manage"))]
