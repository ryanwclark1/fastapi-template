# Using accent-auth-client Library

This guide explains how the `accent-auth-client` library integrates with the authentication system and when to use the full library for advanced operations.

## Overview

The `accent-auth-client` library is the official Python client for Accent-Auth. Our integration uses it for:

1. **Token Validation**: All token operations use `accent-auth-client`
2. **Advanced Operations**: User/group/policy management through the full library

## Library Requirement

The `accent-auth-client` library is **required** for the Accent-Auth integration:

```python
from accent_auth_client import Client as AccentAuthClientLib
from accent_auth_client.exceptions import InvalidTokenException, MissingPermissionsTokenException
from accent_auth_client.types import TokenDict
```

### Async Wrapper

Since `accent-auth-client` is synchronous, we wrap it with `asyncio.to_thread`:

```python
async def validate_token(self, token: str, tenant_uuid: str | None = None) -> AccentAuthToken:
    # Use official client in thread pool (it's synchronous)
    token_dict = await asyncio.to_thread(
        self._client.token.get,
        token,
        required_acl,
        tenant_uuid,
    )
    return AccentAuthToken.from_token_dict(token_dict)
```

### Verifying Installation

```python
from example_service.infra.auth.accent_auth import ACCENT_AUTH_CLIENT_AVAILABLE

if not ACCENT_AUTH_CLIENT_AVAILABLE:
    raise RuntimeError("accent-auth-client is required. Install with: pip install accent-auth-client")
```

---

## Installation

### Option 1: Install from Local Path (Development)

```toml
# pyproject.toml
[tool.uv.sources]
accent-auth-client = { path = "../accent-voice/library/accent-auth-client", editable = true }

[project]
dependencies = [
    "accent-auth-client",
]
```

### Option 2: Install from Git Repository

```toml
# pyproject.toml
[project]
dependencies = [
    "accent-auth-client @ git+https://github.com/your-org/accent-voice.git#subdirectory=library/accent-auth-client",
]
```

### Option 3: Optional Dependency

```toml
# pyproject.toml
[project.optional-dependencies]
accent-auth = ["accent-auth-client"]
```

Then install with:
```bash
uv pip install -e ".[accent-auth]"
```

---

## When to Use the Full Library

### ✅ Use the Library Directly When You Need:

1. **User Management**
   - Creating/updating/deleting users
   - Changing passwords
   - Managing user policies

2. **Group Management**
   - Creating user groups
   - Adding/removing users from groups
   - Group policy assignment

3. **Policy Management**
   - Creating/updating policies
   - Assigning policies to users/groups
   - Policy ACL management

4. **Advanced Auth Features**
   - Multi-factor authentication (MFA)
   - SAML SSO configuration
   - LDAP integration
   - OAuth2 providers
   - WebAuthn/Passkeys

5. **Tenant Administration**
   - Creating child tenants
   - Managing tenant domains
   - Tenant-level policies

### ❌ Don't Use the Library Directly For:

1. **Request Authentication** - Use our FastAPI dependencies (optimized, cached)
2. **Token Validation** - Use our `AccentAuthClient` wrapper (async, cached)
3. **ACL Checking** - Use our `AccentAuthACL` class (local, fast, cached)

---

## Usage Examples

### Setup: Admin Client Dependency

Create a dependency for administrative operations:

