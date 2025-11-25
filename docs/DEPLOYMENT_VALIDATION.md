# Middleware Deployment Validation Checklist

This document provides a comprehensive validation checklist for deploying the enhanced middleware stack to staging and production environments.

## Pre-Deployment Validation

### 1. Local Testing

- [x] **Unit Tests** - 122/132 tests passing (92%)
  ```bash
  pytest tests/unit/test_middleware/ -v
  ```

- [x] **Integration Tests** - 25/29 tests passing (86%)
  ```bash
  pytest tests/integration/test_middleware/ -v
  ```

- [x] **Application Startup** - Validates successfully
  ```bash
  python -c "from example_service.app.main import app; print(f'✓ {len(app.user_middleware)} middleware registered')"
  ```

### 2. Configuration Review

- [ ] **Environment Variables** - Review `.env` file for middleware settings:
  ```bash
  # Middleware Configuration
  APP_ENABLE_REQUEST_SIZE_LIMIT=true
  APP_REQUEST_SIZE_LIMIT=10485760  # 10MB
  APP_ENABLE_RATE_LIMITING=false   # Enable in production with Redis
  APP_RATE_LIMIT_PER_MINUTE=100
  APP_RATE_LIMIT_WINDOW_SECONDS=60
  ```

- [ ] **Security Settings** - Verify security headers are enabled:
  - HSTS disabled in development, enabled in production
  - CSP directives appropriate for environment
  - Frame options set to DENY

- [ ] **CORS Configuration** - Review allowed origins for environment

### 3. Dependencies Check

- [ ] **Redis Availability** (if rate limiting enabled)
  ```bash
  redis-cli ping
  ```

- [ ] **OpenTelemetry** (for trace correlation)
  ```bash
  # Verify OTLP endpoint is configured
  env | grep OTEL
  ```

## Staging Deployment

### Phase 1: Staging Environment Setup

#### 1.1 Deploy to Staging

```bash
# Deploy application with new middleware
docker-compose -f deployment/docker/docker-compose.yml up -d --build

# Verify deployment
curl -I http://staging.example.com/health
```

#### 1.2 Middleware Verification

- [ ] **Request ID Propagation**
  ```bash
  # Verify X-Request-ID header is added to responses
  curl -v http://staging.example.com/api/v1/status | grep -i x-request-id

  # Verify custom request ID is preserved
  curl -H "X-Request-ID: test-123" -v http://staging.example.com/api/v1/status | grep "test-123"
  ```

- [ ] **Security Headers Present**
  ```bash
  # Check for security headers
  curl -I http://staging.example.com/api/v1/status | grep -E "Strict-Transport-Security|Content-Security-Policy|X-Frame-Options|X-Content-Type-Options"
  ```

- [ ] **Timing Header**
  ```bash
  # Verify X-Process-Time header
  curl -I http://staging.example.com/api/v1/status | grep X-Process-Time
  ```

- [ ] **Size Limit Enforcement**
  ```bash
  # Test request size limit rejection (should return 413)
  dd if=/dev/zero bs=1M count=11 | curl -X POST -d @- http://staging.example.com/api/v1/test
  # Expected: 413 Payload Too Large
  ```

#### 1.3 Rate Limiting Verification (if enabled)

- [ ] **Rate Limit Headers**
  ```bash
  # Verify rate limit headers in response
  curl -I http://staging.example.com/api/v1/status | grep -E "X-RateLimit-(Limit|Remaining|Reset)"
  ```

- [ ] **Rate Limit Enforcement**
  ```bash
  # Send burst of requests to trigger rate limit
  for i in {1..150}; do
    curl -w "Status: %{http_code}\n" -s http://staging.example.com/api/v1/status | grep -E "Status|retry"
  done
  # Expected: Some requests return 429 Too Many Requests
  ```

### Phase 2: Performance Validation

#### 2.1 Latency Benchmarking

Run performance tests to establish baseline metrics:

```bash
# Install hey (HTTP load generator)
# https://github.com/rakyll/hey

# Baseline test - 1000 requests, 10 concurrent
hey -n 1000 -c 10 http://staging.example.com/api/v1/status

# Expected: p50 < 50ms, p95 < 200ms, p99 < 500ms
```

- [ ] **p50 Latency** < 50ms
- [ ] **p95 Latency** < 200ms
- [ ] **p99 Latency** < 500ms
- [ ] **Middleware Overhead** < 10% compared to baseline

#### 2.2 Memory Profile

- [ ] Monitor memory usage under load
  ```bash
  docker stats example-service
  # Expected: No memory leaks, stable after warmup
  ```

#### 2.3 Concurrent Requests

