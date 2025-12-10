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
from collections.abc import Awaitable, Callable
from functools import lru_cache
import logging
from typing import TYPE_CHECKING, Any

import httpx
from pydantic import BaseModel, Field, model_validator

from example_service.core.acl import get_cached_access_check
from example_service.core.schemas.auth import AuthUser
from example_service.core.settings import get_auth_settings

if TYPE_CHECKING:
    from types import TracebackType

logger = logging.getLogger(__name__)

# Import the accent-auth-client library (required)
try:
    from accent_auth_client import (
        Client as AccentAuthClientLib,  # type: ignore[import-not-found]
    )
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
    acls: list[str] = Field(default_factory=list, description="Access Control List")
    user_agent: str | None = Field(default=None, description="User agent")
    remote_addr: str | None = Field(default=None, description="Remote address")

    @model_validator(mode="before")
    @classmethod
    def _coerce_acl(cls, data: Any) -> Any:
        """Allow payloads that use either 'acl' or 'acls' keys."""
        if isinstance(data, dict):
            acl = data.get("acl")
            acls = data.get("acls")
            if acl and not acls:
                data["acls"] = acl
            elif acls is None:
                data.setdefault("acls", [])
        return data

    @property
    def acl(self) -> list[str]:
        """Backward compatible alias used by legacy code."""
        return list(self.acls)

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
            acls=data.get("acls") or data.get("acl", []),
            user_agent=data.get("user_agent"),
            remote_addr=data.get("remote_addr"),
        )


