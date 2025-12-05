# Development Mode Authentication

## Overview

Development mode allows you to bypass Accent-Auth authentication during local development and testing. This is useful when:

- Developing UI components without running external auth services
- Testing endpoints with different user personas
- Running integration tests without complex auth setup
- Demonstrating features in development environments

**CRITICAL SECURITY NOTE**: Development mode is completely blocked in production environments. Any attempt to enable it in production will cause the application to fail at startup with a `ValueError`.

## Configuration

### Basic Setup

Enable development mode in `.env`:

```bash
# Enable dev mode
AUTH_DEV_MODE=true

# Choose default persona (admin, user, readonly, service, multitenant_admin, limited_user)
AUTH_DEV_MOCK_USER=admin
```

### Available Personas

| Persona | User Type | Permissions | ACL Patterns | Use Case |
|---------|-----------|-------------|--------------|----------|
| `admin` | User | Full access | `#` (superuser wildcard) | Testing admin operations |
| `user` | User | Standard permissions | `confd.users.me.read`, `webhookd.subscriptions.*.read` | Testing normal user flows |
| `readonly` | User | Read-only | `confd.*.*.read`, `webhookd.*.*.read` | Testing viewer roles |
| `service` | Service | Service-level access | `*.*.*` | Testing service-to-service calls |
| `multitenant_admin` | User | Cross-tenant admin | `#`, `*.*.*` | Testing multi-tenant scenarios |
| `limited_user` | User | Very specific ACLs | `confd.users.me.{read,update}` | Testing fine-grained permissions |

### Quick Persona Switching

Override the persona without changing config files:

```bash
# Run with different persona
AUTH_DEV_MOCK_USER=readonly uvicorn example_service.app.main:app

# Or export for entire session
export AUTH_DEV_MOCK_USER=user
uvicorn example_service.app.main:app
```

### Custom Personas

Define custom personas in YAML configuration (`conf/auth.yaml`):

```yaml
# conf/auth.yaml
dev_mode: true
dev_mock_user: custom_analyst
dev_mock_users:
  custom_analyst:
    user_id: analyst-001
    email: analyst@dev.local
    roles:
      - analyst
      - user
    permissions:
      - reports:read
      - analytics:read
      - dashboards:*
    acl:
      - "confd.users.*.read"
      - "reportd.reports.*"
      - "analyticsd.dashboards.#"
    metadata:
      tenant_uuid: acme-tenant-123
      tenant_slug: acme-corp
      session_uuid: dev-session-analyst
      name: Data Analyst
      department: Analytics
```

## Usage Examples

### Testing Protected Endpoints

```python
# No auth headers needed in dev mode!
import httpx

async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
    response = await client.get("/api/v1/users/me")
    # Returns mock user based on AUTH_DEV_MOCK_USER
    assert response.status_code == 200
```

### Multi-Tenant Testing

All mock users include tenant context by default:

```python
from example_service.core.dependencies.accent_auth import get_current_user
from example_service.core.dependencies.tenant import TenantContextDep

@router.get("/tenant-data")
async def get_data(
    user: Annotated[AuthUser, Depends(get_current_user)],
    tenant: TenantContextDep,
):
    # In dev mode:
    # user.tenant_id == "dev-tenant-001"
    # user.tenant_uuid == "dev-tenant-001"
    # tenant.tenant_slug == "dev-tenant"

    return {
        "user": user.user_id,
        "tenant": tenant.tenant_slug,
        "data": query_tenant_data(tenant.tenant_id),
    }
```

### Testing ACL Patterns

```python
from example_service.core.dependencies.accent_auth import require_acl

# Test Accent-Auth ACL wildcards
@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    user: Annotated[AuthUser, Depends(require_acl("confd.users.delete"))],
):
    # admin persona has "#" - passes ✓
    # user persona lacks delete - fails ✗
    # multitenant_admin has "#" - passes ✓
    # limited_user lacks delete - fails ✗
    pass

@router.get("/users/{user_id}")
async def get_user(
    user_id: str,
    user: Annotated[AuthUser, Depends(require_acl("confd.users.{user_id}.read"))],
):
    # Path parameter substitution works in dev mode
    # limited_user has "confd.users.me.read" - passes if user_id matches ✓
    pass
```

### Testing with Different Personas

