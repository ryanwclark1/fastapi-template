# Multi-Tenancy Architecture

This document explains the tenant context system used for multi-tenant data isolation.

## Overview

The service supports multi-tenancy through a **two-layer architecture**:

1. **Dependency Layer** - FastAPI dependencies for endpoint-level tenant resolution
2. **Context Variable Layer** - Python `contextvars` for request-scoped tenant propagation

These layers are connected via a **bridge** that ensures tenant context flows from HTTP requests to database queries.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         HTTP Request                                 │
│                    (JWT with tenant metadata)                        │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    FastAPI Dependency Layer                          │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  get_tenant_context()                                        │    │
│  │  ├── get_tenant_context_from_user() → JWT metadata          │    │
│  │  └── get_tenant_context_from_header() → X-Tenant-ID header  │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                           │                                          │
│                           │ Returns: TenantContext (storage)         │
│                           │ Sets: middleware context var (bridge)    │
│                           ▼                                          │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                    ┌─────────────┴─────────────┐
                    │                           │
                    ▼                           ▼
┌──────────────────────────────┐  ┌──────────────────────────────────┐
│      Endpoint Handler        │  │    Context Variable Layer         │
│                              │  │                                    │
│  Uses TenantContext for:     │  │  ┌────────────────────────────┐   │
│  • Storage bucket resolution │  │  │  _tenant_context (contextvar) │   │
│  • Audit logging             │  │  └────────────────────────────┘   │
│  • Feature flags             │  │              │                     │
└──────────────────────────────┘  │              ▼                     │
                                  │  ┌────────────────────────────┐   │
                                  │  │  TenantAwareSession         │   │
                                  │  │  (automatic query filtering) │   │
                                  │  └────────────────────────────┘   │
                                  └──────────────────────────────────┘
```

## Components

### 1. Dependency Layer (`core/dependencies/tenant.py`)

The primary interface for tenant resolution in endpoints.

```python
from example_service.core.dependencies.tenant import TenantContextDep

@router.post("/files/upload")
async def upload_file(
    file: UploadFile,
    tenant: TenantContextDep,  # Resolved from JWT or header
    storage: StorageServiceDep,
):
    # tenant.tenant_uuid - Unique tenant identifier
    # tenant.tenant_slug - URL-friendly identifier
    result = await storage.upload_file(file, tenant_context=tenant)
    return result
```

**Resolution Priority:**
1. JWT metadata (`tenant_uuid`, `tenant_slug` fields)
2. `X-Tenant-ID` header (fallback for service-to-service calls)

### 2. Context Variable Layer (`app/middleware/tenant.py`)

Low-level context propagation for non-dependency contexts.

```python
from example_service.app.middleware.tenant import (
    get_tenant_context,
    set_tenant_context,
    require_tenant,
    clear_tenant_context,
)

# Used internally by TenantAwareSession
context = get_tenant_context()
if context:
    print(f"Current tenant: {context.tenant_id}")
```

**When to use directly:**
- Background tasks that need tenant context
- Database session hooks
- Custom middleware

### 3. The Bridge

The dependency layer automatically bridges to the context variable layer:

```python
# In core/dependencies/tenant.py - get_tenant_context()

# After resolving tenant from JWT/header:
if context:
    # Bridge to middleware context var for database layer
    schema_context = SchemaTenantContext(
        tenant_id=context.tenant_uuid,
        identified_by=source,  # "jwt" or "header"
    )
    set_middleware_tenant_context(schema_context)
```

This ensures that when you use `TenantContextDep` in an endpoint, the `TenantAwareSession` can automatically filter database queries.

## TenantContext Schemas

Two `TenantContext` classes exist for different purposes:

| Schema | Location | Fields | Purpose |
|--------|----------|--------|---------|
| Storage | `infra/storage/backends/protocol.py` | `tenant_uuid`, `tenant_slug`, `metadata` | Storage operations, bucket resolution |
| Schema | `core/schemas/tenant.py` | `tenant_id`, `identified_by`, `created_at` | Database filtering, audit trails |

The bridge maps between them:
- `tenant_uuid` → `tenant_id`
- Resolution source → `identified_by`

## Database Tenancy

### TenantMixin

Add tenant isolation to database models:

```python
from example_service.core.database.tenancy import TenantMixin

