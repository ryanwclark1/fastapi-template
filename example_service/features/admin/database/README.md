# Database Administration Feature

This module provides comprehensive database administration capabilities including monitoring, diagnostics, and management operations.

## Overview

The database admin feature exposes endpoints for:
- **Health Monitoring**: Real-time database health status and diagnostics
- **Connection Pool Statistics**: Monitor connection pool utilization
- **Table & Index Health**: Size metrics, bloat detection, and usage statistics
- **Active Query Monitoring**: Track currently executing queries
- **Database Statistics**: Aggregate metrics and performance indicators
- **Audit Logging**: Track administrative operations for compliance

## Architecture

The feature follows the standard three-tier architecture:

```
┌─────────────────────────────────────────────────────┐
│                   Router Layer                      │
│  (HTTP endpoints, validation, response formatting)  │
└─────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────┐
│                  Service Layer                      │
│     (Business logic, authorization, orchestration)   │
└─────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────┐
│                    DAO Layer                        │
│      (Database queries, data transformation)         │
└─────────────────────────────────────────────────────┘
```

### Components

- **schemas.py**: Pydantic models for request/response data (✓ Implemented)
- **dependencies.py**: FastAPI dependency injection setup (✓ Skeleton created)
- **dao.py**: Data access layer for database operations (TODO)
- **service.py**: Business logic and orchestration (TODO)
- **router.py**: FastAPI route handlers and endpoints (TODO)

## API Endpoints

Once implemented, the following endpoints will be available:

### Health Monitoring

```
GET /api/v1/admin/database/health
```
Returns comprehensive database health check including:
- Connection pool statistics
- Database size
- Active connections count
- Cache hit ratio
- Replication lag (if applicable)
- Health warnings

**Response**: `DatabaseHealth`

### Connection Pool Statistics

```
GET /api/v1/admin/database/pool-stats
```
Returns detailed connection pool metrics:
- Active connections
- Idle connections
- Pool utilization percentage

**Response**: `ConnectionPoolStats`

### Table Size Information

```
GET /api/v1/admin/database/tables
GET /api/v1/admin/database/tables/{table_name}
```
Returns table size and row count statistics.

**Response**: `list[TableSizeInfo]` or `TableSizeInfo`

### Index Health

```
GET /api/v1/admin/database/indexes
GET /api/v1/admin/database/indexes/{index_name}
```
Returns index health metrics including size, usage, and bloat.

**Response**: `list[IndexHealthInfo]` or `IndexHealthInfo`

### Active Queries

```
GET /api/v1/admin/database/queries/active
```
Returns currently executing database queries.

**Response**: `list[ActiveQuery]`

### Database Statistics

```
GET /api/v1/admin/database/stats
```
Returns aggregate database statistics and metrics.

**Response**: `DatabaseStats`

### Audit Logs

```
GET /api/v1/admin/database/audit-logs
```
Query administrative audit logs with filtering.

**Query Parameters**: `AuditLogFilters`
**Response**: `AuditLogListResponse`

## Authentication & Authorization

All admin endpoints require:
- **Authentication**: Valid X-Auth-Token header (Accent-Auth)
- **Authorization**: Superuser role or specific ACL permissions

Example:
```python
from example_service.core.dependencies.auth import require_superuser

@router.get("/admin/database/health")
async def get_health(
    user: Annotated[User, Depends(require_superuser)],
    service: AdminServiceDep,
) -> DatabaseHealth:
    return await service.get_health()
```

## Configuration

Settings are managed through `example_service.core.settings.admin.AdminSettings`:

```bash
# Feature toggle
ADMIN_ENABLED=true

# Rate limiting
ADMIN_RATE_LIMIT_ENABLED=true
ADMIN_RATE_LIMIT_MAX_OPS=5
ADMIN_RATE_LIMIT_WINDOW_SECONDS=60

# Query timeouts
ADMIN_DEFAULT_QUERY_TIMEOUT_SECONDS=30
ADMIN_HEALTH_CHECK_TIMEOUT_SECONDS=10

# Health thresholds
ADMIN_CONNECTION_POOL_CRITICAL_THRESHOLD=90.0
ADMIN_CONNECTION_POOL_WARNING_THRESHOLD=75.0
ADMIN_CACHE_HIT_RATIO_WARNING_THRESHOLD=85.0

# Audit retention
ADMIN_AUDIT_LOG_RETENTION_DAYS=90
```

