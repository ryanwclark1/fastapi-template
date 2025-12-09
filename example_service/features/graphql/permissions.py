"""Permission classes for field-level authorization in GraphQL.

This module provides Strawberry permission classes that integrate with the existing
Accent-Auth ACL system. Permissions can be applied at the field or resolver level
for granular access control using ACL patterns.

ACL Pattern Syntax:
    - service.resource.action (e.g., "confd.users.read")
    - Wildcards: * (single level), # (multi-level/recursive)
    - Negation: ! prefix for explicit deny
    - Reserved words: me (current user), my_session (current session)

Usage:
    @strawberry.field(permission_classes=[IsAuthenticated, HasACL("confd.users.read")])
    async def users(self, info: Info) -> list[UserType]:
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

from example_service.infra.auth.accent_auth import AccentAuthACL

if TYPE_CHECKING:
    from strawberry.types import Info

    from example_service.features.graphql.context import GraphQLContext

logger = logging.getLogger(__name__)

__all__ = [
    "CanAccessResource",
    "HasACL",
    "HasAllACLs",
    "HasAnyACL",
    "IsAuthenticated",
    "IsOwner",
    "IsSuperuser",
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
# ACL-Based Permissions
# ============================================================================


class IsSuperuser(BasePermission):
    """Require user to have superuser access (# ACL pattern).

    Checks if the authenticated user has the "#" ACL which grants
    full recursive access to all resources.

    Example:
        @strawberry.mutation(permission_classes=[IsAuthenticated, IsSuperuser])
        async def delete_all_data(self, info: Info) -> bool:
            # Only superusers can do this
            ...
    """

    message = "Superuser access required"

    def has_permission(
        self, _source: Any, info: Info[GraphQLContext, None], **_kwargs: Any
    ) -> bool:
        """Check if user has superuser ACL (#).

        Args:
            source: The parent object being resolved
            info: GraphQL execution info with context
            **kwargs: Field arguments

        Returns:
            True if user is superuser, False otherwise
        """
        user = info.context.user
        if not user:
            return False

        # Get session ID from metadata if available
        session_id = user.metadata.get("session_uuid") or user.metadata.get("token")

        # Create ACL checker with user context
        acl = AccentAuthACL(
            user.permissions,
            auth_id=user.user_id,
            session_id=session_id,
        )

        is_superuser = acl.is_superuser()

        if not is_superuser:
            logger.warning(
                "Non-superuser access attempt to superuser-only resource",
                extra={
                    "user_id": user.user_id,
                    "field": info.field_name,
                    "operation": info.operation.name if info.operation else "anonymous",
                },
            )

        return is_superuser


class HasACL(BasePermission):
    """Require user to have a specific ACL permission.

    Integrates with the Accent-Auth ACL system using dot-notation patterns.
    Supports wildcards (* for single level, # for recursive) and negation (! prefix).

    Example:
        @strawberry.field(permission_classes=[IsAuthenticated, HasACL("confd.users.read")])
        async def users(self, info: Info) -> list[UserType]:
            ...

        @strawberry.mutation(permission_classes=[IsAuthenticated, HasACL("confd.users.delete")])
        async def delete_user(self, info: Info, id: strawberry.ID) -> DeletePayload:
            ...
    """

    def __init__(self, acl_pattern: str):
        """Initialize with required ACL pattern.

        Args:
            acl_pattern: The ACL pattern to check (e.g., "confd.users.read", "storage.#")
        """
        self.acl_pattern = acl_pattern
        self.message = f"ACL '{acl_pattern}' required"

    def has_permission(
        self, _source: Any, info: Info[GraphQLContext, None], **_kwargs: Any
    ) -> bool:
        """Check if user has the required ACL.

        Args:
            source: The parent object being resolved
            info: GraphQL execution info with context
            **kwargs: Field arguments

        Returns:
            True if user has the ACL, False otherwise
        """
        user = info.context.user
        if not user:
            return False

        # Get session ID from metadata if available
        session_id = user.metadata.get("session_uuid") or user.metadata.get("token")

        # Create ACL checker with user context for reserved word substitution
        acl = AccentAuthACL(
            user.permissions,
            auth_id=user.user_id,
            session_id=session_id,
        )

        has_acl = acl.has_permission(self.acl_pattern)

        if not has_acl:
            logger.warning(
                "Access denied: missing required ACL",
                extra={
                    "user_id": user.user_id,
                    "required_acl": self.acl_pattern,
                    "field": info.field_name,
                    "operation": info.operation.name if info.operation else "anonymous",
                },
            )

        return has_acl


class HasAnyACL(BasePermission):
    """Require user to have any of the specified ACL permissions.

    Uses OR logic - user needs at least one of the ACL patterns.

    Example:
        @strawberry.field(permission_classes=[IsAuthenticated, HasAnyACL("confd.users.read", "confd.users.*")])
        async def users(self, info: Info) -> list[UserType]:
            # Users with either ACL can access
            ...
    """

    def __init__(self, *acl_patterns: str):
        """Initialize with required ACL patterns.

        Args:
            *acl_patterns: One or more ACL patterns (any must match)
        """
        self.acl_patterns = acl_patterns
        self.message = f"One of these ACLs required: {', '.join(acl_patterns)}"

    def has_permission(
        self, _source: Any, info: Info[GraphQLContext, None], **_kwargs: Any
    ) -> bool:
        """Check if user has any of the required ACLs.

        Args:
            source: The parent object being resolved
            info: GraphQL execution info with context
            **kwargs: Field arguments

        Returns:
            True if user has any of the ACLs, False otherwise
        """
        user = info.context.user
        if not user:
            return False

        session_id = user.metadata.get("session_uuid") or user.metadata.get("token")

        acl = AccentAuthACL(
            user.permissions,
            auth_id=user.user_id,
            session_id=session_id,
        )

        has_any = acl.has_any_permission(*self.acl_patterns)

        if not has_any:
            logger.warning(
                "Access denied: missing required ACLs (need any)",
                extra={
                    "user_id": user.user_id,
                    "required_acls": self.acl_patterns,
                    "field": info.field_name,
                },
            )

        return has_any


class HasAllACLs(BasePermission):
    """Require user to have all of the specified ACL permissions.

    Uses AND logic - user needs all of the ACL patterns.

    Example:
        @strawberry.field(permission_classes=[IsAuthenticated, HasAllACLs("confd.users.read", "confd.users.admin")])
        async def admin_users(self, info: Info) -> list[UserType]:
            # Users must have both ACLs to access
            ...
    """

    def __init__(self, *acl_patterns: str):
        """Initialize with required ACL patterns.

        Args:
            *acl_patterns: All required ACL patterns
        """
        self.acl_patterns = acl_patterns
        self.message = f"All of these ACLs required: {', '.join(acl_patterns)}"

    def has_permission(
        self, _source: Any, info: Info[GraphQLContext, None], **_kwargs: Any
    ) -> bool:
        """Check if user has all of the required ACLs.

        Args:
            source: The parent object being resolved
            info: GraphQL execution info with context
            **kwargs: Field arguments

        Returns:
            True if user has all ACLs, False otherwise
        """
        user = info.context.user
        if not user:
            return False

        session_id = user.metadata.get("session_uuid") or user.metadata.get("token")

        acl = AccentAuthACL(
            user.permissions,
            auth_id=user.user_id,
            session_id=session_id,
        )

        has_all = acl.has_all_permissions(*self.acl_patterns)

        if not has_all:
            logger.warning(
                "Access denied: missing required ACLs (need all)",
                extra={
                    "user_id": user.user_id,
                    "required_acls": self.acl_patterns,
                    "field": info.field_name,
                },
            )

        return has_all


# ============================================================================
# Resource-Based Access Control
# ============================================================================


class CanAccessResource(BasePermission):
    """Require user to have ACL access to a specific resource action.

    Constructs an ACL pattern from resource type and action, then checks
    against the user's ACL permissions.

    Example:
        @strawberry.field(permission_classes=[IsAuthenticated, CanAccessResource("document", "read")])
        async def document(self, info: Info, id: strawberry.ID) -> DocumentType:
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
        self.acl_pattern = f"{resource_type}.{action}"
        self.message = f"Cannot {action} {resource_type}"

    def has_permission(self, _source: Any, info: Info[GraphQLContext, None], **_kwargs: Any) -> bool:
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
        resource_id = _kwargs.get("id") or _kwargs.get("resource_id")

        session_id = user.metadata.get("session_uuid") or user.metadata.get("token")

        acl = AccentAuthACL(
            user.permissions,
            auth_id=user.user_id,
            session_id=session_id,
        )

        can_access = acl.has_permission(self.acl_pattern)

        if not can_access:
            logger.warning(
                "Access denied: resource access check failed",
                extra={
                    "user_id": user.user_id,
                    "resource_type": self.resource_type,
                    "action": self.action,
                    "acl_pattern": self.acl_pattern,
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
            if reminder.user_id != info.context.user.user_id:
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

        is_owner = str(user.user_id) == str(owner_id)

        if not is_owner:
            logger.warning(
                "Access denied: user is not the owner",
                extra={
                    "user_id": user.user_id,
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

Example: Superuser or owner can access
    # Note: Strawberry evaluates permissions with AND logic by default
    # For OR logic, create a custom permission class:

    class IsSuperuserOrOwner(BasePermission):
        message = "Must be superuser or owner"

        def has_permission(self, source, info, **kwargs):
            return (
                IsSuperuser().has_permission(source, info, **kwargs) or
                IsOwner().has_permission(source, info, **kwargs)
            )

    @strawberry.field(permission_classes=[IsAuthenticated, IsSuperuserOrOwner])
    async def sensitive_field(self, info: Info) -> str:
        ...

Example: Multiple required ACLs
    @strawberry.mutation(permission_classes=[
        IsAuthenticated,
        HasACL("confd.users.write"),
        HasACL("confd.users.admin"),
    ])
    async def create_admin_user(self, info: Info, input: CreateAdminInput) -> UserPayload:
        # User must be authenticated AND have both ACL patterns
        ...

Example: Any of multiple ACLs
    @strawberry.field(permission_classes=[
        IsAuthenticated,
        HasAnyACL("confd.users.read", "confd.admin.#"),
    ])
    async def users(self, info: Info) -> list[UserType]:
        # User must be authenticated AND have at least one of the ACL patterns
        ...
"""
