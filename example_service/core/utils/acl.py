"""ACL checking utilities for route handlers.

Provides high-level functions for common ACL patterns that raise
HTTPException with structured RFC 7807 Problem Details responses.

These utilities are designed for use in route handler bodies (not as
FastAPI dependencies). For dependency-based ACL checking, use the
require_acl() dependency factory from core.dependencies.accent_auth.

Pattern: Imperative permission checking (raises HTTPException on failure)

Key Functions:
    - require_permission(): Check single ACL permission
    - require_any_permission(): Check any of multiple permissions (OR logic)
    - require_owner_or_admin(): Common ownership pattern

Example Usage:
    ```python
    from example_service.core.dependencies.auth import AuthUserDep
    from example_service.core.utils.acl import require_permission, require_owner_or_admin

    @router.delete("/resources/{resource_id}")
    async def delete_resource(
        resource_id: str,
        user: AuthUserDep,
        request: Request,
    ):
        # Imperative permission check
        require_permission(user, "resources.delete", request.url.path)

        # Business logic
        await service.delete(resource_id)
        return {"deleted": resource_id}

    @router.get("/users/{user_id}/profile")
    async def get_profile(
        user_id: str,
        user: AuthUserDep,
        request: Request,
    ):
        # Owner-or-admin pattern (common for user-owned resources)
        require_owner_or_admin(user, user_id, "users.admin", request.url.path)

        return await fetch_profile(user_id)
    ```

When to Use These vs Dependencies:
    - Use these utilities when you need conditional permission checks in route body
    - Use require_acl() dependency when permission is always required for endpoint
    - Use these for owner-or-admin patterns (requires runtime owner ID check)

See Also:
    - example_service.core.dependencies.accent_auth.require_acl - Dependency-based checking
    - example_service.core.schemas.auth.AuthUser - User model with has_acl() methods
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException, status

if TYPE_CHECKING:
    from example_service.core.schemas.auth import AuthUser


def require_permission(
    user: AuthUser,
    required_acl: str,
    request_path: str | None = None,
) -> None:
    """Require user to have specific ACL permission.

    Raises HTTPException(403) with RFC 7807 Problem Details if permission check fails.

    Args:
        user: Authenticated user (from AuthUserDep dependency)
        required_acl: Required ACL pattern (e.g., "resources.delete", "admin.#")
        request_path: Optional request path for error context (use request.url.path)

    Raises:
        HTTPException: 403 Forbidden if user lacks permission

    Example:
        @router.delete("/resources/{resource_id}")
        async def delete_resource(
            resource_id: str,
            user: AuthUserDep,
            request: Request,
        ):
            require_permission(user, "resources.delete", request.url.path)
            await service.delete(resource_id)
            return {"deleted": resource_id}
    """
    if not user.has_acl(required_acl):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "type": "insufficient-permissions",
                "title": "Forbidden",
                "status": 403,
                "detail": f"Missing required permission: {required_acl}",
                "required_acl": required_acl,
                "user_acls": user.permissions,
                "instance": request_path,
            },
        )


def require_any_permission(
    user: AuthUser,
    required_acls: list[str],
    request_path: str | None = None,
) -> None:
    """Require user to have any of the specified permissions (OR logic).

    Useful when multiple permission levels can grant access to the same resource.

    Args:
        user: Authenticated user (from AuthUserDep dependency)
        required_acls: List of ACL patterns (any must match)
        request_path: Optional request path for error context (use request.url.path)

    Raises:
        HTTPException: 403 Forbidden if user lacks all permissions

    Example:
        @router.get("/reports")
        async def get_reports(
            user: AuthUserDep,
            request: Request,
        ):
            # Allow if user has reports.read OR admin access
            require_any_permission(
                user,
                ["reports.read", "admin.#"],
                request.url.path
            )
            return await fetch_reports()
    """
    if not user.has_any_acl(*required_acls):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "type": "insufficient-permissions",
                "title": "Forbidden",
                "status": 403,
                "detail": f"Missing required permissions (need any of): {', '.join(required_acls)}",
                "required_acls": required_acls,
                "user_acls": user.permissions,
                "instance": request_path,
            },
        )


def require_owner_or_admin(
    user: AuthUser,
    resource_owner_id: str,
    admin_acl: str = "#",
    request_path: str | None = None,
) -> None:
    """Require user to be resource owner OR have admin access.

    Common pattern for user-owned resources: allow access if the user owns
    the resource OR has admin privileges to access any resource.

    Args:
        user: Authenticated user (from AuthUserDep dependency)
        resource_owner_id: User ID that owns the resource
        admin_acl: ACL pattern for admin override (default: "#" superuser)
        request_path: Optional request path for error context (use request.url.path)

    Raises:
        HTTPException: 403 Forbidden if user is neither owner nor admin

    Example:
        @router.get("/users/{user_id}/profile")
        async def get_profile(
            user_id: str,
            user: AuthUserDep,
            request: Request,
        ):
            # User can access their own profile OR admin can access anyone's
            require_owner_or_admin(user, user_id, "users.admin", request.url.path)

            return await fetch_profile(user_id)

        @router.put("/mailboxes/{mailbox_id}")
        async def update_mailbox(
            mailbox_id: str,
            user: AuthUserDep,
            request: Request,
        ):
            # Check mailbox ownership
            mailbox = await get_mailbox(mailbox_id)
            require_owner_or_admin(
                user,
                mailbox.owner_id,
                "mailboxes.admin",
                request.url.path
            )

            await update_mailbox(mailbox_id, updates)
    """
    is_owner = user.user_id == resource_owner_id
    is_admin = user.has_acl(admin_acl)

    if not (is_owner or is_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "type": "insufficient-permissions",
                "title": "Forbidden",
                "status": 403,
                "detail": "Must be resource owner or have admin access",
                "resource_owner_id": resource_owner_id,
                "user_id": user.user_id,
                "admin_acl": admin_acl,
                "instance": request_path,
            },
        )


__all__ = [
    "require_any_permission",
    "require_owner_or_admin",
    "require_permission",
]