class Post(Base, TenantMixin, TimestampMixin):
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True)
    title = Column(String(255))
    # tenant_id column added automatically by TenantMixin
```

### TenantAwareSession

Automatically filters queries by tenant:

```python
from example_service.core.database.tenancy import TenantAwareSession

# When tenant context is set (via dependency bridge):
async with TenantAwareSession(engine) as session:
    # This query automatically includes: WHERE tenant_id = <current_tenant>
    posts = await session.execute(select(Post))
```

## Usage Patterns

### Pattern 1: Standard Endpoint (Recommended)

```python
from example_service.core.dependencies.tenant import TenantContextDep

@router.get("/items")
async def list_items(
    tenant: TenantContextDep,
    db: AsyncSession = Depends(get_db_session),
):
    # Tenant context is set - TenantAwareSession works automatically
    # For manual operations, use tenant.tenant_uuid
    items = await db.execute(select(Item))
    return items.scalars().all()
```

### Pattern 2: Optional Tenant (Public + Tenant Routes)

```python
@router.get("/resources/{id}")
async def get_resource(
    id: str,
    tenant: TenantContextDep,  # Can be None for public resources
):
    if tenant:
        # Tenant-specific logic
        return await get_tenant_resource(id, tenant.tenant_uuid)
    else:
        # Public resource logic
        return await get_public_resource(id)
```

### Pattern 3: Background Tasks

```python
from example_service.app.middleware.tenant import set_tenant_context, clear_tenant_context
from example_service.core.schemas.tenant import TenantContext

async def process_tenant_data(tenant_id: str):
    # Manually set context for background task
    context = TenantContext(tenant_id=tenant_id, identified_by="background_task")
    set_tenant_context(context)

    try:
        # TenantAwareSession will now filter by this tenant
        await do_work()
    finally:
        clear_tenant_context()
```

## Testing

### Mocking Tenant Context

```python
from example_service.core.dependencies.tenant import get_tenant_context
from example_service.infra.storage.backends import TenantContext

async def test_endpoint_with_tenant(client, app):
    # Override the dependency
    async def mock_tenant():
        return TenantContext(
            tenant_uuid="test-tenant-uuid",
            tenant_slug="test-tenant",
        )

    app.dependency_overrides[get_tenant_context] = mock_tenant

    response = await client.get("/items")
    assert response.status_code == 200
```

### Testing Context Variable Layer

```python
from example_service.app.middleware.tenant import (
    set_tenant_context,
    get_tenant_context,
    clear_tenant_context,
)
from example_service.core.schemas.tenant import TenantContext

def test_tenant_context_propagation():
    clear_tenant_context()

    context = TenantContext(tenant_id="test", identified_by="test")
    set_tenant_context(context)

    retrieved = get_tenant_context()
    assert retrieved.tenant_id == "test"

    clear_tenant_context()
```

## Migration Notes

### From Middleware-Based Tenancy

If you previously used `TenantMiddleware` with strategies (header, subdomain, path-prefix):

1. **For JWT-based tenancy**: Use `TenantContextDep` dependency (current approach)
2. **For subdomain tenancy**: Implement custom middleware or use a reverse proxy
3. **For path-prefix tenancy**: Use FastAPI's router prefix feature

The strategy classes (`HeaderTenantStrategy`, `SubdomainTenantStrategy`, etc.) have been removed in favor of the simpler dependency-based approach.

## Related Documentation

- [Accent Auth Integration](../integrations/accent-auth-integration.md) - JWT authentication
- [Database Guide](../database/database-guide.md) - Database patterns
- [Storage Features](../features/storage.md) - Multi-tenant storage
