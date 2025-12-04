# Accent-Auth Integration Summary

Quick reference for the Accent-Auth integration in this FastAPI template.

## Architecture at a Glance

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              API Request                                     │
│                    X-Auth-Token: <token>                                     │
│                    Accent-Tenant: <tenant-uuid>                              │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  core/dependencies/accent_auth.py                                            │
│  ├── get_current_user()           → Validates token, returns AuthUser        │
│  ├── require_acl("pattern")       → Checks ACL permission                    │
│  ├── require_any_acl(...)         → Checks any of multiple ACLs              │
│  ├── require_all_acls(...)        → Checks all ACLs required                 │
│  └── require_superuser()          → Requires # wildcard                      │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │
              ┌──────────────────┴──────────────────┐
              │                                     │
              ▼                                     ▼
┌─────────────────────────────┐     ┌─────────────────────────────────────────┐
│  Token Validation           │     │  ACL Evaluation                          │
│  (Remote + Cached)          │     │  (Local + LRU Cached)                    │
│                             │     │                                          │
│  infra/auth/accent_auth.py  │     │  core/acl/access_check.py               │
│  ├── AccentAuthClient       │     │  ├── Pattern matching (regex)            │
│  │   ├── Uses accent-auth-  │     │  ├── Wildcard expansion (* #)            │
│  │   │   client if installed│     │  ├── Negation handling (!)               │
│  │   └── Falls back to HTTP │     │  ├── Reserved words (me, my_session)     │
│  └── Redis cache (5 min)    │     │  └── 3-level LRU caching                 │
│                             │     │                                          │
│  Performance: <5ms cached   │     │  Performance: <1ms                       │
└─────────────────────────────┘     └─────────────────────────────────────────┘
```

## Key Files

| File | Purpose |
|------|---------|
| `core/dependencies/accent_auth.py` | FastAPI dependencies for authentication |
| `core/acl/__init__.py` | ACL module exports |
| `core/acl/access_check.py` | Core pattern matching engine |
| `core/acl/checker.py` | Programmatic ACL checker for business logic |
| `core/acl/derivation.py` | UI permission parsing (read-only display) |
| `infra/auth/accent_auth.py` | Accent-Auth client wrapper |
| `infra/auth/__init__.py` | Auth module exports |
| `core/settings/auth.py` | Auth settings configuration |
| `core/schemas/auth.py` | Auth-related Pydantic models |

---

## Quick Usage

### Protect an Endpoint

```python
from typing import Annotated
from fastapi import APIRouter, Depends
from example_service.core.dependencies.accent_auth import require_acl
from example_service.core.schemas.auth import AuthUser

router = APIRouter()

@router.get("/users")
async def list_users(
    user: Annotated[AuthUser, Depends(require_acl("users.read"))]
):
    return {"user_id": user.user_id}
```

### Path Parameter Substitution

```python
@router.get("/users/{user_id}/profile")
async def get_profile(
    user_id: str,
    user: Annotated[AuthUser, Depends(require_acl("users.{user_id}.read"))]
):
    # {user_id} is replaced with actual value from path
    # A user with ACL "users.me.read" passes if their auth_id matches user_id
    return {"profile": ...}
```

### Optional Authentication

```python
from example_service.core.dependencies.accent_auth import get_current_user_optional

@router.get("/public")
async def public_endpoint(
    user: Annotated[AuthUser | None, Depends(get_current_user_optional)]
):
    if user:
        return {"message": f"Hello, {user.user_id}"}
    return {"message": "Hello, anonymous"}
```

### Custom ACL Logic

```python
from example_service.infra.auth import AccentAuthACL

@router.delete("/items/{item_id}")
async def delete_item(
    item_id: str,
    user: Annotated[AuthUser, Depends(get_current_user)],
):
    acl = AccentAuthACL(
        user.permissions,
        auth_id=user.user_id,
        session_id=user.metadata.get("session_uuid"),
    )

    # Allow if admin OR owner
    if not acl.has_any_permission("admin.items.delete", f"items.{item_id}.owner"):
        raise HTTPException(403, "Access denied")

    return {"deleted": True}
```

---

## ACL Pattern Reference

| Pattern | Matches | Example |
|---------|---------|---------|
| `service.resource.action` | Exact | `users.read` |
| `service.resource.*` | Single wildcard | `users.*` → `users.read`, `users.create` |
| `service.#` | Recursive | `users.#` → `users.a.b.c` |
| `!pattern` | Negation | `!users.delete` denies even if `users.*` grants |
| `me` | Current user | `users.me.read` → `users.{auth_id}.read` |
| `my_session` | Current session | `sessions.my_session.delete` |

---

## Configuration

```env
# Required
AUTH_SERVICE_URL=http://accent-auth:9497

# Optional
AUTH_SERVICE_TOKEN=service-token-for-admin-ops
AUTH_REQUEST_TIMEOUT=5.0
AUTH_TOKEN_CACHE_TTL=300
REDIS_URL=redis://localhost:6379/0
```

---

## Dependencies Available

| Dependency | Use Case |
|------------|----------|
| `get_current_user` | Require authentication |
| `get_current_user_optional` | Optional authentication |
| `require_acl("pattern")` | Require specific ACL |
| `require_any_acl(*patterns)` | Require any of multiple ACLs |
| `require_all_acls(*patterns)` | Require all ACLs |
| `require_superuser()` | Require `#` wildcard |

---

## Imports

```python
# FastAPI Dependencies
from example_service.core.dependencies.accent_auth import (
    get_current_user,
    get_current_user_optional,
    require_acl,
    require_any_acl,
    require_all_acls,
    require_superuser,
)

# ACL Utilities
from example_service.core.acl import ACLChecker, get_cached_access_check
from example_service.infra.auth import AccentAuthACL, get_accent_auth_client

# Models
from example_service.core.schemas.auth import AuthUser

```

---

## Performance

| Operation | First Request | Cached |
|-----------|--------------|--------|
| Token validation | 50-200ms | <5ms (Redis) |
| ACL pattern match | <1ms | <0.1ms (LRU) |
| Full auth check | 50-200ms | <5ms |

### Caching Strategy

```
First Request:
  X-Auth-Token → Redis Miss → Accent-Auth API (~150ms) → Cache (5 min) → Return

Subsequent Requests:
  X-Auth-Token → Redis Hit (<5ms) → Return
```

---

## Key Differences from Generic Auth

| Aspect | Generic Auth | Accent-Auth |
|--------|-------------|-------------|
| **Header** | `Authorization: Bearer token` | `X-Auth-Token: token` |
| **Tenant** | `X-Tenant-ID: slug` | `Accent-Tenant: uuid` |
| **Authorization** | Roles + Permissions | ACL (dot-notation) |
| **Wildcards** | Not supported | `*` (single), `#` (multi) |
| **Negation** | Not supported | `!acl` prefix |
| **Reserved Words** | Not supported | `me`, `my_session` |
| **Token Type** | JWT (local decode) | Opaque (external validation) |

---

## accent-auth-client Requirement

The `accent-auth-client` library is **required** for this integration:

```bash
pip install accent-auth-client
```

The library provides:
- `accent_auth_client.Client` for token operations
- Wrapped with `asyncio.to_thread` for async compatibility
- Full feature support for token validation, checking, and revocation

---

## Related Documentation

- [Accent-Auth Integration Guide](accent-auth-integration.md) - Comprehensive guide
- [Using accent-auth-client Library](using-accent-auth-client.md) - Admin operations
- [Accent-Auth Lifespan](accent-auth-lifespan.md) - Application lifecycle

---

**Updated**: 2025-12-02
**Version**: 2.0.0
