# Accent-Auth Lifespan Integration

## Overview

This document explains how accent-auth integration is handled during application startup and why it's designed to **NOT block** the application lifecycle.

## Architecture Decision: On-Demand vs. Lifespan

### ✅ Current Design: On-Demand (Recommended)

Accent-auth is **NOT tied to the application lifespan**. Authentication happens on a **per-request basis**.

```python
# Client created on-demand, not during startup
client = get_accent_auth_client()
token_info = await client.validate_token(token)
```

**Benefits:**
- ✅ **Resilient Startup**: Service starts even if accent-auth is temporarily down
- ✅ **Loose Coupling**: Auth service issues don't prevent your service from starting
- ✅ **Auto-Recovery**: When accent-auth recovers, requests automatically work again
- ✅ **Graceful Degradation**: Can serve non-authenticated endpoints while auth is down
- ✅ **Health Visibility**: Can report "degraded mode" without blocking startup

### ❌ Alternative: Lifespan-Tied (Not Recommended)

If accent-auth were initialized in `lifespan.py`:

```python
# ❌ This would block startup if accent-auth is unavailable
async with AccentAuthClient(...) as client:
    await client.validate_token("health-check")  # Fails = service won't start
```

**Drawbacks:**
- ❌ Service won't start if accent-auth is temporarily unavailable
- ❌ Requires app restart when accent-auth recovers
- ❌ All-or-nothing availability (no graceful degradation)
- ❌ Tight coupling between services

---

## Comparison Table

| Aspect | On-Demand (Current) | Lifespan-Tied |
|--------|---------------------|---------------|
| **Startup Speed** | ✅ Fast, no blocking | ❌ Blocks if auth down |
| **Availability** | ✅ Starts even if auth down | ❌ Won't start if auth down |
| **Recovery** | ✅ Auto-recovers | ⚠️ Requires restart |
| **Health Reporting** | ✅ Can report degraded mode | ❌ All-or-nothing |
| **Non-Auth Endpoints** | ✅ Still work if auth down | ❌ All endpoints fail |
| **Observability** | ✅ Optional health checks | ⚠️ Startup logs only |

---

## Optional: Health Check Integration

While accent-auth is **not required for startup**, you can **optionally** monitor its availability via health checks.

### Configuration

```bash
# .env
AUTH_SERVICE_URL=http://accent-auth:9497
AUTH_HEALTH_CHECKS_ENABLED=true  # Enable health monitoring (default: false)
```

### What This Does

When `AUTH_HEALTH_CHECKS_ENABLED=true`:

1. **Startup**: Registers an `AccentAuthHealthProvider` with the health aggregator
2. **Runtime**: Periodically checks accent-auth connectivity via `/health` endpoints
3. **Reporting**: Reports health status in `/api/v1/health` responses

**Critical Point**: Even with health checks enabled, **the service still starts** if accent-auth is unavailable. Health checks are **observability only**.

### Health Check Behavior

```bash
# Accent-auth is available
GET /api/v1/health/
{
  "status": "healthy",
  "components": {
    "accent-auth": {
      "status": "healthy",
      "details": {
        "url": "http://accent-auth:9497",
        "latency_ms": 45.2
      }
    }
  }
}

# Accent-auth is unavailable (service still runs!)
GET /api/v1/health/
{
  "status": "degraded",
  "components": {
    "accent-auth": {
      "status": "unhealthy",
      "details": {
        "url": "http://accent-auth:9497",
        "error": "Connection failed"
      }
    }
  }
}
```

---

## Implementation Details

### 1. No Lifespan Dependency

Accent-auth client is **not initialized** in `lifespan.py` startup:

```python
# example_service/app/lifespan.py

async def lifespan(app: FastAPI):
    # ✅ These are initialized (database, cache, etc.)
    await init_database()
    await start_cache()

    # ❌ Accent-auth is NOT initialized here
    # It's created on-demand per request

    yield

    # ❌ No accent-auth cleanup needed
    await close_database()
    await stop_cache()
```

