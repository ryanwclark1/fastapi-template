"""Dependencies for storage management endpoints."""

from typing import Annotated

from fastapi import Depends

from example_service.core.dependencies.accent_auth import require_acl
from example_service.core.dependencies.tenant import TenantContextDep
from example_service.core.schemas.auth import AuthUser
from example_service.infra.storage.service import StorageService, get_storage_service

# Storage service dependency
StorageServiceDep = Annotated[StorageService, Depends(get_storage_service)]

# Admin authentication using ACL - only users with storage admin ACL can manage storage
# Uses dot-notation ACL pattern: "storage.#" means full access to all storage operations
# Alternative patterns:
#   - "storage.buckets.create" - create buckets only
#   - "storage.buckets.*" - all bucket operations
#   - "storage.objects.*" - all object operations
AdminUser = Annotated[AuthUser, Depends(require_acl("storage.#"))]

# Tenant context dependency - re-exported for convenience
__all__ = ["AdminUser", "StorageServiceDep", "TenantContextDep"]
