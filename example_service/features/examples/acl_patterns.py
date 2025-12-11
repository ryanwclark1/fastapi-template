"""Example routes demonstrating ACL patterns and best practices.

This module provides working examples of different ACL authorization patterns
that can be used as a reference when implementing authentication in your own
routes.

These examples demonstrate:
- Basic authentication (required vs optional)
- Dependency-based ACL checking
- Imperative ACL checking in route body
- Owner-or-admin patterns
- Path parameter substitution
- Multiple permission requirements (AND/OR logic)

Note: These are EXAMPLE routes for educational purposes. You can mount this
router in your application during development, but consider removing it in
production unless you need a testing/demo endpoint.

Usage:
    # In your main.py or router setup
    from example_service.features.examples import acl_router

    app.include_router(acl_router, prefix="/api/v1", tags=["Examples"])
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from example_service.core.dependencies.auth import (
    AuthUserDep,
    OptionalAuthUser,
    ReadOnlyUserDep,
    SuperuserDep,
    require_acl,
    require_all_acls,
    require_any_acl,
)
from example_service.core.schemas.auth import AuthUser
from example_service.core.utils.acl import (
    require_any_permission,
    require_owner_or_admin,
    require_permission,
)

router = APIRouter(prefix="/examples/acl", tags=["Examples - ACL Patterns"])


# ============================================================================
# Response Models
# ============================================================================


class ExampleResponse(BaseModel):
    """Standard response for example endpoints."""

    message: str
    user_id: str | None = None
    pattern: str
    description: str


# ============================================================================
# Basic Authentication Patterns
# ============================================================================


@router.get(
    "/basic-auth",
    response_model=ExampleResponse,
    summary="Basic Authentication",
    description="Requires valid X-Auth-Token header. No specific permissions needed.",
)
async def basic_auth(user: AuthUserDep) -> ExampleResponse:
    """Basic authentication - requires valid token only.

    This is the most common pattern for endpoints that need to identify
    the user but don't require specific permissions.
    """
    return ExampleResponse(
        message=f"Hello {user.user_id}",
        user_id=user.user_id,
        pattern="AuthUserDep",
        description="Basic authentication with no specific permission checks",
    )


@router.get(
    "/optional-auth",
    response_model=ExampleResponse,
    summary="Optional Authentication",
    description="Works with or without authentication. Returns different content based on auth status.",
)
async def optional_auth(user: OptionalAuthUser) -> ExampleResponse:
    """Optional authentication - works for both authenticated and anonymous users.

    Use this pattern for endpoints that provide different functionality
    based on whether the user is authenticated.
    """
    if user:
        return ExampleResponse(
            message=f"Hello authenticated user {user.user_id}",
            user_id=user.user_id,
            pattern="OptionalAuthUser",
            description="Authenticated user - personalized content",
        )

    return ExampleResponse(
        message="Hello anonymous user",
        user_id=None,
        pattern="OptionalAuthUser",
        description="Anonymous user - public content only",
    )


# ============================================================================
# Permission-Based Access Control
# ============================================================================


@router.get(
    "/superuser-only",
    response_model=ExampleResponse,
    summary="Superuser Only",
    description="Requires # ACL (full system access). For critical admin operations.",
)
async def superuser_only(admin: SuperuserDep) -> ExampleResponse:
    """Superuser access only - requires # ACL.

    The # wildcard grants access to everything. This should only be
    used for the most critical administrative operations.
    """
    return ExampleResponse(
        message=f"Superuser {admin.user_id} has full access",
        user_id=admin.user_id,
        pattern="SuperuserDep (require # ACL)",
        description="Full system access - use sparingly for critical operations",
    )


@router.get(
    "/read-only",
    response_model=ExampleResponse,
    summary="Read-Only Access",
    description="Requires *.*.read ACL. For users who can read all resources.",
)
async def read_only(user: ReadOnlyUserDep) -> ExampleResponse:
    """Read-only access - requires *.*.read ACL.

    Use this pattern for endpoints that should be accessible to users
    with read permissions across all resources.
    """
    return ExampleResponse(
        message=f"User {user.user_id} has read-only access",
        user_id=user.user_id,
        pattern="ReadOnlyUserDep (require *.*.read ACL)",
        description="Read access to all resources using wildcard pattern",
    )


@router.delete(
    "/resources/{resource_id}",
    response_model=ExampleResponse,
    summary="Specific Permission",
    description="Requires resources.delete ACL. Demonstrates single permission check.",
)
async def delete_resource(
    resource_id: str,
    user: Annotated[AuthUser, Depends(require_acl("resources.delete"))],
) -> ExampleResponse:
    """Delete resource - requires resources.delete ACL.

    This demonstrates using require_acl() as a FastAPI dependency
    to enforce a specific permission.
    """
    return ExampleResponse(
        message=f"User {user.user_id} deleted resource {resource_id}",
        user_id=user.user_id,
        pattern="require_acl('resources.delete')",
        description="Single permission requirement using dependency",
    )


# ============================================================================
# Multiple Permission Patterns (AND/OR Logic)
# ============================================================================


@router.get(
    "/admin-or-stats",
    response_model=ExampleResponse,
    summary="Multiple Permissions (OR Logic)",
    description="Requires EITHER admin.# OR stats.read ACL. User needs any one of them.",
)
async def admin_or_stats(
    user: Annotated[
        AuthUser,
        Depends(require_any_acl("admin.#", "stats.read")),
    ],
) -> ExampleResponse:
    """Admin or stats access - requires ANY of multiple permissions.

    Use require_any_acl() when the user needs at least one of several
    permissions to access the endpoint (OR logic).
    """
    return ExampleResponse(
        message=f"User {user.user_id} has admin or stats access",
        user_id=user.user_id,
        pattern="require_any_acl('admin.#', 'stats.read')",
        description="OR logic - user needs at least one of the specified permissions",
    )


@router.post(
    "/admin-users",
    response_model=ExampleResponse,
    summary="Multiple Permissions (AND Logic)",
    description="Requires BOTH users.create AND users.admin ACLs. User must have all.",
)
async def create_admin_user(
    user: Annotated[
        AuthUser,
        Depends(require_all_acls("users.create", "users.admin")),
    ],
) -> ExampleResponse:
    """Create admin user - requires ALL specified permissions.

    Use require_all_acls() when the user must have every single
    permission to perform the operation (AND logic).
    """
    return ExampleResponse(
        message=f"User {user.user_id} can create admin users",
        user_id=user.user_id,
        pattern="require_all_acls('users.create', 'users.admin')",
        description="AND logic - user must have all specified permissions",
    )


# ============================================================================
# Imperative Permission Checking (In Route Body)
# ============================================================================


@router.post(
    "/resources",
    response_model=ExampleResponse,
    summary="Imperative Permission Check",
    description="Demonstrates checking permissions in route body for conditional logic.",
)
async def create_resource(
    user: AuthUserDep,
    request: Request,
    resource_type: str = "public",
) -> ExampleResponse:
    """Create resource with imperative permission checking.

    Use imperative checks (require_permission) when you need to check
    permissions conditionally based on request data.
    """
    # Check different permissions based on resource type
    if resource_type == "public":
        require_permission(user, "resources.create.public", request.url.path)
        message = "Created public resource"
    else:
        require_permission(user, "resources.create.private", request.url.path)
        message = "Created private resource"

    return ExampleResponse(
        message=message,
        user_id=user.user_id,
        pattern=f"require_permission('resources.create.{resource_type}')",
        description="Conditional permission check based on resource type",
    )


@router.get(
    "/flexible-permissions",
    response_model=ExampleResponse,
    summary="Flexible Permission Logic",
    description="Demonstrates complex permission logic with require_any_permission.",
)
async def flexible_permissions(
    user: AuthUserDep,
    request: Request,
) -> ExampleResponse:
    """Flexible permission checking with OR logic in route body.

    Use require_any_permission() when you need OR logic for permissions
    that can't be determined until runtime.
    """
    # Allow if user has any of these permissions
    require_any_permission(
        user,
        ["reports.read", "reports.admin", "admin.#"],
        request.url.path,
    )

    return ExampleResponse(
        message=f"User {user.user_id} has access to reports",
        user_id=user.user_id,
        pattern="require_any_permission(['reports.read', 'reports.admin', 'admin.#'])",
        description="OR logic with imperative checking in route body",
    )


# ============================================================================
# Owner-or-Admin Pattern
# ============================================================================


@router.get(
    "/users/{user_id}/profile",
    response_model=ExampleResponse,
    summary="Owner or Admin Pattern",
    description="User can access their own profile OR admin can access anyone's profile.",
)
async def get_user_profile(
    user_id: str,
    user: AuthUserDep,
    request: Request,
) -> ExampleResponse:
    """Get user profile - owner or admin pattern.

    This is a very common pattern: allow access if the user is the
    resource owner OR has admin privileges.

    Use require_owner_or_admin() for this pattern.
    """
    # Check if user is owner OR has admin ACL
    require_owner_or_admin(user, user_id, "users.admin", request.url.path)

    return ExampleResponse(
        message=f"Accessed profile for user {user_id}",
        user_id=user.user_id,
        pattern="require_owner_or_admin(user_id, 'users.admin')",
        description="Owner can access own resource OR admin can access any resource",
    )


# ============================================================================
# Path Parameter Substitution
# ============================================================================


@router.get(
    "/users/{user_id}/settings",
    response_model=ExampleResponse,
    summary="Path Parameter Substitution",
    description="ACL pattern with {user_id} placeholder gets replaced with actual path value.",
)
async def get_user_settings(
    user_id: str,
    user: Annotated[AuthUser, Depends(require_acl("users.{user_id}.read"))],
) -> ExampleResponse:
    """Get user settings - demonstrates path parameter substitution in ACL.

    The {user_id} placeholder in the ACL pattern gets replaced with the
    actual user_id from the URL path. This enables fine-grained permissions
    like "users.123.read" for user with ID 123.
    """
    return ExampleResponse(
        message=f"Accessed settings for user {user_id}",
        user_id=user.user_id,
        pattern=f"require_acl('users.{{user_id}}.read') → 'users.{user_id}.read'",
        description="Path parameter substitution for fine-grained ACL control",
    )


# ============================================================================
# Summary Endpoint
# ============================================================================


@router.get(
    "/",
    response_model=dict,
    summary="ACL Patterns Summary",
    description="Lists all available ACL pattern examples with descriptions.",
)
async def list_patterns() -> dict:
    """List all available ACL pattern examples.

    This endpoint provides an overview of all the patterns demonstrated
    in this module.
    """
    return {
        "title": "ACL Pattern Examples",
        "description": "Educational examples demonstrating ACL authorization patterns",
        "patterns": [
            {
                "endpoint": "/examples/acl/basic-auth",
                "pattern": "AuthUserDep",
                "description": "Basic authentication - requires valid token only",
            },
            {
                "endpoint": "/examples/acl/optional-auth",
                "pattern": "OptionalAuthUser",
                "description": "Optional authentication - works with or without token",
            },
            {
                "endpoint": "/examples/acl/superuser-only",
                "pattern": "SuperuserDep (# ACL)",
                "description": "Superuser access only - full system permissions",
            },
            {
                "endpoint": "/examples/acl/read-only",
                "pattern": "ReadOnlyUserDep (*.*.read ACL)",
                "description": "Read-only access to all resources",
            },
            {
                "endpoint": "/examples/acl/resources/{id}",
                "pattern": "require_acl('resources.delete')",
                "description": "Single specific permission requirement",
            },
            {
                "endpoint": "/examples/acl/admin-or-stats",
                "pattern": "require_any_acl(...)",
                "description": "OR logic - need any of multiple permissions",
            },
            {
                "endpoint": "/examples/acl/admin-users",
                "pattern": "require_all_acls(...)",
                "description": "AND logic - need all specified permissions",
            },
            {
                "endpoint": "/examples/acl/resources (POST)",
                "pattern": "require_permission() in body",
                "description": "Imperative permission check for conditional logic",
            },
            {
                "endpoint": "/examples/acl/flexible-permissions",
                "pattern": "require_any_permission() in body",
                "description": "Flexible OR logic with runtime evaluation",
            },
            {
                "endpoint": "/examples/acl/users/{user_id}/profile",
                "pattern": "require_owner_or_admin()",
                "description": "Common owner-or-admin access pattern",
            },
            {
                "endpoint": "/examples/acl/users/{user_id}/settings",
                "pattern": "require_acl('users.{user_id}.read')",
                "description": "Path parameter substitution in ACL patterns",
            },
        ],
        "note": "These are example routes for educational purposes. Consider removing in production.",
    }
