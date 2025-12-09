"""Authentication dependencies - re-exports from accent_auth for ACL-based auth.

This module provides FastAPI dependencies for authentication and authorization
using the Accent-Auth ACL system. All functions are re-exported from the
accent_auth module to maintain backward compatibility while standardizing
on ACL-based authorization.

For new code, prefer importing directly from accent_auth:
    from example_service.core.dependencies.accent_auth import (
        get_current_user,
        require_acl,
        require_any_acl,
        require_all_acls,
        require_superuser,
    )

ACL Pattern Syntax:
    - service.resource.action (e.g., "confd.users.read")
    - Wildcards: * (single level), # (multi-level/recursive)
    - Negation: ! prefix for explicit deny
    - Reserved words: me (current user), my_session (current session)

Examples:
    # Basic authentication
    @router.get("/protected")
    async def protected_endpoint(
        user: Annotated[AuthUser, Depends(get_current_user)]
    ):
        return {"user_id": user.identifier}

    # Require specific ACL
    @router.delete("/users/{user_id}")
    async def delete_user(
        user: Annotated[AuthUser, Depends(require_acl("users.delete"))]
    ):
        pass

    # Require admin-level access
    AdminUser = Annotated[AuthUser, Depends(require_acl("admin.#"))]

    @router.post("/admin/settings")
    async def admin_settings(user: AdminUser):
        pass
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from example_service.core.schemas.auth import AuthUser

# Re-export all ACL-based auth functions from accent_auth
from example_service.core.dependencies.accent_auth import (
    get_current_user,
    get_current_user_optional,
    get_tenant_uuid,
    require_acl,
    require_all_acls,
    require_any_acl,
    require_superuser,
)

# Type aliases for dependency injection
CurrentUser = Annotated[AuthUser, Depends(get_current_user)]
CurrentActiveUser = Annotated[AuthUser, Depends(get_current_user)]
OptionalUser = Annotated[AuthUser | None, Depends(get_current_user_optional)]

# Superuser type alias - requires # ACL (full access)
SuperUser = Annotated[AuthUser, Depends(require_superuser())]


__all__ = [
    # Type aliases
    "CurrentActiveUser",
    "CurrentUser",
    "OptionalUser",
    "SuperUser",
    # Functions (re-exported from accent_auth)
    "get_current_user",
    "get_current_user_optional",
    "get_tenant_uuid",
    "require_acl",
    "require_all_acls",
    "require_any_acl",
    "require_superuser",
]
