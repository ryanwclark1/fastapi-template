"""Accent-Auth data models and ACL helpers.

This module contains Protocol-agnostic data structures used across all
authentication implementations (HttpAuthClient, DatabaseAuthClient, MockAuthClient).

By extracting these models from the concrete client implementations, we:
- Enable reuse across different AuthClient implementations
- Provide a stable data contract independent of transport mechanism
- Simplify testing with well-defined data structures
- Support both HTTP API responses and database model conversions

Key Models:
    - AccentAuthMetadata: User and tenant identification metadata
    - AccentAuthToken: Complete token information with timestamps and ACLs
    - AccentAuthACL: Helper class for ACL pattern matching and validation

Pattern: Shared data models (similar to messaging events, storage metadata)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from example_service.core.acl import get_cached_access_check

if TYPE_CHECKING:
    # Token model only needed for from_token_model() conversion (internal mode)
    try:
        from accent_auth.features.tokens.models import Token
    except ImportError:
        Token = None  # type: ignore[misc,assignment]


class AccentAuthMetadata(BaseModel):
    """Accent-Auth token metadata.

    Contains user and tenant identification information extracted from
    the authentication token. This metadata is consistent across both
    HTTP API responses and database model conversions.

    Attributes:
        uuid: User UUID (primary user identifier)
        tenant_uuid: Tenant UUID (for multi-tenant isolation)
        auth_id: Authentication backend ID (optional)
        pbx_user_uuid: PBX-specific user UUID (optional, legacy)
        accent_uuid: Accent platform UUID (optional)
    """

    uuid: str = Field(description="User UUID")
    tenant_uuid: str = Field(description="Tenant UUID")
    auth_id: str | None = Field(default=None, description="Auth backend ID")
    pbx_user_uuid: str | None = Field(default=None, description="PBX user UUID")
    accent_uuid: str | None = Field(default=None, description="Accent UUID")


class AccentAuthToken(BaseModel):
    """Accent-Auth token response model.

    Represents a validated authentication token with complete metadata,
    ACL permissions, and timing information. This model is used consistently
    across all AuthClient implementations.

    Supports two conversion paths:
    1. from_token_dict() - Convert from HTTP API response (external mode)
    2. from_token_model() - Convert from database model (internal mode)

    Attributes:
        token: Token value (UUID string)
        auth_id: Authentication backend identifier
        session_uuid: Session identifier (optional)
        accent_uuid: Accent platform identifier (optional)
        issued_at: Token issue timestamp (ISO format)
        expires_at: Token expiration timestamp (ISO format)
        utc_issued_at: UTC issue timestamp (ISO format)
        utc_expires_at: UTC expiration timestamp (ISO format)
        metadata: User and tenant metadata
        acl: Access Control List (permission patterns)
        user_agent: Client user agent string (optional)
        remote_addr: Client IP address (optional)
    """

    token: str = Field(description="Token value")
    auth_id: str = Field(description="Authentication ID")
    session_uuid: str | None = Field(default=None, description="Session UUID")
    accent_uuid: str | None = Field(default=None, description="Accent UUID")
    issued_at: str = Field(description="Token issue timestamp")
    expires_at: str = Field(description="Token expiration timestamp")
    utc_issued_at: str = Field(description="UTC issue timestamp")
    utc_expires_at: str = Field(description="UTC expiration timestamp")
    metadata: AccentAuthMetadata = Field(description="Token metadata")
    acl: list[str] = Field(default_factory=list, description="Access Control List")
    user_agent: str | None = Field(default=None, description="User agent")
    remote_addr: str | None = Field(default=None, description="Remote address")

    @classmethod
    def from_token_dict(cls, data: dict[str, Any]) -> AccentAuthToken:
        """Create from accent-auth-client TokenDict.

        Used by HttpAuthClient (external mode) to convert HTTP API responses
        from the accent-auth-client library into our internal data model.

        Args:
            data: Token dictionary from accent-auth-client API

        Returns:
            AccentAuthToken instance

        Raises:
            ValueError: If required fields are missing from token dict

        Example:
            # Response from accent-auth HTTP API
            token_dict = {
                "token": "abc-123",
                "auth_id": "user-456",
                "metadata": {"uuid": "user-456", "tenant_uuid": "tenant-789"},
                "acl": ["confd.users.read"],
                ...
            }
            token_info = AccentAuthToken.from_token_dict(token_dict)
        """
        # Validate required fields
        required_fields = ["token", "auth_id"]
        missing = [f for f in required_fields if not data.get(f)]
        if missing:
            msg = f"Token dict missing required fields: {missing}"
            raise ValueError(msg)

        metadata = AccentAuthMetadata(
            uuid=data.get("metadata", {}).get("uuid", ""),
            tenant_uuid=data.get("metadata", {}).get("tenant_uuid", ""),
            auth_id=data.get("metadata", {}).get("auth_id"),
            pbx_user_uuid=data.get("metadata", {}).get("pbx_user_uuid"),
            accent_uuid=data.get("metadata", {}).get("accent_uuid"),
        )
        return cls(
            token=data.get("token", ""),
            auth_id=data.get("auth_id", ""),
            session_uuid=data.get("session_uuid"),
            accent_uuid=data.get("accent_uuid"),
            issued_at=data.get("issued_at", ""),
            expires_at=data.get("expires_at", ""),
            utc_issued_at=data.get("utc_issued_at", ""),
            utc_expires_at=data.get("utc_expires_at", ""),
            metadata=metadata,
            acl=data.get("acl", []),
            user_agent=data.get("user_agent"),
            remote_addr=data.get("remote_addr"),
        )

    @classmethod
    def from_token_model(cls, token: Token) -> AccentAuthToken:
        """Create from internal Token model (for internal usage).

        Used by DatabaseAuthClient (internal mode) to convert database
        Token models into our internal data model. This enables the
        accent-auth service to validate tokens via direct database access
        instead of circular HTTP calls.

        Args:
            token: Internal Token database model

        Returns:
            AccentAuthToken with data from Token model

        Example:
            # Database Token model from TokenRepository
            db_token = await token_repo.get(session, token_uuid)
            token_info = AccentAuthToken.from_token_model(db_token)
        """
        metadata = AccentAuthMetadata(
            uuid=token.metadata_.get("uuid", token.auth_id) if token.metadata_ else token.auth_id,
            tenant_uuid=token.metadata_.get("tenant_uuid", "")
            if token.metadata_
            else "",
            auth_id=token.auth_id,
            pbx_user_uuid=token.pbx_user_uuid,
            accent_uuid=token.metadata_.get("accent_uuid") if token.metadata_ else None,
        )

        # Convert timestamps to ISO format
        issued_at_str = (
            token.utc_issued_at.isoformat()
            if token.utc_issued_at
            else datetime.fromtimestamp(token.issued_t, tz=UTC).isoformat()
            if token.issued_t
            else ""
        )
        expires_at_str = (
            token.utc_expires_at.isoformat()
            if token.utc_expires_at
            else datetime.fromtimestamp(token.expire_t, tz=UTC).isoformat()
            if token.expire_t
            else ""
        )

        return cls(
            token=token.uuid,
            auth_id=token.auth_id,
            session_uuid=token.session_uuid,
            accent_uuid=token.metadata_.get("accent_uuid") if token.metadata_ else None,
            issued_at=issued_at_str,
            expires_at=expires_at_str,
            utc_issued_at=issued_at_str,
            utc_expires_at=expires_at_str,
            metadata=metadata,
            acl=token.acl or [],
            user_agent=token.metadata_.get("user_agent") if token.metadata_ else None,
            remote_addr=token.metadata_.get("remote_addr") if token.metadata_ else None,
        )


class AccentAuthACL:
    """Helper class for working with Accent-Auth ACL patterns.

    Accent-Auth uses dot-notation ACLs with wildcard support:
    - service.resource.action (e.g., "confd.users.read")
    - Wildcards: * (single level), # (multi-level)
    - Negation: ! prefix (e.g., "!confd.users.delete")
    - Reserved: me, my_session, my_tenant (dynamic substitution)

    This class delegates to the core ACL module which provides:
    - Full regex-based pattern matching
    - LRU caching at multiple levels for performance
    - Proper reserved word substitution

    The ACL checker supports dynamic substitution of reserved words:
    - 'me' → user's auth_id (for user-specific permissions)
    - 'my_session' → user's session_id (for session-specific permissions)
    - 'my_tenant' → user's tenant_id (for tenant-specific permissions)

    Example:
        # Basic ACL checking
        acl = AccentAuthACL(["confd.users.*", "webhookd.#"])
        acl.has_permission("confd.users.read")  # True
        acl.has_permission("confd.users.delete")  # True
        acl.has_permission("webhookd.subscriptions.read")  # True

        # With user context (enables 'me' and 'my_session' substitution)
        acl = AccentAuthACL(
            ["users.me.read", "sessions.my_session.delete"],
            auth_id="user-123",
            session_id="sess-456",
        )
        acl.has_permission("users.user-123.read")  # True

        # With tenant context (enables 'my_tenant' substitution)
        acl = AccentAuthACL(
            ["storage.my_tenant.#", "confd.my_tenant.users.read"],
            auth_id="user-123",
            session_id="sess-456",
            tenant_id="tenant-789",
        )
        acl.has_permission("storage.tenant-789.buckets.list")  # True
        acl.has_permission("confd.tenant-789.users.read")  # True

        # Checking multiple permissions
        acl.has_any_permission("confd.users.read", "confd.users.write")  # True
        acl.has_all_permissions("confd.users.read", "webhookd.#")  # True
        acl.is_superuser()  # False (no # wildcard)
    """

    def __init__(
        self,
        acls: list[str],
        auth_id: str | None = None,
        session_id: str | None = None,
        tenant_id: str | None = None,
    ) -> None:
        """Initialize with list of ACL patterns.

        Args:
            acls: List of ACL patterns (e.g., ["confd.users.*", "webhookd.#"])
            auth_id: User auth ID for 'me' reserved word substitution
            session_id: Session ID for 'my_session' reserved word substitution
            tenant_id: Tenant ID for 'my_tenant' reserved word substitution
        """
        self.acls = acls
        self.auth_id = auth_id
        self.session_id = session_id
        self.tenant_id = tenant_id

        # Use the full ACL implementation with caching
        self._checker = get_cached_access_check(
            auth_id=auth_id,
            session_id=session_id,
            acl=acls,
            tenant_id=tenant_id,
        )

    def has_permission(self, required: str) -> bool:
        """Check if ACL grants permission.

        Args:
            required: Required permission (e.g., "confd.users.read")

        Returns:
            True if permission is granted

        Example:
            acl = AccentAuthACL(["confd.users.*"])
            acl.has_permission("confd.users.read")  # True
            acl.has_permission("confd.users.delete")  # True
            acl.has_permission("webhookd.subscriptions.read")  # False
        """
        return self._checker.matches_required_access(required)

    def has_any_permission(self, *required: str) -> bool:
        """Check if ACL grants any of the specified permissions.

        Args:
            *required: Required permissions to check

        Returns:
            True if any permission is granted

        Example:
            acl = AccentAuthACL(["confd.users.read"])
            acl.has_any_permission("confd.users.read", "confd.users.write")  # True
            acl.has_any_permission("webhookd.#", "dird.#")  # False
        """
        return any(self.has_permission(r) for r in required)

    def has_all_permissions(self, *required: str) -> bool:
        """Check if ACL grants all of the specified permissions.

        Args:
            *required: Required permissions to check

        Returns:
            True if all permissions are granted

        Example:
            acl = AccentAuthACL(["confd.users.*", "webhookd.#"])
            acl.has_all_permissions("confd.users.read", "webhookd.subscriptions.read")  # True
            acl.has_all_permissions("confd.users.read", "dird.contacts.read")  # False
        """
        return all(self.has_permission(r) for r in required)

    def is_superuser(self) -> bool:
        """Check if ACL grants superuser access (# wildcard).

        The # wildcard grants access to all resources and actions.
        This is typically reserved for system administrators.

        Returns:
            True if user has # ACL

        Example:
            admin_acl = AccentAuthACL(["#"])
            admin_acl.is_superuser()  # True

            user_acl = AccentAuthACL(["confd.users.read"])
            user_acl.is_superuser()  # False
        """
        return self.has_permission("#")


__all__ = [
    "AccentAuthACL",
    "AccentAuthMetadata",
    "AccentAuthToken",
]