```python
# example_service/core/dependencies/accent_admin.py
"""FastAPI dependency for accent-auth-client admin operations."""

from typing import Annotated, AsyncIterator
from contextlib import asynccontextmanager
import asyncio

from fastapi import Depends

try:
    from accent_auth_client import Client as AccentAuthLibClient
    ADMIN_CLIENT_AVAILABLE = True
except ImportError:
    AccentAuthLibClient = None
    ADMIN_CLIENT_AVAILABLE = False

from example_service.core.settings import get_auth_settings


class AccentAdminClient:
    """Async wrapper for accent-auth-client admin operations."""

    def __init__(self, client: "AccentAuthLibClient"):
        self._client = client

    async def list_users(self, tenant_uuid: str, limit: int = 50, offset: int = 0):
        """List users in a tenant."""
        return await asyncio.to_thread(
            self._client.users.list,
            tenant_uuid=tenant_uuid,
            limit=limit,
            offset=offset,
        )

    async def create_user(self, **user_data):
        """Create a new user."""
        return await asyncio.to_thread(
            self._client.users.new,
            **user_data,
        )

    async def get_user(self, user_uuid: str):
        """Get user details."""
        return await asyncio.to_thread(
            self._client.users.get,
            user_uuid,
        )

    async def delete_user(self, user_uuid: str):
        """Delete a user."""
        return await asyncio.to_thread(
            self._client.users.delete,
            user_uuid,
        )

    async def change_password(self, user_uuid: str, new_password: str):
        """Change user's password."""
        return await asyncio.to_thread(
            self._client.users.set_password,
            user_uuid,
            new_password,
        )

    async def add_policy(self, user_uuid: str, policy_uuid: str):
        """Add policy to user."""
        return await asyncio.to_thread(
            self._client.users.add_policy,
            user_uuid,
            policy_uuid,
        )


@asynccontextmanager
async def get_admin_client() -> AsyncIterator[AccentAdminClient]:
    """Provide accent-auth admin client as async context manager.

    Use this for user/group/policy management operations.
    Do NOT use for request authentication - use FastAPI dependencies instead.

    Raises:
        RuntimeError: If accent-auth-client is not installed
    """
    if not ADMIN_CLIENT_AVAILABLE:
        raise RuntimeError(
            "accent-auth-client not installed. "
            "Install with: pip install accent-auth-client"
        )

    settings = get_auth_settings()

    # Parse URL for client initialization
    from urllib.parse import urlparse
    parsed = urlparse(str(settings.service_url))

    client = AccentAuthLibClient(
        host=parsed.hostname or "localhost",
        port=parsed.port or (443 if parsed.scheme == "https" else 80),
        https=parsed.scheme == "https",
        token=settings.service_token.get_secret_value() if settings.service_token else None,
    )

    yield AccentAdminClient(client)
```

### Example: User Management Endpoints

