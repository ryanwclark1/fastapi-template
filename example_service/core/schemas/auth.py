"""Authentication and authorization schemas.

This module provides schemas for authentication tokens and authorized users
using the Accent-Auth ACL system.

ACL Pattern Syntax:
    - service.resource.action (e.g., "confd.users.read")
    - Wildcards: * (single level), # (multi-level/recursive)
    - Negation: ! prefix for explicit deny
    - Reserved words: me (current user), my_session (current session)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

if TYPE_CHECKING:
    from example_service.infra.auth.accent_auth import AccentAuthACL


class TokenPayload(BaseModel):
    """Decoded token payload from external auth service.

    This represents the data returned from the external auth service
    after validating a token.
    """

    sub: str = Field(
        min_length=1, max_length=255, description="Subject (user ID or service ID)"
    )
    user_id: str | None = Field(
        default=None, max_length=255, description="User ID if authenticated as user"
    )
    service_id: str | None = Field(
        default=None,
        max_length=255,
        description="Service ID if authenticated as service",
    )
    email: EmailStr | None = Field(default=None, description="User email")
    permissions: list[str] = Field(
        default_factory=list,
        max_length=200,
        description="ACL patterns granted to user (e.g., 'confd.users.read')",
    )
    acl: dict[str, list[str] | dict[str, bool]] = Field(
        default_factory=dict,
        description="Legacy ACL dict - prefer using permissions list with ACL patterns",
    )
    exp: int | None = Field(
        default=None, ge=0, description="Token expiration timestamp"
    )
    iat: int | None = Field(default=None, ge=0, description="Token issued at timestamp")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional user/service metadata"
    )

    @field_validator("permissions", mode="after")
    @classmethod
    def validate_permissions(cls, v: list[str]) -> list[str]:
        """Validate permission/ACL patterns are not empty."""
        if any(not perm.strip() for perm in v):
            msg = "ACL patterns cannot be empty or whitespace"
            raise ValueError(msg)
        return v

    model_config = ConfigDict(
        str_strip_whitespace=True,
    )


class AuthUser(BaseModel):
    """Authenticated user or service with ACL permissions.

    This is the model that will be injected into endpoints via
    dependency injection after successful authentication.

    The permissions field contains ACL patterns in dot-notation format
    that are checked using the Accent-Auth ACL engine.
    """

    user_id: str | None = Field(default=None, max_length=255, description="User ID")
    service_id: str | None = Field(
        default=None, max_length=255, description="Service ID"
    )
    email: EmailStr | None = Field(default=None, description="User email")
    permissions: list[str] = Field(
        default_factory=list,
        max_length=200,
        description="ACL patterns granted to user (e.g., 'confd.users.read', 'storage.#')",
    )
    acl: dict[str, list[str] | dict[str, bool]] = Field(
        default_factory=dict,
        description="Legacy ACL dict - prefer using permissions list with ACL patterns",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional user/service metadata"
    )

    @field_validator("permissions", mode="after")
    @classmethod
    def validate_permissions(cls, v: list[str]) -> list[str]:
        """Validate ACL patterns are not empty."""
        if any(not perm.strip() for perm in v):
            msg = "ACL patterns cannot be empty or whitespace"
            raise ValueError(msg)
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

    @property
    def tenant_id(self) -> str | None:
        """Get tenant UUID from metadata.

        This is a convenience property that extracts tenant_uuid from metadata.
        For Accent-Auth integrations, this comes from the JWT token payload.

        Returns:
            Tenant UUID if available, None otherwise.

        """
        return self.metadata.get("tenant_uuid")

    @property
    def tenant_uuid(self) -> str | None:
        """Alias for tenant_id for consistency with Accent-Auth naming.

        Returns:
            Tenant UUID if available, None otherwise.

        """
        return self.tenant_id

    @property
    def session_id(self) -> str | None:
        """Get session UUID from metadata.

        For Accent-Auth, this is the session_uuid from the JWT token.

        Returns:
            Session UUID if available, None otherwise.

        """
        return self.metadata.get("session_uuid")

    def _get_acl_checker(self) -> AccentAuthACL:
        """Get an ACL checker instance for this user.

        Returns:
            AccentAuthACL instance configured with user's permissions and context.
        """
        from example_service.infra.auth.accent_auth import AccentAuthACL

        return AccentAuthACL(
            self.permissions,
            auth_id=self.user_id,
            session_id=self.session_id,
        )

    def has_acl(self, acl_pattern: str) -> bool:
        """Check if user has a specific ACL permission.

        Uses Accent-Auth ACL pattern matching with support for:
        - Dot-notation patterns (e.g., "confd.users.read")
        - Wildcards (* for single level, # for recursive)
        - Negation (! prefix for explicit deny)
        - Reserved word substitution (me, my_session)

        Args:
            acl_pattern: ACL pattern to check (e.g., "confd.users.read", "storage.#")

        Returns:
            True if ACL is granted, False otherwise.

        Example:
            if user.has_acl("confd.users.read"):
                # User can read users
                pass
        """
        if not acl_pattern or not acl_pattern.strip():
            return False
        return self._get_acl_checker().has_permission(acl_pattern)

    def has_any_acl(self, *acl_patterns: str) -> bool:
        """Check if user has any of the specified ACL permissions.

        Args:
            *acl_patterns: ACL patterns to check (any must match)

        Returns:
            True if any ACL is granted, False otherwise.

        Example:
            if user.has_any_acl("confd.users.read", "confd.admin.#"):
                # User can read users or is admin
                pass
        """
        if not acl_patterns:
            return False
        return self._get_acl_checker().has_any_permission(*acl_patterns)

    def has_all_acls(self, *acl_patterns: str) -> bool:
        """Check if user has all of the specified ACL permissions.

        Args:
            *acl_patterns: ACL patterns to check (all must match)

        Returns:
            True if all ACLs are granted, False otherwise.

        Example:
            if user.has_all_acls("confd.users.read", "confd.users.write"):
                # User can read and write users
                pass
        """
        if not acl_patterns:
            return False
        return self._get_acl_checker().has_all_permissions(*acl_patterns)

    def is_superuser(self) -> bool:
        """Check if user has superuser access (# ACL pattern).

        Returns:
            True if user has full recursive access, False otherwise.

        Example:
            if user.is_superuser():
                # User has full system access
                pass
        """
        return self._get_acl_checker().is_superuser()

    # Legacy method aliases for backward compatibility
    def has_permission(self, permission: str) -> bool:
        """Check if user has a specific ACL permission.

        This is an alias for has_acl() maintained for backward compatibility.

        Args:
            permission: ACL pattern to check.

        Returns:
            True if ACL is granted, False otherwise.
        """
        return self.has_acl(permission)

    def can_access_resource(self, resource: str, action: str) -> bool:
        """Check if user can perform action on resource using ACL.

        Constructs an ACL pattern from resource and action, then checks
        against user's permissions.

        Args:
            resource: Resource identifier (e.g., "users", "storage").
            action: Action to perform (e.g., "read", "write", "delete").

        Returns:
            True if access is allowed, False otherwise.

        Example:
            if user.can_access_resource("users", "delete"):
                # User can delete users
                pass
        """
        if not resource or not resource.strip() or not action or not action.strip():
            return False
        acl_pattern = f"{resource}.{action}"
        return self.has_acl(acl_pattern)
