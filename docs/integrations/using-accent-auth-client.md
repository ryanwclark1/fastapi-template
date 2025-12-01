# Using accent-auth-client Library (Optional)

This guide explains when and how to use the `accent-auth-client` library for advanced features beyond basic token validation.

## When to Use accent-auth-client

### ✅ Use the Library When You Need:

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

### ❌ Don't Use the Library For:

1. **Request Authentication** - Use our custom FastAPI dependencies (lighter, optimized)
2. **Token Validation** - Use our custom client (simpler, FastAPI-native)
3. **ACL Checking** - Use our `AccentAuthACL` class (efficient)

---

## Installation

The `accent-auth-client` is part of the accent-voice2 monorepo and not published to PyPI.

### Option 1: Install from Local Path (Development)

```bash
# Add to pyproject.toml
[tool.uv.sources]
accent-auth-client = { path = "../accent-voice2/library/accent-auth-client", editable = true }

[project]
dependencies = [
    "accent-auth-client",
]
```

### Option 2: Install from Git Repository

```bash
# Add to pyproject.toml
[project]
dependencies = [
    "accent-auth-client @ git+https://github.com/your-org/accent-voice2.git#subdirectory=library/accent-auth-client",
]
```

### Option 3: Copy to Local Dependencies

```bash
# Copy the library to your project
cp -r ../accent-voice2/library/accent-auth-client ./libs/
```

---

## Integration Pattern: Hybrid Approach

### Architecture

```
┌─────────────────────────────────────────────┐
│         FastAPI Application                 │
└─────────────────┬───────────────────────────┘
                  │
                  ├──> Request Auth (Custom)
                  │    - Token validation
                  │    - ACL checking
                  │    - FastAPI dependencies
                  │
                  └──> User Management (Library)
                       - User CRUD
                       - Group management
                       - Policy management
                       - Advanced features
```

### Code Organization

```
example_service/
├── core/
│   └── dependencies/
│       ├── accent_auth.py        # Custom (token validation)
│       └── accent_client.py      # Library wrapper (user mgmt)
├── infra/
│   └── auth/
│       └── accent_auth.py        # Custom client (lightweight)
└── features/
    └── admin/
        └── users.py              # Uses library for CRUD
```

---

## Usage Examples

### Setup: Client Dependency

```python
# example_service/core/dependencies/accent_client.py
"""FastAPI dependency for accent-auth-client library."""

from typing import Annotated
from fastapi import Depends
from accent_auth_client import Client as AccentAuthLibClient

from example_service.core.settings import get_auth_settings


async def get_accent_client() -> AccentAuthLibClient:
    """Provide accent-auth-client instance as FastAPI dependency.

    Use this for user/group/policy management operations.
    Do NOT use for request authentication - use our custom dependencies instead.
    """
    settings = get_auth_settings()

    async with AccentAuthLibClient(
        host=settings.service_url.host,
        port=settings.service_url.port or 443,
        https=settings.service_url.scheme == "https",
        token=settings.service_token,  # Service token for admin operations
        tenant=settings.master_tenant_uuid,  # Or from request context
    ) as client:
        yield client
```

### Example 1: User Management Endpoints

