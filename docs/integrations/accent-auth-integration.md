# Accent-Auth Integration Guide

This guide covers integration with Accent-Auth, your enterprise authentication service with ACL-based authorization and multi-tenancy support.

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Configuration](#configuration)
3. [Authentication Flow](#authentication-flow)
4. [ACL System](#acl-system)
5. [Using ACL Permissions](#using-acl-permissions)
6. [Multi-Tenancy](#multi-tenancy)
7. [API Examples](#api-examples)
8. [Testing](#testing)
9. [Troubleshooting](#troubleshooting)

---

## Architecture Overview

### Design Philosophy

The integration follows a **hybrid architecture**:

1. **Token Validation**: Remote (via Accent-Auth API or accent-auth-client library)
2. **ACL Evaluation**: Local (fast, LRU-cached pattern matching)

This design provides:
- ✅ **Security**: Token validation always contacts the authoritative source
- ✅ **Performance**: ACL pattern matching is local and cached
- ✅ **Flexibility**: Works with or without the accent-auth-client library

### Component Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           FastAPI Application                                │
├─────────────────────────────────────────────────────────────────────────────┤
│  core/dependencies/accent_auth.py          │  core/acl/                     │
│  ├── get_current_user                      │  ├── access_check.py          │
│  ├── get_current_user_optional             │  │   └── AccessCheck class    │
│  ├── require_acl(pattern)                  │  │   └── LRU caching          │
│  ├── require_any_acl(*patterns)            │  ├── checker.py               │
│  ├── require_all_acls(*patterns)           │  │   └── ACLChecker class     │
│  └── require_superuser()                   │  └── derivation.py            │
│                                            │      └── UI permission parse  │
├─────────────────────────────────────────────────────────────────────────────┤
│                         infra/auth/accent_auth.py                            │
│  ├── AccentAuthClient      - Async wrapper for token validation             │
│  ├── AccentAuthToken       - Token response model                            │
│  ├── AccentAuthMetadata    - Token metadata                                  │
│  ├── AccentAuthACL         - ACL pattern matching helper                     │
│  └── get_accent_auth_client() - Singleton factory                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                         External: Accent-Auth Service                        │
│  ├── Token validation endpoint: GET /api/auth/0.1/token/{token}              │
│  ├── Token check endpoint: HEAD /api/auth/0.1/token/{token}                  │
│  └── Token revoke endpoint: DELETE /api/auth/0.1/token/{token}               │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Features

| Feature | Description |
|---------|-------------|
| **Token validation** | Via Accent-Auth API (cached in Redis) |
| **ACL-based authorization** | Dot-notation with wildcards |
| **Multi-tenant support** | Via `Accent-Tenant` header |
| **Wildcard permissions** | `*` (single level) and `#` (recursive) |
| **Negation ACLs** | `!` prefix for explicit deny |
| **Reserved words** | `me` (current user), `my_session` (current session) |
| **Path parameter substitution** | Dynamic ACL patterns like `users.{user_id}.read` |

### accent-auth-client Requirement

The integration requires the official `accent-auth-client` library:

```python
# The accent-auth-client library is required:
# - Uses accent_auth_client.Client for token operations
# - Wraps sync calls with asyncio.to_thread for FastAPI compatibility
```

Installation:

```bash
pip install accent-auth-client
```

Check availability at startup:

```python
from example_service.infra.auth.accent_auth import ACCENT_AUTH_CLIENT_AVAILABLE

if not ACCENT_AUTH_CLIENT_AVAILABLE:
    raise RuntimeError("accent-auth-client is required. Install with: pip install accent-auth-client")
```

---

## Configuration

### Environment Variables

```env
# Accent-Auth Service
AUTH_SERVICE_URL=http://accent-auth:9497
AUTH_REQUEST_TIMEOUT=5.0
AUTH_MAX_RETRIES=3

# Optional: Service token for privileged operations
AUTH_SERVICE_TOKEN=your-service-token

# Caching
AUTH_TOKEN_CACHE_TTL=300
AUTH_ENABLE_PERMISSION_CACHING=true
AUTH_ENABLE_ACL_CACHING=true

# Redis (for token caching)
REDIS_URL=redis://localhost:6379/0
```

### Verify Configuration

```python
from example_service.core.settings import get_auth_settings

settings = get_auth_settings()
print(f"Auth URL: {settings.service_url}")
print(f"Cache TTL: {settings.token_cache_ttl}s")
```

---

## Authentication Flow

### How It Works

```
┌─────────────────┐
│   Client        │
└────────┬────────┘
         │ X-Auth-Token: <token>
         │ Accent-Tenant: <uuid> (optional)
         ↓
┌─────────────────┐
│   FastAPI       │ get_current_user dependency
│   Middleware    │
└────────┬────────┘
         │
         ├──> 1. Check Redis Cache (by token prefix + tenant)
         │         ↓ (cache miss)
         │
         ├──> 2. Call Accent-Auth API
         │    • Uses accent-auth-client if installed
         │    • Falls back to httpx if not
         │         ↓
         │    Response includes:
         │      - user_uuid
         │      - tenant_uuid
         │      - acls: ["confd.users.read", ...]
         │      - session_uuid
         │      - expires_at
         │
         ├──> 3. Cache result in Redis (TTL: 5 min)
         │
         ├──> 4. Convert to AuthUser model
         │         - user_id = metadata.uuid
         │         - permissions = acls
         │         - metadata = {tenant_uuid, session_uuid, ...}
         │
         └──> 5. Inject into endpoint & set request.state
              ↓
┌─────────────────┐
│   Endpoint      │
│   Handler       │
└─────────────────┘
```

### Token Validation Methods

The `AccentAuthClient` provides several validation methods:

#### 1. Full Validation (GET) - Returns token info with ACLs

```python
from example_service.infra.auth import get_accent_auth_client

async with get_accent_auth_client() as client:
    token_info = await client.validate_token(
        token="user-token",
        tenant_uuid="optional-tenant-uuid",  # For tenant scoping
        required_acl="optional.acl.check",   # Fails if token lacks this ACL
    )

    print(f"User: {token_info.metadata.uuid}")
    print(f"Tenant: {token_info.metadata.tenant_uuid}")
    print(f"ACLs: {token_info.acl}")
    print(f"Expires: {token_info.expires_at}")
```

#### 2. Quick Check (HEAD) - Returns True/False, raises on failure

```python
async with get_accent_auth_client() as client:
    try:
        is_valid = await client.check_token(
            token="user-token",
            required_acl="confd.users.read",
        )
        # is_valid is True if token is valid and has ACL
    except InvalidTokenException:
        # Token is invalid or expired
        pass
    except MissingPermissionsTokenException:
        # Token lacks required ACL
        pass
```

#### 3. Silent Check - Returns True/False, never raises

```python
async with get_accent_auth_client() as client:
    is_valid = await client.is_token_valid(
        token="user-token",
        required_acl="confd.users.read",
    )
    # Returns False for any error condition
```

#### 4. Token Revocation

```python
async with get_accent_auth_client() as client:
    await client.revoke_token("user-token")
```

---

## ACL System

### Architecture

The ACL system has three layers, each with specific responsibilities:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Layer 1: core/acl/access_check.py - Pattern Evaluation Engine             │
│                                                                              │
│  • AccessCheck class: Core pattern matching with regex                       │
│  • Reserved word substitution: me → auth_id, my_session → session_id        │
│  • Negation handling: !pattern explicitly denies                             │
│  • Wildcard expansion: * (single), # (recursive)                             │
│  • 3-level LRU caching for performance                                       │
│                                                                              │
│  Example:                                                                    │
│    acls = ["users.*", "!users.admin"]                                        │
│    checker = get_cached_access_check("user-123", "sess-456", acls)           │
│    checker.matches_required_access("users.read")  # True                     │
│    checker.matches_required_access("users.admin") # False (negated)          │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│  Layer 2: core/acl/checker.py - Programmatic ACL Checker                    │
│                                                                              │
│  • ACLChecker class: High-level API for business logic                       │
│  • Wraps validated token payload                                             │
│  • Methods: has_acl, has_any_acl, has_all_acls, is_superuser                │
│  • Delegation checking: can_grant_acl, can_revoke_acl                        │
│                                                                              │
│  Example:                                                                    │
│    checker = ACLChecker(token)                                               │
│    if checker.has_any_acl("admin.*", f"users.{user_id}.owner"):              │
│        # Allow operation                                                     │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│  Layer 3: core/dependencies/accent_auth.py - FastAPI Dependencies           │
│                                                                              │
│  • require_acl(pattern) - Single ACL requirement                             │
│  • require_any_acl(*patterns) - Any of multiple ACLs                         │
│  • require_all_acls(*patterns) - All of multiple ACLs                        │
│  • require_superuser() - Requires # wildcard                                 │
│  • Path parameter substitution: {user_id} → actual value                     │
│                                                                              │
│  Example:                                                                    │
│    @router.get("/users/{user_id}")                                           │
│    async def get_user(                                                       │
│        user: Annotated[AuthUser, Depends(require_acl("users.{user_id}.read"))]│
│    ):                                                                        │
│        ...                                                                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### ACL Pattern Syntax

| Pattern | Description | Example |
|---------|-------------|---------|
| `service.resource.action` | Exact match | `confd.users.read` |
| `*` | Single-level wildcard | `confd.users.*` matches `confd.users.read`, `confd.users.create` |
| `#` | Recursive wildcard | `confd.#` matches `confd.users.read`, `confd.users.groups.list` |
| `!pattern` | Negation (explicit deny) | `!confd.users.delete` denies even if `confd.users.*` grants |
| `me` | Current user ID | `users.me.read` → `users.{auth_id}.read` |
| `my_session` | Current session ID | `sessions.my_session.delete` |

### Wildcard Precedence

Negation patterns (`!`) always take precedence over positive patterns:

```python
acls = [
    "confd.#",           # Grant all confd access
    "!confd.users.delete",  # Except delete
]

acl = AccentAuthACL(acls)
acl.has_permission("confd.users.read")    # True
acl.has_permission("confd.users.delete")  # False (negated)
acl.has_permission("confd.calls.hangup")  # True
```

### Reserved Word Substitution

The ACL system automatically substitutes reserved words:

```python
acl = AccentAuthACL(
    acls=["users.me.read", "sessions.my_session.delete"],
    auth_id="user-123",
    session_id="sess-456",
)

# "users.me.read" becomes "users.user-123.read" internally
acl.has_permission("users.user-123.read")  # True
acl.has_permission("users.other-user.read")  # False

# "sessions.my_session.delete" becomes "sessions.sess-456.delete"
acl.has_permission("sessions.sess-456.delete")  # True
```

### LRU Caching

The ACL system uses three levels of caching for performance:

```python
# Level 1: Pattern compilation (regex)
@lru_cache(maxsize=1024)
def _compile_acl_pattern(pattern: str) -> re.Pattern:
    ...

# Level 2: Reserved word substitution
@lru_cache(maxsize=256)
def _substitute_reserved_words(pattern: str, auth_id: str, session_id: str) -> str:
    ...

# Level 3: AccessCheck instance creation
@lru_cache(maxsize=512)
def get_cached_access_check(auth_id, session_id, acl_tuple) -> AccessCheck:
    ...
```

---

## Using ACL Permissions

### Endpoint Protection

#### Basic ACL Requirement

```python
from typing import Annotated
from fastapi import APIRouter, Depends
from example_service.core.dependencies.accent_auth import (
    get_current_user,
    require_acl,
)
from example_service.core.schemas.auth import AuthUser

router = APIRouter()

@router.get("/users")
async def list_users(
    user: Annotated[AuthUser, Depends(require_acl("confd.users.read"))]
):
    """Requires confd.users.read ACL."""
    return {"users": []}
```

#### Path Parameter Substitution

```python
@router.get("/users/{user_id}/profile")
async def get_profile(
    user_id: str,
    user: Annotated[AuthUser, Depends(require_acl("users.{user_id}.read"))]
):
    """The {user_id} is replaced with the actual path parameter.

    If user_id="456", checks for "users.456.read" permission.
    A user with "users.me.read" and auth_id="456" would pass.
    """
    return {"user_id": user_id}
```

#### Require Any ACL (OR logic)

```python
from example_service.core.dependencies.accent_auth import require_any_acl

@router.get("/users/{user_id}")
async def get_user(
    user_id: str,
    user: Annotated[
        AuthUser,
        Depends(require_any_acl("confd.users.read", "users.{user_id}.read"))
    ]
):
    """Requires EITHER confd.users.read OR users.{user_id}.read."""
    return {"user_id": user_id}
```

#### Require All ACLs (AND logic)

```python
from example_service.core.dependencies.accent_auth import require_all_acls

@router.post("/admin/users")
async def create_admin_user(
    user: Annotated[
        AuthUser,
        Depends(require_all_acls("confd.users.create", "admin.users.*"))
    ]
):
    """Requires BOTH confd.users.create AND admin.users.*."""
    return {"created": True}
```

#### Superuser Requirement

```python
from example_service.core.dependencies.accent_auth import require_superuser

@router.post("/system/reset")
async def reset_system(
    user: Annotated[AuthUser, Depends(require_superuser())]
):
    """Requires the # wildcard ACL (full system access)."""
    return {"reset": True}
```

### Programmatic ACL Checking

For complex permission logic within business code, use `ACLChecker`:

```python
from example_service.core.acl import ACLChecker

async def transfer_ownership(token: TokenPayload, resource_id: str, new_owner_id: str):
    checker = ACLChecker(token)

    # Must have admin OR be current owner
    if not checker.has_any_acl(
        "admin.resources.*",
        f"resources.{resource_id}.transfer",
    ):
        raise PermissionError("Cannot transfer resource")

    # Proceed with transfer
    ...
```

Or use `AccentAuthACL` directly for the lowest-level control:

```python
from example_service.infra.auth import AccentAuthACL

@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    user: Annotated[AuthUser, Depends(get_current_user)],
):
    """Custom ACL logic."""
    acl = AccentAuthACL(
        user.permissions,
        auth_id=user.user_id,
        session_id=user.metadata.get("session_uuid"),
    )

    # Allow if user has admin ACL or is deleting themselves
    if not (acl.has_permission("admin.users.delete") or user.user_id == user_id):
        raise HTTPException(status_code=403, detail="Access denied")

    return {"deleted": True}
```

### ACL Delegation Checking

Check if a user can grant/revoke permissions to others:

```python
from example_service.core.acl import ACLChecker

async def grant_permission(granter: TokenPayload, target_user_id: str, acl_to_grant: str):
    checker = ACLChecker(granter)

    # Users can only delegate permissions they themselves have
    if not checker.can_grant_acl(acl_to_grant):
        raise PermissionError(f"Cannot grant {acl_to_grant} - you don't have it")

    # Proceed with granting
    ...
```

---

## Multi-Tenancy

### Tenant Context

Accent-Auth provides tenant isolation via the `Accent-Tenant` header:

```bash
curl -H "X-Auth-Token: <token>" \
     -H "Accent-Tenant: <tenant-uuid>" \
     https://api.example.com/endpoint
```

### Accessing Tenant in Endpoints

The tenant UUID is available in multiple places:

```python
@router.get("/tenant-data")
async def get_tenant_data(
    request: Request,
    user: Annotated[AuthUser, Depends(get_current_user)],
):
    # Option 1: From user metadata (recommended)
    tenant_uuid = user.metadata.get("tenant_uuid")

    # Option 2: From request state (set by get_current_user)
    tenant_uuid = getattr(request.state, "tenant_uuid", None)

    return {"tenant_uuid": tenant_uuid}
```

### Tenant-Aware Models

Use `TenantMixin` for tenant-scoped data:

```python
from sqlalchemy.orm import Mapped, mapped_column
from example_service.core.database.base import Base, TenantMixin, TimestampMixin

class Post(Base, TenantMixin, TimestampMixin):
    """Tenant-aware model."""
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    content: Mapped[str]
    # tenant_id added automatically by TenantMixin
```

**Note**: The `TenantMixin` adds a `tenant_id` string column. With Accent-Auth, store the `tenant_uuid` from the token.

---

## API Examples

### Example 1: Full Protected Endpoint

```python
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from example_service.core.dependencies.accent_auth import (
    get_current_user,
    require_acl,
    require_any_acl,
)
from example_service.core.schemas.auth import AuthUser
from example_service.infra.auth import AccentAuthACL

router = APIRouter(prefix="/api/v1/reminders", tags=["reminders"])

@router.get("/")
async def list_reminders(
    user: Annotated[AuthUser, Depends(require_acl("reminders.read"))],
):
    """List reminders - requires reminders.read ACL."""
    return {
        "user_uuid": user.user_id,
        "tenant_uuid": user.metadata.get("tenant_uuid"),
        "reminders": [],
    }

@router.post("/")
async def create_reminder(
    reminder: ReminderCreate,
    user: Annotated[AuthUser, Depends(require_acl("reminders.create"))],
):
    """Create reminder - requires reminders.create ACL."""
    return {"created": True}

@router.delete("/{reminder_id}")
async def delete_reminder(
    reminder_id: int,
    user: Annotated[
        AuthUser,
        Depends(require_any_acl("reminders.delete", "reminders.{reminder_id}.owner"))
    ],
):
    """Delete reminder - requires reminders.delete or be owner."""
    return {"deleted": True}
```

### Example 2: Optional Authentication

```python
from example_service.core.dependencies.accent_auth import get_current_user_optional

@router.get("/public-data")
async def get_public_data(
    user: Annotated[AuthUser | None, Depends(get_current_user_optional)],
):
    """Endpoint with optional authentication."""
    if user:
        return {
            "message": f"Hello, {user.user_id}",
            "tenant_uuid": user.metadata.get("tenant_uuid"),
        }
    return {"message": "Hello, anonymous"}
```

### Example 3: Complex Permission Logic

```python
@router.put("/users/{user_id}/settings")
async def update_user_settings(
    user_id: str,
    settings: UserSettings,
    current_user: Annotated[AuthUser, Depends(get_current_user)],
):
    """Update user settings with complex permission logic."""
    acl = AccentAuthACL(
        current_user.permissions,
        auth_id=current_user.user_id,
        session_id=current_user.metadata.get("session_uuid"),
    )

    # Three ways to be authorized:
    # 1. Admin permission
    # 2. User is updating their own settings (via "me" reserved word)
    # 3. Specific delegation
    can_update = acl.has_any_permission(
        "admin.users.settings",        # Admin
        f"users.{user_id}.settings",   # Specific user (works with "me")
    )

    if not can_update:
        raise HTTPException(403, "Cannot update these settings")

    return {"updated": True}
```

---

## Testing

### Unit Tests for ACL Patterns

```python
import pytest
from example_service.infra.auth import AccentAuthACL

def test_acl_wildcard():
    """Test ACL wildcard matching."""
    acl = AccentAuthACL(["confd.users.*", "calld.#"])

    assert acl.has_permission("confd.users.read") is True
    assert acl.has_permission("confd.users.create") is True
    assert acl.has_permission("calld.calls.hangup") is True
    assert acl.has_permission("calld.a.b.c.d") is True  # # is recursive
    assert acl.has_permission("admin.all") is False

def test_acl_negation():
    """Test ACL negation takes precedence."""
    acl = AccentAuthACL([
        "confd.#",
        "!confd.users.delete",
    ])

    assert acl.has_permission("confd.users.read") is True
    assert acl.has_permission("confd.users.delete") is False  # Negated!

def test_acl_reserved_words():
    """Test reserved word substitution."""
    acl = AccentAuthACL(
        ["users.me.read", "sessions.my_session.delete"],
        auth_id="user-123",
        session_id="sess-456",
    )

    # "me" becomes "user-123"
    assert acl.has_permission("users.user-123.read") is True
    assert acl.has_permission("users.other.read") is False

    # "my_session" becomes "sess-456"
    assert acl.has_permission("sessions.sess-456.delete") is True

def test_acl_superuser():
    """Test # ACL grants everything."""
    acl = AccentAuthACL(["#"])

    assert acl.has_permission("anything.at.all") is True
    assert acl.is_superuser() is True
```

### Testing ACLChecker

```python
from example_service.core.acl import ACLChecker
from unittest.mock import MagicMock

def test_acl_checker():
    """Test ACLChecker for business logic."""
    token = MagicMock()
    token.sub = "user-123"
    token.session_id = "sess-456"
    token.acl = ["users.*", "!users.admin"]

    checker = ACLChecker(token)

    assert checker.has_acl("users.read") is True
    assert checker.has_acl("users.admin") is False  # Negated
    assert checker.has_any_acl("admin.all", "users.read") is True
    assert checker.has_all_acls("users.read", "users.admin") is False
```

### Integration Test with FastAPI

```python
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock

def test_protected_endpoint(test_client: TestClient):
    """Test endpoint with ACL protection."""
    # Mock the auth client
    mock_token = AsyncMock()
    mock_token.metadata.uuid = "user-123"
    mock_token.metadata.tenant_uuid = "tenant-456"
    mock_token.acl = ["reminders.read"]

    with patch("example_service.core.dependencies.accent_auth.get_accent_auth_client") as mock:
        mock.return_value.validate_token = AsyncMock(return_value=mock_token)

        response = test_client.get(
            "/api/v1/reminders",
            headers={"X-Auth-Token": "valid-token"},
        )

        assert response.status_code == 200

def test_missing_acl(test_client: TestClient):
    """Test endpoint returns 403 when ACL is missing."""
    mock_token = AsyncMock()
    mock_token.metadata.uuid = "user-123"
    mock_token.metadata.tenant_uuid = "tenant-456"
    mock_token.acl = []  # No ACLs!

    with patch("example_service.core.dependencies.accent_auth.get_accent_auth_client") as mock:
        mock.return_value.validate_token = AsyncMock(return_value=mock_token)

        response = test_client.get(
            "/api/v1/reminders",
            headers={"X-Auth-Token": "valid-token"},
        )

        assert response.status_code == 403
        assert "insufficient_permissions" in response.json()["detail"]["error"]
```

### Manual Testing

```bash
# Get token from accent-auth
export TOKEN="your-token-here"
export TENANT_UUID="your-tenant-uuid"

# Test protected endpoint
curl -H "X-Auth-Token: $TOKEN" \
     -H "Accent-Tenant: $TENANT_UUID" \
     http://localhost:8000/api/v1/reminders

# Expected (200 OK):
{
  "user_uuid": "...",
  "tenant_uuid": "...",
  "reminders": []
}

# Test without token (401):
curl http://localhost:8000/api/v1/reminders

# Expected (401 Unauthorized):
{
  "detail": "Missing X-Auth-Token header"
}

# Test with invalid ACL (403):
curl -H "X-Auth-Token: $TOKEN" http://localhost:8000/admin/reset

# Expected (403 Forbidden):
{
  "detail": {
    "error": "insufficient_permissions",
    "message": "Missing required ACL: admin.reset",
    "required_acl": "admin.reset"
  }
}
```

---

## Troubleshooting

### Common Issues

#### 1. "Missing X-Auth-Token header" (401)

**Problem**: Endpoint requires authentication but no token provided

**Solutions**:
- Verify you're sending `X-Auth-Token` header (not `Authorization: Bearer`)
- Header name is case-sensitive

```bash
# Correct
curl -H "X-Auth-Token: my-token" ...

# Incorrect
curl -H "Authorization: Bearer my-token" ...
```

#### 2. "Invalid or expired token" (401)

**Problem**: Token validation failed

**Solutions**:
- Check Accent-Auth service is running and reachable
- Verify `AUTH_SERVICE_URL` is correct
- Test token directly:
  ```bash
  curl -X HEAD http://accent-auth:9497/api/auth/0.1/token/YOUR_TOKEN \
       -H "X-Auth-Token: YOUR_TOKEN"
  # 204 = valid, 404 = invalid/expired
  ```

#### 3. "Missing required ACL" (403)

**Problem**: Token is valid but lacks required permission

**Solutions**:
- Verify user has the required ACL in Accent-Auth
- Check ACL string matches exactly
- Debug with:
  ```python
  from example_service.infra.auth import AccentAuthACL

  acl = AccentAuthACL(user.permissions)
  print(f"User ACLs: {user.permissions}")
  print(f"Has permission: {acl.has_permission('required.acl')}")
  ```

#### 4. Path Parameter Substitution Not Working

**Problem**: `{user_id}` not being replaced

**Solutions**:
- Ensure path parameter name matches exactly
- Check that parameter is defined in the route path

```python
# Correct - parameter names match
@router.get("/users/{user_id}")
async def get_user(
    user: Annotated[AuthUser, Depends(require_acl("users.{user_id}.read"))]
):

# Incorrect - parameter name mismatch
@router.get("/users/{id}")  # "id" not "user_id"
async def get_user(
    user: Annotated[AuthUser, Depends(require_acl("users.{user_id}.read"))]  # Won't work!
):
```

#### 5. Reserved Words Not Substituting

**Problem**: `me` and `my_session` not working

**Solutions**:
- Ensure `auth_id` and `session_id` are provided to AccentAuthACL
- The dependencies do this automatically, but check custom usage:

```python
# Correct - provides context
acl = AccentAuthACL(
    user.permissions,
    auth_id=user.user_id,
    session_id=user.metadata.get("session_uuid"),
)

# Incorrect - no context for substitution
acl = AccentAuthACL(user.permissions)  # me/my_session won't work!
```

#### 6. Caching Issues

**Problem**: ACL changes not reflected immediately

**Solutions**:
- Token validation is cached for `AUTH_TOKEN_CACHE_TTL` (default: 300s)
- For immediate effect, clear Redis cache:
  ```bash
  redis-cli KEYS "accent_auth:token:*" | xargs redis-cli DEL
  ```
- Or reduce TTL for development:
  ```env
  AUTH_TOKEN_CACHE_TTL=30
  ```

---

## Performance Considerations

### Caching Layers

1. **Token Validation Cache** (Redis): 5 minute default TTL
   - Key: `accent_auth:token:{token_prefix}:tenant:{tenant_uuid}`
   - Reduces external API calls by ~95%

2. **ACL Pattern Cache** (LRU in-memory): 1024 patterns
   - Compiled regex patterns cached
   - Sub-millisecond pattern matching

3. **AccessCheck Instance Cache** (LRU): 512 instances
   - Full checker objects cached by (auth_id, session_id, acl_tuple)

### Typical Performance

| Operation | First Request | Cached |
|-----------|--------------|--------|
| Token validation | 50-200ms | <5ms (Redis) |
| ACL pattern match | <1ms | <0.1ms (LRU) |
| Full auth check | 50-200ms | <5ms |

### Best Practices

1. **Use caching**: Ensure Redis is configured for token caching
2. **Batch ACL checks**: Use `has_any_acl` or `has_all_acls` instead of multiple `has_acl` calls
3. **Prefer dependencies**: Use `require_acl` over manual checking when possible
4. **Monitor cache hit rates**: Track Redis cache metrics

---

## Quick Reference

### Headers

```bash
X-Auth-Token: <token>          # Required for authentication
Accent-Tenant: <tenant-uuid>   # Optional for multi-tenant
```

### Dependencies

```python
from example_service.core.dependencies.accent_auth import (
    get_current_user,           # Required auth
    get_current_user_optional,  # Optional auth
    require_acl,                # Single ACL
    require_any_acl,            # Any of ACLs
    require_all_acls,           # All ACLs
    require_superuser,          # Requires #
)

# Usage
user: Annotated[AuthUser, Depends(get_current_user)]
user: Annotated[AuthUser, Depends(require_acl("confd.users.read"))]
user: Annotated[AuthUser, Depends(require_acl("users.{user_id}.read"))]
```

### ACL Patterns

```python
"confd.users.read"              # Exact match
"confd.users.*"                 # Single-level wildcard
"confd.#"                       # Multi-level wildcard
"!confd.users.delete"           # Negation (deny)
"confd.users.me.#"              # Reserved word (current user)
"sessions.my_session.delete"    # Reserved word (current session)
```

### Code Imports

```python
# Dependencies
from example_service.core.dependencies.accent_auth import (
    get_current_user,
    require_acl,
)

# ACL utilities
from example_service.core.acl import ACLChecker, get_cached_access_check
from example_service.infra.auth import AccentAuthACL, get_accent_auth_client

# Models
from example_service.core.schemas.auth import AuthUser
```

---

**Updated**: 2025-12-02
**Version**: 2.0.0
**Integration**: Accent-Auth with accent-auth-client support
