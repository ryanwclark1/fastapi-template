"""Authentication and authorization schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class TokenPayload(BaseModel):
    """Decoded token payload from external auth service.

    This represents the data returned from the external auth service
    after validating a token.
    """

    sub: str = Field(min_length=1, max_length=255, description="Subject (user ID or service ID)")
    user_id: str | None = Field(
        default=None, max_length=255, description="User ID if authenticated as user"
    )
    service_id: str | None = Field(
        default=None, max_length=255, description="Service ID if authenticated as service"
    )
    email: EmailStr | None = Field(default=None, description="User email")
    roles: list[str] = Field(
        default_factory=list, max_length=50, description="User or service roles"
    )
    permissions: list[str] = Field(
        default_factory=list, max_length=200, description="Granted permissions"
    )
    acl: dict[str, list[str] | dict[str, bool]] = Field(
        default_factory=dict,
        description="Access Control List with resource permissions",
    )
    exp: int | None = Field(default=None, ge=0, description="Token expiration timestamp")
    iat: int | None = Field(default=None, ge=0, description="Token issued at timestamp")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional user/service metadata"
    )

    @field_validator("roles", mode="after")
    @classmethod
    def validate_roles(cls, v: list[str]) -> list[str]:
        """Validate role names are not empty."""
        if any(not role.strip() for role in v):
            raise ValueError("Role names cannot be empty or whitespace")
        return v

    @field_validator("permissions", mode="after")
    @classmethod
    def validate_permissions(cls, v: list[str]) -> list[str]:
        """Validate permission names are not empty."""
        if any(not perm.strip() for perm in v):
            raise ValueError("Permission names cannot be empty or whitespace")
        return v

    model_config = ConfigDict(
        str_strip_whitespace=True,
    )


class AuthUser(BaseModel):
    """Authenticated user or service with permissions.

    This is the model that will be injected into endpoints via
    dependency injection after successful authentication.
    """

    user_id: str | None = Field(default=None, max_length=255, description="User ID")
    service_id: str | None = Field(default=None, max_length=255, description="Service ID")
    email: EmailStr | None = Field(default=None, description="User email")
    roles: list[str] = Field(
        default_factory=list, max_length=50, description="User or service roles"
    )
    permissions: list[str] = Field(
        default_factory=list, max_length=200, description="Granted permissions"
    )
    acl: dict[str, list[str] | dict[str, bool]] = Field(
        default_factory=dict,
        description="Access Control List with resource permissions",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional user/service metadata"
    )

    @field_validator("roles", mode="after")
    @classmethod
    def validate_roles(cls, v: list[str]) -> list[str]:
        """Validate role names are not empty."""
        if any(not role.strip() for role in v):
            raise ValueError("Role names cannot be empty or whitespace")
        return v

    @field_validator("permissions", mode="after")
    @classmethod
    def validate_permissions(cls, v: list[str]) -> list[str]:
        """Validate permission names are not empty."""
        if any(not perm.strip() for perm in v):
            raise ValueError("Permission names cannot be empty or whitespace")
        return v

    model_config = ConfigDict(
        str_strip_whitespace=True,
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
        if not permission or not permission.strip():
            return False
        return permission in self.permissions

    def has_role(self, role: str) -> bool:
        """Check if user/service has a specific role.

        Args:
            role: Role to check.

        Returns:
            True if role is assigned, False otherwise.
        """
        if not role or not role.strip():
            return False
        return role in self.roles

    def can_access_resource(self, resource: str, action: str) -> bool:
        """Check if user/service can perform action on resource.

        Args:
            resource: Resource identifier (e.g., "users", "posts").
            action: Action to perform (e.g., "read", "write", "delete").

        Returns:
            True if access is allowed, False otherwise.

        Example:
                    if user.can_access_resource("posts", "delete"):
                # Allow deletion
                pass
        """
        if not resource or not resource.strip() or not action or not action.strip():
            return False

        if resource not in self.acl:
            return False

        resource_acl = self.acl[resource]
        if isinstance(resource_acl, list):
            return action in resource_acl
        elif isinstance(resource_acl, dict):
            return bool(resource_acl.get(action, False))

        return False
