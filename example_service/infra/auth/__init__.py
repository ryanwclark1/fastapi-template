"""Authentication infrastructure for Accent-Auth integration.

This module provides Protocol-based authentication via the accent-auth-client
library with automatic dual-mode routing. The new Protocol-based API provides
consistent interfaces, improved testability, and better type safety.

ARCHITECTURE
============

Protocol-Based Design (PEP 544):
    - AuthClient Protocol defines the contract
    - HttpAuthClient implements external HTTP communication
    - DatabaseAuthClient implements internal database access
    - MockAuthClient for testing (no mocking library needed)

Automatic Mode Detection:
    - get_auth_client() factory automatically chooses implementation
    - SERVICE_NAME == "accent-auth" → DatabaseAuthClient (internal mode)
    - SERVICE_NAME != "accent-auth" → HttpAuthClient (external mode)

USAGE PATTERNS
==============

Recommended (Protocol-Based API):
    ```python
    from example_service.infra.auth import AuthClient
    from example_service.core.dependencies.auth_client import AuthClientDep

    # Via dependency injection (recommended)
    @router.get("/validate")
    async def validate_endpoint(client: AuthClientDep, token: str):
        token_info = await client.validate_token(token)
        return {"user_id": token_info.metadata.uuid}

    # Direct usage (testing)
    from example_service.infra.auth import HttpAuthClient, DatabaseAuthClient

    # External mode
    client = HttpAuthClient(host="auth.example.com", port=443)
    token_info = await client.validate_token("token-uuid")

    # Internal mode
    client = DatabaseAuthClient(session=session, token_service=token_service)
    token_info = await client.validate_token("token-uuid")
    ```

Legacy API (Still Supported):
    ```python
    from example_service.infra.auth import AccentAuthClient, get_accent_auth_client

    async with AccentAuthClient() as client:
        token_info = await client.validate_token(token)
    ```

Data Models (Protocol-Agnostic):
    ```python
    from example_service.infra.auth import (
        AccentAuthToken,      # Token response model
        AccentAuthMetadata,   # Token metadata
        AccentAuthACL,        # ACL helper class
    )

    # ACL pattern matching
    acl = AccentAuthACL(["confd.users.*", "webhookd.#"])
    if acl.has_permission("confd.users.read"):
        print("Access granted")
    ```

Testing with Protocol-Based Test Doubles:
    ```python
    from example_service.infra.auth.testing import MockAuthClient

    # No mocking library needed!
    mock_client = MockAuthClient.admin()  # Full admin access
    app.dependency_overrides[get_auth_client] = lambda: mock_client

    # Or custom permissions
    mock_client = MockAuthClient(
        user_id="user-123",
        permissions=["confd.users.read"],
    )
    ```

CONFIGURATION
=============

External Mode (Template Services - Default):
    ```bash
    # .env file
    SERVICE_NAME=your-service-name  # Will use HTTP mode
    AUTH_SERVICE_URL=https://accent-auth:443
    AUTH_SERVICE_TOKEN=your-service-token
    ```

Internal Mode (Only for accent-auth service):
    ```bash
    # .env file
    SERVICE_NAME=accent-auth  # Will use database mode
    # No AUTH_SERVICE_URL needed
    ```

Installation:
    ```bash
    pip install accent-auth-client
    ```

MIGRATION GUIDE
===============

Old Code:
    ```python
    from example_service.infra.auth import get_accent_auth_client

    async with get_accent_auth_client() as client:
        token_info = await client.validate_token(token)
        user = client.to_auth_user(token_info)
    ```

New Code:
    ```python
    from example_service.core.dependencies.auth_client import AuthClientDep
    from example_service.infra.auth import to_auth_user

    @router.get("/endpoint")
    async def endpoint(client: AuthClientDep):
        token_info = await client.validate_token(token)
        user = to_auth_user(token_info)
    ```

Benefits of Protocol-Based API:
    - No async context manager needed (simpler usage)
    - Protocol-based test doubles (no unittest.mock)
    - Type-safe dependency injection
    - Consistent interface across implementations
    - Easier to extend with new implementations
"""

from __future__ import annotations

# ============================================================================
# Legacy API (backward compatibility)
# ============================================================================
from .accent_auth import (
    ACCENT_AUTH_CLIENT_AVAILABLE,
    AccentAuthClient,
    get_accent_auth_client,
)

# ============================================================================
# Protocol-Based API (recommended)
# ============================================================================
from .db_client import DatabaseAuthClient
from .http_client import (
    HttpAuthClient,
    InvalidTokenException,
    MissingPermissionsTokenException,
)
from .models import AccentAuthACL, AccentAuthMetadata, AccentAuthToken
from .protocols import AuthClient
from .utils import to_auth_user

# Exported symbols kept sorted for Ruff compliance.
__all__ = [
    "ACCENT_AUTH_CLIENT_AVAILABLE",
    "AccentAuthACL",
    "AccentAuthClient",
    "AccentAuthMetadata",
    "AccentAuthToken",
    "AuthClient",
    "DatabaseAuthClient",
    "HttpAuthClient",
    "InvalidTokenException",
    "MissingPermissionsTokenException",
    "get_accent_auth_client",
    "to_auth_user",
]