```python
# example_service/features/admin/users.py
"""User management endpoints using accent-auth-client."""

from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from accent_auth_client import Client as AccentAuthClient
from accent_auth_client.exceptions import ResourceNotFoundError

from example_service.core.dependencies.accent_auth import require_acl
from example_service.core.dependencies.accent_client import get_accent_client
from example_service.core.schemas.auth import AuthUser

router = APIRouter(prefix="/admin/users", tags=["admin", "users"])


class UserCreate(BaseModel):
    """User creation schema."""
    username: str
    email: str
    firstname: str | None = None
    lastname: str | None = None
    password: str


@router.post("/")
async def create_user(
    user_data: UserCreate,
    current_user: Annotated[AuthUser, Depends(require_acl("admin.users.create"))],
    client: Annotated[AccentAuthClient, Depends(get_accent_client)],
):
    """Create a new user via accent-auth.

    Requires: admin.users.create ACL
    """
    # Create user using library
    new_user = await client.users.new(
        username=user_data.username,
        email=user_data.email,
        firstname=user_data.firstname,
        lastname=user_data.lastname,
        password=user_data.password,
        tenant_uuid=current_user.metadata.get("tenant_uuid"),
    )

    return new_user


@router.get("/")
async def list_users(
    current_user: Annotated[AuthUser, Depends(require_acl("admin.users.read"))],
    client: Annotated[AccentAuthClient, Depends(get_accent_client)],
    limit: int = 50,
    offset: int = 0,
):
    """List all users in tenant.

    Requires: admin.users.read ACL
    """
    tenant_uuid = current_user.metadata.get("tenant_uuid")
    users = await client.users.list(
        tenant_uuid=tenant_uuid,
        limit=limit,
        offset=offset,
    )

    return users


@router.get("/{user_uuid}")
async def get_user(
    user_uuid: str,
    current_user: Annotated[AuthUser, Depends(require_acl("admin.users.read"))],
    client: Annotated[AccentAuthClient, Depends(get_accent_client)],
):
    """Get user details.

    Requires: admin.users.read ACL
    """
    try:
        user = await client.users.get(user_uuid)
        return user
    except ResourceNotFoundError:
        raise HTTPException(404, "User not found")


@router.put("/{user_uuid}")
async def update_user(
    user_uuid: str,
    user_data: UserUpdate,
    current_user: Annotated[AuthUser, Depends(require_acl("admin.users.update"))],
    client: Annotated[AccentAuthClient, Depends(get_accent_client)],
):
    """Update user details.

    Requires: admin.users.update ACL
    """
    try:
        updated_user = await client.users.edit(
            user_uuid,
            **user_data.model_dump(exclude_unset=True)
        )
        return updated_user
    except ResourceNotFoundError:
        raise HTTPException(404, "User not found")


@router.delete("/{user_uuid}")
async def delete_user(
    user_uuid: str,
    current_user: Annotated[AuthUser, Depends(require_acl("admin.users.delete"))],
    client: Annotated[AccentAuthClient, Depends(get_accent_client)],
):
    """Delete a user.

    Requires: admin.users.delete ACL
    """
    try:
        await client.users.delete_user(user_uuid)
        return {"deleted": True, "user_uuid": user_uuid}
    except ResourceNotFoundError:
        raise HTTPException(404, "User not found")


@router.post("/{user_uuid}/policies/{policy_uuid}")
async def add_user_policy(
    user_uuid: str,
    policy_uuid: str,
    current_user: Annotated[AuthUser, Depends(require_acl("admin.users.policies"))],
    client: Annotated[AccentAuthClient, Depends(get_accent_client)],
):
    """Add policy to user.

    Requires: admin.users.policies ACL
    """
    await client.users.add_policy(user_uuid, policy_uuid)
    return {"added": True}


@router.delete("/{user_uuid}/policies/{policy_uuid}")
async def remove_user_policy(
    user_uuid: str,
    policy_uuid: str,
    current_user: Annotated[AuthUser, Depends(require_acl("admin.users.policies"))],
    client: Annotated[AccentAuthClient, Depends(get_accent_client)],
):
    """Remove policy from user.

    Requires: admin.users.policies ACL
    """
    await client.users.remove_policy(user_uuid, policy_uuid)
    return {"removed": True}


@router.put("/{user_uuid}/password")
async def change_user_password(
    user_uuid: str,
    new_password: str,
    current_user: Annotated[AuthUser, Depends(require_acl("admin.users.password"))],
    client: Annotated[AccentAuthClient, Depends(get_accent_client)],
):
    """Change user password.

    Requires: admin.users.password ACL
    """
    await client.users.change_password(user_uuid, new_password)
    return {"changed": True}
```

### Example 2: Group Management

```python
# example_service/features/admin/groups.py
"""Group management endpoints."""

@router.post("/groups")
async def create_group(
    group_data: GroupCreate,
    current_user: Annotated[AuthUser, Depends(require_acl("admin.groups.create"))],
    client: Annotated[AccentAuthClient, Depends(get_accent_client)],
):
    """Create a new group."""
    new_group = await client.groups.new(
        name=group_data.name,
        tenant_uuid=current_user.metadata.get("tenant_uuid"),
    )
    return new_group


@router.post("/groups/{group_uuid}/users/{user_uuid}")
async def add_user_to_group(
    group_uuid: str,
    user_uuid: str,
    current_user: Annotated[AuthUser, Depends(require_acl("admin.groups.members"))],
    client: Annotated[AccentAuthClient, Depends(get_accent_client)],
):
    """Add user to group."""
    await client.groups.add_user(group_uuid, user_uuid)
    return {"added": True}
```

### Example 3: Policy Management

```python
# example_service/features/admin/policies.py
"""Policy management endpoints."""

@router.post("/policies")
async def create_policy(
    policy_data: PolicyCreate,
    current_user: Annotated[AuthUser, Depends(require_acl("admin.policies.create"))],
    client: Annotated[AccentAuthClient, Depends(get_accent_client)],
):
    """Create a new policy with ACLs."""
    new_policy = await client.policies.new(
        name=policy_data.name,
        description=policy_data.description,
        acl_templates=policy_data.acls,  # List of ACL strings
        tenant_uuid=current_user.metadata.get("tenant_uuid"),
    )
    return new_policy
```