### 2. On-Demand Client Creation

Client is created when needed:

```python
# example_service/infra/auth/accent_auth.py:314

def get_accent_auth_client() -> AccentAuthClient:
    """Get configured Accent-Auth client instance."""
    settings = get_auth_settings()
    return AccentAuthClient(
        base_url=str(settings.service_url),
        timeout=settings.request_timeout,
        max_retries=settings.max_retries,
    )
```

### 3. Per-Request Validation

Authentication happens in FastAPI dependencies:

```python
# example_service/core/dependencies/accent_auth.py

async def get_current_user(
    request: Request,
    x_auth_token: Annotated[str | None, Header(alias="X-Auth-Token")] = None,
    cache: Annotated[RedisCache, Depends(get_cache)] = None,
) -> AuthUser:
    """Get currently authenticated user.

    This runs on EVERY authenticated request.
    If accent-auth is unavailable, the request fails with 503.
    But the service itself continues running.
    """
    if not x_auth_token:
        raise HTTPException(401, "Authentication required")

    # Create client on-demand
    client = get_accent_auth_client()

    try:
        # Validate token (will retry per client config)
        async with client:
            token_info = await client.validate_token(x_auth_token)
            return convert_to_auth_user(token_info)
    except httpx.ConnectError:
        # Accent-auth unavailable - fail this request only
        raise HTTPException(503, "Authentication service unavailable")
```

### 4. Optional Health Check Registration

Health checks are registered during startup **if enabled**:

```python
# example_service/app/lifespan.py:237-255

# Register Accent-Auth health provider (optional, never blocks startup)
if auth_settings.health_checks_enabled and auth_settings.service_url:
    try:
        from example_service.features.health.accent_auth_provider import (
            AccentAuthHealthProvider,
        )

        aggregator = get_health_aggregator()
        if aggregator:
            aggregator.add_provider(AccentAuthHealthProvider())
            logger.info("Accent-Auth health provider registered")
    except Exception as e:
        logger.warning(
            "Failed to register Accent-Auth health provider",
            extra={"error": str(e)},
        )
```

**Key Points:**
- Only runs if `AUTH_HEALTH_CHECKS_ENABLED=true`
- Wrapped in try/except - never blocks startup
- Logs warning if registration fails

---

## Failure Scenarios

### Scenario 1: Accent-Auth Down at Startup

**Without Health Checks:**
```
[INFO] Application starting
[INFO] Database connection initialized
[INFO] Redis cache initialized
[INFO] Application startup complete
```

**With Health Checks Enabled:**
```
[INFO] Application starting
[INFO] Database connection initialized
[INFO] Redis cache initialized
[INFO] Accent-Auth health provider registered
[INFO] Application startup complete
```

**Result:** Service starts successfully in both cases. Health endpoint will report:
- Without checks: No mention of accent-auth
- With checks: `accent-auth: unhealthy` (but overall status may be `degraded`, not `unhealthy`)

### Scenario 2: Accent-Auth Down During Runtime

```bash
# Request to authenticated endpoint
curl -H "X-Auth-Token: abc123" http://localhost:8000/api/v1/data

HTTP/1.1 503 Service Unavailable
{
  "detail": "Authentication service unavailable"
}
```

**Service Behavior:**
- ✅ Service continues running
- ✅ Non-authenticated endpoints still work
- ✅ Health endpoint shows degraded status (if checks enabled)
- ✅ Logs warning about connection failure
- ✅ Automatically recovers when accent-auth comes back

### Scenario 3: Accent-Auth Recovers

```bash
# Next request automatically works
curl -H "X-Auth-Token: abc123" http://localhost:8000/api/v1/data

HTTP/1.1 200 OK
{
  "user_uuid": "...",
  "data": "..."
}
```

**No restart needed!** The service automatically starts working again.

---

## Best Practices

### 1. Enable Health Checks in Production

```bash
# Production .env
AUTH_HEALTH_CHECKS_ENABLED=true
```

