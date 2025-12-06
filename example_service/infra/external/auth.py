"""Auth service client for accent-auth API.

Provides methods for authentication, user management, and authorization.
"""

from __future__ import annotations

import logging
from typing import Any

from .base_client import BaseHTTPClient

logger = logging.getLogger(__name__)


class AuthClient(BaseHTTPClient):
    """Client for accent-auth service.

    Handles authentication, token management, and user operations.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 9497,
        token: str | None = None,
        tenant: str | None = None,
        https: bool = True,
        verify_certificate: bool = True,
        timeout: float = 30.0,
        retries: int = 3,
    ) -> None:
        """Initialize auth client.

        Args:
            host: Auth service hostname.
            port: Auth service port.
            token: Optional authentication token.
            tenant: Optional tenant UUID.
            https: Use HTTPS protocol.
            verify_certificate: Verify SSL certificates.
            timeout: Request timeout in seconds.
            retries: Number of retry attempts.
        """
        protocol = "https" if https else "http"
        base_url = f"{protocol}://{host}:{port}"
        headers = {}
        if token:
            headers["X-Auth-Token"] = token
        if tenant:
            headers["Accent-Tenant"] = tenant
        super().__init__(base_url=base_url, timeout=timeout, max_retries=retries, headers=headers)
        self._token = token
        self._tenant = tenant
        self._verify_certificate = verify_certificate
        self.token = token
        self.tenant_uuid = tenant

    def set_token(self, token: str) -> None:
        """Set authentication token for requests."""
        self._token = token
        self.token = token
        self.client.headers["X-Auth-Token"] = token

    async def is_healthy(self) -> bool:
        """Check if auth service is healthy."""
        try:
            await self.get("/0.1/status")
            return True
        except Exception:
            return False

    async def get_token_info(self, token: str | None = None) -> dict[str, Any]:
        """Get information about a token."""
        check_token = token or self._token
        headers = {"X-Auth-Token": check_token} if check_token else {}
        return await self.get("/0.1/token", headers=headers)

    async def create_token(
        self,
        username: str,
        password: str,
        expiration: int = 3600,
    ) -> dict[str, Any]:
        """Create a new authentication token."""
        return await self.post(
            "/0.1/token",
            json={
                "username": username,
                "password": password,
                "expiration": expiration,
            },
        )

    async def revoke_token(self, token: str) -> None:
        """Revoke an authentication token."""
        await self.delete(f"/0.1/token/{token}")

    async def list_users(
        self,
        tenant_uuid: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List users."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        headers = {}
        if tenant_uuid:
            headers["Accent-Tenant"] = tenant_uuid
        return await self.get("/0.1/users", params=params, headers=headers)

    async def get_user(self, user_uuid: str) -> dict[str, Any]:
        """Get a specific user."""
        return await self.get(f"/0.1/users/{user_uuid}")

    async def create_user(self, user_data: dict[str, Any]) -> dict[str, Any]:
        """Create a new user."""
        return await self.post("/0.1/users", json=user_data)

    async def update_user(
        self,
        user_uuid: str,
        user_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Update an existing user."""
        return await self.put(f"/0.1/users/{user_uuid}", json=user_data)

    async def delete_user(self, user_uuid: str) -> None:
        """Delete a user."""
        await self.delete(f"/0.1/users/{user_uuid}")

    async def list_tenants(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List tenants."""
        return await self.get(
            "/0.1/tenants",
            params={"limit": limit, "offset": offset},
        )

    async def get_tenant(self, tenant_uuid: str) -> dict[str, Any]:
        """Get a specific tenant."""
        return await self.get(f"/0.1/tenants/{tenant_uuid}")

    async def list_policies(
        self,
        tenant_uuid: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List policies."""
        headers = {}
        if tenant_uuid:
            headers["Accent-Tenant"] = tenant_uuid
        return await self.get(
            "/0.1/policies",
            params={"limit": limit, "offset": offset},
            headers=headers,
        )

    async def list_groups(
        self,
        tenant_uuid: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List groups."""
        headers = {}
        if tenant_uuid:
            headers["Accent-Tenant"] = tenant_uuid
        return await self.get(
            "/0.1/groups",
            params={"limit": limit, "offset": offset},
            headers=headers,
        )

    async def check_health(self) -> dict[str, Any]:
        """Check auth service health."""
        return await self.get("/0.1/status")


__all__ = ["AuthClient"]
