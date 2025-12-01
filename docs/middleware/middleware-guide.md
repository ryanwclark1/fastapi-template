# Middleware Guide

Complete guide to all middleware available in the FastAPI template, including configuration, best practices, and performance considerations.

## Table of Contents

1. [Overview](#overview)
2. [Middleware Stack Order](#middleware-stack-order)
3. [Core Middleware](#core-middleware)
4. [Security Middleware](#security-middleware)
5. [Observability Middleware](#observability-middleware)
6. [Development Middleware](#development-middleware)
7. [Configuration Reference](#configuration-reference)
8. [Best Practices](#best-practices)
9. [Performance Considerations](#performance-considerations)
10. [Troubleshooting](#troubleshooting)

---

## Overview

The FastAPI template includes a comprehensive middleware stack that provides:

- 🔒 **Security**: Headers, rate limiting, size limits
- 📊 **Observability**: Metrics, logging, tracing
- 🌍 **Multi-tenancy**: Tenant isolation and context
- 🐛 **Development**: Debug tools, N+1 detection
- 🌐 **I18n**: Multi-language support

### Quick Reference

| Middleware | Purpose | When to Enable | Performance Impact |
|------------|---------|----------------|-------------------|
| [Security Headers](#security-headers-middleware) | HTTP security headers | Always (production) | Minimal |
| [Rate Limiting](#rate-limiting-middleware) | DDoS protection | Production recommended | Low |
| [Request Size Limit](#request-size-limit-middleware) | DoS protection | Always | Minimal |
| [Request ID](#request-id-middleware) | Request tracking | Always | Minimal |
| [Correlation ID](#correlation-id-middleware) | Distributed tracing | Always | Minimal |
| [Metrics](#metrics-middleware) | Prometheus metrics | Production | Low |
| [Request Logging](#request-logging-middleware) | Detailed logging | Debug only | Medium-High |
| [Debug](#debug-middleware) | Comprehensive debug | Development only | High |
| [N+1 Detection](#n1-detection-middleware) | SQL optimization | Development only | Medium |
| [I18n](#i18n-middleware) | Localization | As needed | Low |
| [Tenant](#tenant-middleware) | Multi-tenancy | Multi-tenant apps | Minimal |

---

## Middleware Stack Order

Middleware execution order is **critical** for correct behavior. Middleware is applied in **reverse order** (last added = first executed).

### Execution Order (Outer to Inner)

```
1. Debug Middleware         ← First to see request/response
2. Request ID              ← Generate unique ID early
3. Security Headers        ← Apply security policies
4. Metrics                 ← Track request timing
5. CORS (dev only)         ← Handle preflight requests
6. Trusted Host (prod)     ← Validate Host header
7. Rate Limiting           ← Reject before processing
8. Request Logging         ← Log after rate limit
9. Size Limit              ← Protect against large payloads
10. Correlation ID         ← Transaction-level tracking
11. Tenant Middleware      ← Set tenant context
    ↓
Application Routes
```

### Why Order Matters

```python
# ❌ Wrong order - security headers added after app processes request
app.add_middleware(RateLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
# Rate limiting happens first, security headers never applied

# ✅ Correct order - security headers wrap rate limiting
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
# Security headers applied to all responses including rate limit errors
```

---

## Core Middleware

### Request ID Middleware

Generates unique IDs for each request to track operations across logs.

#### Configuration

```bash
# .env
LOG_INCLUDE_REQUEST_ID=true  # Enable request ID tracking
```

#### Features

- ✅ Generates UUIDv4 for each request
- ✅ Adds `X-Request-ID` header to response
- ✅ Available in logging context
- ✅ Automatic propagation to all logs

#### Usage in Code

```python
from example_service.app.middleware.request_id import get_request_id

@router.get("/data")
async def get_data():
    request_id = get_request_id()
    logger.info(f"Processing request: {request_id}")
    return {"request_id": request_id}
```

#### Log Output

```json
{
  "timestamp": "2025-12-01T10:00:00Z",
  "level": "INFO",
  "message": "GET /api/v1/data",
  "request_id": "123e4567-e89b-12d3-a456-426614174000",
  "method": "GET",
  "path": "/api/v1/data"
}
```

---

### Correlation ID Middleware

Tracks transactions across multiple services in distributed systems.

#### Configuration

```bash
# .env
# No configuration needed - always enabled
```

#### Features

- ✅ Accepts `X-Correlation-ID` from upstream
- ✅ Generates new ID if not provided
- ✅ Propagates through microservices
- ✅ Separate from Request ID (correlation = transaction, request = hop)

#### Usage

```python
from example_service.app.middleware.correlation_id import get_correlation_id

@router.post("/process")
async def process_data():
    correlation_id = get_correlation_id()

    # Pass to downstream services
    async with httpx.AsyncClient() as client:
        await client.post(
            "http://other-service/api",
            headers={"X-Correlation-ID": correlation_id}
        )
```

#### Client Usage

```bash
# Start a transaction with correlation ID
CORRELATION_ID=$(uuidgen)

# Call multiple services with same ID
curl -H "X-Correlation-ID: $CORRELATION_ID" http://api1.example.com/users
curl -H "X-Correlation-ID: $CORRELATION_ID" http://api2.example.com/orders

# All logs share same correlation_id for tracking
```

---

## Security Middleware

### Security Headers Middleware

Adds comprehensive HTTP security headers to protect against common attacks.

#### Configuration

```bash
# .env
APP_STRICT_CSP=true        # Use strict Content Security Policy
APP_DISABLE_DOCS=false     # Disable API docs (enables strict CSP)
APP_DEBUG=false            # Enable HSTS in production only
```

#### Security Headers Applied

| Header | Purpose | Production Value |
|--------|---------|------------------|
| **HSTS** | Force HTTPS | `max-age=31536000; includeSubDomains` |
| **CSP** | Prevent XSS | Strict: `default-src 'self'` |
| **X-Frame-Options** | Prevent clickjacking | `DENY` |
| **X-Content-Type-Options** | Prevent MIME sniffing | `nosniff` |
| **X-XSS-Protection** | XSS filter (legacy) | `1; mode=block` |
| **Referrer-Policy** | Control referrer | `strict-origin-when-cross-origin` |
| **Permissions-Policy** | Feature restrictions | Restrictive |

#### CSP Modes

**Relaxed CSP** (docs enabled):
```
default-src 'self';
script-src 'self' 'unsafe-inline';
style-src 'self' 'unsafe-inline';
img-src 'self' data: https:;
```

**Strict CSP** (production):
```
default-src 'self';
script-src 'self';
style-src 'self';
img-src 'self';
connect-src 'self';
```

#### Security Testing

```bash
# Check security headers
curl -I https://api.example.com/api/v1/health/

# Expected headers in production
HTTP/2 200
strict-transport-security: max-age=31536000; includeSubDomains
content-security-policy: default-src 'self'
x-frame-options: DENY
x-content-type-options: nosniff
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin
```

---

### Rate Limiting Middleware

Protects against DDoS and abuse using token bucket algorithm with Redis.

#### Configuration

```bash
# .env
APP_ENABLE_RATE_LIMITING=true
APP_RATE_LIMIT_PER_MINUTE=120      # Requests per minute
APP_RATE_LIMIT_WINDOW_SECONDS=60   # Window size
REDIS_REDIS_URL=redis://localhost:6379/0
```

#### Features

- ✅ Token bucket algorithm (smooth rate limiting)
- ✅ Redis-backed (shared across instances)
- ✅ Per-IP rate limiting
- ✅ Custom limits per endpoint
- ✅ Exempt paths (health checks, metrics)
- ✅ Standard HTTP 429 responses

#### Default Exempt Paths

```python
EXEMPT_PATHS = [
    "/health",
    "/health/live",
    "/health/ready",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
]
```

#### Custom Rate Limits

```python
from example_service.app.middleware.rate_limit import rate_limit

@router.post("/expensive-operation")
@rate_limit(limit=10, window=60)  # 10 requests per minute
async def expensive_operation():
    return {"status": "processing"}

@router.get("/public-data")
@rate_limit(limit=1000, window=60)  # Higher limit for reads
async def get_public_data():
    return {"data": []}
```

#### Response on Rate Limit

```json
{
  "detail": "Rate limit exceeded. Try again in 45 seconds.",
  "retry_after": 45
}
```

#### Monitoring

```python
# Prometheus metrics
rate_limit_exceeded_total{endpoint="/api/v1/data"} 10
rate_limit_requests_total{endpoint="/api/v1/data",allowed="true"} 1000
```

---

### Request Size Limit Middleware

Protects against large payload DoS attacks.

#### Configuration

```bash
# .env
APP_ENABLE_REQUEST_SIZE_LIMIT=true
APP_REQUEST_SIZE_LIMIT=10485760  # 10MB in bytes
```

#### Features

- ✅ Validates Content-Length header
- ✅ Fast rejection (before reading body)
- ✅ Configurable size limit
- ✅ Standard HTTP 413 response

#### Size Recommendations

| Use Case | Recommended Limit |
|----------|------------------|
| **API-only** | 1MB - 5MB |
| **File uploads** | 10MB - 50MB |
| **Large documents** | 50MB - 100MB |
| **Video/media** | 100MB - 500MB |

#### Error Response

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -d @large-file.json \
  http://localhost:8000/api/v1/data

# Response: 413 Payload Too Large
{
  "detail": "Request body too large. Maximum size is 10485760 bytes (10.0 MB)."
}
```

---

## Observability Middleware

### Metrics Middleware

Collects HTTP request metrics for Prometheus.

#### Configuration

```bash
# .env
OTEL_ENABLED=true
OTEL_ENDPOINT=http://localhost:4317
OTEL_INSTRUMENT_FASTAPI=true
```

#### Metrics Collected

```python
# HTTP request counter
http_requests_total{
  method="GET",
  endpoint="/api/v1/data",
  status="200"
} 1000

# Request duration histogram
http_request_duration_seconds{
  method="GET",
  endpoint="/api/v1/data"
} 0.025

# Request size
http_request_size_bytes{
  method="POST",
  endpoint="/api/v1/data"
} 1024

# Response size
http_response_size_bytes{
  method="GET",
  endpoint="/api/v1/data"
} 2048
```

#### Custom Timing Header

```bash
curl -I http://localhost:8000/api/v1/data

HTTP/1.1 200 OK
x-process-time: 0.025  # Request processing time in seconds
```

#### Grafana Dashboard

See `deployment/configs/grafana/dashboards/fastapi.json` for pre-built dashboard.

---

### Request Logging Middleware

Logs detailed request/response information with PII masking.

#### Configuration

```bash
# .env
LOG_LEVEL=DEBUG  # Auto-enables request logging
# OR
APP_DEBUG=true   # Also enables request logging
```

#### Features

- ✅ Request method, path, headers
- ✅ Request body (configurable)
- ✅ Response status, headers
- ✅ Response body (optional, expensive)
- ✅ **Automatic PII masking**
- ✅ Request timing

#### PII Masking

Automatically masks sensitive data:

```python
# Masked fields
PII_PATTERNS = [
    "password",
    "token",
    "api_key",
    "secret",
    "authorization",
    "credit_card",
    "ssn",
    "email",
    "phone",
]
```

#### Example Log

```json
{
  "timestamp": "2025-12-01T10:00:00Z",
  "level": "INFO",
  "message": "Request completed",
  "method": "POST",
  "path": "/api/v1/auth/login",
  "status_code": 200,
  "duration_ms": 45.2,
  "request_body": {
    "username": "john",
    "password": "***MASKED***"
  },
  "response_body": {
    "token": "***MASKED***",
    "user_id": "123"
  }
}
```

#### Performance Warning

⚠️ **Request logging is expensive** - only enable in debug/development:
- Adds 5-20ms per request
- Increases log storage significantly
- Can log sensitive data (PII masking helps but isn't perfect)

---

## Development Middleware

### Debug Middleware

Comprehensive debugging with trace context and detailed logging.

#### Configuration

```bash
# .env
APP_ENABLE_DEBUG_MIDDLEWARE=true
APP_DEBUG_LOG_REQUESTS=true
APP_DEBUG_LOG_RESPONSES=true
APP_DEBUG_LOG_TIMING=true
APP_DEBUG_HEADER_PREFIX=X-
```

#### Features

- ✅ Detailed request/response logging
- ✅ Timing information for all stages
- ✅ Exception details and tracebacks
- ✅ Debug headers in response
- ✅ Memory usage tracking

#### Debug Headers

```bash
curl -I http://localhost:8000/api/v1/data

HTTP/1.1 200 OK
X-Request-ID: 123e4567-e89b-12d3-a456-426614174000
X-Process-Time: 0.025
X-Debug-Trace-ID: abc123
X-Debug-Memory-MB: 45.2
```

#### Example Debug Log

```json
{
  "timestamp": "2025-12-01T10:00:00Z",
  "level": "DEBUG",
  "message": "Request processing stages",
  "trace_id": "abc123",
  "stages": {
    "middleware_entry": 0.0,
    "auth_check": 0.005,
    "db_query": 0.015,
    "serialization": 0.003,
    "middleware_exit": 0.025
  },
  "memory_mb": 45.2
}
```

⚠️ **Never enable in production** - exposes sensitive information and adds significant overhead.

---

### N+1 Detection Middleware

Detects and alerts on N+1 query patterns in SQLAlchemy.

#### Setup

```python
from example_service.app.middleware import setup_n_plus_one_monitoring

# In lifespan or startup
async def lifespan(app: FastAPI):
    # Setup N+1 detection
    engine = get_engine()
    setup_n_plus_one_monitoring(
        engine=engine,
        threshold=5,  # Alert after 5 similar queries
        log_queries=True,
        raise_on_detection=False,  # Set True in tests
    )
    yield
```

#### Configuration

```bash
# .env
# No specific env vars - configured in code
APP_DEBUG=true  # Required for N+1 detection
```

#### Features

- ✅ Detects similar queries in rapid succession
- ✅ Query pattern normalization
- ✅ Configurable thresholds
- ✅ Detailed query logging
- ✅ Can raise exceptions in tests

#### Example Detection

```python
# ❌ N+1 query pattern
posts = await session.execute(select(Post))
for post in posts:
    # Separate query for each post's author
    author = await session.execute(
        select(User).where(User.id == post.author_id)
    )
```

**Detection Log:**
```json
{
  "level": "WARNING",
  "message": "Potential N+1 query detected",
  "pattern": "SELECT * FROM users WHERE id = ?",
  "count": 10,
  "threshold": 5,
  "suggestion": "Consider using eager loading: selectinload() or joinedload()"
}
```

**Fix:**
```python
# ✅ Fixed with eager loading
posts = await session.execute(
    select(Post).options(selectinload(Post.author))
)
for post in posts:
    # Author already loaded, no additional query
    author = post.author
```

---

### I18n Middleware

Multi-language response localization.

#### Configuration

```bash
# .env
I18N_ENABLED=true
I18N_DEFAULT_LOCALE=en
I18N_SUPPORTED_LOCALES=["en", "es", "fr", "de"]
I18N_COOKIE_NAME=locale
I18N_QUERY_PARAM=lang
I18N_USE_ACCEPT_LANGUAGE=true
```

#### Locale Detection Priority

1. Query parameter (`?lang=es`)
2. Cookie (`locale=es`)
3. User preference (from database)
4. Accept-Language header
5. Default locale

#### Usage

```python
from example_service.app.middleware.i18n import get_locale, translate

@router.get("/greeting")
async def get_greeting():
    locale = get_locale()
    greeting = translate("greeting.hello", locale=locale)
    return {"message": greeting, "locale": locale}
```

#### Translation Files

```yaml
# conf/i18n/en.yaml
greeting:
  hello: "Hello!"
  goodbye: "Goodbye!"

errors:
  not_found: "Resource not found"
```

```yaml
# conf/i18n/es.yaml
greeting:
  hello: "¡Hola!"
  goodbye: "¡Adiós!"

errors:
  not_found: "Recurso no encontrado"
```

#### Client Usage

```bash
# Using query parameter
curl http://localhost:8000/api/v1/greeting?lang=es
# Response: {"message": "¡Hola!", "locale": "es"}

# Using Accept-Language header
curl -H "Accept-Language: fr" http://localhost:8000/api/v1/greeting
# Response: {"message": "Bonjour!", "locale": "fr"}

# Using cookie
curl -b "locale=de" http://localhost:8000/api/v1/greeting
# Response: {"message": "Hallo!", "locale": "de"}
```

---

## Configuration Reference

### Environment Variables

```bash
# ============================================================================
# Core Application
# ============================================================================
APP_DEBUG=false
APP_ENVIRONMENT=production

# ============================================================================
# Middleware Toggles
# ============================================================================
APP_ENABLE_DEBUG_MIDDLEWARE=false        # Debug middleware
APP_ENABLE_RATE_LIMITING=true           # Rate limiting
APP_ENABLE_REQUEST_SIZE_LIMIT=true      # Size limits
LOG_INCLUDE_REQUEST_ID=true             # Request ID tracking

# ============================================================================
# Security Configuration
# ============================================================================
APP_STRICT_CSP=true                     # Strict Content Security Policy
APP_DISABLE_DOCS=false                  # Disable API docs
APP_ALLOWED_HOSTS=["example.com"]       # Trusted hosts (production)

# ============================================================================
# Rate Limiting
# ============================================================================
APP_RATE_LIMIT_PER_MINUTE=120
APP_RATE_LIMIT_WINDOW_SECONDS=60
REDIS_REDIS_URL=redis://localhost:6379/0

# ============================================================================
# Request Size Limits
# ============================================================================
APP_REQUEST_SIZE_LIMIT=10485760         # 10MB

# ============================================================================
# CORS (Development Only)
# ============================================================================
APP_CORS_ORIGINS=["http://localhost:3000"]
APP_CORS_ALLOW_CREDENTIALS=true
APP_CORS_ALLOW_METHODS=["*"]
APP_CORS_ALLOW_HEADERS=["*"]

# ============================================================================
# Logging
# ============================================================================
LOG_LEVEL=INFO
LOG_JSON_LOGS=true
LOG_INCLUDE_REQUEST_ID=true
LOG_LOG_SLOW_REQUESTS=true
LOG_SLOW_REQUEST_THRESHOLD=1.0

# ============================================================================
# OpenTelemetry
# ============================================================================
OTEL_ENABLED=true
OTEL_ENDPOINT=http://localhost:4317
OTEL_INSTRUMENT_FASTAPI=true
OTEL_INSTRUMENT_HTTPX=true
OTEL_INSTRUMENT_SQLALCHEMY=true

# ============================================================================
# I18n (Optional)
# ============================================================================
I18N_ENABLED=false
I18N_DEFAULT_LOCALE=en
I18N_SUPPORTED_LOCALES=["en", "es", "fr"]
```

---

## Best Practices

### Production Configuration

```bash
# Recommended production settings
APP_DEBUG=false
APP_ENVIRONMENT=production
APP_STRICT_CSP=true
APP_ENABLE_RATE_LIMITING=true
APP_ENABLE_REQUEST_SIZE_LIMIT=true
APP_ENABLE_DEBUG_MIDDLEWARE=false
LOG_LEVEL=INFO
LOG_JSON_LOGS=true
OTEL_ENABLED=true
```

### Development Configuration

```bash
# Recommended development settings
APP_DEBUG=true
APP_ENVIRONMENT=development
APP_ENABLE_RATE_LIMITING=false
APP_ENABLE_DEBUG_MIDDLEWARE=true
LOG_LEVEL=DEBUG
LOG_JSON_LOGS=false
OTEL_ENABLED=false
```

### Security Checklist

- ✅ Enable security headers in production
- ✅ Use strict CSP when possible
- ✅ Enable rate limiting
- ✅ Set request size limits
- ✅ Use HTTPS (HSTS enabled)
- ✅ Validate Host headers
- ✅ Disable debug middleware
- ✅ Enable PII masking in logs

### Performance Optimization

1. **Disable expensive middleware in production**:
   - Debug middleware
   - Request body logging
   - N+1 detection

2. **Enable caching**:
   - Rate limiting needs Redis
   - Token validation caching
   - Response caching where applicable

3. **Monitor metrics**:
   - Request duration
   - Rate limit hits
   - Cache hit rates

4. **Tune rate limits**:
   - Start conservative (100-200/min)
   - Monitor and adjust based on traffic
   - Set per-endpoint limits for expensive operations

---

## Performance Considerations

### Middleware Overhead

| Middleware | Latency Added | Memory Impact | CPU Impact |
|------------|---------------|---------------|------------|
| Request ID | <0.1ms | Minimal | Minimal |
| Correlation ID | <0.1ms | Minimal | Minimal |
| Security Headers | <0.1ms | Minimal | Minimal |
| Rate Limiting | 1-5ms | Low | Low |
| Metrics | 0.5-2ms | Low | Low |
| Request Size Limit | <0.5ms | Minimal | Minimal |
| Request Logging | 5-20ms | Medium | Medium |
| Debug Middleware | 10-50ms | High | High |
| N+1 Detection | 5-15ms | Medium | Medium |

### Optimization Tips

1. **Order matters for performance**:
   ```python
   # Fast rejection first
   app.add_middleware(RequestSizeLimitMiddleware)  # Fast
   app.add_middleware(RateLimitMiddleware)         # 1-5ms
   app.add_middleware(MetricsMiddleware)           # Last
   ```

2. **Use Redis for rate limiting**:
   - Shared state across instances
   - Fast in-memory operations
   - Automatic key expiration

3. **Limit log verbosity**:
   ```bash
   # Production
   LOG_LEVEL=INFO  # Or WARNING

   # Development
   LOG_LEVEL=DEBUG  # Only when debugging
   ```

4. **Monitor middleware performance**:
   ```python
   # Metrics show middleware overhead
   http_middleware_duration_seconds{
     middleware="RateLimitMiddleware"
   } 0.003
   ```

---

## Troubleshooting

### Rate Limiting Issues

**Problem**: Rate limits too strict

```bash
# Check current limit
curl -I http://localhost:8000/api/v1/data
X-RateLimit-Limit: 120
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1701432000
```

**Solution**: Increase limits or add exemptions
```bash
APP_RATE_LIMIT_PER_MINUTE=300  # Increase global limit
```

---

### Security Headers Blocking Content

**Problem**: CSP blocking resources

```
Refused to load script from 'https://cdn.example.com/script.js'
because it violates the Content Security Policy directive
```

**Solution**: Relax CSP for development
```bash
APP_STRICT_CSP=false
APP_DEBUG=true
```

---

### High Memory Usage

**Problem**: Memory increases over time

**Possible Causes**:
1. Request logging enabled in production
2. Debug middleware enabled
3. Large response bodies logged

**Solution**:
```bash
APP_ENABLE_DEBUG_MIDDLEWARE=false
LOG_LEVEL=INFO  # Not DEBUG
# Disable response body logging
```

---

### CORS Errors

**Problem**: CORS preflight requests failing

```
Access to fetch at 'http://api.example.com' from origin
'http://localhost:3000' has been blocked by CORS policy
```

**Solution**: Configure CORS origins
```bash
APP_DEBUG=true  # Enables CORS in development
APP_CORS_ORIGINS=["http://localhost:3000", "http://localhost:8080"]
```

---

### Slow Requests

**Problem**: Requests taking longer than expected

**Debug**:
```bash
# Check timing header
curl -I http://localhost:8000/api/v1/data
X-Process-Time: 2.5  # 2.5 seconds

# Enable slow request logging
LOG_LOG_SLOW_REQUESTS=true
LOG_SLOW_REQUEST_THRESHOLD=1.0
```

**Common Causes**:
1. N+1 queries (enable detection)
2. Missing database indexes
3. External API calls
4. Large response serialization

---

## Additional Resources

### Internal Documentation

- [Middleware Architecture](MIDDLEWARE_ARCHITECTURE.md) - Technical deep dive
- [Security Configuration](SECURITY_CONFIGURATION.md) - Security hardening
- [Correlation ID Usage](CORRELATION_ID_USAGE.md) - Distributed tracing guide
- [Monitoring Setup](MONITORING_SETUP.md) - Metrics and dashboards

### External Resources

- [FastAPI Middleware](https://fastapi.tiangolo.com/advanced/middleware/)
- [OWASP Security Headers](https://owasp.org/www-project-secure-headers/)
- [Content Security Policy](https://developer.mozilla.org/en-US/docs/Web/HTTP/CSP)
- [Rate Limiting Patterns](https://cloud.google.com/architecture/rate-limiting-strategies-techniques)

---

**Version**: 1.0.0
**Last Updated**: 2025-12-01
**Template**: FastAPI Production Template