---

## Best Practices

### 1. Use Service Token for Admin Operations

```python
# In settings
AUTH_SERVICE_TOKEN=your-admin-service-token
AUTH_MASTER_TENANT_UUID=master-tenant-uuid

# In dependency
async def get_accent_client():
    """Use service token for privileged operations."""
    async with AccentAuthClient(
        host=settings.service_url.host,
        token=settings.service_token,  # Admin token
        tenant=settings.master_tenant_uuid,
    ) as client:
        yield client
```

### 2. Don't Mix Auth Methods

```python
# ❌ Don't do this
@router.get("/users")
async def list_users(
    # Using library for validation (slow, heavyweight)
    token: str,
    client: Annotated[AccentAuthClient, Depends(get_accent_client)],
):
    await client.tokens.check(token)  # Slow!

# ✅ Do this
@router.get("/users")
async def list_users(
    # Use our custom dependency for auth (fast)
    user: Annotated[AuthUser, Depends(get_current_user)],
    # Use library only for user operations
    client: Annotated[AccentAuthClient, Depends(get_accent_client)],
):
    users = await client.users.list()
```

### 3. Handle Library Exceptions

```python
from accent_auth_client.exceptions import (
    ResourceNotFoundError,
    ValidationError,
    AuthenticationError,
    AuthorizationError,
)

try:
    user = await client.users.get(user_uuid)
except ResourceNotFoundError:
    raise HTTPException(404, "User not found")
except ValidationError as e:
    raise HTTPException(400, str(e))
except AuthenticationError:
    raise HTTPException(401, "Authentication failed")
except AuthorizationError:
    raise HTTPException(403, "Access denied")
```

### 4. Tenant Context

```python
# Always pass tenant context when using library
tenant_uuid = current_user.metadata.get("tenant_uuid")

users = await client.users.list(tenant_uuid=tenant_uuid)
groups = await client.groups.list(tenant_uuid=tenant_uuid)
```

---

## Performance Considerations

### Library vs Custom Client

| Operation | Custom Client | accent-auth-client | Recommendation |
|-----------|---------------|-------------------|----------------|
| Token validation | 5ms (cached) | 50-100ms | Use Custom |
| ACL check | <1ms (local) | 50-100ms | Use Custom |
| User CRUD | Not available | 50-100ms | Use Library |
| Group management | Not available | 50-100ms | Use Library |
| Policy management | Not available | 50-100ms | Use Library |

**Key Insight**: Our custom client is **10-20x faster** for authentication because it's:
- Optimized for FastAPI dependency injection
- Caches aggressively
- Only does what's needed

The library should be used for **administrative operations** that happen less frequently.

---

## Testing with accent-auth-client

```python
# tests/integration/test_user_management.py
"""Test user management with accent-auth-client."""

import pytest
from accent_auth_client import Client as AccentAuthClient


@pytest.fixture
async def accent_client():
    """Provide accent-auth-client for testing."""
    async with AccentAuthClient(
        host="accent-auth-test",
        token="test-token",
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_create_user(accent_client):
    """Test user creation via library."""
    user = await accent_client.users.new(
        username="testuser",
        email="test@example.com",
        password="secure-pass",
    )

    assert user["username"] == "testuser"
    assert user["email"] == "test@example.com"

    # Cleanup
    await accent_client.users.delete_user(user["uuid"])
```

---

## Summary

### Our Architecture

```
┌──────────────────────────────────────────┐
│   Request Authentication (Fast)         │
│   - Custom accent_auth.py                │
│   - FastAPI dependencies                 │
│   - Token validation (5ms cached)        │
│   - ACL checking (<1ms local)            │
└──────────────────────────────────────────┘
              ↓
┌──────────────────────────────────────────┐
│   Administrative Operations (Full)       │
│   - accent-auth-client library           │
│   - User/Group/Policy CRUD               │
│   - Advanced features (MFA, SAML, etc.)  │
└──────────────────────────────────────────┘
```

### Decision Matrix

| Need | Use |
|------|-----|
| Authenticate API requests | Custom dependencies |
| Check ACL permissions | Custom `AccentAuthACL` |
| Create/update users | accent-auth-client |
| Manage groups | accent-auth-client |
| Manage policies | accent-auth-client |
| MFA/SAML/LDAP | accent-auth-client |
| Tenant administration | accent-auth-client |

---

**Recommendation**: Keep the hybrid approach. Use our custom client for all request authentication (fast, optimized) and optionally add accent-auth-client when you need user/group/policy management features.

---

**Generated**: 2025-12-01
**Status**: Optional Enhancement Guide
