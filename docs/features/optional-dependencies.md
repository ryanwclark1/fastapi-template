# Optional Dependencies and Graceful Degradation

## Overview

This template is designed with **graceful degradation** in mind. All infrastructure dependencies are optional and the application will start and run even if they're unavailable.

This document explains which dependencies are optional, how to enable/disable them, and what happens when they're unavailable.

---

## Design Philosophy

**Core Principle**: The application should start and run regardless of which infrastructure services are available.

**Benefits**:
- ✅ **Fast development**: Don't need all services running locally
- ✅ **Resilient production**: Service survives dependency outages
- ✅ **Flexible deployment**: Can run with minimal infrastructure
- ✅ **Easier testing**: Can test with mock dependencies

**Pattern**:
```python
# All optional dependencies follow this pattern:
if settings.is_configured:
    try:
        result = await start_service()
        if not result:
            logger.warning("Service unavailable, continuing without it")
    except Exception as e:
        logger.warning("Service error, continuing without it", error=str(e))
```

---

## Dependency Matrix

| Dependency | Optional? | Default | Blocks Startup? | Graceful Degradation |
|------------|-----------|---------|-----------------|---------------------|
| **PostgreSQL** | ✅ Yes | Enabled | Configurable | `DB_STARTUP_REQUIRE_DB=false` |
| **Redis** | ✅ Yes | Enabled | Configurable | `REDIS_STARTUP_REQUIRE_CACHE=false` |
| **RabbitMQ** | ✅ Yes | Enabled | ❌ No | Always optional |
| **Consul** | ✅ Yes | Disabled | ❌ No | Always optional |
| **Accent-Auth** | ✅ Yes | Required | ❌ No | Per-request failure only |
| **OpenTelemetry** | ✅ Yes | Disabled | ❌ No | Always optional |
| **S3/MinIO** | ✅ Yes | Optional | ❌ No | Always optional |

---

## Detailed Breakdown

### 1. PostgreSQL Database

**Purpose**: Persistent data storage

**Configuration**:
```bash
# Enable/disable
DB_ENABLED=true

# Control startup behavior
DB_STARTUP_REQUIRE_DB=false  # false = optional, true = required

# Connection string
DB_DSN=postgresql+psycopg://postgres:postgres@localhost:5432/example_service
```

**Behavior**:

| Setting | Database Available | Database Unavailable |
|---------|-------------------|---------------------|
| `DB_STARTUP_REQUIRE_DB=true` | ✅ App starts | ❌ App fails to start |
| `DB_STARTUP_REQUIRE_DB=false` | ✅ App starts | ⚠️ App starts in degraded mode |

**Degraded Mode**:
- Application starts successfully
- Endpoints requiring database return 503 errors
- Health endpoint reports `degraded` status
- Automatically recovers when database becomes available

**Code** (`lifespan.py:182-196`):
```python
if db_settings.is_configured:
    try:
        await init_database()
        logger.info("Database connection initialized")
    except Exception as e:
        if db_settings.startup_require_db:
            logger.error("Database required but unavailable, failing startup")
            raise  # ← Only raises if required
        else:
            logger.warning("Database unavailable, continuing in degraded mode")
            # App continues without database
```

**Recommendation**:
- **Development**: `DB_STARTUP_REQUIRE_DB=false` (faster iteration)
- **Production**: `DB_STARTUP_REQUIRE_DB=true` (ensure data layer works)

---

### 2. Redis Cache

**Purpose**: Token caching, rate limiting, distributed locking

**Configuration**:
```bash
# Connection
REDIS_REDIS_URL=redis://localhost:6379/0

# Control startup behavior
REDIS_STARTUP_REQUIRE_CACHE=false  # false = optional, true = required
```

**Behavior**:

| Setting | Redis Available | Redis Unavailable |
|---------|----------------|-------------------|
| `REDIS_STARTUP_REQUIRE_CACHE=true` | ✅ App starts | ❌ App fails to start |
| `REDIS_STARTUP_REQUIRE_CACHE=false` | ✅ App starts | ⚠️ App starts in degraded mode |

**Degraded Mode**:
- Application starts successfully
- Token validation is **slower** (no caching, direct API calls)
- Rate limiting is **disabled** automatically
- Task tracking is unavailable
- Health endpoint reports `degraded` status