class AccentAuthClient:
    """Async wrapper for Accent-Auth client.

    Provides an HTTP-based integration that mirrors the accent-auth-client
    features but works in environments where the official package is not
    installed. Requests are performed with httpx and include:
    - Token validation (HEAD/GET)
    - ACL checks
    - Token revocation
    - Optional retry and timeout handling
    """

    def __init__(
        self,
        base_url: str | None = None,
        host: str | None = None,
        port: int | None = None,
        https: bool = True,
        verify_certificate: bool = True,
        timeout: float | None = None,
        token: str | None = None,
        max_retries: int | None = None,
    ):
        """Initialize Accent-Auth client.

        Args:
            base_url: Full Accent-Auth base URL.
            host: Optional host when base_url not provided.
            port: Optional port when constructing base_url from host.
            https: Whether to use HTTPS when base_url not provided.
            verify_certificate: Verify SSL certificates for requests.
            timeout: Request timeout in seconds (defaults to auth settings).
            token: Optional service token for service-to-service requests.
            max_retries: Number of retry attempts for transient errors.
        """
        settings = get_auth_settings()

        if base_url is None and host is None and settings.service_url:
            base_url = str(settings.service_url)

        if base_url is None and host is not None:
            protocol = "https" if https else "http"
            resolved_port = port or (443 if https else 80)
            base_url = f"{protocol}://{host}:{resolved_port}"

        if base_url is None:
            msg = "AUTH_SERVICE_URL must be configured or base_url provided."
            raise ValueError(msg)

        self.base_url = str(base_url).rstrip("/")
        self.verify_certificate = verify_certificate
        self.timeout = timeout if timeout is not None else settings.request_timeout
        self.max_retries = max_retries if max_retries is not None else settings.max_retries
        self.token = token or (
            settings.service_token.get_secret_value() if settings.service_token else None
        )
        self._token_endpoint = settings.token_validation_endpoint or "/api/auth/0.1/token"
        self._token_header = settings.token_header or "X-Auth-Token"
        self._token_scheme = settings.token_scheme.strip() if settings.token_scheme else ""
        self._client: httpx.AsyncClient | None = None

        logger.info(
            "Accent-Auth client initialized",
            extra={
                "base_url": self.base_url,
                "timeout": self.timeout,
                "max_retries": self.max_retries,
            },
        )

    async def __aenter__(self) -> AccentAuthClient:
        """Async context manager entry."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Async context manager exit."""
        await self.close()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _create_client(self) -> httpx.AsyncClient:
        """Create a configured AsyncClient instance."""
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout),
            verify=self.verify_certificate,
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
            ),
            headers={"User-Agent": "example-service/AccentAuthClient"},
        )

    def _get_client(self) -> httpx.AsyncClient:
        """Return a shared AsyncClient (lazily instantiated)."""
        if self._client is None:
            self._client = self._create_client()
        return self._client

    @property
    def base_url(self) -> str:
        """Get the base URL for the Accent-Auth service."""
        return self._base_url

    @base_url.setter
    def base_url(self, value: str) -> None:
        self._base_url = value

    def build_headers(
        self,
        token: str | None = None,
        tenant_uuid: str | None = None,
    ) -> dict[str, str]:
        """Public helper to build Accent-Auth request headers."""
        return self._build_headers(token=token, tenant_uuid=tenant_uuid)

    def _build_headers(
        self,
        token: str | None = None,
        tenant_uuid: str | None = None,
    ) -> dict[str, str]:
        headers: dict[str, str] = {}
        header_token = token or self.token
        if header_token:
            if self._token_scheme:
                headers[self._token_header] = f"{self._token_scheme} {header_token}"
            else:
                headers[self._token_header] = header_token
        if tenant_uuid:
            headers["Accent-Tenant"] = tenant_uuid
        return headers

    async def _send_with_retries(
        self,
        method: str,
        path: str,
        sender: Callable[[], Awaitable[httpx.Response]],
    ) -> httpx.Response:
        """Perform HTTP request with retry handling."""
        last_error: Exception | None = None
        for attempt in range(max(1, self.max_retries + 1)):
            try:
                return await sender()
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning(
                    "Accent-Auth request failed, retrying",
                    extra={
                        "method": method,
                        "path": path,
                        "attempt": attempt + 1,
                        "max_retries": self.max_retries,
                    },
                )
                if attempt >= self.max_retries:
                    raise
                await asyncio.sleep(min(0.1 * (2**attempt), 1.5))
        assert last_error is not None
        raise last_error

    async def head(
        self,
        path: str,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Expose HEAD request for health checks."""
        client = self._get_client()

        async def _call() -> httpx.Response:
            return await client.head(path, headers=headers)

        return await self._send_with_retries("HEAD", path, _call)

    async def validate_token_simple(
        self,
        token: str,
        tenant_uuid: str | None = None,
        required_acl: str | None = None,
    ) -> bool:
        """Perform lightweight HEAD request to verify token validity."""
        headers = self._build_headers(token=token, tenant_uuid=tenant_uuid)
        params = {"acl": required_acl} if required_acl else None
        client = self._get_client()

        async def _call() -> httpx.Response:
            return await client.head(self._token_endpoint, headers=headers, params=params)

        response = await self._send_with_retries("HEAD", self._token_endpoint, _call)

        if response.status_code in {200, 202, 204}:
            return True
        if response.status_code in {401, 403, 404}:
            return False

        response.raise_for_status()
        return False

    async def validate_token(
        self,
        token: str,
        tenant_uuid: str | None = None,
        required_acl: str | None = None,
    ) -> AccentAuthToken:
        """Validate token and retrieve metadata via GET request."""
        headers = self._build_headers(token=token, tenant_uuid=tenant_uuid)
        params = {"acl": required_acl} if required_acl else None
        client = self._get_client()

        async def _call() -> httpx.Response:
            return await client.get(self._token_endpoint, headers=headers, params=params)

        response = await self._send_with_retries("GET", self._token_endpoint, _call)

        if response.status_code == 403:
            msg = "Token missing required ACL"
            raise MissingPermissionsTokenException(msg)
        if response.status_code in {401, 404}:
            msg = "Token invalid or not found"
            raise InvalidTokenException(msg)

        response.raise_for_status()

        payload = response.json()
        token_payload = payload.get("data", payload)
        token_payload.setdefault("token", token)

        token_info = AccentAuthToken.from_token_dict(token_payload)

        logger.info(
            "Token validated successfully",
            extra={
                "user_uuid": token_info.metadata.uuid,
                "tenant_uuid": token_info.metadata.tenant_uuid,
                "acl_count": len(token_info.acls),
            },
        )

        return token_info

    async def check_token(
        self,
        token: str,
        required_acl: str | None = None,
        tenant_uuid: str | None = None,
    ) -> bool:
        """Compatibility wrapper for validate_token_simple."""
        return await self.validate_token_simple(
            token=token,
            required_acl=required_acl,
            tenant_uuid=tenant_uuid,
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
        try:
            return await self.validate_token_simple(
                token=token,
                required_acl=required_acl,
                tenant_uuid=tenant_uuid,
            )
        except httpx.HTTPError:
            logger.exception("Token validation failed due to HTTP error")
            return False

    async def revoke_token(self, token: str) -> None:
        """Revoke a token.

        Args:
            token: Token to revoke
        """
        path = f"{self._token_endpoint.rstrip('/')}/{token}"
        headers = self._build_headers()
        client = self._get_client()

        async def _call() -> httpx.Response:
            return await client.delete(path, headers=headers)

        response = await self._send_with_retries("DELETE", path, _call)
        if response.is_error:
            response.raise_for_status()

    async def check_acl(
        self,
        token: str,
        required_acl: str,
        tenant_uuid: str | None = None,
    ) -> bool:
        """Return True if token includes the required ACL."""
        try:
            await self.validate_token(
                token=token,
                tenant_uuid=tenant_uuid,
                required_acl=required_acl,
            )
        except MissingPermissionsTokenException:
            return False
        except InvalidTokenException:
            return False
        return True

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
            permissions=token_info.acls,
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
    settings = get_auth_settings()

    if not settings.service_url:
        msg = (
            "AUTH_SERVICE_URL must be configured for Accent-Auth. "
            "Set AUTH_SERVICE_URL environment variable or configure in settings."
        )
        raise ValueError(
            msg
        )

    if not ACCENT_AUTH_CLIENT_AVAILABLE:
        logger.info(
            "accent-auth-client not installed, falling back to HTTP implementation",
        )

    return AccentAuthClient(base_url=str(settings.service_url))


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

        # With tenant context (enables 'my_tenant' substitution)
        acl = AccentAuthACL(
            ["storage.my_tenant.#", "confd.my_tenant.users.read"],
            auth_id="user-123",
            session_id="sess-456",
            tenant_id="tenant-789",
        )
        acl.has_permission("storage.tenant-789.buckets.list")  # True
        acl.has_permission("confd.tenant-789.users.read")  # True
    """

    def __init__(
        self,
        acls: list[str],
        auth_id: str | None = None,
        session_id: str | None = None,
        tenant_id: str | None = None,
    ):
        """Initialize with list of ACL patterns.

        Args:
            acls: List of ACL patterns
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