**Why:**
- Monitoring tools can detect accent-auth issues
- Operations team gets early warning
- Helps debug authentication failures

### 2. Monitor Health Endpoints

```bash
# Kubernetes liveness probe (basic)
livenessProbe:
  httpGet:
    path: /api/v1/health/live
    port: 8000

# Kubernetes readiness probe (includes dependencies)
readinessProbe:
  httpGet:
    path: /api/v1/health/ready
    port: 8000
```

**Note:** The readiness probe will fail if accent-auth is down AND health checks are enabled. This prevents routing traffic to instances that can't authenticate.

### 3. Set Reasonable Timeouts

```bash
# Balance between retrying and failing fast
AUTH_REQUEST_TIMEOUT=5.0
AUTH_MAX_RETRIES=3
```

**Why:**
- Too short: False positives on slow networks
- Too long: Slow response times when accent-auth is actually down

### 4. Use Token Caching Aggressively

```bash
# Cache valid tokens for 5 minutes (default)
AUTH_TOKEN_CACHE_TTL=300
AUTH_ENABLE_PERMISSION_CACHING=true
AUTH_ENABLE_ACL_CACHING=true
```

**Why:**
- Reduces load on accent-auth
- 95%+ of requests hit cache (5ms vs 100-200ms)
- Service can handle accent-auth being temporarily slow

---

## Debugging

### Check if Accent-Auth is Configured

```bash
# Check environment
echo $AUTH_SERVICE_URL

# Check at runtime
curl http://localhost:8000/api/v1/health/

# Look for accent-auth in components (if health checks enabled)
```

### Test Accent-Auth Connectivity

```bash
# Direct test (from application host)
curl -I http://accent-auth:9497/api/auth/0.1/token/check

# Should return 401 (unauthorized) which means service is up
```

### View Logs

```bash
# Startup logs
grep "Accent-Auth" logs/example-service.log.jsonl

# Runtime errors
grep "Authentication service unavailable" logs/example-service.log.jsonl
```

---

## Migration Guide

### From Generic Auth to Accent-Auth

If you're migrating from a lifespan-tied auth system:

**Before (Generic Auth):**
```python
# lifespan.py
async def lifespan(app: FastAPI):
    # ❌ Old way - blocks startup
    auth_client = await init_auth_client()

    yield

    await auth_client.close()
```

**After (Accent-Auth):**
```python
# lifespan.py
async def lifespan(app: FastAPI):
    # ✅ New way - no auth initialization needed

    # Optional: Register health checks
    if auth_settings.health_checks_enabled:
        aggregator.add_provider(AccentAuthHealthProvider())

    yield

    # ✅ No auth cleanup needed
```

---

## Summary

### Key Principles

1. **Accent-auth is NOT required for service startup**
   - Service starts even if accent-auth is down
   - Authentication happens per-request

2. **Health checks are optional observability**
   - Enable with `AUTH_HEALTH_CHECKS_ENABLED=true`
   - Never blocks startup
   - Reports degraded mode when auth unavailable

3. **Auto-recovery is built-in**
   - When accent-auth recovers, requests automatically work
   - No application restart needed

4. **Graceful degradation is possible**
   - Non-authenticated endpoints still work
   - Can implement fallback authentication methods

### Decision Matrix

| Scenario | Should Use Lifespan? |
|----------|---------------------|
| Authentication is critical for ALL endpoints | ⚠️ Consider it, but still not recommended |
| Some endpoints are public | ❌ No - use on-demand |
| Need graceful degradation | ❌ No - use on-demand |
| Need fast startup | ❌ No - use on-demand |
| Want auto-recovery | ❌ No - use on-demand |
| Need health visibility | ✅ Use on-demand + health checks |

**Recommendation:** Always use on-demand (current design). Enable health checks for observability.

---

**Generated**: 2025-12-01
**Status**: Production Pattern
**Design**: On-Demand Authentication (Non-Blocking)