**Code** (`lifespan.py:199-262`):
```python
if redis_settings.is_configured:
    try:
        await start_cache()
        await start_tracker()
        logger.info("Redis cache initialized")
    except Exception as e:
        if redis_settings.startup_require_cache:
            logger.error("Redis required but unavailable, failing startup")
            raise
        else:
            logger.warning("Redis unavailable, continuing in degraded mode")
            # Mark rate limiter as disabled
            tracker.mark_disabled()
```

**Recommendation**:
- **Development**: `REDIS_STARTUP_REQUIRE_CACHE=false` (optional for testing)
- **Production**: `REDIS_STARTUP_REQUIRE_CACHE=true` (ensure caching works)

---

### 3. RabbitMQ Message Broker

**Purpose**: Event-driven messaging, background tasks, WebSocket broadcasting

**Configuration**:
```bash
RABBIT_ENABLED=true
RABBIT_AMQP_URI=amqp://guest:guest@localhost:5672/
```

**Behavior**: **Always optional** - never blocks startup

| RabbitMQ Status | Application Behavior |
|-----------------|---------------------|
| ✅ Available | Full messaging features enabled |
| ❌ Unavailable | App starts, messaging features disabled |

**Degraded Mode**:
- Application starts successfully
- Event publishing is disabled (outbox processor doesn't start)
- Background tasks (Taskiq) are unavailable
- WebSocket event bridge is disabled
- Endpoints work normally (non-messaging features)

**Code** (`lifespan.py:265-279`):
```python
if rabbit_settings.is_configured:
    await start_broker()
    logger.info("RabbitMQ/FastStream broker initialized")

# Outbox processor requires both database and RabbitMQ
if db_settings.is_configured and rabbit_settings.is_configured:
    try:
        await start_outbox_processor()
    except Exception as e:
        logger.warning("Failed to start outbox processor, events will not be published")
        # ← App continues!
```

**Recommendation**:
- **Development**: Optional (unless testing messaging features)
- **Production**: Required for event-driven features

---

### 4. Consul Service Discovery

**Purpose**: Service registration, health status reporting, service mesh

**Configuration**:
```bash
CONSUL_ENABLED=false  # Default: disabled
CONSUL_HOST=consul.service.consul
CONSUL_PORT=8500
CONSUL_HEALTH_CHECK_MODE=ttl  # or "http"
```

**Behavior**: **Always optional** - disabled by default

| Consul Status | Application Behavior |
|---------------|---------------------|
| ✅ Enabled + Available | Service registered, health reported |
| ✅ Enabled + Unavailable | App starts, service discovery disabled |
| ❌ Disabled | No registration attempted |

**Degraded Mode**:
- Application starts successfully
- Service is **not** registered with Consul
- Other services can't discover this instance
- Health status is not reported to Consul mesh
- All endpoints work normally

**Code** (`lifespan.py:168-180`):
```python
# Initialize Consul service discovery (optional, never blocks startup)
if consul_settings.is_configured:
    discovery_started = await start_discovery()
    if discovery_started:
        logger.info("Consul service discovery started")
    else:
        logger.warning("Consul failed to start, continuing without it")
        # ← App continues regardless!
```

**Recommendation**:
- **Development**: `CONSUL_ENABLED=false` (not needed)
- **Production (Kubernetes)**: `CONSUL_ENABLED=false` (use K8s service discovery)
- **Production (VMs/Consul)**: `CONSUL_ENABLED=true` (if using Consul mesh)

---

### 5. Accent-Auth Service

**Purpose**: Authentication, authorization (ACL-based)

**Configuration**:
```bash
AUTH_SERVICE_URL=http://accent-auth:9497
AUTH_HEALTH_CHECKS_ENABLED=false  # Optional health monitoring
```

**Behavior**: **Per-request failure only** - never blocks startup

| Accent-Auth Status | Application Behavior |
|--------------------|---------------------|
| ✅ Available | Authentication works |
| ❌ Unavailable at startup | App starts successfully |
| ❌ Unavailable at runtime | Individual auth requests fail with 503 |

**Degraded Mode**:
- Application starts successfully
- **Protected** endpoints return 503 (auth service unavailable)
- **Public** endpoints continue to work
- Automatically recovers when accent-auth comes back
- No restart needed

**Code** (`dependencies/accent_auth.py`):
```python
async def get_current_user(...) -> AuthUser:
    """Authenticate user via Accent-Auth.

    This runs per-request, NOT during startup.
    """
    try:
        token_info = await client.validate_token(token)
        return convert_to_auth_user(token_info)
    except httpx.ConnectError:
        # Accent-auth unavailable - fail THIS request only
        raise HTTPException(503, "Authentication service unavailable")
```

**Recommendation**:
- **Development**: Point to dev accent-auth instance
- **Production**: Ensure `AUTH_SERVICE_URL` is set correctly
- **Monitoring**: Enable `AUTH_HEALTH_CHECKS_ENABLED=true` for visibility

**See Also**: `docs/integrations/accent-auth-lifespan.md`

---

### 6. OpenTelemetry Tracing

**Purpose**: Distributed tracing, performance monitoring

**Configuration**:
```bash
OTEL_ENABLED=false  # Default: disabled
OTEL_ENDPOINT=http://localhost:4317
OTEL_SERVICE_NAME=example-service
```

**Behavior**: **Always optional** - disabled by default

| OpenTelemetry Status | Application Behavior |
|----------------------|---------------------|
| ✅ Enabled + Available | Traces exported |
| ✅ Enabled + Unavailable | App starts, traces dropped |
| ❌ Disabled | No tracing overhead |

**Degraded Mode**:
- Application starts successfully
- Traces are not exported (local spans still work)
- Performance is not affected
- All endpoints work normally

**Code** (`lifespan.py:148-153`):
```python
if otel_settings.is_configured:
    setup_tracing()  # Never raises exceptions
    logger.info("OpenTelemetry tracing enabled")
```

**Recommendation**:
- **Development**: `OTEL_ENABLED=false` (unless debugging performance)
- **Production**: `OTEL_ENABLED=true` (export to Jaeger/Tempo)

---

### 7. S3/MinIO Object Storage

**Purpose**: File uploads, document storage

**Configuration**:
```bash
STORAGE_ENABLED=false  # Default: disabled
STORAGE_ENDPOINT=http://localhost:9000
STORAGE_BUCKET=example-service
```

**Behavior**: **Always optional** - disabled by default

| S3 Status | Application Behavior |
|-----------|---------------------|
| ✅ Enabled + Available | File operations work |
| ✅ Enabled + Unavailable | App starts, file endpoints fail |
| ❌ Disabled | No file operations |

**Degraded Mode**:
- Application starts successfully
- File upload endpoints return errors
- Other endpoints work normally

**Recommendation**:
- **Development**: Optional (unless testing file features)
- **Production**: Enable if using file storage features

---

## Startup Scenarios

### Scenario 1: Minimal (Development)

**Configuration**:
```bash
# Only required service
AUTH_SERVICE_URL=http://accent-auth:9497

# All optional
DB_ENABLED=false
REDIS_REDIS_URL=
RABBIT_ENABLED=false
CONSUL_ENABLED=false
OTEL_ENABLED=false
```

**Result**: App starts in ~1 second, public endpoints work, protected endpoints require accent-auth

---

### Scenario 2: Full Stack (Production)

**Configuration**:
```bash
# All services enabled
AUTH_SERVICE_URL=http://accent-auth:9497
DB_STARTUP_REQUIRE_DB=true
REDIS_STARTUP_REQUIRE_CACHE=true
RABBIT_ENABLED=true
CONSUL_ENABLED=true
OTEL_ENABLED=true
```

**Result**: App starts with all features, fails if critical dependencies unavailable

---

### Scenario 3: Degraded Mode (Production Outage)

**Situation**: Redis goes down during runtime

**Behavior**:
- ✅ Application continues running
- ⚠️ Token validation is slower (no caching)
- ⚠️ Rate limiting is disabled
- ⚠️ Health endpoint reports `degraded`
- ✅ Automatically recovers when Redis comes back

**No restart needed!**

---

## Health Endpoint Integration

The `/api/v1/health` endpoint reports the status of all dependencies:

```bash
# All dependencies healthy
GET /api/v1/health/
{
  "status": "healthy",
  "components": {
    "database": {"status": "healthy"},
    "cache": {"status": "healthy"},
    "messaging": {"status": "healthy"}
  }
}

# Redis unavailable (degraded mode)
GET /api/v1/health/
{
  "status": "degraded",
  "components": {
    "database": {"status": "healthy"},
    "cache": {"status": "unhealthy", "error": "Connection failed"},
    "messaging": {"status": "healthy"}
  }
}
```

**Kubernetes Integration**:
```yaml
# Liveness probe - basic check (almost never fails)
livenessProbe:
  httpGet:
    path: /api/v1/health/live
    port: 8000

# Readiness probe - includes dependencies
readinessProbe:
  httpGet:
    path: /api/v1/health/ready
    port: 8000
  # Pod removed from load balancer if dependencies fail
```

---

## Best Practices

### 1. Development Environment

**Goal**: Fast iteration, minimal dependencies

```bash
# Minimal configuration
AUTH_SERVICE_URL=http://accent-auth:9497
DB_STARTUP_REQUIRE_DB=false
REDIS_STARTUP_REQUIRE_CACHE=false
RABBIT_ENABLED=false
CONSUL_ENABLED=false
OTEL_ENABLED=false
```

**Benefits**:
- Fast startup (~1 second)
- Can test without all services running
- Easy to mock dependencies

### 2. Production Environment

**Goal**: Full features, fail fast on critical errors

```bash
# Require critical dependencies
AUTH_SERVICE_URL=http://accent-auth:9497
DB_STARTUP_REQUIRE_DB=true
REDIS_STARTUP_REQUIRE_CACHE=true

# Enable full stack
RABBIT_ENABLED=true
CONSUL_ENABLED=true  # If using service mesh
OTEL_ENABLED=true

# Enable health monitoring
AUTH_HEALTH_CHECKS_ENABLED=true
REDIS_HEALTH_CHECKS_ENABLED=true
```

**Benefits**:
- Catch configuration errors at startup
- Full observability
- Graceful degradation for runtime failures

### 3. Testing Environment

**Goal**: Isolated testing, fast test execution

```bash
# Use in-memory/mock dependencies
DB_DSN=sqlite+aiosqlite:///:memory:
REDIS_REDIS_URL=redis://mock
RABBIT_ENABLED=false
AUTH_SERVICE_URL=http://mock-auth
```

**Benefits**:
- No external dependencies needed
- Fast test execution
- Predictable behavior

---

## Troubleshooting

### Problem: App won't start

**Check**:
1. Is a required dependency unavailable?
   - `DB_STARTUP_REQUIRE_DB=true` and database is down?
   - `REDIS_STARTUP_REQUIRE_CACHE=true` and Redis is down?

**Solution**: Set to `false` for development or fix the dependency

### Problem: App starts but features don't work

**Check**:
1. Look at startup logs:
   ```bash
   grep "unavailable\|failed\|degraded" logs/example-service.log.jsonl
   ```

2. Check health endpoint:
   ```bash
   curl http://localhost:8000/api/v1/health/
   ```

**Solution**: Start the missing dependency or check configuration

### Problem: Slow authentication

**Check**: Is Redis available?
```bash
redis-cli ping
# PONG = working
```

**Impact**: Without Redis caching:
- Token validation: 5ms → 100-200ms (20-40x slower)
- Still works, just slower

**Solution**: Start Redis for caching

---

## Summary

### Key Principles

1. **No dependency blocks startup** (unless explicitly configured)
2. **Fail at request time** (not startup time)
3. **Log warnings** (always continue)
4. **Auto-recovery** (reconnect when dependency comes back)
5. **Observability** (health checks show status)

### Configuration Flags

| Flag | Default | Production Recommendation |
|------|---------|--------------------------|
| `DB_STARTUP_REQUIRE_DB` | `true` | `true` |
| `REDIS_STARTUP_REQUIRE_CACHE` | `false` | `true` |
| `CONSUL_ENABLED` | `false` | `true` (if using Consul) |
| `AUTH_HEALTH_CHECKS_ENABLED` | `false` | `true` |
| `OTEL_ENABLED` | `false` | `true` |

### Decision Matrix

**When should a dependency block startup?**

| Dependency | Block Startup? | Reasoning |
|------------|---------------|-----------|
| PostgreSQL | ✅ Production | Data layer is critical |
| Redis | ✅ Production | Caching is important for performance |
| RabbitMQ | ❌ Never | Can be added later |
| Consul | ❌ Never | Service discovery is optional |
| Accent-Auth | ❌ Never | Fails per-request, not startup |
| OpenTelemetry | ❌ Never | Observability is optional |

---

**Generated**: 2025-12-01
**Status**: Production Pattern
**Philosophy**: Graceful Degradation with Optional Dependencies
