"""Accent-Auth integration for authentication and authorization.

This module provides integration with the Accent-Auth service, supporting:
- Token validation via accent-auth API
- ACL-based authorization with dot-notation
- Multi-tenant support via Accent-Tenant header
- Session management
- Policy-based access control
"""

from __future__ import annotations

import logging

import httpx
from pydantic import BaseModel, Field

from example_service.core.schemas.auth import AuthUser
from example_service.core.settings import get_auth_settings
from example_service.utils.retry import retry

logger = logging.getLogger(__name__)


class AccentAuthMetadata(BaseModel):
    """Accent-Auth token metadata."""

    uuid: str = Field(description="User UUID")
    tenant_uuid: str = Field(description="Tenant UUID")
    auth_id: str | None = Field(default=None, description="Auth backend ID")
    pbx_user_uuid: str | None = Field(default=None, description="PBX user UUID")


class AccentAuthToken(BaseModel):
    """Accent-Auth token response model."""

    token: str = Field(description="Token value")
    auth_id: str = Field(description="Authentication ID")
    accent_uuid: str | None = Field(default=None, description="Accent UUID")
    issued_at: str = Field(description="Token issue timestamp")
    expires_at: str = Field(description="Token expiration timestamp")
    utc_issued_at: str = Field(description="UTC issue timestamp")
    utc_expires_at: str = Field(description="UTC expiration timestamp")
    metadata: AccentAuthMetadata = Field(description="Token metadata")
    acls: list[str] = Field(default_factory=list, description="Access Control List")


class AccentAuthSession(BaseModel):
    """Accent-Auth session information."""

    uuid: str = Field(description="Session UUID")
    tenant_uuid: str = Field(description="Tenant UUID")
    mobile: bool = Field(default=False, description="Mobile session flag")