```python
import pytest
import os

async def test_admin_can_delete_users(client, dev_mode_persona):
    """Test admin persona has delete permissions."""
    dev_mode_persona("admin")

    response = await client.delete("/api/v1/users/123")
    assert response.status_code == 200

async def test_readonly_cannot_delete_users(client, dev_mode_persona):
    """Test readonly persona lacks delete permissions."""
    dev_mode_persona("readonly")

    response = await client.delete("/api/v1/users/123")
    assert response.status_code == 403

async def test_limited_user_specific_access(client, dev_mode_persona):
    """Test limited_user persona has very specific ACLs."""
    dev_mode_persona("limited_user")

    # Can read own profile
    response = await client.get("/api/v1/users/me")
    assert response.status_code == 200

    # Cannot read admin data
    response = await client.get("/api/v1/admin/settings")
    assert response.status_code == 403
```

## Testing Strategy

### Unit Tests with Dev Mode

```python
import pytest
from example_service.core.settings.loader import clear_settings_cache

@pytest.fixture
def dev_mode_enabled(monkeypatch):
    """Enable dev mode for tests."""
    monkeypatch.setenv("APP_ENVIRONMENT", "development")
    monkeypatch.setenv("AUTH_DEV_MODE", "true")
    monkeypatch.setenv("AUTH_DEV_MOCK_USER", "admin")
    clear_settings_cache()
    yield
    clear_settings_cache()

async def test_protected_endpoint(client, dev_mode_enabled):
    """Test endpoint with dev mode authentication."""
    response = await client.get("/api/v1/admin/users")
    assert response.status_code == 200
```

### Integration Tests with Personas

```python
@pytest.fixture
def dev_mode_persona(monkeypatch):
    """Factory fixture for testing with different personas."""
    from example_service.core.settings.loader import clear_settings_cache

    def set_persona(persona: str):
        monkeypatch.setenv("APP_ENVIRONMENT", "development")
        monkeypatch.setenv("AUTH_DEV_MODE", "true")
        monkeypatch.setenv("AUTH_DEV_MOCK_USER", persona)
        clear_settings_cache()

    yield set_persona
    clear_settings_cache()

async def test_permission_boundaries(client, dev_mode_persona):
    """Test different personas respect permission boundaries."""

    # Admin can access everything
    dev_mode_persona("admin")
    response = await client.get("/api/v1/admin/settings")
    assert response.status_code == 200

    # Regular user cannot access admin endpoints
    dev_mode_persona("user")
    response = await client.get("/api/v1/admin/settings")
    assert response.status_code == 403

    # Service account has service-level access
    dev_mode_persona("service")
    response = await client.post("/api/v1/internal/jobs")
    assert response.status_code == 200
```

## Production Safety

### Automatic Blocking

Dev mode is automatically blocked in production through a Pydantic model validator:

```python
# This will raise ValueError at startup!
# Environment: production
# AUTH_DEV_MODE: true

# Error message:
# "CRITICAL SECURITY ERROR: Development mode (AUTH_DEV_MODE=true)
#  is enabled in production environment. This bypasses all authentication
#  and MUST NOT be used in production. Set AUTH_DEV_MODE=false."
```

### Environment Detection

The safety check uses `APP_ENVIRONMENT` from app settings:

```bash
# ✓ Safe - development
APP_ENVIRONMENT=development AUTH_DEV_MODE=true

# ✓ Safe - test
APP_ENVIRONMENT=test AUTH_DEV_MODE=true

# ✗ BLOCKED - production
APP_ENVIRONMENT=production AUTH_DEV_MODE=true  # Startup fails!
```

### Logging and Observability

Dev mode logs a **WARNING** for every authenticated request:

```json
{
  "level": "WARNING",
  "message": "DEV MODE: Using mock authentication",
  "persona": "admin",
  "user_id": "dev-admin-001",
  "tenant_uuid": "dev-tenant-001",
  "acl_count": 1,
  "dev_mode": true,
  "timestamp": "2025-12-05T10:30:00Z"
}
```

This makes it immediately obvious if dev mode is accidentally enabled.

## Troubleshooting

### Dev Mode Not Working

1. **Check environment variable:**
   ```bash
   echo $AUTH_DEV_MODE  # Should be "true"
   ```

2. **Clear settings cache:**
   ```python
   from example_service.core.settings.loader import clear_settings_cache
   clear_settings_cache()
   ```

3. **Check environment:**
   ```bash
   echo $APP_ENVIRONMENT  # Should NOT be "production"
   ```

4. **Review logs for validation errors:**
   ```bash
   # Look for "CRITICAL SECURITY ERROR" messages
   tail -f logs/app.log | grep -i "dev mode"
   ```

