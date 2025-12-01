# Security Configuration

Comprehensive guide to security configuration for the FastAPI application, covering request size limits, rate limiting, security headers, PII masking, and production hardening.

## Table of Contents

- [Overview](#overview)
- [Request Size Limits](#request-size-limits)
- [Rate Limiting](#rate-limiting)
- [Security Headers](#security-headers)
- [PII Masking](#pii-masking)
- [Production Security Checklist](#production-security-checklist)
- [Environment-Specific Configuration](#environment-specific-configuration)
- [Monitoring and Alerting](#monitoring-and-alerting)
- [Common Security Scenarios](#common-security-scenarios)

## Overview

The application implements defense-in-depth security with multiple layers:

1. **Network Layer**: Request size limits, rate limiting
2. **Application Layer**: Security headers, CORS, input validation
3. **Data Layer**: PII masking, secrets management
4. **Observability Layer**: Security event logging, metrics, alerting

All security features are configurable via environment variables and YAML configuration files, enabling different security postures for development, staging, and production environments.

## Request Size Limits

### Purpose

Protect against Denial of Service (DoS) attacks that exploit large request payloads to:
- Exhaust server memory
- Consume bandwidth
- Slow down request processing
- Cause application crashes

### How It Works

The `RequestSizeLimitMiddleware` checks the `Content-Length` header **before reading the request body** and rejects oversized requests with HTTP 413 (Payload Too Large).

```python
# Pure ASGI implementation for maximum performance
if content_length > self.max_size:
    return {
        "status": 413,
        "detail": f"Request size {content_length} exceeds maximum {self.max_size} bytes"
    }
```

### Configuration

#### Environment Variables

```bash
# Enable/disable size limiting
APP_ENABLE_REQUEST_SIZE_LIMIT=true

# Maximum request size in bytes
APP_REQUEST_SIZE_LIMIT=10485760  # 10MB (default)
```

#### YAML Configuration

```yaml
# conf/app.yaml
app:
  enable_request_size_limit: true
  request_size_limit: 10485760  # 10MB
```

#### Programmatic Configuration

```python
from example_service.core.settings import get_app_settings

settings = get_app_settings()
print(f"Max request size: {settings.request_size_limit} bytes")
print(f"Max request size: {settings.request_size_limit / (1024 * 1024):.1f} MB")
```

### Default Values and Constraints

| Setting | Default | Minimum | Maximum | Notes |
|---------|---------|---------|---------|-------|
| `request_size_limit` | 10MB | 1KB | 100MB | Validated by Pydantic |

### Production Recommendations

#### By Endpoint Type

| Endpoint Type | Recommended Limit | Rationale |
|--------------|-------------------|-----------|
| JSON APIs | 1-5MB | Most JSON payloads are <100KB |
| File Upload | 50-100MB | Depends on use case |
| Webhook Receivers | 1-2MB | External webhooks rarely >1MB |
| GraphQL | 5-10MB | Complex queries can be large |
| Health Checks | 1KB | Should be minimal |

#### Example: Different Limits by Path

```python
# Custom middleware for path-specific limits
class DynamicSizeLimitMiddleware:
    """Apply different size limits based on request path."""

    PATH_LIMITS = {
        "/api/v1/upload": 100 * 1024 * 1024,  # 100MB for uploads
        "/api/v1/webhooks": 2 * 1024 * 1024,   # 2MB for webhooks
        "/api/v1": 10 * 1024 * 1024,           # 10MB default for API
    }

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")

        # Find matching limit (longest prefix wins)
        max_size = 10 * 1024 * 1024  # Default
        for prefix, limit in sorted(self.PATH_LIMITS.items(), key=lambda x: -len(x[0])):
            if path.startswith(prefix):
                max_size = limit
                break

        # Check size limit
        # ... implementation ...
```

### Response Format

When request size is exceeded:

```json
{
  "detail": "Request size 15728640 exceeds maximum 10485760 bytes"
}
```

**HTTP Status**: 413 Payload Too Large

### Monitoring

Track size limit violations:

```python
# Add custom metric
from prometheus_client import Counter

request_size_limit_exceeded = Counter(
    "request_size_limit_exceeded_total",
    "Number of requests rejected due to size limit",
    ["path"]
)

# In middleware
if content_length > self.max_size:
    request_size_limit_exceeded.labels(path=scope["path"]).inc()
```

### Troubleshooting

#### Problem: Legitimate Requests Rejected

**Symptom**: Valid file uploads fail with 413 errors

**Solutions**:
1. Increase limit: `APP_REQUEST_SIZE_LIMIT=52428800` (50MB)
2. Path-specific limits: Use dynamic middleware
3. Streaming uploads: Bypass size check for chunked transfers

#### Problem: Size Limit Not Applied

**Symptom**: Large requests accepted despite configuration

**Causes**:
1. Middleware disabled: Check `APP_ENABLE_REQUEST_SIZE_LIMIT=true`
2. Reverse proxy limits: Nginx/HAProxy might have lower limits
3. Chunked transfers: Some clients don't send `Content-Length`

**Solution**:
```bash
# Check middleware is active
docker logs <container> | grep "Request size limit enabled"

# Test with curl
curl -X POST http://localhost:8000/api/v1/test \
  -H "Content-Type: application/json" \
  -d @large_file.json
```

## Rate Limiting

### Purpose

Protect against:
- **DDoS attacks**: Distributed denial of service
- **Brute force attacks**: Password guessing, token enumeration
- **API abuse**: Excessive requests from single client
- **Resource exhaustion**: Prevent single user from consuming all capacity

### How It Works

The `RateLimitMiddleware` uses a **token bucket algorithm** with Redis for distributed rate limiting:

1. Each client gets a bucket with tokens
2. Each request consumes one token
3. Tokens refill at a fixed rate
4. Requests are rejected when bucket is empty

**Algorithm**: Sliding window with Redis sorted sets for atomic operations.

```lua
-- Redis Lua script for atomic rate limiting
local current = redis.call('ZCARD', key)
if current + cost <= limit then
    redis.call('ZADD', key, now, now .. ':' .. request_id)
    redis.call('EXPIRE', key, window)
    return {1, limit - (current + cost)}  -- Allowed, remaining
else
    return {0, 0}  -- Denied, no tokens
end
```

### Configuration

#### Prerequisites

**Required**: Redis connection for distributed rate limiting.

```bash
# Redis connection
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=your_secure_password
```

#### Environment Variables

```bash
# Enable/disable rate limiting
APP_ENABLE_RATE_LIMITING=true

# Rate limit per minute (global default)
APP_RATE_LIMIT_PER_MINUTE=100

# Time window in seconds
APP_RATE_LIMIT_WINDOW_SECONDS=60
```

#### YAML Configuration

```yaml
# conf/app.yaml
app:
  enable_rate_limiting: true
  rate_limit_per_minute: 1000      # Higher for production
  rate_limit_window_seconds: 60

# conf/redis.yaml
redis:
  host: redis
  port: 6379
  db: 0
  password: ${REDIS_PASSWORD}
  pool_size: 50
  socket_timeout: 5.0
```

### Default Values and Constraints

| Setting | Default | Minimum | Maximum | Notes |
|---------|---------|---------|---------|-------|
| `rate_limit_per_minute` | 100 | 1 | 10,000 | Per client |
| `rate_limit_window_seconds` | 60 | 1 | 3,600 | Max 1 hour |

### Production Recommendations

#### By Environment

| Environment | Requests/Min | Window | Rationale |
|------------|--------------|--------|-----------|
| Development | 1000 | 60s | No limits for testing |
| Staging | 500 | 60s | Similar to production |
| Production | 100-500 | 60s | Based on capacity |
| Production (API Keys) | 1000-5000 | 60s | Trusted clients |

#### By Client Type

| Client Type | Identifier | Limit | Notes |
|------------|------------|-------|-------|
| Anonymous | IP Address | 100/min | Strictest limit |
| Authenticated | User ID | 500/min | Known users |
| API Keys | API Key Hash | 5000/min | Trusted integrations |
| Internal Services | Service Name | No limit | Exempt from limiting |

#### Example: Custom Rate Limit Keys

```python
# Custom key function for rate limiting
def custom_rate_limit_key(request: Request) -> str:
    """Extract rate limit identifier from request.

    Priority:
    1. API key (if present)
    2. User ID (if authenticated)
    3. IP address (fallback)
    """
    # Check for API key
    api_key = request.headers.get("X-API-Key")
    if api_key:
        # Hash for privacy
        import hashlib
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:16]
        return f"apikey:{key_hash}"

    # Check for authenticated user
    if hasattr(request.state, "user") and request.state.user:
        return f"user:{request.state.user.id}"

    # Fallback to IP address
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    else:
        client_ip = request.client.host if request.client else "unknown"

    return f"ip:{client_ip}"

# Configure middleware with custom key function
app.add_middleware(
    RateLimitMiddleware,
    limiter=limiter,
    key_func=custom_rate_limit_key
)
```

### Exempt Paths

The following paths are **automatically exempt** from rate limiting:

```python
EXEMPT_PATHS = [
    "/health",
    "/health/ready",
    "/health/live",
    "/health/startup",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
]
```

**Rationale**: Health checks and monitoring endpoints should not be rate limited to ensure uptime monitoring works correctly.

#### Custom Exempt Paths

```python
# Add custom exempt paths
CUSTOM_EXEMPT_PATHS = EXEMPT_PATHS + [
    "/api/v1/webhooks/github",    # GitHub webhooks
    "/api/v1/callbacks/payment",  # Payment provider callbacks
]

app.add_middleware(
    RateLimitMiddleware,
    limiter=limiter,
    exempt_paths=CUSTOM_EXEMPT_PATHS
)
```

### Response Headers

Rate limiting information is returned in response headers:

```http
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 47
X-RateLimit-Reset: 1700912400
```

When rate limited:

```http
HTTP/1.1 429 Too Many Requests
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1700912400
Retry-After: 60

{
  "detail": "Rate limit exceeded. Retry after 60 seconds",
  "instance": "/api/v1/reminders",
  "limit": 100,
  "remaining": 0,
  "reset": 1700912400,
  "retry_after": 60
}
```

### Monitoring

Track rate limiting metrics:

```promql
# Rate limit violations by path
rate(request_rate_limit_exceeded_total[5m])

# Rate limit utilization
rate_limit_remaining / rate_limit_limit

# Top offenders
topk(10, sum by (client_ip) (request_rate_limit_exceeded_total))
```

### Troubleshooting

#### Problem: Rate Limiting Not Working

**Symptom**: No rate limiting applied, missing headers

**Causes**:
1. Redis not connected
2. Middleware disabled
3. Path is exempt
4. Key function returns inconsistent values

**Solution**:
```bash
# Test Redis
redis-cli ping

# Check logs
docker logs <container> | grep "Rate limiting enabled"

# Test rate limiting
for i in {1..150}; do
  curl -i http://localhost:8000/api/v1/test
done
# Should get 429 after 100 requests
```

#### Problem: False Positives

**Symptom**: Legitimate users rate limited

**Causes**:
1. Shared IP addresses (NAT, corporate proxy)
2. Limits too aggressive
3. Key collision

**Solution**:
```python
# Use authenticated user ID instead of IP
def user_based_key(request: Request) -> str:
    if hasattr(request.state, "user"):
        return f"user:{request.state.user.id}"
    # Fallback to IP with warning
    logger.warning("Anonymous request, using IP for rate limiting")
    return f"ip:{request.client.host}"
```

#### Problem: Redis Connection Failures

**Symptom**: All requests allowed despite configuration

**Behavior**: Middleware **fails open** (allows requests) when Redis is unavailable.

**Rationale**: Availability over security - service continues to function.

**Solution**:
```python
# Monitor Redis failures
redis_rate_limit_errors = Counter(
    "redis_rate_limit_errors_total",
    "Redis errors during rate limiting"
)

# Alert on failures
if error_rate > threshold:
    send_alert("Rate limiting degraded: Redis unavailable")
```

## Security Headers

### Purpose

Protect against common web vulnerabilities identified by OWASP:

- **XSS (Cross-Site Scripting)**: Inject malicious scripts
- **Clickjacking**: Trick users into clicking invisible elements
- **MIME Sniffing**: Execute files as different types
- **Man-in-the-Middle**: Intercept HTTP traffic
- **Information Disclosure**: Reveal server details

### Headers Applied

The `SecurityHeadersMiddleware` adds the following headers to all responses:

#### Strict-Transport-Security (HSTS)

**Purpose**: Force HTTPS for all future requests

```http
Strict-Transport-Security: max-age=31536000; includeSubDomains
```

**Configuration**:
```python
app.add_middleware(
    SecurityHeadersMiddleware,
    enable_hsts=True,              # Disable in development
    hsts_max_age=31536000,         # 1 year
    hsts_include_subdomains=True,  # Apply to all subdomains
    hsts_preload=False,            # Enable after testing
)
```

**Production**: Enable HSTS only after testing HTTPS is working correctly. Once enabled, browsers will refuse to connect over HTTP for the duration of `max-age`.

**Preloading**: Submit to [HSTS Preload List](https://hstspreload.org/) for browsers to enforce HTTPS before first visit.

#### Content-Security-Policy (CSP)

**Purpose**: Control which resources can be loaded to prevent XSS

```http
Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'
```

**Default Directives**:
```python
{
    "default-src": "'self'",                    # Only same origin
    "script-src": "'self' 'unsafe-inline' 'unsafe-eval'",  # Relaxed for Swagger UI
    "style-src": "'self' 'unsafe-inline'",      # Relaxed for Swagger UI
    "img-src": "'self' data: https:",           # Allow images
    "font-src": "'self' data:",                 # Allow fonts
    "connect-src": "'self'",                    # API calls same origin
    "frame-ancestors": "'none'",                # No embedding
    "base-uri": "'self'",                       # Prevent base tag injection
    "form-action": "'self'",                    # Forms to same origin
}
```

**Production CSP** (stricter):
```python
csp_directives = {
    "default-src": "'self'",
    "script-src": "'self'",                     # No inline scripts
    "style-src": "'self'",                      # No inline styles
    "img-src": "'self' https:",
    "font-src": "'self'",
    "connect-src": "'self' https://api.example.com",
    "frame-ancestors": "'none'",
    "base-uri": "'self'",
    "form-action": "'self'",
    "upgrade-insecure-requests": "",            # Upgrade HTTP to HTTPS
}
```

#### X-Frame-Options

**Purpose**: Prevent clickjacking by controlling iframe embedding

```http
X-Frame-Options: DENY
```

**Options**:
- `DENY`: Never allow framing
- `SAMEORIGIN`: Allow framing only from same origin
- `ALLOW-FROM https://example.com`: Allow specific origin (deprecated)

**Recommendation**: Use `DENY` unless you specifically need iframe embedding.

#### X-Content-Type-Options

**Purpose**: Prevent MIME type sniffing

```http
X-Content-Type-Options: nosniff
```

Forces browsers to respect the declared `Content-Type` header, preventing execution of files disguised as images/documents.

#### X-XSS-Protection

**Purpose**: Enable browser XSS filtering (legacy)

```http
X-XSS-Protection: 1; mode=block
```

**Note**: Largely superseded by CSP, but still useful for older browsers.

#### Referrer-Policy

**Purpose**: Control referrer information sent with requests

```http
Referrer-Policy: strict-origin-when-cross-origin
```

**Options**:
- `no-referrer`: Never send referrer
- `strict-origin-when-cross-origin`: Send origin for HTTPS→HTTPS, nothing for HTTPS→HTTP
- `same-origin`: Only send for same-origin requests

#### Permissions-Policy

**Purpose**: Control which browser features can be used

```http
Permissions-Policy: geolocation=(), microphone=(), camera=(), payment=(), usb=()
```

**Default**: Deny all dangerous features unless explicitly needed.

#### X-Permitted-Cross-Domain-Policies

**Purpose**: Control cross-domain policy files (Flash, PDF)

```http
X-Permitted-Cross-Domain-Policies: none
```

### Configuration

#### Environment-Aware Settings

```python
# Development: Relaxed for Swagger UI
if app_settings.debug:
    enable_hsts = False  # Allow HTTP
    csp_directives = {
        "default-src": "'self'",
        "script-src": "'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net",
        "style-src": "'self' 'unsafe-inline' https://cdn.jsdelivr.net",
        "img-src": "'self' data: https: http:",
    }
else:
    # Production: Strict security
    enable_hsts = True
    csp_directives = {
        "default-src": "'self'",
        "script-src": "'self'",  # No unsafe-inline
        "style-src": "'self'",
        "img-src": "'self' https:",
    }

app.add_middleware(
    SecurityHeadersMiddleware,
    enable_hsts=enable_hsts,
    csp_directives=csp_directives,
)
```

#### Custom Configuration

```python
app.add_middleware(
    SecurityHeadersMiddleware,
    # HSTS
    enable_hsts=True,
    hsts_max_age=63072000,  # 2 years
    hsts_include_subdomains=True,
    hsts_preload=True,
    # CSP
    enable_csp=True,
    csp_directives={
        "default-src": "'self'",
        "script-src": "'self' https://cdn.example.com",
        "connect-src": "'self' https://api.example.com",
    },
    # Frame options
    enable_frame_options=True,
    frame_options="SAMEORIGIN",  # Allow same-origin framing
    # Others
    enable_xss_protection=True,
    enable_content_type_options=True,
    enable_referrer_policy=True,
    referrer_policy="no-referrer",
    enable_permissions_policy=True,
    permissions_policy={
        "geolocation": ["self"],  # Allow geolocation on same origin
        "microphone": [],         # Deny microphone
        "camera": [],             # Deny camera
    },
)
```

### Testing Security Headers

Use [Security Headers](https://securityheaders.com/) to test your deployment:

```bash
# Test security headers
curl -I https://your-domain.com

# Expected headers
HTTP/2 200
strict-transport-security: max-age=31536000; includeSubDomains
x-frame-options: DENY
x-content-type-options: nosniff
content-security-policy: default-src 'self'; ...
```

Target grade: **A** or **A+** on securityheaders.com.

## PII Masking

### Purpose

Protect Personally Identifiable Information (PII) in logs and error reports:

- **Regulatory Compliance**: GDPR, CCPA, HIPAA requirements
- **Security**: Prevent credential leakage in logs
- **Privacy**: Minimize PII exposure in case of log access

### What Gets Masked

The `PIIMasker` class automatically detects and masks:

#### Pattern-Based Detection

| Type | Pattern | Example | Masked |
|------|---------|---------|--------|
| Email | RFC 5322 | user@example.com | u***@example.com |
| Phone | US/International | 555-123-4567 | ***-***-4567 |
| Credit Card | 16 digits | 4532-1234-5678-9010 | ****-****-****-9010 |
| SSN | XXX-XX-XXXX | 123-45-6789 | ********* |
| API Key | 32+ chars | abc123def456... | ******** |

#### Field-Based Detection

Sensitive field names are completely masked:

```python
SENSITIVE_FIELDS = {
    "password", "passwd", "pwd",
    "secret", "token", "api_key", "apikey",
    "access_token", "refresh_token",
    "authorization", "auth",
    "credit_card", "creditcard", "card_number",
    "cvv", "ssn", "social_security",
    "tax_id", "driver_license",
}
```

### Configuration

#### Default Behavior

```python
masker = PIIMasker(
    mask_char="*",              # Character for masking
    preserve_domain=True,       # Show domain in emails
    preserve_last_4=True,       # Show last 4 digits
)
```

#### Custom Patterns

```python
import re

# Add custom PII patterns
custom_patterns = {
    "employee_id": re.compile(r"\bEMP-\d{6}\b"),
    "account_number": re.compile(r"\bACCT-\d{8}\b"),
}

masker = PIIMasker(
    custom_patterns=custom_patterns
)

# Mask custom fields
custom_fields = {"employee_id", "internal_id"}

masker = PIIMasker(
    custom_fields=custom_fields
)
```

#### Masking Examples

```python
from example_service.app.middleware.request_logging import PIIMasker

masker = PIIMasker()

# Email masking
masker.mask_email("john.doe@example.com")
# Output: "j***@example.com"

# Phone masking
masker.mask_phone("555-123-4567")
# Output: "***-***-4567"

# Dictionary masking
data = {
    "username": "john_doe",
    "email": "john@example.com",
    "password": "secret123",
    "phone": "555-123-4567",
}

masked = masker.mask_dict(data)
# Output: {
#   "username": "john_doe",
#   "email": "j***@example.com",
#   "password": "********",
#   "phone": "***-***-4567"
# }
```

### Log Output Examples

#### Before Masking

```json
{
  "email": "john.doe@example.com",
  "password": "MySecureP@ssw0rd",
  "phone": "555-123-4567",
  "credit_card": "4532-1234-5678-9010",
  "message": "Contact me at john.doe@example.com"
}
```

#### After Masking

```json
{
  "email": "j***@example.com",
  "password": "********",
  "phone": "***-***-4567",
  "credit_card": "****-****-****-9010",
  "message": "Contact me at j***@example.com"
}
```

### Best Practices

1. **Never Log Sensitive Fields**: Add to `SENSITIVE_FIELDS`
2. **Mask at Collection**: Mask in middleware before writing logs
3. **Test Masking**: Verify PII patterns are detected
4. **Audit Logs Regularly**: Check for PII leakage
5. **Use Structured Logging**: JSON logs are easier to mask

### Compliance Considerations

#### GDPR (General Data Protection Regulation)

- **Right to be Forgotten**: Ensure logs can be purged
- **Data Minimization**: Only log what's necessary
- **Anonymization**: Mask all personal data in logs

#### HIPAA (Health Insurance Portability and Accountability Act)

- **PHI Protection**: Mask all health information
- **Audit Trails**: Secure logging without PII exposure

#### PCI-DSS (Payment Card Industry Data Security Standard)

- **Cardholder Data**: Never log full credit card numbers
- **Mask Primary Account Number**: Show last 4 digits only
- **CVV**: Never log CVV codes

## Production Security Checklist

### Pre-Deployment

- [ ] **HTTPS Only**: Disable HTTP, enforce TLS 1.2+
- [ ] **HSTS Enabled**: `enable_hsts=True` in production
- [ ] **Debug Mode Off**: `APP_DEBUG=false`
- [ ] **Docs Disabled**: `APP_DISABLE_DOCS=true` in production
- [ ] **Rate Limiting**: Enable and tune for production traffic
- [ ] **Request Size Limits**: Configure appropriate limits
- [ ] **Security Headers**: All headers enabled
- [ ] **PII Masking**: Test log output for sensitive data
- [ ] **Secrets Management**: No secrets in environment variables
- [ ] **Database Credentials**: Use connection strings with auth
- [ ] **Redis Password**: Set `REDIS_PASSWORD`
- [ ] **CORS Origins**: Whitelist specific domains only

### Post-Deployment

- [ ] **Security Headers Test**: A+ on securityheaders.com
- [ ] **SSL Labs Test**: A+ on ssllabs.com
- [ ] **OWASP ZAP Scan**: No high/critical vulnerabilities
- [ ] **Dependency Audit**: `poetry audit` or `pip-audit`
- [ ] **Log Audit**: Check for PII leakage
- [ ] **Rate Limit Test**: Verify 429 responses
- [ ] **Metrics**: Monitor security events

### Ongoing Maintenance

- [ ] **Weekly**: Review security logs and alerts
- [ ] **Monthly**: Dependency updates and audits
- [ ] **Quarterly**: Penetration testing
- [ ] **Yearly**: Security architecture review

## Environment-Specific Configuration

### Development

**Priority**: Developer experience, debugging

```yaml
# conf/app.yaml (development)
app:
  environment: development
  debug: true
  disable_docs: false

  # Relaxed security for local development
  enable_rate_limiting: false
  enable_request_size_limit: true
  request_size_limit: 52428800  # 50MB

  # CORS for local frontend
  cors_origins:
    - http://localhost:3000
    - http://localhost:5173
  cors_allow_credentials: true

# Security headers (relaxed)
# - HSTS disabled (allow HTTP)
# - CSP allows unsafe-inline for Swagger UI
# - All features available for testing
```

### Staging

**Priority**: Production parity, testing

```yaml
# conf/app.yaml (staging)
app:
  environment: staging
  debug: false
  disable_docs: false  # Keep docs for API testing

  # Enable security features
  enable_rate_limiting: true
  rate_limit_per_minute: 500
  enable_request_size_limit: true
  request_size_limit: 10485760  # 10MB

  # CORS for staging frontend
  cors_origins:
    - https://staging.example.com
  cors_allow_credentials: true

# Security headers (production-like)
# - HSTS enabled
# - Strict CSP (test compatibility)
# - All security features enabled
```

### Production

**Priority**: Security, performance, reliability

```yaml
# conf/app.yaml (production)
app:
  environment: production
  debug: false
  disable_docs: true  # Disable API docs

  # Strict security
  enable_rate_limiting: true
  rate_limit_per_minute: 1000
  enable_request_size_limit: true
  request_size_limit: 10485760  # 10MB

  # CORS locked down
  cors_origins:
    - https://app.example.com
    - https://admin.example.com
  cors_allow_credentials: true
  cors_allow_methods:
    - GET
    - POST
    - PUT
    - DELETE
  cors_allow_headers:
    - Authorization
    - Content-Type

# Security headers (strict)
# - HSTS with preload
# - Strict CSP (no unsafe-inline)
# - All security features enabled
# - Permissions-Policy denies all
```

## Monitoring and Alerting

### Security Metrics

Define Prometheus metrics for security events:

```python
# security_metrics.py
from prometheus_client import Counter, Histogram

# Rate limiting
rate_limit_exceeded_total = Counter(
    "rate_limit_exceeded_total",
    "Total requests rejected due to rate limiting",
    ["path", "client_type"]
)

# Size limiting
request_size_limit_exceeded_total = Counter(
    "request_size_limit_exceeded_total",
    "Total requests rejected due to size limit",
    ["path"]
)

# Authentication failures
auth_failures_total = Counter(
    "auth_failures_total",
    "Total authentication failures",
    ["reason"]
)

# Suspicious activity
suspicious_activity_total = Counter(
    "suspicious_activity_total",
    "Suspicious activity detected",
    ["activity_type"]
)
```

### Grafana Dashboards

Create dashboards for security monitoring:

```yaml
# Security Overview Dashboard
panels:
  - title: "Rate Limit Violations (5m)"
    query: "rate(rate_limit_exceeded_total[5m])"
    alert: "rate > 10"

  - title: "Request Size Violations (5m)"
    query: "rate(request_size_limit_exceeded_total[5m])"
    alert: "rate > 1"

  - title: "Authentication Failures (5m)"
    query: "rate(auth_failures_total[5m])"
    alert: "rate > 5"

  - title: "Top Rate Limited IPs"
    query: "topk(10, sum by (client_ip) (rate_limit_exceeded_total))"

  - title: "HTTP 4xx/5xx Error Rate"
    query: "rate(http_requests_total{status=~'4..|5..'}[5m])"
```

### Alerting Rules

```yaml
# prometheus/alerts/security.yml
groups:
  - name: security
    rules:
      # Rate limiting spike
      - alert: HighRateLimitViolations
        expr: rate(rate_limit_exceeded_total[5m]) > 100
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High rate limit violations"
          description: "{{ $value }} rate limit violations per second"

      # Authentication failures
      - alert: AuthenticationFailureSpike
        expr: rate(auth_failures_total[5m]) > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Authentication failure spike"
          description: "Possible brute force attack"

      # Request size abuse
      - alert: RequestSizeAbuse
        expr: rate(request_size_limit_exceeded_total[5m]) > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Request size limit violations"
          description: "Possible DoS attempt"
```

### Log-Based Alerts

```python
# Use structured logging for security events
logger.warning(
    "Rate limit exceeded",
    extra={
        "security_event": "rate_limit_exceeded",
        "client_ip": client_ip,
        "path": path,
        "limit": limit,
        "window": window,
    }
)

# Log aggregation (e.g., Loki) can alert on patterns
# LogQL: {app="example-service"} |= "security_event" | json | security_event="rate_limit_exceeded"
```

## Common Security Scenarios

### Scenario 1: Brute Force Attack

**Symptom**: High authentication failure rate from single IP

**Detection**:
```promql
rate(auth_failures_total{client_ip="1.2.3.4"}[1m]) > 10
```

**Response**:
1. **Immediate**: Rate limit the IP more aggressively
2. **Short-term**: Temporary IP block (firewall rule)
3. **Long-term**: Implement CAPTCHA after N failures

**Implementation**:
```python
# Adaptive rate limiting based on auth failures
async def adaptive_rate_limit(request: Request, limiter: RateLimiter):
    client_ip = get_client_ip(request)

    # Check auth failure count
    failure_count = await get_auth_failures(client_ip, window=300)

    # Adjust limit based on failures
    if failure_count > 10:
        limit = 10  # Very strict
    elif failure_count > 5:
        limit = 50  # Strict
    else:
        limit = 100  # Normal

    await limiter.check_limit(f"ip:{client_ip}", limit=limit, window=60)
```

### Scenario 2: DoS via Large Payloads

**Symptom**: Multiple large requests consuming bandwidth

**Detection**:
```promql
rate(request_size_limit_exceeded_total[5m]) > 10
```

**Response**:
1. **Immediate**: Reject oversized requests (already handled)
2. **Short-term**: Lower size limit temporarily
3. **Long-term**: Implement request streaming for large uploads

### Scenario 3: API Key Leakage

**Symptom**: API key used from unexpected IP addresses

**Detection**:
```python
# Track API key usage by IP
api_key_ips = defaultdict(set)

def detect_key_leakage(api_key: str, client_ip: str):
    api_key_ips[api_key].add(client_ip)

    # Alert if key used from >5 IPs
    if len(api_key_ips[api_key]) > 5:
        logger.error(
            "Possible API key leakage",
            extra={
                "api_key_hash": hash_api_key(api_key),
                "unique_ips": len(api_key_ips[api_key]),
            }
        )
```

**Response**:
1. **Immediate**: Rotate the API key
2. **Short-term**: Notify key owner
3. **Long-term**: Implement key IP whitelisting

### Scenario 4: CORS Misconfiguration

**Symptom**: Unauthorized domain accessing API

**Detection**: Check CORS preflight requests from unexpected origins

**Response**:
```python
# Strict CORS validation
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://app.example.com",  # Explicit whitelist
        "https://admin.example.com",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],  # No wildcard
    allow_headers=["Authorization", "Content-Type"],  # Explicit headers
)

# Never use:
# allow_origins=["*"]  # Dangerous in production
```

### Scenario 5: PII Leakage in Logs

**Symptom**: Sensitive data visible in log aggregation

**Detection**: Log audit reveals unmasked emails/phone numbers

**Response**:
1. **Immediate**: Purge affected logs
2. **Short-term**: Update masking patterns
3. **Long-term**: Automated PII detection in logs

**Prevention**:
```python
# Test PII masking
import pytest

def test_pii_masking():
    masker = PIIMasker()

    data = {
        "email": "test@example.com",
        "password": "secret123",
        "phone": "555-1234",
        "name": "John Doe",
    }

    masked = masker.mask_dict(data)

    # Assertions
    assert "test@example.com" not in str(masked)
    assert "secret123" not in str(masked)
    assert masked["password"] == "********"
    assert masked["name"] == "John Doe"  # Not sensitive
```

## Related Documentation

- [Middleware Architecture](MIDDLEWARE_ARCHITECTURE.md) - Middleware stack and execution order
- [OpenTelemetry Configuration](example_service/infra/tracing/README.md) - Distributed tracing setup
- [Prometheus Metrics](example_service/infra/metrics/README.md) - Metrics and monitoring

## References

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [OWASP Secure Headers Project](https://owasp.org/www-project-secure-headers/)
- [OWASP API Security Top 10](https://owasp.org/www-project-api-security/)
- [Mozilla Web Security Guidelines](https://infosec.mozilla.org/guidelines/web_security)
- [Security Headers Scanner](https://securityheaders.com/)
- [NIST Cybersecurity Framework](https://www.nist.gov/cyberframework)
