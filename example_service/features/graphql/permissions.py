"""Permission classes for field-level authorization in GraphQL.

This module provides Strawberry permission classes that integrate with the existing
authentication and authorization system. Permissions can be applied at the field or
resolver level for granular access control.

Usage:
    @strawberry.field(permission_classes=[IsAuthenticated, HasPermission("reminders:read")])
    async def reminders(self, info: Info) -> list[ReminderType]:
        ...

Example in types:
    @strawberry.type
    class UserType:
        email: str = strawberry.field(permission_classes=[IsAuthenticated])
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from strawberry.permission import BasePermission

if TYPE_CHECKING:
    from strawberry.types import Info

    from example_service.features.graphql.context import GraphQLContext

logger = logging.getLogger(__name__)

__all__ = [
    "CanAccessResource",
    "HasPermission",
    "HasRole",
    "IsAdmin",
    "IsAuthenticated",
    "IsOwner",
]


# ============================================================================
# Base Authentication Permission
# ============================================================================


class IsAuthenticated(BasePermission):
    """Require user to be authenticated.

    This is the most basic permission - it only checks that a user is logged in.
    Should be applied to any field that requires authentication.

    Example:
        @strawberry.field(permission_classes=[IsAuthenticated])
        async def my_profile(self, info: Info) -> UserType:
            return info.context.user
    """

    message = "You must be authenticated to access this resource"

    def has_permission(
        self, _source: Any, info: Info[GraphQLContext, None], **_kwargs: Any
    ) -> bool:
        """Check if user is authenticated.

        Args:
            source: The parent object being resolved
            info: GraphQL execution info with context
            **kwargs: Field arguments

        Returns:
            True if user is authenticated, False otherwise
        """
        is_authed = info.context.user is not None

        if not is_authed:
            logger.warning(
                "Unauthenticated access attempt",
                extra={
                    "field": info.field_name,
                    "parent_type": info.parent_type.name if info.parent_type else None,
                    "operation": info.operation.name if info.operation else "anonymous",
                },
            )

        return is_authed


# ============================================================================
# Role-Based Permissions
# ============================================================================


class IsAdmin(BasePermission):
    """Require user to have admin role.

    Checks if the authenticated user has the "admin" role using the
    existing AuthUser.has_role() method from the auth system.

    Example:
        @strawberry.mutation(permission_classes=[IsAuthenticated, IsAdmin])
        async def delete_all_data(self, info: Info) -> bool:
            # Only admins can do this
            ...
    """

    message = "Administrator access required"

    def has_permission(
        self, _source: Any, info: Info[GraphQLContext, None], **_kwargs: Any
    ) -> bool:
        """Check if user has admin role.

        Args:
            source: The parent object being resolved
            info: GraphQL execution info with context
            **kwargs: Field arguments

        Returns:
            True if user is admin, False otherwise
        """
        user = info.context.user
        if not user:
            return False

        is_admin = user.has_role("admin")

        if not is_admin:
            logger.warning(
                "Non-admin access attempt to admin-only resource",
                extra={
                    "user_id": str(user.id),
                    "field": info.field_name,
                    "operation": info.operation.name if info.operation else "anonymous",
                },
            )

        return is_admin


class HasRole(BasePermission):
    """Require user to have a specific role.

    This is a configurable version of IsAdmin that works with any role.

    Example:
        @strawberry.field(permission_classes=[IsAuthenticated, HasRole("moderator")])
        async def moderation_queue(self, info: Info) -> list[Item]:
            ...
    """

    def __init__(self, role: str):
        """Initialize with required role.

        Args:
            role: The role name to check (e.g., "admin", "moderator", "editor")
        """
        self.role = role
        self.message = f"Role '{role}' required"

    def has_permission(
        self, _source: Any, info: Info[GraphQLContext, None], **_kwargs: Any
    ) -> bool:
        """Check if user has the required role.

        Args:
            source: The parent object being resolved
            info: GraphQL execution info with context
            **kwargs: Field arguments

        Returns:
            True if user has the role, False otherwise
        """
        user = info.context.user
        if not user:
            return False

        has_role = user.has_role(self.role)

        if not has_role:
            logger.warning(
                "Access denied: missing required role",
                extra={
                    "user_id": str(user.id),
                    "required_role": self.role,
                    "field": info.field_name,
                },
            )

        return has_role


# ============================================================================
# Permission-Based Access Control
# ============================================================================


class HasPermission(BasePermission):
    """Require user to have a specific permission.

    Integrates with the existing AuthUser.has_permission() method from the
    auth system. Permissions are more granular than roles (e.g., "reminders:read",
    "reminders:write", "tasks:cancel").

    Example:
        @strawberry.field(permission_classes=[IsAuthenticated, HasPermission("reminders:read")])
        async def reminders(self, info: Info) -> list[ReminderType]:
            ...

        @strawberry.mutation(permission_classes=[IsAuthenticated, HasPermission("reminders:delete")])
        async def delete_reminder(self, info: Info, id: strawberry.ID) -> DeletePayload:
            ...
    """

    def __init__(self, permission: str):
        """Initialize with required permission.

        Args:
            permission: The permission string to check (e.g., "reminders:read", "tasks:trigger")
        """
        self.permission = permission
        self.message = f"Permission '{permission}' required"

    def has_permission(
        self, _source: Any, info: Info[GraphQLContext, None], **_kwargs: Any
    ) -> bool:
        """Check if user has the required permission.

        Args:
            source: The parent object being resolved
            info: GraphQL execution info with context
            **kwargs: Field arguments

        Returns:
            True if user has the permission, False otherwise
        """
        user = info.context.user
        if not user:
            return False

        has_perm = user.has_permission(self.permission)

        if not has_perm:
            logger.warning(
                "Access denied: missing required permission",
                extra={
                    "user_id": str(user.id),
                    "required_permission": self.permission,
                    "field": info.field_name,
                    "operation": info.operation.name if info.operation else "anonymous",
                },
            )

        return has_perm


# ============================================================================
# Resource-Based Access Control
# ============================================================================


class CanAccessResource(BasePermission):
    """Require user to have access to a specific resource.

    Uses the AuthUser.can_access_resource() method for resource-level access
    control, which integrates with the ACL (Access Control List) system.

    Example:
        @strawberry.field(permission_classes=[IsAuthenticated, CanAccessResource("document", "read")])
        async def document(self, info: Info, id: strawberry.ID) -> DocumentType:
            # Additional resource-level check can be done in resolver
            ...
    """

    def __init__(self, resource_type: str, action: str):
        """Initialize with resource type and action.

        Args:
            resource_type: Type of resource (e.g., "document", "reminder", "file")
            action: Action to perform (e.g., "read", "write", "delete")
        """
        self.resource_type = resource_type
        self.action = action
        self.message = f"Cannot {action} {resource_type}"

    def has_permission(self, _source: Any, info: Info[GraphQLContext, None], **kwargs: Any) -> bool:
        """Check if user can access the resource.

        Args:
            source: The parent object being resolved
            info: GraphQL execution info with context
            **kwargs: Field arguments (may include resource_id)

        Returns:
            True if user can access the resource, False otherwise
        """
        user = info.context.user
        if not user:
            return False

        # Extract resource_id from kwargs if available
        resource_id = kwargs.get("id") or kwargs.get("resource_id")

        can_access = user.can_access_resource(
            resource=self.resource_type,
            action=self.action,
        )

        if not can_access:
            logger.warning(
                "Access denied: resource access check failed",
                extra={
                    "user_id": str(user.id),
                    "resource_type": self.resource_type,
                    "action": self.action,
                    "resource_id": str(resource_id) if resource_id else None,
                    "field": info.field_name,
                },
            )

        return can_access


# ============================================================================
# Ownership-Based Permissions
# ============================================================================


class IsOwner(BasePermission):
    """Require user to be the owner of the resource.

    This permission should be used in combination with resolvers that fetch
    the resource and check ownership. It's a common pattern for user-specific
    data like "my reminders", "my profile", etc.

    Example:
        @strawberry.field(permission_classes=[IsAuthenticated, IsOwner])
        async def reminder(self, info: Info, id: strawberry.ID) -> ReminderType | None:
            reminder = await load_reminder(id)
            if reminder.user_id != info.context.user.id:
                return None  # IsOwner permission will already have logged this
            return reminder

    Note: This requires the source object to have an owner_id or user_id attribute.
    For more complex ownership checks, implement a custom permission class.
    """

    message = "You can only access your own resources"

    def has_permission(self, source: Any, info: Info[GraphQLContext, None], **_kwargs: Any) -> bool:
        """Check if user owns the resource.

        Args:
            source: The parent object being resolved (should have user_id or owner_id)
            info: GraphQL execution info with context
            **kwargs: Field arguments

        Returns:
            True if user owns the resource, False otherwise
        """
        user = info.context.user
        if not user:
            return False

        # Try to extract owner/user id from source
        owner_id = None
        if hasattr(source, "user_id"):
            owner_id = source.user_id
        elif hasattr(source, "owner_id"):
            owner_id = source.owner_id
        elif hasattr(source, "created_by"):
            owner_id = source.created_by

        if owner_id is None:
            # Cannot determine ownership from source, deny access
            logger.error(
                "IsOwner permission used but source has no owner/user_id attribute",
                extra={
                    "source_type": type(source).__name__,
                    "field": info.field_name,
                },
            )
            return False

        is_owner = str(user.id) == str(owner_id)

        if not is_owner:
            logger.warning(
                "Access denied: user is not the owner",
                extra={
                    "user_id": str(user.id),
                    "owner_id": str(owner_id),
                    "field": info.field_name,
                },
            )

        return is_owner


# ============================================================================
# Combining Permissions
# ============================================================================

"""
Multiple permissions can be combined in a single field. All permissions must pass.

Example: Admin or owner can access
    # Note: Strawberry evaluates permissions with AND logic by default
    # For OR logic, create a custom permission class:

    class IsAdminOrOwner(BasePermission):
        message = "Must be admin or owner"

        def has_permission(self, source, info, **kwargs):
            return (
                IsAdmin().has_permission(source, info, **kwargs) or
                IsOwner().has_permission(source, info, **kwargs)
            )

    @strawberry.field(permission_classes=[IsAuthenticated, IsAdminOrOwner])
    async def sensitive_field(self, info: Info) -> str:
        ...

Example: Multiple required permissions
    @strawberry.mutation(permission_classes=[
        IsAuthenticated,
        HasPermission("reminders:write"),
        HasRole("verified_user"),
    ])
    async def create_reminder(self, info: Info, input: CreateReminderInput) -> ReminderPayload:
        # User must be authenticated AND have reminders:write permission AND have verified_user role
        ...
"""
