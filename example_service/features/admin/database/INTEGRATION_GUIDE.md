# Database Admin Router Integration Guide

This document provides step-by-step instructions for integrating the database admin router into the main application once it's implemented.

## Current Status

The following components are **ready**:
- ✓ Pydantic schemas (`schemas.py`)
- ✓ Package structure (`__init__.py`)
- ✓ Dependency injection skeleton (`dependencies.py`)
- ✓ Documentation (`README.md`)

The following components are **pending implementation**:
- ⏳ Data Access Object (`dao.py`)
- ⏳ Service layer (`service.py`)
- ⏳ FastAPI router (`router.py`)

## Integration Steps

Once `router.py` is implemented, follow these steps to integrate it into the application:

### Step 1: Import the Router

Add the router import to `/home/administrator/Code/fastapi-template/example_service/app/router.py`:

**Location**: After line 13 (after the email admin router import)

```python
# Current line 13:
from example_service.features.admin.email import router as admin_email_router

# Add after line 13:
from example_service.features.admin.database import router as admin_database_router
```

### Step 2: Register the Router

Add the router registration in the `setup_routers()` function.

**Location**: After line 86 (after the admin_email_router registration)

```python
# Current lines 85-91:
app.include_router(email_router, prefix=api_prefix, tags=["email-configuration"])
app.include_router(admin_email_router, prefix=api_prefix, tags=["admin-email"])
logger.info(
    "Email configuration endpoints registered at %s/email and %s/admin/email",
    api_prefix,
    api_prefix,
)

# Add after line 91:
app.include_router(admin_database_router, prefix=api_prefix, tags=["admin-database"])
logger.info("Database admin router registered at %s/admin/database", api_prefix)
```

### Step 3: Update Package Exports

Update `/home/administrator/Code/fastapi-template/example_service/features/admin/database/__init__.py`:

**Uncomment** line 35 and line 50:

```python
# Change from:
# from .router import router

# To:
from .router import router

# And change from:
# "router",  # TODO: Uncomment when router is implemented

# To:
"router",
```

### Step 4: Update Dependencies

Once DAO and Service are implemented, update the `dependencies.py` file:

1. Uncomment the import statements (lines 11-12):
```python
from .dao import DatabaseAdminDAO
from .service import DatabaseAdminService
```

2. Update the `get_admin_dao()` function to return `DatabaseAdminDAO`:
```python
async def get_admin_dao(
    session: SessionDep,
) -> AsyncGenerator[DatabaseAdminDAO]:  # Update return type
    """Get database admin DAO instance."""
    dao = DatabaseAdminDAO(session=session)
    yield dao
```

3. Update the `get_admin_service()` function to return `DatabaseAdminService`:
```python
async def get_admin_service(
    session: SessionDep,
    settings: AdminSettingsDep,
) -> AsyncGenerator[DatabaseAdminService]:  # Update return type
    """Get database admin service instance."""
    dao = DatabaseAdminDAO(session=session)
    service = DatabaseAdminService(dao=dao, settings=settings)
    yield service
```

4. Uncomment the type aliases (lines 71-72):
```python
AdminDAODep = Annotated[DatabaseAdminDAO, Depends(get_admin_dao)]
AdminServiceDep = Annotated[DatabaseAdminService, Depends(get_admin_service)]
```

5. Update `__all__` exports (lines 75-80):
```python
__all__ = [
    "SessionDep",
    "AdminSettingsDep",
    "get_admin_dao",
    "get_admin_service",
    "AdminDAODep",      # Uncomment
    "AdminServiceDep",  # Uncomment
]
```

## Router Implementation Pattern

When implementing `router.py`, follow the pattern from `admin/email/router.py`:

```python
"""Admin endpoints for database system management.

This module provides administrative endpoints for:
- Database health monitoring
- Connection pool statistics
- Table and index health metrics
- Active query monitoring
- Database statistics
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Query

if TYPE_CHECKING:
    from example_service.features.admin.database.dependencies import (
        AdminServiceDep,
    )

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/database", tags=["admin-database"])


@router.get(
    "/health",
    summary="Check database health",
    description="Get comprehensive database health status and diagnostics.",
)
async def get_database_health(
    service: AdminServiceDep,
) -> DatabaseHealth:
    """Get database health status."""
    return await service.get_health()

# ... more endpoints
```

## Expected Endpoint Structure

Once integrated, the following endpoints will be available:

```
GET  /api/v1/admin/database/health               - Database health check
GET  /api/v1/admin/database/pool-stats          - Connection pool statistics
GET  /api/v1/admin/database/tables              - List all tables with size info
GET  /api/v1/admin/database/tables/{name}       - Get specific table info
GET  /api/v1/admin/database/indexes             - List all indexes with health
GET  /api/v1/admin/database/indexes/{name}      - Get specific index info
GET  /api/v1/admin/database/queries/active      - List active queries
GET  /api/v1/admin/database/stats               - Database statistics
GET  /api/v1/admin/database/audit-logs          - Query audit logs
```

## Testing Integration

After integration, verify with:

```bash
# Start the application
uv run uvicorn example_service.app.main:app --reload

# Check OpenAPI docs
curl http://localhost:8000/docs

# Verify the admin database endpoints appear under "admin-database" tag

# Test health endpoint (requires auth)
curl -H "X-Auth-Token: your-token" http://localhost:8000/api/v1/admin/database/health
```

## Configuration

Ensure the following environment variables are set:

```bash
# Enable the feature
ADMIN_ENABLED=true

# Configure rate limiting
ADMIN_RATE_LIMIT_ENABLED=true
ADMIN_RATE_LIMIT_MAX_OPS=5
ADMIN_RATE_LIMIT_WINDOW_SECONDS=60

# Set query timeouts
ADMIN_DEFAULT_QUERY_TIMEOUT_SECONDS=30
ADMIN_HEALTH_CHECK_TIMEOUT_SECONDS=10
```

## OpenAPI Documentation

The integrated router will automatically appear in:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

All endpoints will be grouped under the **admin-database** tag.

## Rollback

If you need to temporarily disable the admin database router:

1. Comment out the import in `router.py`:
   ```python
   # from example_service.features.admin.database import router as admin_database_router
   ```

2. Comment out the registration:
   ```python
   # app.include_router(admin_database_router, prefix=api_prefix, tags=["admin-database"])
   # logger.info("Database admin router registered at %s/admin/database", api_prefix)
   ```

3. Or use the feature flag:
   ```bash
   ADMIN_ENABLED=false
   ```

## Next Steps

1. Implement `dao.py` with database query methods
2. Implement `service.py` with business logic
3. Implement `router.py` with FastAPI endpoints
4. Follow this integration guide to wire everything together
5. Add comprehensive tests
6. Update OpenAPI documentation as needed

## Reference Files

- Main router registry: `/home/administrator/Code/fastapi-template/example_service/app/router.py`
- Admin settings: `/home/administrator/Code/fastapi-template/example_service/core/settings/admin.py`
- Similar pattern: `/home/administrator/Code/fastapi-template/example_service/features/admin/email/router.py`
