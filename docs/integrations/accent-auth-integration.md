# Accent-Auth Integration Guide

This guide covers integration with Accent-Auth, your enterprise authentication service with ACL-based authorization and multi-tenancy support.

## Table of Contents

1. [Overview](#overview)
2. [Configuration](#configuration)
3. [Authentication Flow](#authentication-flow)
4. [Using ACL Permissions](#using-acl-permissions)
5. [Multi-Tenancy](#multi-tenancy)
6. [API Examples](#api-examples)
7. [Testing](#testing)
8. [Troubleshooting](#troubleshooting)

---

## Overview

Accent-Auth integration provides:
- ✅ **Token validation** via Accent-Auth API
- ✅ **ACL-based authorization** with dot-notation
- ✅ **Multi-tenant support** via `Accent-Tenant` header
- ✅ **Wildcard permissions** (* and #)
- ✅ **Negation ACLs** (! prefix)
- ✅ **Token caching** for performance
- ✅ **Session management**

### Key Differences from Generic Auth

| Feature | Generic Auth | Accent-Auth |
|---------|-------------|-------------|
| **Auth Header** | `Authorization: Bearer token` | `X-Auth-Token: token` |
| **Tenant Header** | `X-Tenant-ID` | `Accent-Tenant` |
| **Authorization** | Roles + Permissions | ACL with wildcards |
| **Token Format** | JWT | Opaque token |
| **Validation** | Local or external | External (cached) |

---

## Configuration

### Environment Variables

```.env
# Accent-Auth Service
AUTH_SERVICE_URL=http://accent-auth:9497
AUTH_REQUEST_TIMEOUT=5.0
AUTH_MAX_RETRIES=3

# Caching
AUTH_TOKEN_CACHE_TTL=300
AUTH_ENABLE_PERMISSION_CACHING=true
AUTH_ENABLE_ACL_CACHING=true

# Redis (for caching)
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
│   FastAPI       │
│   Middleware    │
└────────┬────────┘
         │
         ├──> Check Redis Cache
         │         ↓ (miss)
         │
         ├──> Call Accent-Auth API
         │    GET /api/auth/0.1/token/{token}
         │    Headers:
         │      X-Auth-Token: <token>
         │      Accent-Tenant: <uuid>
         │         ↓
         │    Response:
         │      - user_uuid
         │      - tenant_uuid
         │      - acls: ["confd.users.read", ...]
         │
         ├──> Cache result (5 min)
         │
         ├──> Create AuthUser object
         │
         └──> Inject into endpoint
              ↓
┌─────────────────┐
│   Endpoint      │
│   Handler       │
└─────────────────┘
```

### Token Validation Methods

Accent-Auth supports multiple validation methods:

#### 1. Simple Validation (HEAD)

```python
from example_service.infra.auth.accent_auth import get_accent_auth_client

client = get_accent_auth_client()
is_valid = await client.validate_token_simple(token)
# Returns: True/False
```

**Use when:** You only need to check if token is valid

#### 2. Full Validation (GET)

```python
token_info = await client.validate_token(token)
# Returns: AccentAuthToken with ACLs and metadata
```

**Use when:** You need user info and ACLs

#### 3. ACL Check

```python
has_access = await client.check_acl(token, "confd.users.read")
# Returns: True if token has the ACL
```

**Use when:** Checking specific permission

---

## Using ACL Permissions

### ACL Format

Accent-Auth uses dot-notation ACLs:

```
service.resource.action

Examples:
- confd.users.read
- confd.users.create
- webhookd.subscriptions.read
- calld.calls.hangup
```

### Wildcard Support

| Pattern | Meaning | Examples |
|---------|---------|----------|
| `*` | Single-level wildcard | `confd.users.*` matches `confd.users.read`, `confd.users.create` |
| `#` | Multi-level wildcard | `calld.#` matches `calld.calls.read`, `calld.calls.hangup` |
| `!` | Negation | `!confd.users.delete` explicitly denies |

### Reserved Words

- `me` - Current user (e.g., `confd.users.me.read`)
- `my_session` - Current session (e.g., `calld.calls.my_session.*`)

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

#### Require Any ACL

```python
from example_service.core.dependencies.accent_auth import require_any_acl

@router.get("/users/{user_id}")
async def get_user(
    user_id: str,
    user: Annotated[
        AuthUser,
        Depends(require_any_acl("confd.users.read", "confd.users.me.read"))
    ]
):
    """Requires either confd.users.read OR confd.users.me.read."""
    return {"user_id": user_id}
```

#### Require All ACLs

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

#### Custom ACL Logic

```python
@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    user: Annotated[AuthUser, Depends(get_current_user)],
):
    """Custom ACL logic."""
    from example_service.infra.auth.accent_auth import AccentAuthACL

    acl = AccentAuthACL(user.permissions)

    # Allow if user has admin ACL or is deleting themselves
    if not (acl.has_permission("admin.users.delete") or user.user_id == user_id):
        raise HTTPException(status_code=403, detail="Access denied")

    # Delete user logic
    return {"deleted": True}
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

### Middleware Setup

```python
from fastapi import FastAPI
from example_service.core.middleware.tenant import (
    TenantMiddleware,
    HeaderTenantStrategy,
)

app = FastAPI()

# Add tenant middleware
app.add_middleware(
    TenantMiddleware,
    strategies=[
        HeaderTenantStrategy(header_name="Accent-Tenant"),
    ],
    required=False,  # Optional for accent-auth
)
```

### Access Tenant in Endpoints

```python
from example_service.core.middleware.tenant import get_tenant_context

@router.get("/tenant-data")
async def get_tenant_data(
    user: Annotated[AuthUser, Depends(get_current_user)],
):
    """Access tenant from context."""
    # Get from middleware context
    tenant_context = get_tenant_context()
    tenant_uuid = tenant_context.tenant_id if tenant_context else None

    # Or get from user metadata (set during auth)
    tenant_uuid = user.metadata.get("tenant_uuid")

    return {"tenant_uuid": tenant_uuid}
```

### Tenant-Aware Models

```python
from example_service.core.database.tenancy import TenantMixin

class Post(Base, TenantMixin, TimestampMixin):
    """Tenant-aware model."""

    __tablename__ = "posts"

    id = Column(Integer, primary_key=True)
    title = Column(String(255))
    content = Column(Text)
    # tenant_id added automatically
```

**Note**: With Accent-Auth, `tenant_id` should store the `tenant_uuid` from the token.

---

## API Examples

### Example 1: Protected Endpoint

```python
from typing import Annotated
from fastapi import APIRouter, Depends
from example_service.core.dependencies.accent_auth import (
    get_current_user,
    require_acl,
)

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
        Depends(require_any_acl("reminders.delete", "reminders.me.delete"))
    ],
):
    """Delete reminder - requires reminders.delete or own reminder."""
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

### Example 3: Admin Endpoint

```python
@router.post("/admin/reset")
async def admin_reset(
    user: Annotated[
        AuthUser,
        Depends(require_all_acls("admin.system.write", "admin.reset"))
    ],
):
    """Admin-only endpoint."""
    return {"reset": True}
```

---

## Testing

### Unit Tests

```python
import pytest
from example_service.infra.auth.accent_auth import AccentAuthACL

def test_acl_wildcard():
    """Test ACL wildcard matching."""
    acl = AccentAuthACL(["confd.users.*", "calld.#"])

    assert acl.has_permission("confd.users.read") is True
    assert acl.has_permission("confd.users.create") is True
    assert acl.has_permission("calld.calls.hangup") is True
    assert acl.has_permission("admin.all") is False

def test_acl_negation():
    """Test ACL negation."""
    acl = AccentAuthACL([
        "confd.#",
        "!confd.users.delete",
    ])

    assert acl.has_permission("confd.users.read") is True
    assert acl.has_permission("confd.users.delete") is False
```

### Integration Tests

```bash
# Run accent-auth integration tests
uv run pytest tests/integration/test_accent_auth.py -v

# Run specific test class
uv run pytest tests/integration/test_accent_auth.py::TestAccentAuthClient -v

# Run with coverage
uv run pytest tests/integration/test_accent_auth.py --cov=example_service.infra.auth.accent_auth
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

# Expected response (200 OK):
{
  "user_uuid": "...",
  "tenant_uuid": "...",
  "reminders": []
}

# Test without token (401):
curl http://localhost:8000/api/v1/reminders

# Expected response (401 Unauthorized):
{
  "detail": "Missing X-Auth-Token header"
}
```

---

## Troubleshooting

### Common Issues

#### 1. "Missing X-Auth-Token header"

**Problem**: 401 error when calling endpoint

**Solutions**:
- Verify you're sending `X-Auth-Token` header (not `Authorization`)
- Check token is not empty or expired
- Ensure header name is exact (case-sensitive)

```bash
# Correct
curl -H "X-Auth-Token: my-token" ...

# Incorrect
curl -H "Authorization: Bearer my-token" ...
```

#### 2. "Invalid or expired token"

**Problem**: 401 error with valid-looking token

**Solutions**:
- Check Accent-Auth service is running
- Verify `AUTH_SERVICE_URL` is correct
- Test token directly with Accent-Auth:
  ```bash
  curl -X HEAD http://accent-auth:9497/api/auth/0.1/token/YOUR_TOKEN \
       -H "X-Auth-Token: YOUR_TOKEN"
  # Should return 204 if valid
  ```

#### 3. "Missing required ACL"

**Problem**: 403 Forbidden error

**Solutions**:
- Check user has required ACL in Accent-Auth
- Verify ACL string matches exactly
- Test ACL with accent-auth client:
  ```python
  from example_service.infra.auth.accent_auth import get_accent_auth_client

  client = get_accent_auth_client()
  has_acl = await client.check_acl(token, "confd.users.read")
  print(f"Has ACL: {has_acl}")
  ```

#### 4. Tenant Context Not Working

**Problem**: Tenant UUID not available

**Solutions**:
- Ensure `Accent-Tenant` header is sent
- Verify middleware is added to application
- Check middleware order (should be after CORS, before routes)
- Access tenant from user metadata:
  ```python
  tenant_uuid = user.metadata.get("tenant_uuid")
  ```

#### 5. Caching Issues

**Problem**: Changes not reflected immediately

**Solutions**:
- Wait for cache TTL (default: 5 minutes)
- Clear Redis cache manually:
  ```bash
  redis-cli FLUSHDB
  ```
- Reduce `AUTH_TOKEN_CACHE_TTL` for development

---

## Performance Considerations

### Token Caching

Token validation results are cached for 5 minutes by default:

- **First request**: ~100-200ms (external call)
- **Cached requests**: <5ms (Redis lookup)
- **Cache hit rate**: Typically 95%+

### Best Practices

1. **Use simple validation** when you only need to check token validity
2. **Cache ACL checks** for frequently accessed permissions
3. **Set appropriate TTL** based on security requirements
4. **Monitor cache metrics** for optimization opportunities

### Metrics

```python
# Available Prometheus metrics
http_requests_total{endpoint="/api/v1/reminders", status="200"}
auth_token_validations_total{result="success", cached="true"}
auth_acl_checks_total{acl="confd.users.read", result="allowed"}
```

---

## Migration from Generic Auth

If migrating from the generic auth system:

### Code Changes

| Old | New |
|-----|-----|
| `from ...dependencies.auth import get_current_user` | `from ...dependencies.accent_auth import get_current_user` |
| `require_permission("users:read")` | `require_acl("confd.users.read")` |
| `require_role("admin")` | `require_acl("admin.#")` |
| `X-Tenant-ID` header | `Accent-Tenant` header |
| `Authorization: Bearer` | `X-Auth-Token` header |

### Environment Variables

```bash
# Remove (not needed for accent-auth)
AUTH_JWT_ENABLED
AUTH_JWT_ISSUER
AUTH_JWKS_URI
AUTH_API_KEY_ENABLED

# Keep/Update
AUTH_SERVICE_URL=http://accent-auth:9497  # Update URL
AUTH_TOKEN_CACHE_TTL=300
```

---

## Additional Resources

### Accent-Auth Documentation

For complete Accent-Auth documentation, see:
- `/home/administrator/Code/accent-voice2/ACCENT_AUTH_ARCHITECTURE_ANALYSIS.md`
- `/home/administrator/Code/accent-voice2/ACCENT_AUTH_QUICK_REFERENCE.md`

### Internal Documentation

- [Multi-Tenancy Guide](TENANCY_GUIDE.md)
- [Testing Guide](../tests/README.md)
- [Security Configuration](SECURITY_CONFIGURATION.md)

### Examples

- Integration tests: `tests/integration/test_accent_auth.py`
- Client usage: `example_service/infra/auth/accent_auth.py`
- Dependencies: `example_service/core/dependencies/accent_auth.py`

---

## Quick Reference

### Headers

```bash
X-Auth-Token: <token>          # Required for authentication
Accent-Tenant: <tenant-uuid>   # Optional for multi-tenant
```

### Dependencies

```python
# Authentication
from example_service.core.dependencies.accent_auth import (
    get_current_user,           # Required auth
    get_current_user_optional,  # Optional auth
    require_acl,                # Single ACL
    require_any_acl,            # Any of ACLs
    require_all_acls,           # All ACLs
)

# Usage
user: Annotated[AuthUser, Depends(get_current_user)]
user: Annotated[AuthUser, Depends(require_acl("confd.users.read"))]
```

### ACL Patterns

```python
"confd.users.read"          # Exact match
"confd.users.*"             # Single-level wildcard
"confd.#"                   # Multi-level wildcard
"!confd.users.delete"       # Negation
"confd.users.me.#"          # Reserved word (me)
```

### Testing

```bash
# Run tests
uv run pytest tests/integration/test_accent_auth.py -v

# Test endpoint
curl -H "X-Auth-Token: TOKEN" http://localhost:8000/api/v1/endpoint
```

---

**Generated**: 2025-12-01
**Version**: 1.0.0
**Integration**: Accent-Auth
