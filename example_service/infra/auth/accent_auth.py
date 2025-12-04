"""Accent-Auth integration for authentication and authorization.

This module provides integration with the Accent-Auth service via the
official accent-auth-client library. It supports:
- Token validation and retrieval
- ACL-based authorization with dot-notation
- Multi-tenant support via Accent-Tenant header
- Session management

Requirements:
    pip install accent-auth-client

    Or add to pyproject.toml:
    [project.dependencies]
    accent-auth-client = "..."
"""

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from example_service.core.acl import get_cached_access_check
from example_service.core.schemas.auth import AuthUser
from example_service.core.settings import get_auth_settings

if TYPE_CHECKING:
    from types import TracebackType

logger = logging.getLogger(__name__)

# Import the accent-auth-client library (required)
try:
    from accent_auth_client import Client as AccentAuthClientLib  # type: ignore[import-not-found]
    from accent_auth_client.exceptions import (  # type: ignore[import-not-found]
        InvalidTokenException,
        MissingPermissionsTokenException,
    )
    from accent_auth_client.types import TokenDict  # type: ignore[import-not-found]

    ACCENT_AUTH_CLIENT_AVAILABLE = True
    logger.debug("accent-auth-client library loaded")
except ImportError:
    ACCENT_AUTH_CLIENT_AVAILABLE = False
    AccentAuthClientLib = None
    InvalidTokenException = Exception
    MissingPermissionsTokenException = Exception
    TokenDict = dict
    logger.warning(
        "accent-auth-client library not installed. "
        "Install with: pip install accent-auth-client"
    )


class AccentAuthMetadata(BaseModel):
    """Accent-Auth token metadata."""

    uuid: str = Field(description="User UUID")
    tenant_uuid: str = Field(description="Tenant UUID")
    auth_id: str | None = Field(default=None, description="Auth backend ID")
    pbx_user_uuid: str | None = Field(default=None, description="PBX user UUID")
    accent_uuid: str | None = Field(default=None, description="Accent UUID")


class AccentAuthToken(BaseModel):
    """Accent-Auth token response model."""

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
        """Create from accent-auth-client TokenDict."""
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