class AccentAuthClient:
    """Client for Accent-Auth API integration.

    This client provides methods for:
    - Token validation (HEAD, GET, check)
    - ACL verification
    - Session management
    - Multi-tenant context handling

    Example:
        client = AccentAuthClient(base_url="http://accent-auth:9497")
        token_info = await client.validate_token(token)
        has_access = await client.check_acl(token, "confd.users.read")
    """

    def __init__(
        self,
        base_url: str,
        timeout: float = 5.0,
        max_retries: int = 3,
    ):
        """Initialize Accent-Auth client.

        Args:
            base_url: Base URL of accent-auth service
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._client: httpx.AsyncClient | None = None

        logger.info(
            "Accent-Auth client initialized",
            extra={"base_url": base_url, "timeout": timeout},
        )

    async def __aenter__(self):
        """Async context manager entry."""
        self._client = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self._client:
            await self._client.aclose()

    def _get_client(self) -> httpx.AsyncClient:
        """Get HTTP client instance."""
        if not self._client:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    @retry(
        max_attempts=3,
        initial_delay=0.5,
        max_delay=5.0,
        retry_if=lambda e: isinstance(e, (httpx.TimeoutException, httpx.NetworkError)),
    )
    async def validate_token_simple(
        self,
        token: str,
        tenant_uuid: str | None = None,
    ) -> bool:
        """Validate token using HEAD request (simple validation).

        Args:
            token: Bearer token to validate
            tenant_uuid: Optional tenant UUID for validation

        Returns:
            True if token is valid, False otherwise
        """
        headers = {"X-Auth-Token": token}
        if tenant_uuid:
            headers["Accent-Tenant"] = tenant_uuid

        client = self._get_client()
        response = await client.head(
            f"{self.base_url}/api/auth/0.1/token/{token}",
            headers=headers,
        )

        is_valid = response.status_code == 204
        logger.debug(
            f"Token validation (simple): {'valid' if is_valid else 'invalid'}",
            extra={"status_code": response.status_code},
        )

        return is_valid

    @retry(
        max_attempts=3,
        initial_delay=0.5,
        max_delay=5.0,
        retry_if=lambda e: isinstance(e, (httpx.TimeoutException, httpx.NetworkError)),
    )
    async def validate_token(
        self,
        token: str,
        tenant_uuid: str | None = None,
        scopes: list[str] | None = None,
    ) -> AccentAuthToken:
        """Validate token and retrieve full token information.

        Args:
            token: Bearer token to validate
            tenant_uuid: Optional tenant UUID for validation
            scopes: Optional ACL scopes to check

        Returns:
            Token information with ACLs and metadata

        Raises:
            httpx.HTTPStatusError: If token is invalid or lacks required ACLs
        """
        headers = {"X-Auth-Token": token}
        if tenant_uuid:
            headers["Accent-Tenant"] = tenant_uuid

        # Build URL with scopes if provided
        url = f"{self.base_url}/api/auth/0.1/token/{token}"
        # Use scopes parameter for ACL checking if provided
        params = {"scope": scopes} if scopes else {}

        client = self._get_client()
        response = await client.get(url, headers=headers, params=params)

        if response.status_code == 404:
            logger.warning("Token not found or invalid")
            raise httpx.HTTPStatusError(
                "Token not found",
                request=response.request,
                response=response,
            )

        if response.status_code == 403:
            logger.warning(
                "Token lacks required ACLs",
                extra={"required_scopes": scopes},
            )
            raise httpx.HTTPStatusError(
                "Insufficient permissions",
                request=response.request,
                response=response,
            )

        response.raise_for_status()

        data = response.json()
        token_info = AccentAuthToken(**data["data"])

        logger.info(
            "Token validated successfully",
            extra={
                "user_uuid": token_info.metadata.uuid,
                "tenant_uuid": token_info.metadata.tenant_uuid,
                "acl_count": len(token_info.acls),
            },
        )

        return token_info

    async def check_acl(
        self,
        token: str,
        required_acl: str,
        tenant_uuid: str | None = None,
    ) -> bool:
        """Check if token has specific ACL permission.

        Args:
            token: Bearer token
            required_acl: Required ACL (e.g., "confd.users.read")
            tenant_uuid: Optional tenant UUID

        Returns:
            True if ACL is granted, False otherwise
        """
        try:
            await self.validate_token(token, tenant_uuid, scopes=[required_acl])
            return True
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                return False
            raise

    async def check_multiple_acls(
        self,
        token: str,
        required_acls: list[str],
        tenant_uuid: str | None = None,
    ) -> bool:
        """Check if token has all required ACLs.

        Args:
            token: Bearer token
            required_acls: List of required ACLs
            tenant_uuid: Optional tenant UUID

        Returns:
            True if all ACLs are granted, False otherwise
        """
        try:
            await self.validate_token(token, tenant_uuid, scopes=required_acls)
            return True
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                return False
            raise

    def to_auth_user(self, token_info: AccentAuthToken) -> AuthUser:
        """Convert Accent-Auth token to AuthUser model.

        Args:
            token_info: Accent-Auth token information

        Returns:
            AuthUser model for use in FastAPI dependencies
        """
        # Convert ACL list to structured permissions
        # Accent uses dot-notation: service.resource.action
        permissions = token_info.acls

        # Build ACL dict grouped by resource
        acl_dict: dict[str, list[str]] = {}
        for permission in permissions:
            parts = permission.split(".")
            if len(parts) >= 2:
                resource = ".".join(parts[:-1])  # e.g., "confd.users"
                action = parts[-1]  # e.g., "read"

                if resource not in acl_dict:
                    acl_dict[resource] = []
                acl_dict[resource].append(action)

        return AuthUser(
            user_id=token_info.metadata.uuid,
            service_id=None,  # Accent-Auth doesn't use service_id
            email=None,  # Not provided in token info
            roles=[],  # Accent uses ACLs, not roles
            permissions=permissions,
            acl=acl_dict,
            metadata={
                "tenant_uuid": token_info.metadata.tenant_uuid,
                "auth_id": token_info.metadata.auth_id,
                "token": token_info.token,
                "expires_at": token_info.expires_at,
            },
        )


def get_accent_auth_client() -> AccentAuthClient:
    """Get configured Accent-Auth client instance.

    Returns:
        Configured AccentAuthClient
    """
    settings = get_auth_settings()

    if not settings.service_url:
        raise ValueError("AUTH_SERVICE_URL must be configured for Accent-Auth")

    return AccentAuthClient(
        base_url=str(settings.service_url),
        timeout=settings.request_timeout,
        max_retries=settings.max_retries,
    )


class AccentAuthACL:
    """Helper class for working with Accent-Auth ACL patterns.

    Accent-Auth uses dot-notation ACLs with wildcard support:
    - service.resource.action (e.g., "confd.users.read")
    - Wildcards: * (single level), # (multi-level)
    - Negation: ! prefix (e.g., "!confd.users.delete")
    - Reserved: me, my_session (dynamic substitution)

    Example:
        acl = AccentAuthACL(["confd.users.*", "webhookd.#"])
        acl.has_permission("confd.users.read")  # True
        acl.has_permission("confd.users.delete")  # True
        acl.has_permission("webhookd.subscriptions.read")  # True
    """

    def __init__(self, acls: list[str]):
        """Initialize with list of ACL patterns.

        Args:
            acls: List of ACL patterns
        """
        self.acls = acls
        self.positive_acls = [acl for acl in acls if not acl.startswith("!")]
        self.negative_acls = [acl[1:] for acl in acls if acl.startswith("!")]

    def has_permission(self, required: str) -> bool:
        """Check if ACL grants permission.

        Args:
            required: Required permission (e.g., "confd.users.read")

        Returns:
            True if permission is granted
        """
        # Check negative ACLs first (explicit deny)
        for negative_pattern in self.negative_acls:
            if self._matches_pattern(required, negative_pattern):
                return False

        # Check positive ACLs
        for positive_pattern in self.positive_acls:
            if self._matches_pattern(required, positive_pattern):
                return True

        return False

    def _matches_pattern(self, permission: str, pattern: str) -> bool:
        """Check if permission matches ACL pattern.

        Args:
            permission: Permission to check
            pattern: ACL pattern with wildcards

        Returns:
            True if matches
        """
        # Exact match
        if permission == pattern:
            return True

        # Multi-level wildcard (#)
        if "#" in pattern:
            prefix = pattern.split("#")[0]
            if permission.startswith(prefix):
                return True

        # Single-level wildcard (*)
        if "*" in pattern:
            perm_parts = permission.split(".")
            pattern_parts = pattern.split(".")

            if len(perm_parts) != len(pattern_parts):
                return False

            for perm_part, pattern_part in zip(perm_parts, pattern_parts, strict=False):
                if pattern_part != "*" and perm_part != pattern_part:
                    return False

            return True

        return False
