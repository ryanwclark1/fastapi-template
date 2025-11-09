"""Authentication and authorization schemas."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TokenPayload(BaseModel):
    """Decoded token payload from external auth service.

    This represents the data returned from the external auth service
    after validating a token.
    """

    sub: str = Field(description="Subject (user ID or service ID)")
    user_id: str | None = Field(default=None, description="User ID if authenticated as user")
    service_id: str | None = Field(
        default=None, description="Service ID if authenticated as service"
    )
    email: str | None = Field(default=None, description="User email")
    roles: list[str] = Field(default_factory=list, description="User or service roles")
    permissions: list[str] = Field(default_factory=list, description="Granted permissions")
    acl: dict[str, Any] = Field(
        default_factory=dict, description="Access Control List with resource permissions"
    )
    exp: int | None = Field(default=None, description="Token expiration timestamp")
    iat: int | None = Field(default=None, description="Token issued at timestamp")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional user/service metadata"
    )


class AuthUser(BaseModel):
    """Authenticated user or service with permissions.

    This is the model that will be injected into endpoints via
    dependency injection after successful authentication.
    """

    user_id: str | None = Field(default=None, description="User ID")
    service_id: str | None = Field(default=None, description="Service ID")
    email: str | None = Field(default=None, description="User email")
    roles: list[str] = Field(default_factory=list, description="User or service roles")
    permissions: list[str] = Field(default_factory=list, description="Granted permissions")
    acl: dict[str, Any] = Field(
        default_factory=dict, description="Access Control List with resource permissions"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional user/service metadata"
    )

    @property
    def is_user(self) -> bool:
        """Check if authenticated as a user."""
        return self.user_id is not None

    @property
    def is_service(self) -> bool:
        """Check if authenticated as a service."""
        return self.service_id is not None

    @property
    def identifier(self) -> str:
        """Get the primary identifier (user_id or service_id)."""
        return self.user_id or self.service_id or "unknown"

    def has_permission(self, permission: str) -> bool:
        """Check if user/service has a specific permission.

        Args:
            permission: Permission to check.

        Returns:
            True if permission is granted, False otherwise.
        """
        return permission in self.permissions

    def has_role(self, role: str) -> bool:
        """Check if user/service has a specific role.

        Args:
            role: Role to check.

        Returns:
            True if role is assigned, False otherwise.
        """
        return role in self.roles

    def can_access_resource(self, resource: str, action: str) -> bool:
        """Check if user/service can perform action on resource.

        Args:
            resource: Resource identifier (e.g., "users", "posts").
            action: Action to perform (e.g., "read", "write", "delete").

        Returns:
            True if access is allowed, False otherwise.

        Example:
            ```python
            if user.can_access_resource("posts", "delete"):
                # Allow deletion
                pass
            ```
        """
        if resource not in self.acl:
            return False

        resource_acl = self.acl[resource]
        if isinstance(resource_acl, list):
            return action in resource_acl
        elif isinstance(resource_acl, dict):
            return resource_acl.get(action, False)

        return False
