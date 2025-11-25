# Quick Start Guide: Using the New Improvements

This guide shows you how to quickly start using the new error handling, security, and resilience features.

## Table of Contents

1. [Error Handling with RFC 7807](#1-error-handling-with-rfc-7807)
2. [Rate Limiting](#2-rate-limiting)
3. [Circuit Breaker & Retry](#3-circuit-breaker--retry)
4. [Security Headers](#4-security-headers)

---

## 1. Error Handling with RFC 7807

### Throwing Custom Exceptions

```python
from example_service.core.exceptions import (
    NotFoundException,
    ValidationException,
    RateLimitException,
)

# In your route handler
@router.get("/users/{user_id}")
async def get_user(user_id: str):
    user = await user_service.get_by_id(user_id)
    if not user:
        raise NotFoundException(
            detail=f"User with ID '{user_id}' not found",
            instance=f"/api/v1/users/{user_id}",
            extra={"user_id": user_id, "suggestion": "Check if the user ID is correct"}
        )
    return user

# Validation errors with field details
@router.post("/users")
async def create_user(email: str, age: int):
    if age < 18:
        raise ValidationException(
            detail="User must be at least 18 years old",
            extra={
                "field": "age",
                "value": age,
                "min_value": 18
            }
        )
    # ... create user
```

### Client Response Example

```json
{
  "type": "not-found",
  "title": "Not Found",
  "status": 404,
  "detail": "User with ID 'abc123' not found",
  "instance": "/api/v1/users/abc123",
  "request_id": "xyz789",
  "user_id": "abc123",
  "suggestion": "Check if the user ID is correct"
}
```

---

## 2. Rate Limiting

### Option A: Global Middleware (All Endpoints)

Add to your middleware configuration (already done if using the template):

```python
# In example_service/app/middleware/__init__.py
from example_service.infra.cache import get_cache
from example_service.infra.ratelimit import RateLimitMiddleware, RateLimiter

# Configure in middleware setup
redis = get_cache()
limiter = RateLimiter(redis)

app.add_middleware(
    RateLimitMiddleware,
    limiter=limiter,
    default_limit=100,  # 100 requests
    default_window=60,   # per 60 seconds
)
```

### Option B: Per-Endpoint Rate Limiting

```python
from typing import Annotated
from fastapi import Depends
from example_service.core.dependencies.ratelimit import rate_limit

# Apply custom rate limit to specific endpoint
@router.post("/expensive-operation")
async def expensive_op(
    _: Annotated[None, Depends(rate_limit(limit=5, window=60))]
):
    # Only 5 requests per minute allowed
    return {"result": "success"}
```

### Option C: Per-User Rate Limiting

```python
from example_service.core.dependencies.ratelimit import per_user_rate_limit
from example_service.core.dependencies.auth import get_current_user

@router.post("/user/update-profile")
async def update_profile(
    _: Annotated[None, Depends(per_user_rate_limit(limit=20, window=60))],
    user: Annotated[User, Depends(get_current_user)],
    new_name: str
):
    # Each user can update profile 20 times per minute
    # ...
```

### Option D: Custom Rate Limit Key

```python
from fastapi import Request
from example_service.core.dependencies.ratelimit import rate_limit

def api_key_limiter(request: Request) -> str:
    """Extract API key from header"""
    api_key = request.headers.get("X-API-Key", "unknown")
    return f"apikey:{api_key}"

@router.get("/api/data")
async def get_data(
    _: Annotated[None, Depends(
        rate_limit(limit=1000, window=3600, key_func=api_key_limiter)
    )]
):
    # 1000 requests per hour per API key
    return {"data": "value"}
```

### Rate Limit Response Headers

Every response includes rate limit headers:

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 87
X-RateLimit-Reset: 1735234567
```

When rate limited (429 response):

```json
{
  "type": "rate-limit-exceeded",
  "title": "Too Many Requests",
  "status": 429,
  "detail": "Rate limit exceeded. Retry after 60 seconds",
  "limit": 100,
  "remaining": 0,
  "retry_after": 60
}
```

---

## 3. Circuit Breaker & Retry

### Circuit Breaker for External Services

```python
from example_service.infra.resilience import CircuitBreaker
import httpx

# Create circuit breaker (typically at module level)
auth_breaker = CircuitBreaker(
    name="auth_service",
    failure_threshold=5,      # Open after 5 consecutive failures
    recovery_timeout=60,      # Wait 60s before testing recovery
    expected_exception=httpx.HTTPError,
    success_threshold=2       # Need 2 successes to close circuit
)

# Use as decorator
@auth_breaker
async def verify_token(token: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://auth.example.com/verify",
            json={"token": token},
            timeout=5.0
        )
        response.raise_for_status()
        return response.json()

# Or use as context manager
async def call_auth_service():
    async with auth_breaker:
        return await verify_token("token123")
```

### Retry with Exponential Backoff

```python
from example_service.infra.resilience import with_retry
import httpx

# Retry decorator
@with_retry(
    max_attempts=5,
    base_delay=1.0,
    max_delay=60.0,
    jitter=True,
    retryable_exceptions=(httpx.HTTPError, TimeoutError)
)
async def fetch_user_data(user_id: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.get(f"https://api.example.com/users/{user_id}")
        response.raise_for_status()
        return response.json()
```

### Combining Circuit Breaker and Retry

```python
from example_service.infra.resilience import (
    CircuitBreaker,
    RetryConfig,
    combine_circuit_breaker_and_retry
)

api_breaker = CircuitBreaker("external_api", failure_threshold=5)
retry_config = RetryConfig(max_attempts=3, base_delay=2.0)

@combine_circuit_breaker_and_retry(api_breaker, retry_config)
async def call_external_api(endpoint: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.get(f"https://api.example.com/{endpoint}")
        response.raise_for_status()
        return response.json()
```

### Circuit Breaker States

```python
# Check circuit breaker state
if api_breaker.is_open:
    print("Circuit is open - failing fast")
elif api_breaker.is_half_open:
    print("Circuit is half-open - testing recovery")
else:
    print("Circuit is closed - operating normally")

# Get statistics
stats = api_breaker.get_stats()
print(f"State: {stats['state']}")
print(f"Failures: {stats['failure_count']}/{stats['failure_threshold']}")

# Manually reset circuit
await api_breaker.reset()
```

### Circuit Breaker Response

When circuit is open:

```json
{
  "type": "circuit-breaker-open",
  "title": "Service Unavailable",
  "status": 503,
  "detail": "Circuit breaker 'auth_service' is open",
  "service": "auth_service",
  "failures": 5,
  "retry_after": 45
}
```

---

## 4. Security Headers

Security headers are automatically added by the middleware. No code changes needed!

### Verifying Security Headers

```bash
curl -I http://localhost:8000/api/v1/health
```

You should see:

```
HTTP/1.1 200 OK
strict-transport-security: max-age=31536000; includeSubDomains
content-security-policy: default-src 'self'; script-src 'self' 'unsafe-inline'; ...
x-frame-options: DENY
x-content-type-options: nosniff
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin
permissions-policy: geolocation=(), microphone=(), camera=()
```

### Debug Mode (Development)

In debug mode (`APP_DEBUG=true`):
- HSTS is disabled (allows HTTP)
- CSP is relaxed for Swagger UI/ReDoc

---

## Complete Example: Protected Endpoint

Here's a complete example combining all features:

```python
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from example_service.core.dependencies.auth import get_current_user
from example_service.core.dependencies.ratelimit import per_user_rate_limit
from example_service.core.exceptions import (
    NotFoundException,
    ValidationException,
    CircuitBreakerOpenException,
)
from example_service.infra.resilience import CircuitBreaker, with_retry
import httpx

router = APIRouter()

# Circuit breaker for external service
external_api_breaker = CircuitBreaker(
    name="external_api",
    failure_threshold=3,
    recovery_timeout=30
)

@with_retry(max_attempts=3, base_delay=1.0)
@external_api_breaker
async def fetch_external_data(item_id: str) -> dict:
    """Fetch data from external API with retry and circuit breaker."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://api.example.com/items/{item_id}",
            timeout=5.0
        )
        response.raise_for_status()
        return response.json()


@router.get("/items/{item_id}")
async def get_item(
    item_id: str,
    # Rate limit: 50 requests per minute per user
    _: Annotated[None, Depends(per_user_rate_limit(limit=50, window=60))],
    # Require authentication
    user: Annotated[dict, Depends(get_current_user)],
):
    """
    Get item details with:
    - User authentication required
    - Per-user rate limiting (50 req/min)
    - Circuit breaker protection
    - Automatic retries
    - RFC 7807 error responses
    - Security headers
    """
    # Validate input
    if not item_id or len(item_id) < 3:
        raise ValidationException(
            detail="Invalid item ID format",
            extra={"field": "item_id", "min_length": 3}
        )

    try:
        # Fetch from external API with resilience
        data = await fetch_external_data(item_id)

        # Check if item exists
        if not data:
            raise NotFoundException(
                detail=f"Item {item_id} not found",
                extra={"item_id": item_id}
            )

        return {
            "item": data,
            "user": user["username"]
        }

    except CircuitBreakerOpenException as e:
        # Circuit breaker is open
        raise HTTPException(
            status_code=503,
            detail="External service temporarily unavailable"
        )
    except httpx.HTTPError as e:
        # External API error
        raise HTTPException(
            status_code=502,
            detail="Failed to fetch data from external service"
        )
```

### Testing the Complete Example

```bash
# 1. Successful request
curl -H "Authorization: Bearer token" http://localhost:8000/api/v1/items/abc123

# Response:
# {
#   "item": {"id": "abc123", "name": "..."},
#   "user": "john_doe"
# }

# 2. Rate limit exceeded (after 50 requests in a minute)
curl -H "Authorization: Bearer token" http://localhost:8000/api/v1/items/abc123

# Response (429):
# {
#   "type": "rate-limit-exceeded",
#   "title": "Too Many Requests",
#   "status": 429,
#   "detail": "Rate limit exceeded. Retry after 47 seconds",
#   "limit": 50,
#   "remaining": 0,
#   "retry_after": 47
# }

# 3. Validation error
curl -H "Authorization: Bearer token" http://localhost:8000/api/v1/items/ab

# Response (422):
# {
#   "type": "validation-error",
#   "title": "Validation Error",
#   "status": 422,
#   "detail": "Invalid item ID format",
#   "field": "item_id",
#   "min_length": 3
# }

# 4. Circuit breaker open (after external API failures)
curl -H "Authorization: Bearer token" http://localhost:8000/api/v1/items/abc123

# Response (503):
# {
#   "type": "circuit-breaker-open",
#   "title": "Service Unavailable",
#   "status": 503,
#   "detail": "Circuit breaker 'external_api' is open",
#   "service": "external_api",
#   "failures": 3,
#   "retry_after": 25
# }
```

---

## Configuration

### Environment Variables

Add to your `.env` file:

```bash
# Rate Limiting
REDIS_REDIS_URL=redis://localhost:6379/0

# Security
APP_DEBUG=false  # Set to true for development

# Circuit Breaker Settings (optional - defaults are good)
# These would be set programmatically when creating CircuitBreaker instances
```

### Middleware Order

The middleware runs in this order (configured in `example_service/app/middleware/__init__.py`):

1. **CORS** (outermost)
2. **Security Headers**
3. **Request ID** (correlation)
4. **Metrics** (observability)
5. **Timing** (performance)

Exception handlers run before middleware.

---

## Monitoring

### Check Circuit Breaker Health

```python
from example_service.infra.resilience import CircuitBreaker

# Get all circuit breakers (you'd need to track them)
breakers = {
    "auth": auth_breaker,
    "api": api_breaker,
}

# Health check endpoint
@router.get("/health/circuit-breakers")
async def circuit_breaker_health():
    return {
        name: breaker.get_stats()
        for name, breaker in breakers.items()
    }

# Response:
# {
#   "auth": {
#     "name": "auth_service",
#     "state": "closed",
#     "failure_count": 0,
#     "success_count": 150,
#     "failure_threshold": 5,
#     "recovery_timeout": 60
#   },
#   "api": {
#     "name": "external_api",
#     "state": "open",
#     "failure_count": 5,
#     "success_count": 0,
#     "failure_threshold": 3,
#     "recovery_timeout": 30,
#     "last_failure_time": 1735234567.89
#   }
# }
```

### Monitor Rate Limits

```python
from example_service.infra.ratelimit import RateLimiter
from example_service.infra.cache import get_cache

@router.get("/admin/rate-limits/{key}")
async def get_rate_limit_info(key: str):
    redis = get_cache()
    limiter = RateLimiter(redis)
    info = await limiter.get_limit_info(key, window=60)
    return info

# Response:
# {
#   "limit": 100,
#   "remaining": 73,
#   "reset": 1735234612,
#   "current": 27
# }
```

---

## Best Practices

### 1. Error Handling
- ✅ Always provide context in `extra` dict
- ✅ Use specific exception types (not generic `AppException`)
- ✅ Include field names in validation errors
- ✅ Set meaningful `instance` paths
- ❌ Don't expose sensitive information in error details

### 2. Rate Limiting
- ✅ Use per-user rate limiting for authenticated endpoints
- ✅ Use stricter limits for expensive operations
- ✅ Exempt health checks and metrics endpoints
- ✅ Document rate limits in API documentation
- ❌ Don't use global IP-based limiting for authenticated APIs

### 3. Circuit Breakers
- ✅ Create one circuit breaker per external service
- ✅ Set reasonable failure thresholds (3-5 failures)
- ✅ Use appropriate recovery timeouts (30-60 seconds)
- ✅ Combine with retry logic
- ❌ Don't use circuit breakers for internal database calls

### 4. Retries
- ✅ Use exponential backoff with jitter
- ✅ Limit max attempts (3-5 is usually enough)
- ✅ Only retry idempotent operations
- ✅ Specify retryable exception types
- ❌ Don't retry operations that change state (POST, PUT, DELETE)

---

## Troubleshooting

### Rate Limiting Not Working

**Check Redis connection:**
```bash
redis-cli ping
# Should return: PONG
```

**Check Redis keys:**
```bash
redis-cli KEYS "ratelimit:*"
```

### Circuit Breaker Stuck Open

**Manually reset:**
```python
await breaker.reset()
```

**Check failure count:**
```python
stats = breaker.get_stats()
print(f"Failures: {stats['failure_count']}/{stats['failure_threshold']}")
```

### Security Headers Not Appearing

**Check middleware order:**
Security headers middleware should be registered before other middleware.

**Verify in debug mode:**
HSTS is disabled in debug mode - this is intentional.

---

## Next Steps

1. **Add Monitoring**: Set up Prometheus metrics for rate limits and circuit breakers
2. **Configure Alerts**: Alert when circuit breakers open or rate limits are frequently exceeded
3. **Add Dashboards**: Visualize error rates, rate limits, and circuit breaker states
4. **Document API**: Add rate limit information to API documentation
5. **Load Testing**: Test rate limits and circuit breakers under load

For more details, see [IMPROVEMENTS.md](./IMPROVEMENTS.md).