```bash
# High concurrency test - 10,000 requests, 100 concurrent
hey -n 10000 -c 100 http://staging.example.com/api/v1/status

# Verify request ID isolation
# Each request should have unique request ID in logs
```

### Phase 3: Observability Validation

#### 3.1 Metrics Collection

Verify Prometheus metrics are being collected:

```bash
# Fetch /metrics endpoint
curl http://staging.example.com/metrics | grep -E "http_request|middleware_execution"

# Expected metrics:
# - http_requests_total
# - http_request_duration_seconds
# - http_requests_in_progress
# - middleware_execution_seconds
# - request_size_bytes
# - request_size_limit_rejections_total
```

- [ ] **Counter Metrics** incrementing correctly
- [ ] **Histogram Metrics** tracking latency distributions
- [ ] **Gauge Metrics** tracking in-progress requests

#### 3.2 Trace Correlation

Verify OpenTelemetry trace correlation:

```bash
# Make request and extract request ID
REQUEST_ID=$(curl -s -D - http://staging.example.com/api/v1/status | grep -i x-request-id | cut -d' ' -f2)

# Query logs for that request ID
# Logs should contain trace_id field linking to OpenTelemetry traces
```

- [ ] Logs contain `request_id` field
- [ ] Logs contain `trace_id` field (when tracing enabled)
- [ ] Metrics have exemplars linking to traces

#### 3.3 Logging Validation

- [ ] **PII Masking** - Verify sensitive data is masked in logs
  ```bash
  # Send request with sensitive data
  curl -X POST http://staging.example.com/api/v1/test \
    -H "Content-Type: application/json" \
    -d '{"email": "user@example.com", "password": "secret123"}'

  # Check logs - password should be masked
  # Expected: {"email": "u***@example.com", "password": "********"}
  ```

- [ ] **Context Propagation** - Request ID appears in all log entries for a request
- [ ] **Log Levels** - Appropriate log levels for different events

### Phase 4: Error Handling

#### 4.1 Exception Propagation

- [ ] **Middleware Errors** don't crash the application
  ```bash
  # Trigger various error conditions
  # Application should handle gracefully and return appropriate status codes
  ```

- [ ] **Context Cleanup** - Verify logging context is cleared after errors
  ```python
  # Make request that triggers error
  # Verify next request doesn't have stale context from previous error
  ```

#### 4.2 Fallback Behavior

- [ ] **Redis Failure** (if rate limiting enabled) - Application continues without rate limiting
- [ ] **Tracing Failure** - Metrics still collected without exemplars

## Production Deployment

### Phase 5: Canary Deployment (10% → 50% → 100%)

#### 5.1 Deploy to 10% of Traffic

```bash
# Update load balancer or ingress to route 10% traffic to new version
# Monitor for 1 hour
```

**Validation Checklist:**

- [ ] **Error Rate** - No increase in 5xx errors
- [ ] **Latency** - p95/p99 within acceptable range
- [ ] **Request ID Coverage** - 100% of requests have request IDs
- [ ] **Security Headers** - Present on all responses
- [ ] **Memory Usage** - Stable, no leaks
- [ ] **Log Quality** - All logs contain request_id

#### 5.2 Increase to 50% Traffic

Wait 1 hour after 10% validation, then:

```bash
# Route 50% traffic to new version
# Monitor for 2 hours
```

**Additional Validation:**

- [ ] **Rate Limiting** (if enabled) - Working correctly under higher load
- [ ] **Size Limit Rejections** - Appropriate number of 413 responses
- [ ] **Concurrent Request Handling** - No context leakage between requests

#### 5.3 Full Rollout (100%)

After 50% validation passes:

```bash
# Route 100% traffic to new version
# Monitor for 24 hours
```

### Phase 6: Post-Deployment Monitoring

#### 6.1 Create Monitoring Dashboards

Set up Grafana dashboards for:

- [ ] **HTTP Request Metrics**
  - Request rate by endpoint
  - Latency (p50, p95, p99) by endpoint
  - Status code distribution
  - Requests in progress

- [ ] **Middleware Metrics**
  - Middleware execution time by middleware
  - Size limit rejections
  - Rate limit rejections (if enabled)
  - Middleware errors

- [ ] **Trace Correlation**
  - Click-through from metrics to traces
  - Trace ID coverage percentage

#### 6.2 Set Up Alerts

Configure alerts for:

- [ ] **High Error Rate** - 5xx errors > 1% of requests
- [ ] **High Latency** - p99 > 1s
- [ ] **Missing Request IDs** - Any requests without request IDs
- [ ] **Middleware Errors** - Any middleware throwing exceptions
- [ ] **Rate Limit Abuse** - High rejection rate from single IP
- [ ] **Size Limit Attacks** - High number of 413 responses