## Usage Examples

### Check Database Health

```python
import httpx

async with httpx.AsyncClient() as client:
    response = await client.get(
        "http://localhost:8000/api/v1/admin/database/health",
        headers={"X-Auth-Token": "your-token"},
    )
    health = response.json()
    print(f"Database status: {health['status']}")
    print(f"Pool utilization: {health['connection_pool']['utilization_percent']}%")
```

### Get Top Tables by Size

```python
async with httpx.AsyncClient() as client:
    response = await client.get(
        "http://localhost:8000/api/v1/admin/database/stats",
        headers={"X-Auth-Token": "your-token"},
    )
    stats = response.json()
    for table in stats['top_tables'][:5]:
        print(f"{table['table_name']}: {table['total_size_human']}")
```

### Monitor Active Queries

```python
async with httpx.AsyncClient() as client:
    response = await client.get(
        "http://localhost:8000/api/v1/admin/database/queries/active",
        headers={"X-Auth-Token": "your-token"},
    )
    queries = response.json()
    long_running = [q for q in queries if q['duration_seconds'] > 30]
    for query in long_running:
        print(f"Long query (PID {query['pid']}): {query['duration_seconds']}s")
```

## Development Notes

### Implementation Checklist

- [x] Define Pydantic schemas for all response models
- [x] Create package structure and __init__.py
- [x] Set up dependency injection skeleton
- [x] Document API endpoints and usage
- [ ] Implement DAO layer with database queries
- [ ] Implement Service layer with business logic
- [ ] Create FastAPI router with all endpoints
- [ ] Add authentication and authorization
- [ ] Add rate limiting for admin operations
- [ ] Implement audit logging
- [ ] Add comprehensive unit tests
- [ ] Add integration tests
- [ ] Add performance tests for heavy queries
- [ ] Update OpenAPI documentation
- [ ] Register router in main application

### Testing Strategy

1. **Unit Tests**:
   - Test DAO queries with mock database
   - Test service logic with mock DAO
   - Test router handlers with mock service

2. **Integration Tests**:
   - Test against real test database
   - Verify health checks return accurate data
   - Test rate limiting enforcement
   - Verify audit log creation

3. **Performance Tests**:
   - Ensure admin queries don't impact production workload
   - Test query timeouts
   - Verify connection pool doesn't get exhausted

### Security Considerations

1. **Query Injection**: All table/index names must be validated against system catalogs
2. **Denial of Service**: Rate limiting prevents abuse of expensive operations
3. **Information Disclosure**: Ensure proper authorization before exposing sensitive data
4. **Audit Trail**: All admin operations must be logged for compliance

### Pattern Reference

Follow the pattern established in `example_service/features/admin/email/`:

1. **Dependencies**: Use AsyncGenerator with proper type hints
2. **Router**: Use prefix `/admin/database`, tags `["admin-database"]`
3. **Service**: Implement business logic, call DAO for data
4. **DAO**: Keep queries focused, return typed results
5. **Schemas**: Use comprehensive Pydantic models with examples

## Related Documentation

- [Admin Settings Configuration](../../../core/settings/admin.py)
- [Database Base Classes](../../../../docs/architecture/database-base-classes.md)
- [Email Admin Pattern](../email/README.md) - Similar implementation pattern

## Integration

Once the router is implemented, it will be registered in `example_service/app/router.py`:

```python
from example_service.features.admin.database import router as admin_database_router

# Add to setup_routers():
app.include_router(admin_database_router, prefix=api_prefix, tags=["admin-database"])
logger.info("Database admin router registered at %s/admin/database", api_prefix)
```