```python
# example_service/features/admin/users.py
"""User management endpoints using accent-auth-client."""

from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from example_service.core.dependencies.accent_auth import require_acl
from example_service.core.dependencies.accent_admin import get_admin_client, AccentAdminClient
from example_service.core.schemas.auth import AuthUser

router = APIRouter(prefix="/admin/users", tags=["admin", "users"])


class UserCreate(BaseModel):
    """User creation schema."""
    username: str
    email: str
    firstname: str | None = None
    lastname: str | None = None
    password: str


class UserUpdate(BaseModel):
    """User update schema."""
    firstname: str | None = None
    lastname: str | None = None
    email: str | None = None


@router.get("/")
async def list_users(
    current_user: Annotated[AuthUser, Depends(require_acl("admin.users.read"))],
    limit: int = 50,
    offset: int = 0,
):
    """List all users in tenant.

    Requires: admin.users.read ACL
    """
    tenant_uuid = current_user.metadata.get("tenant_uuid")

    async with get_admin_client() as client:
        users = await client.list_users(
            tenant_uuid=tenant_uuid,
            limit=limit,
            offset=offset,
        )

    return users


@router.post("/")
async def create_user(
    user_data: UserCreate,
    current_user: Annotated[AuthUser, Depends(require_acl("admin.users.create"))],
):
    """Create a new user via accent-auth.

    Requires: admin.users.create ACL
    """
    async with get_admin_client() as client:
        new_user = await client.create_user(
            username=user_data.username,
            email=user_data.email,
            firstname=user_data.firstname,
            lastname=user_data.lastname,
            password=user_data.password,
            tenant_uuid=current_user.metadata.get("tenant_uuid"),
        )

    return new_user


@router.get("/{user_uuid}")
async def get_user(
    user_uuid: str,
    current_user: Annotated[AuthUser, Depends(require_acl("admin.users.read"))],
):
    """Get user details.

    Requires: admin.users.read ACL
    """
    async with get_admin_client() as client:
        try:
            user = await client.get_user(user_uuid)
            return user
        except Exception as e:
            if "404" in str(e) or "not found" in str(e).lower():
                raise HTTPException(404, "User not found")
            raise


@router.delete("/{user_uuid}")
async def delete_user(
    user_uuid: str,
    current_user: Annotated[AuthUser, Depends(require_acl("admin.users.delete"))],
):
    """Delete a user.

    Requires: admin.users.delete ACL
    """
    async with get_admin_client() as client:
        try:
            await client.delete_user(user_uuid)
            return {"deleted": True, "user_uuid": user_uuid}
        except Exception as e:
            if "404" in str(e) or "not found" in str(e).lower():
                raise HTTPException(404, "User not found")
            raise


@router.put("/{user_uuid}/password")
async def change_user_password(
    user_uuid: str,
    new_password: str,
    current_user: Annotated[AuthUser, Depends(require_acl("admin.users.password"))],
):
    """Change user password.

    Requires: admin.users.password ACL
    """
    async with get_admin_client() as client:
        await client.change_password(user_uuid, new_password)

    return {"changed": True}


@router.post("/{user_uuid}/policies/{policy_uuid}")
async def add_user_policy(
    user_uuid: str,
    policy_uuid: str,
    current_user: Annotated[AuthUser, Depends(require_acl("admin.users.policies"))],
):
    """Add policy to user.

    Requires: admin.users.policies ACL
    """
    async with get_admin_client() as client:
        await client.add_policy(user_uuid, policy_uuid)

    return {"added": True}
```

---

## Architecture: Hybrid Approach

Our architecture uses a hybrid approach for optimal performance:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         FastAPI Application                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Request Authentication (Fast, Optimized)                                    │
│  ├── core/dependencies/accent_auth.py                                        │
│  │   ├── get_current_user         → Uses AccentAuthClient                    │
│  │   ├── require_acl              → Uses AccentAuthACL                       │
│  │   └── Token caching            → Redis (5 min TTL)                        │
│  │                                                                           │
│  ├── infra/auth/accent_auth.py                                               │
│  │   ├── AccentAuthClient         → Async wrapper                            │
│  │   │   └── Uses accent-auth-client (required)                              │
│  │   └── AccentAuthACL            → Local ACL matching                       │
│  │       └── Uses core/acl/ (LRU cached)                                     │
│  │                                                                           │
│  └── Performance: <5ms cached, 50-200ms uncached                             │
│                                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Administrative Operations (Full Library)                                    │
│  ├── core/dependencies/accent_admin.py                                       │
│  │   └── AccentAdminClient        → Async wrapper for admin ops              │
│  │                                                                           │
│  ├── Direct accent-auth-client usage                                         │
│  │   ├── users.new(), users.list(), users.delete()                           │
│  │   ├── groups.new(), groups.add_user()                                     │
│  │   ├── policies.new(), policies.list()                                     │
│  │   └── Advanced: MFA, SAML, LDAP, OAuth                                    │
│  │                                                                           │
│  └── Performance: 50-200ms per operation (no caching)                        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Performance Comparison

| Operation | Our Custom Client | Direct Library | Recommendation |
|-----------|------------------|----------------|----------------|
| Token validation | 5ms (cached) | 50-200ms | Use Custom |
| ACL check | <1ms (local) | 50-200ms | Use Custom |
| User CRUD | N/A | 50-200ms | Use Library |
| Group management | N/A | 50-200ms | Use Library |
| Policy management | N/A | 50-200ms | Use Library |