### Invalid Persona Error

```bash
# Error: Mock user persona 'typo' not found
AUTH_DEV_MOCK_USER=typo  # ✗ Invalid

# Available personas
# admin, user, readonly, service, multitenant_admin, limited_user
AUTH_DEV_MOCK_USER=admin  # ✓ Valid
```

### Tenant Context Missing

Ensure mock user includes tenant metadata:

```yaml
# ✗ Missing tenant context
dev_mock_users:
  myuser:
    user_id: test-001
    roles: ["user"]
    # Missing metadata!

# ✓ Correct with tenant context
dev_mock_users:
  myuser:
    user_id: test-001
    roles: ["user"]
    metadata:
      tenant_uuid: required-for-multi-tenancy
      tenant_slug: required-for-storage
      session_uuid: required-for-session-tracking
```

### ACL Permissions Not Working

Check ACL pattern syntax:

```python
# Accent-Auth ACL patterns use dot-notation
"confd.users.read"     # ✓ Correct
"confd.users.*"        # ✓ Single-level wildcard
"confd.#"              # ✓ Multi-level wildcard
"#"                    # ✓ Superuser wildcard

"users:read"           # ✗ Wrong format (colon separator)
"confd/users/read"     # ✗ Wrong format (slash separator)
```

## Migration Notes

### From Manual Mocking

**Before** (manual mocking in tests):

```python
async def test_endpoint(client, monkeypatch):
    # Manually mock auth dependency
    async def mock_auth():
        return AuthUser(
            user_id="test-001",
            email="test@example.com",
            roles=["user"],
            permissions=["users:read"],
            metadata={"tenant_uuid": "test-tenant"},
        )

    app.dependency_overrides[get_current_user] = mock_auth
    response = await client.get("/protected")
```

**After** (use dev mode):

```python
async def test_endpoint(client, dev_mode_enabled):
    # Dev mode handles mocking automatically
    response = await client.get("/protected")
    # Uses default admin persona with full permissions
```

### Backward Compatibility

- ✅ Existing tests continue to work
- ✅ Manual dependency overrides still function
- ✅ Dev mode is opt-in via configuration
- ✅ Default is `dev_mode=false` (safe by default)
- ✅ No breaking changes to existing code

## Best Practices

1. **Never commit `AUTH_DEV_MODE=true` to production configs**
   - Use `.env.local` for local overrides
   - Add `.env.local` to `.gitignore`

2. **Use specific personas for specific tests**
   - Don't always use `admin` with full permissions
   - Test permission boundaries with `readonly` and `limited_user`

3. **Test multi-tenant scenarios**
   - Use `multitenant_admin` to test cross-tenant access
   - Ensure tenant isolation works correctly

4. **Document custom personas**
   - Add comments explaining why custom personas exist
   - Include ACL patterns in persona descriptions

5. **Keep tenant context realistic**
   - Use real tenant UUIDs and slugs from your system
   - Test tenant-scoped queries and filters

6. **Monitor dev mode logs**
   - Look for unexpected dev mode warnings in logs
   - Ensure dev mode is not accidentally enabled

## Performance Considerations

### Dev Mode Impact

| Operation | Production | Dev Mode |
|-----------|------------|----------|
| Auth check | 50-200ms (Accent-Auth) | <1ms (in-memory) |
| Cache lookup | 5ms (Redis) | 0ms (no cache needed) |
| Token validation | 50-200ms (external API) | 0ms (skip validation) |
| Total latency | ~50-200ms per request | ~<1ms per request |

**Note**: Dev mode is significantly faster since it bypasses all external API calls and cache lookups.

## Security Checklist

Before deploying to production:

- [ ] `AUTH_DEV_MODE` is set to `false` or not set at all
- [ ] `APP_ENVIRONMENT` is set to `production`
- [ ] No dev mode environment variables in production configs
- [ ] Application starts successfully (no "CRITICAL SECURITY ERROR")
- [ ] Logs do not contain "DEV MODE: Using mock authentication"
- [ ] Accent-Auth service is properly configured and reachable
- [ ] Authentication tests pass with real Accent-Auth tokens

## See Also

- [Authentication Architecture](../architecture/authentication.md)
- [Multi-Tenancy Guide](../features/multi-tenancy.md)
- [Testing Guide](../testing/integration-tests.md)
- [Accent-Auth Integration](../integrations/accent-auth.md)
