"""Authentication dependencies - ACL-based auth using Accent-Auth.

This module provides FastAPI dependencies for authentication and authorization
in consumer services (services that use Accent-Auth as an external authentication
provider). Uses Protocol-based client architecture with automatic dual-mode routing.

**Dual-Mode Architecture:**
- When SERVICE_NAME="accent-auth": Uses DatabaseAuthClient (internal, direct DB access)
- When SERVICE_NAME≠"accent-auth": Uses HttpAuthClient (external, HTTP calls to accent-auth)
- Auto-detection is transparent - no code changes needed

**Key Features:**
- Clean type aliases for common patterns (AuthUserDep, SuperuserDep, etc.)
- ACL checking with wildcards, negation, and reserved words
- Token validation caching (Redis)
- RFC 7807 Problem Details error responses
- Integration with imperative ACL utilities

**Import Recommendation:**
    # This is the RECOMMENDED import location for all routers:
    from example_service.core.dependencies.auth import (
        AuthUserDep,          # Type alias for authenticated user
        OptionalAuthUser,     # Type alias for optional auth
        SuperuserDep,         # Type alias for superuser access
        require_acl,          # Dependency factory for ACL checks
        require_any_acl,      # OR-logic ACL checks
    )

**ACL Pattern Syntax:**
    - service.resource.action (e.g., "users.read", "confd.*.delete")
    - Wildcards:
        * = single level (e.g., "users.*" matches "users.read" but not "users.123.read")
        # = multi-level/recursive (e.g., "admin.#" matches everything under "admin")
    - Negation: ! prefix for explicit deny (e.g., "!users.delete")
    - Reserved words:
        me = current user ID
        my_session = current session ID
        my_tenant = current tenant ID
    - Path substitution: {user_id} in ACL pattern gets replaced with actual value

**Basic Examples:**

    # 1. Simple authentication (requires valid token)
    from example_service.core.dependencies.auth import AuthUserDep

    @router.get("/profile")
    async def get_profile(user: AuthUserDep):
        return {"user_id": user.user_id, "email": user.email}

    # 2. Optional authentication (public or private endpoint)
    from example_service.core.dependencies.auth import OptionalAuthUser

    @router.get("/public-or-private")
    async def optional_endpoint(user: OptionalAuthUser):
        if user:
            return {"message": f"Hello {user.user_id}"}
        return {"message": "Hello anonymous user"}

    # 3. Superuser-only endpoint
    from example_service.core.dependencies.auth import SuperuserDep

    @router.post("/admin/reset")
    async def admin_only(admin: SuperuserDep):
        # Only users with # ACL can access
        return await perform_reset()

    # 4. Specific permission check (dependency)
    from example_service.core.dependencies.auth import require_acl

    @router.delete("/resources/{resource_id}")
    async def delete_resource(
        resource_id: str,
        user: Annotated[AuthUser, Depends(require_acl("resources.delete"))],
    ):
        return await service.delete(resource_id)

    # 5. Multiple permissions (OR logic)
    @router.get("/admin/stats")
    async def get_stats(
        user: Annotated[
            AuthUser,
            Depends(require_any_acl("admin.#", "stats.read"))
        ],
    ):
        # User needs EITHER admin access OR stats.read permission
        return await compute_stats()

**Advanced Patterns:**

    # Owner or admin pattern (using imperative utility)
    from example_service.core.dependencies.auth import AuthUserDep
    from example_service.core.utils.acl import require_owner_or_admin

    @router.get("/users/{user_id}/settings")
    async def get_settings(
        user_id: str,
        user: AuthUserDep,
        request: Request,
    ):
        # Allows access if user is owner OR has admin ACL
        require_owner_or_admin(user, user_id, "users.admin", request.url.path)
        return await fetch_settings(user_id)

    # Dynamic ACL with path parameters
    @router.delete("/users/{user_id}")
    async def delete_user(
        user_id: str,
        user: Annotated[AuthUser, Depends(require_acl("users.{user_id}.delete"))],
    ):
        # ACL pattern interpolates {user_id} from path
        return await user_service.delete(user_id)

    # Conditional permission in route body
    from example_service.core.utils.acl import require_permission

    @router.post("/resources")
    async def create_resource(
        data: CreateResourceData,
        user: AuthUserDep,
        request: Request,
    ):
        # Different permissions based on resource type
        if data.resource_type == "public":
            require_permission(user, "resources.create.public", request.url.path)
        else:
            require_permission(user, "resources.create.private", request.url.path)

        return await create(data)

**Related Utilities:**

    # For route handlers (raises HTTPException):
    from example_service.core.utils.acl import (
        require_permission,      # Single ACL check with auto-error
        require_any_permission,  # OR-logic with auto-error
        require_owner_or_admin,  # Common ownership pattern
    )

    # For business logic (returns boolean):
    if user.has_acl("resources.admin"):
        # Custom logic
        pass

**Migration from Old Names:**
    If you have old code using deprecated names, update imports:

    # Before (DEPRECATED):
    from example_service.core.dependencies.auth import CurrentUser, SuperUser

    # After (RECOMMENDED):
    from example_service.core.dependencies.auth import AuthUserDep, SuperuserDep

    Everything else stays the same!

**Testing:**
    Use Protocol-based mock client for testing:

    ```python
    from example_service.infra.auth.testing import MockAuthClient
    from example_service.core.dependencies.auth_client import get_auth_client

    # No mocking library needed!
    mock_client = MockAuthClient.admin()
    app.dependency_overrides[get_auth_client] = lambda: mock_client

    response = client.get("/admin/endpoint")
    assert response.status_code == 200
    ```

**See Also:**
- example_service.core.utils.acl - Helper functions for route handlers
- example_service.core.dependencies.accent_auth - Underlying implementation
- example_service.infra.auth.testing - MockAuthClient for testing
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

# Re-export all ACL-based auth functions from accent_auth
from example_service.core.dependencies.accent_auth import (
    get_auth_user,
    get_auth_user_optional,
    get_tenant_uuid,
    require_acl,
    require_all_acls,
    require_any_acl,
    require_superuser,
)
from example_service.core.schemas.auth import AuthUser

# ============================================================================
# Type Aliases for Dependency Injection (Protocol Pattern)
# ============================================================================

AuthUserDep = Annotated[AuthUser, Depends(get_auth_user)]
"""Authenticated user dependency (required).