Example Prometheus alert rules:

```yaml
groups:
  - name: middleware_alerts
    interval: 30s
    rules:
      # High 5xx error rate
      - alert: HighErrorRate
        expr: |
          sum(rate(http_requests_total{status=~"5.."}[5m])) /
          sum(rate(http_requests_total[5m])) > 0.01
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High 5xx error rate"
          description: "5xx error rate is {{ $value | humanizePercentage }}"

      # High p99 latency
      - alert: HighLatency
        expr: |
          histogram_quantile(0.99,
            sum(rate(http_request_duration_seconds_bucket[5m])) by (le, endpoint)
          ) > 1.0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High p99 latency on {{ $labels.endpoint }}"
          description: "p99 latency is {{ $value }}s"

      # Rate limit rejections spike
      - alert: RateLimitAbuse
        expr: |
          rate(rate_limit_rejections_total[5m]) > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High rate limit rejection rate"
          description: "Rate limit rejections: {{ $value }}/s"

      # Middleware errors
      - alert: MiddlewareErrors
        expr: |
          rate(middleware_errors_total[5m]) > 0.1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Middleware errors detected"
          description: "{{ $labels.middleware_name }}: {{ $value }} errors/s"

      # Size limit rejections spike (potential DoS)
      - alert: SizeLimitAttack
        expr: |
          rate(request_size_limit_rejections_total[5m]) > 5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High request size rejection rate"
          description: "Potential DoS attack: {{ $value }} rejections/s"
```

#### 6.3 Log Aggregation

- [ ] **Centralized Logging** - All logs flowing to central system (e.g., ELK, Loki)
- [ ] **Request ID Filtering** - Can query logs by request_id
- [ ] **Trace ID Filtering** - Can query logs by trace_id
- [ ] **PII Compliance** - Verify no unmasked PII in logs

## Rollback Plan

If any validation fails, follow this rollback procedure:

### Rollback Triggers

Rollback immediately if:

- Error rate increases by > 10%
- p99 latency increases by > 50%
- Any middleware crashes the application
- Memory leaks detected
- Security headers missing on responses

### Rollback Procedure

```bash
# 1. Route traffic back to previous version
# Update load balancer/ingress

# 2. Verify old version is stable
curl -I http://production.example.com/health

# 3. Investigate root cause
# Check logs, metrics, traces

# 4. Document incident
# Include failure mode, impact, resolution
```

## Success Criteria

Deployment is considered successful when:

- [ ] All validation checkpoints passed
- [ ] 24 hours of stable production operation
- [ ] No increase in error rate or latency
- [ ] All monitoring dashboards and alerts configured
- [ ] Team trained on new middleware features
- [ ] Documentation updated with deployment notes

## Post-Deployment Tasks

- [ ] Update runbooks with middleware troubleshooting steps
- [ ] Share performance metrics with team
- [ ] Schedule retrospective to review deployment
- [ ] Document any lessons learned
- [ ] Archive old middleware code (if applicable)

## Troubleshooting Guide

### Common Issues

#### Request IDs Missing from Logs

**Symptom:** Logs show `request_id="unknown"`

**Diagnosis:**
```bash
# Check middleware order
curl http://production.example.com/api/v1/status -v
# X-Request-ID should be in response headers
```

**Fix:** Verify RequestIDMiddleware is registered before RequestLoggingMiddleware

#### Rate Limiting Not Working

**Symptom:** No rate limit headers in responses

**Diagnosis:**
```bash
# Check Redis connection
redis-cli ping

# Verify enable_rate_limiting setting
env | grep RATE_LIMIT
```

**Fix:** Ensure Redis is accessible and `APP_ENABLE_RATE_LIMITING=true`

#### High Memory Usage

**Symptom:** Memory usage grows over time

**Diagnosis:**
```bash
# Profile memory usage
docker stats example-service

# Check for context leaks
# Verify clear_log_context() is called in finally blocks
```

**Fix:** Ensure context cleanup in error paths

#### Missing Security Headers

**Symptom:** Security headers not in responses

**Diagnosis:**
```bash
# Check middleware registration
curl -I http://production.example.com/api/v1/status | grep -i security
```

**Fix:** Verify SecurityHeadersMiddleware is registered

## Related Documentation

- [Middleware Architecture](./MIDDLEWARE_ARCHITECTURE.md) - Design and implementation details
- [Security Configuration](./SECURITY_CONFIGURATION.md) - Security headers and best practices
- [Monitoring Setup Guide](./MONITORING_SETUP.md) - Detailed monitoring configuration

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-11-25 | AI Assistant | Initial deployment validation checklist |