class AccentAuthClient:
    """Async wrapper for Accent-Auth client.

    This client wraps the official accent-auth-client library to provide
    async support for FastAPI applications.

    Example:
        async with AccentAuthClient() as client:
            token_info = await client.validate_token(token)
            has_access = await client.check_token(token, "confd.users.read")
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        https: bool = True,
        verify_certificate: bool = True,
        timeout: float = 5.0,
        token: str | None = None,
    ):
        """Initialize Accent-Auth client.

        Args:
            host: Accent-Auth service hostname (default from settings)
            port: Accent-Auth service port (default 443 for https, 80 for http)
            https: Use HTTPS (default True)
            verify_certificate: Verify SSL certificate (default True)
            timeout: Request timeout in seconds
            token: Service token for authentication

        Raises:
            RuntimeError: If accent-auth-client is not installed
        """
        if not ACCENT_AUTH_CLIENT_AVAILABLE:
            raise RuntimeError(
                "accent-auth-client library is required but not installed. "
                "Install with: pip install accent-auth-client"
            )

        settings = get_auth_settings()

        # Parse host/port from settings if not provided
        if host is None and settings.service_url:
            from urllib.parse import urlparse

            parsed = urlparse(str(settings.service_url))
            host = parsed.hostname or "localhost"
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            https = parsed.scheme == "https"

        self.host = host or "localhost"
        self.port = port or (443 if https else 80)
        self.https = https
        self.verify_certificate = verify_certificate
        self.timeout = timeout
        self.token = token or (
            settings.service_token.get_secret_value() if settings.service_token else None
        )

        self._client: Any = None

        logger.info(
            "Accent-Auth client initialized",
            extra={
                "host": self.host,
                "port": self.port,
                "https": self.https,
            },
        )

    async def __aenter__(self) -> AccentAuthClient:
        """Async context manager entry."""
        self._client = AccentAuthClientLib(
            host=self.host,
            port=self.port,
            https=self.https,
            verify_certificate=self.verify_certificate,
            timeout=self.timeout,
            token=self.token,
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Async context manager exit."""
        # accent-auth-client doesn't require explicit cleanup
        pass

    @property
    def base_url(self) -> str:
        """Get the base URL for the Accent-Auth service."""
        protocol = "https" if self.https else "http"
        return f"{protocol}://{self.host}:{self.port}"

    async def validate_token(
        self,
        token: str,
        tenant_uuid: str | None = None,
        required_acl: str | None = None,
    ) -> AccentAuthToken:
        """Validate token and retrieve full token information.

        Args:
            token: Bearer token to validate
            tenant_uuid: Optional tenant UUID for validation
            required_acl: Optional ACL to check during validation

        Returns:
            Token information with ACLs and metadata

        Raises:
            InvalidTokenException: If token is invalid
            MissingPermissionsTokenException: If token lacks required ACL
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with' context manager.")

        # Use official client in thread pool (it's synchronous)
        token_dict = await asyncio.to_thread(
            self._client.token.get,
            token,
            required_acl,
            tenant_uuid,
        )
        token_info = AccentAuthToken.from_token_dict(token_dict)

        logger.info(
            "Token validated successfully",
            extra={
                "user_uuid": token_info.metadata.uuid,
                "tenant_uuid": token_info.metadata.tenant_uuid,
                "acl_count": len(token_info.acl),
            },
        )

        return token_info

    async def check_token(
        self,
        token: str,
        required_acl: str | None = None,
        tenant_uuid: str | None = None,
    ) -> bool:
        """Check if token is valid (lightweight HEAD request).

        Args:
            token: Bearer token to check
            required_acl: Optional ACL to check
            tenant_uuid: Optional tenant UUID

        Returns:
            True if token is valid (and has required ACL if specified)

        Raises:
            InvalidTokenException: If token is invalid
            MissingPermissionsTokenException: If token lacks required ACL
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with' context manager.")

        return await asyncio.to_thread(
            self._client.token.check,
            token,
            required_acl,
            tenant_uuid,
        )

    async def is_token_valid(
        self,
        token: str,
        required_acl: str | None = None,
        tenant_uuid: str | None = None,
    ) -> bool:
        """Check if token is valid without raising exceptions.

        Args:
            token: Bearer token to check
            required_acl: Optional ACL to check
            tenant_uuid: Optional tenant UUID

        Returns:
            True if token is valid, False otherwise
        """
        if not self._client:
            return False

        return await asyncio.to_thread(
            self._client.token.is_valid,
            token,
            required_acl,
            tenant_uuid,
        )

    async def revoke_token(self, token: str) -> None:
        """Revoke a token.

        Args:
            token: Token to revoke
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with' context manager.")

        await asyncio.to_thread(self._client.token.revoke, token)

    def to_auth_user(self, token_info: AccentAuthToken) -> AuthUser:
        """Convert Accent-Auth token to AuthUser model.

        Args:
            token_info: Accent-Auth token information

        Returns:
            AuthUser model for use in FastAPI dependencies
        """
        return AuthUser(
            user_id=token_info.metadata.uuid,
            service_id=None,
            email=None,
            roles=[],
            permissions=token_info.acl,
            acl={},  # ACL dict built from permissions in can_access_resource
            metadata={
                "tenant_uuid": token_info.metadata.tenant_uuid,
                "auth_id": token_info.metadata.auth_id or token_info.auth_id,
                "session_uuid": token_info.session_uuid,
                "token": token_info.token,
                "expires_at": token_info.expires_at,
                "accent_uuid": token_info.accent_uuid,
            },
        )


@lru_cache(maxsize=1)
def get_accent_auth_client() -> AccentAuthClient:
    """Get configured Accent-Auth client instance.

    Returns:
        Configured AccentAuthClient

    Raises:
        ValueError: If AUTH_SERVICE_URL is not configured
        RuntimeError: If accent-auth-client is not installed
    """
    if not ACCENT_AUTH_CLIENT_AVAILABLE:
        raise RuntimeError(
            "accent-auth-client library is required but not installed. "
            "Install with: pip install accent-auth-client"
        )

    settings = get_auth_settings()

    if not settings.service_url:
        raise ValueError(
            "AUTH_SERVICE_URL must be configured for Accent-Auth. "
            "Set AUTH_SERVICE_URL environment variable or configure in settings."
        )

    return AccentAuthClient()


class AccentAuthACL:
    """Helper class for working with Accent-Auth ACL patterns.

    Accent-Auth uses dot-notation ACLs with wildcard support:
    - service.resource.action (e.g., "confd.users.read")
    - Wildcards: * (single level), # (multi-level)
    - Negation: ! prefix (e.g., "!confd.users.delete")
    - Reserved: me, my_session (dynamic substitution)

    This class delegates to the core ACL module which provides:
    - Full regex-based pattern matching
    - LRU caching at multiple levels for performance
    - Proper reserved word substitution

    Example:
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
    """

    def __init__(
        self,
        acls: list[str],
        auth_id: str | None = None,
        session_id: str | None = None,
    ):
        """Initialize with list of ACL patterns.

        Args:
            acls: List of ACL patterns
            auth_id: User auth ID for 'me' reserved word substitution
            session_id: Session ID for 'my_session' reserved word substitution
        """
        self.acls = acls
        self.auth_id = auth_id
        self.session_id = session_id

        # Use the full ACL implementation with caching
        self._checker = get_cached_access_check(
            auth_id=auth_id,
            session_id=session_id,
            acl=acls,
        )

    def has_permission(self, required: str) -> bool:
        """Check if ACL grants permission.

        Args:
            required: Required permission (e.g., "confd.users.read")

        Returns:
            True if permission is granted
        """
        return self._checker.matches_required_access(required)

    def has_any_permission(self, *required: str) -> bool:
        """Check if ACL grants any of the specified permissions.

        Args:
            *required: Required permissions to check

        Returns:
            True if any permission is granted
        """
        return any(self.has_permission(r) for r in required)

    def has_all_permissions(self, *required: str) -> bool:
        """Check if ACL grants all of the specified permissions.

        Args:
            *required: Required permissions to check

        Returns:
            True if all permissions are granted
        """
        return all(self.has_permission(r) for r in required)

    def is_superuser(self) -> bool:
        """Check if ACL grants superuser access (# wildcard).

        Returns:
            True if user has # ACL
        """
        return self.has_permission("#")