**Key Insight**: Our custom client is **10-20x faster** for authentication because it:
- Uses async/await natively (or wraps sync with to_thread)
- Caches token validation in Redis
- Evaluates ACLs locally with LRU caching
- Is optimized for FastAPI dependency injection

The library should be used for **administrative operations** that happen less frequently.

---

## Best Practices

### 1. Use Service Token for Admin Operations

```python
# In settings
AUTH_SERVICE_TOKEN=your-admin-service-token

# In admin client
client = AccentAuthLibClient(
    host=settings.service_url.host,
    token=settings.service_token,  # Admin token
)
```

### 2. Don't Mix Auth Methods

```python
# ❌ Don't do this - using library for validation
@router.get("/users")
async def list_users(token: str):
    async with get_admin_client() as client:
        # Using library for token validation (slow!)
        await asyncio.to_thread(client._client.token.check, token)
        ...

# ✅ Do this - use our dependencies for auth
@router.get("/users")
async def list_users(
    # Fast: Use our custom dependency
    user: Annotated[AuthUser, Depends(require_acl("admin.users.read"))],
):
    # Use library only for admin operations
    async with get_admin_client() as client:
        users = await client.list_users(user.metadata.get("tenant_uuid"))
```

### 3. Handle Library Exceptions

```python
from accent_auth_client.exceptions import (
    InvalidTokenException,
    MissingPermissionsTokenException,
)

try:
    user = await client.get_user(user_uuid)
except InvalidTokenException:
    raise HTTPException(401, "Invalid token")
except MissingPermissionsTokenException:
    raise HTTPException(403, "Insufficient permissions")
except Exception as e:
    if "404" in str(e):
        raise HTTPException(404, "User not found")
    raise
```

### 4. Always Pass Tenant Context

```python
# Always pass tenant context when using library
tenant_uuid = current_user.metadata.get("tenant_uuid")

users = await client.list_users(tenant_uuid=tenant_uuid)
groups = await client.list_groups(tenant_uuid=tenant_uuid)
```

---

## Testing

### Unit Test with Mocked Client

```python
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

@pytest.mark.asyncio
async def test_list_users():
    """Test listing users with mocked admin client."""
    mock_users = [{"uuid": "user-1", "username": "test"}]

    with patch("example_service.core.dependencies.accent_admin.AccentAuthLibClient") as mock:
        mock.return_value.users.list.return_value = mock_users

        async with get_admin_client() as client:
            users = await client.list_users("tenant-123")

        assert users == mock_users
```

### Integration Test

```python
import pytest

@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_and_delete_user():
    """Test full user lifecycle."""
    async with get_admin_client() as client:
        # Create user
        user = await client.create_user(
            username="test-user",
            email="test@example.com",
            password="secure-password",
            tenant_uuid="test-tenant",
        )

        assert user["username"] == "test-user"

        # Clean up
        await client.delete_user(user["uuid"])
```

---

## Summary

### Decision Matrix

| Need | Use |
|------|-----|
| Authenticate API requests | `get_current_user` dependency |
| Check ACL permissions | `require_acl` / `AccentAuthACL` |
| Validate tokens programmatically | `AccentAuthClient.validate_token()` |
| Create/update users | `accent-auth-client` library |
| Manage groups | `accent-auth-client` library |
| Manage policies | `accent-auth-client` library |
| MFA/SAML/LDAP | `accent-auth-client` library |
| Tenant administration | `accent-auth-client` library |

### Quick Reference

```python
# For request authentication (fast, cached)
from example_service.core.dependencies.accent_auth import (
    get_current_user,
    require_acl,
)

# For ACL checking (fast, local)
from example_service.infra.auth import AccentAuthACL

# For admin operations (requires library)
from example_service.core.dependencies.accent_admin import get_admin_client

```

---

**Updated**: 2025-12-02
**Version**: 2.0.0
**Status**: Integration Guide