Validates X-Auth-Token header and returns AuthUser with ACL permissions.
Raises HTTP 401 if authentication fails.

Example:
    ```python
    from example_service.core.dependencies.auth import AuthUserDep

    @router.get("/profile")
    async def get_profile(user: AuthUserDep):
        return {"user_id": user.user_id}
    ```

Pattern: Required dependency (like BusPublisherDep, StorageServiceDep)
"""

OptionalAuthUser = Annotated[AuthUser | None, Depends(get_auth_user_optional)]
"""Optional authenticated user dependency.

Returns None if X-Auth-Token header is missing or invalid, allowing graceful
degradation for endpoints that work with or without authentication.

Example:
    ```python
    from example_service.core.dependencies.auth import OptionalAuthUser

    @router.get("/public-or-private")
    async def get_data(user: OptionalAuthUser):
        if user:
            return {"message": f"Hello, {user.user_id}"}
        return {"message": "Hello, anonymous"}
    ```

Pattern: Optional dependency (like OptionalDiscoveryService, OptionalStorage)
"""

SuperuserDep = Annotated[AuthUser, Depends(require_superuser())]
"""Superuser dependency (requires # ACL).

Validates that the user has the # (hash) ACL pattern, which grants full
system access. Raises HTTP 403 if user lacks superuser permissions.

The # wildcard is the highest level of access and should be reserved for
system administrators and critical operations.

Example:
    ```python
    from example_service.core.dependencies.auth import SuperuserDep

    @router.post("/system/reset")
    async def reset_system(user: SuperuserDep):
        # Only users with # ACL can access
        perform_system_reset()
        return {"status": "reset_complete"}
    ```

Pattern: Role-based dependency (superuser = full access)
"""

# Permission-specific type aliases (customize per service)
ReadOnlyUserDep = Annotated[AuthUser, Depends(require_acl("*.*.read"))]
"""Read-only user dependency (requires *.*.read ACL).

Grants read access to all resources using wildcard patterns.
Raises HTTP 403 if user lacks read permissions.

Example:
    ```python
    from example_service.core.dependencies.auth import ReadOnlyUserDep

    @router.get("/resources")
    async def list_resources(user: ReadOnlyUserDep):
        # Users with *.*.read can access
        return await fetch_resources()
    ```

Pattern: Permission-based dependency (read-only access)
"""


__all__ = [
    # ========================================================================
    # Type Aliases (recommended for new code)
    # ========================================================================
    "AuthUserDep",
    "OptionalAuthUser",
    "ReadOnlyUserDep",
    "SuperuserDep",
    # ========================================================================
    # Functions (re-exported from accent_auth)
    # ========================================================================
    "get_auth_user",
    "get_auth_user_optional",
    "get_tenant_uuid",
    "require_acl",
    "require_all_acls",
    "require_any_acl",
    "require_superuser",
]
