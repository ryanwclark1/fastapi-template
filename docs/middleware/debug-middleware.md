# Debug Middleware with Distributed Tracing

## Overview

The Debug Middleware provides comprehensive debugging capabilities with distributed tracing support. It automatically generates and propagates trace IDs across service boundaries, enabling request tracking and correlation in microservice architectures.

## Features

- **Trace ID Generation**: Automatic generation of UUID-based trace IDs for distributed tracing
- **Span ID Generation**: Unique 8-character hex span IDs for request-level tracking
- **Request/Response Logging**: Structured logging with full context
- **Exception Tracking**: Automatic trace context in error logs
- **Performance Timing**: Request duration tracking in milliseconds
- **Context Injection**: Automatic context propagation to all log records
- **Feature Flags**: Gradual rollout via configuration
- **Backward Compatibility**: Works with existing X-Request-Id headers

## Architecture

### Trace vs Span IDs

- **Trace ID**: Identifies an entire distributed transaction across multiple services
  - Format: UUID v4 (e.g., `a1b2c3d4-e5f6-7890-abcd-ef1234567890`)
  - Propagated across service boundaries
  - Shared by all requests in a transaction

- **Span ID**: Identifies a specific operation within a trace
  - Format: 8-character hex (e.g., `f47ac10b`)
  - Unique per request/operation
  - Used for request-level debugging

### Header Precedence

The middleware checks for trace IDs in the following order:

1. `X-Trace-Id` (standard distributed tracing)
2. `X-Request-Id` (backward compatibility)
3. Generate new UUID v4

## Configuration

### Environment Variables

```bash
# Enable debug middleware
APP_ENABLE_DEBUG_MIDDLEWARE=true

# Feature flags
APP_DEBUG_LOG_REQUESTS=true
APP_DEBUG_LOG_RESPONSES=true
APP_DEBUG_LOG_TIMING=true

# Header prefix (X-, Trace-, etc.)
APP_DEBUG_HEADER_PREFIX=X-
```

### Settings

Add to your `AppSettings` class:

```python
# Debug middleware configuration
enable_debug_middleware: bool = Field(default=False)
debug_log_requests: bool = Field(default=True)
debug_log_responses: bool = Field(default=True)
debug_log_timing: bool = Field(default=True)
debug_header_prefix: str = Field(default="X-")
```

### Middleware Registration

The middleware is automatically registered when enabled:

```python
# In example_service/app/middleware/__init__.py
if app_settings.enable_debug_middleware:
    app.add_middleware(
        DebugMiddleware,
        enabled=True,
        log_requests=app_settings.debug_log_requests,
        log_responses=app_settings.debug_log_responses,
        log_timing=app_settings.debug_log_timing,
        header_prefix=app_settings.debug_header_prefix,
    )
```

## Usage

### Basic Usage

1. **Enable in Development**:
   ```bash
   APP_ENABLE_DEBUG_MIDDLEWARE=true
   APP_DEBUG_LOG_REQUESTS=true
   APP_DEBUG_LOG_RESPONSES=true
   ```

2. **Make Requests**:
   ```bash
   curl -X GET http://localhost:8000/api/v1/reminders
   ```

3. **Check Logs**:
   ```json
   {
     "timestamp": "2025-01-07T10:30:45.123Z",
     "level": "INFO",
     "message": "Request started",
     "trace_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
     "span_id": "f47ac10b",
     "method": "GET",
     "path": "/api/v1/reminders"
   }
   ```

### Propagate Trace IDs

**Client → Service A**:
```bash
# Client generates trace ID
TRACE_ID=$(uuidgen)
curl -H "X-Trace-Id: $TRACE_ID" http://service-a/endpoint
```

**Service A → Service B**:
```python
# Service A propagates trace ID to Service B
async with httpx.AsyncClient() as client:
    response = await client.get(
        "http://service-b/endpoint",
        headers={"X-Trace-Id": request.state.trace_id}
    )
```

### Access Trace Context in Code

The trace context is automatically available in:

1. **Request State**:
   ```python
   @app.get("/endpoint")
   async def endpoint(request: Request):
       trace_id = request.state.trace_id
       span_id = request.state.span_id
       return {"trace_id": trace_id, "span_id": span_id}
   ```

2. **Logging Context**:
   ```python
   @app.get("/endpoint")
   async def endpoint():
       # Trace context automatically injected
       logger.info("Processing request")
       # Log includes: trace_id, span_id, method, path
       return {"status": "ok"}
   ```

3. **Response Headers**:
   ```python
   # Trace headers automatically added to response
   response.headers["X-Trace-Id"]  # Available in response
   response.headers["X-Span-Id"]   # Available in response
   ```

## Production Deployment

### Gradual Rollout

Enable debug middleware gradually using feature flags:

**Phase 1: Staging Environment**
```bash
# Enable in staging first
APP_ENABLE_DEBUG_MIDDLEWARE=true
APP_DEBUG_LOG_REQUESTS=true
APP_DEBUG_LOG_RESPONSES=true
```

**Phase 2: Production (Sampling)**
```bash
# Enable in production with reduced logging
APP_ENABLE_DEBUG_MIDDLEWARE=true
APP_DEBUG_LOG_REQUESTS=false   # Reduce noise
APP_DEBUG_LOG_RESPONSES=true   # Keep completion logs
APP_DEBUG_LOG_TIMING=true      # Track performance
```

**Phase 3: Full Production**
```bash
# Enable fully with log sampling
APP_ENABLE_DEBUG_MIDDLEWARE=true
APP_DEBUG_LOG_REQUESTS=true
APP_DEBUG_LOG_RESPONSES=true

# Use log sampling to reduce volume
LOG_ENABLE_SAMPLING=true
LOG_SAMPLING_RATE_DEFAULT=0.1  # Sample 10% of requests
```

### Performance Considerations

The middleware is designed for minimal overhead:

- **When Disabled**: Near-zero overhead (simple boolean check)
- **When Enabled**: ~0.1-0.5ms per request
- **Trace ID Generation**: UUID v4 is fast (~0.01ms)
- **Span ID Generation**: Simple hex slice (~0.001ms)
- **Logging**: Uses async queue handler for non-blocking I/O

### Security Considerations

**What is Logged**:
- ✅ Trace/Span IDs (non-sensitive)
- ✅ HTTP method and path
- ✅ Status codes
- ✅ Query parameters (can contain sensitive data)
- ✅ User/Tenant IDs (when authenticated)
- ✅ Request timing

**What is NOT Logged**:
- ❌ Request headers (except trace headers)
- ❌ Request body (use RequestLoggingMiddleware for this)
- ❌ Response body (potential PII/sensitive data)
- ❌ Authentication tokens
- ❌ Passwords or secrets

**Disable Query Param Logging**:
If query parameters contain sensitive data, modify the middleware:

```python
# In _build_request_context, comment out:
# if request.query_params:
#     context["query_params"] = dict(request.query_params)
```

## Integration Examples

### With OpenTelemetry

```python
from opentelemetry import trace

@app.get("/endpoint")
async def endpoint(request: Request):
    # Use trace_id from debug middleware
    trace_id = request.state.trace_id

    # Set as OTel trace context
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("endpoint-processing") as span:
        span.set_attribute("trace.id", trace_id)
        span.set_attribute("span.id", request.state.span_id)
        # Process request
        return {"status": "ok"}
```

### With External Monitoring

```python
import sentry_sdk

@app.get("/endpoint")
async def endpoint(request: Request):
    # Tag Sentry events with trace context
    sentry_sdk.set_tag("trace_id", request.state.trace_id)
    sentry_sdk.set_tag("span_id", request.state.span_id)

    # Process request
    return {"status": "ok"}
```

### With Database Queries

```python
@app.get("/users/{user_id}")
async def get_user(user_id: int, request: Request):
    # Add trace context to SQL comments for debugging
    trace_id = request.state.trace_id
    query = f"""
        -- trace_id: {trace_id}
        SELECT * FROM users WHERE id = :user_id
    """
    result = await db.execute(query, {"user_id": user_id})
    return result
```

## Log Output Examples

### Successful Request

```json
{
  "timestamp": "2025-01-07T10:30:45.123Z",
  "level": "INFO",
  "message": "Request started",
  "trace_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "span_id": "f47ac10b",
  "method": "POST",
  "path": "/api/v1/reminders",
  "client_host": "192.168.1.100",
  "query_params": {"filter": "active"}
}

{
  "timestamp": "2025-01-07T10:30:45.246Z",
  "level": "INFO",
  "message": "Request completed",
  "trace_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "span_id": "f47ac10b",
  "method": "POST",
  "path": "/api/v1/reminders",
  "client_host": "192.168.1.100",
  "status_code": 201,
  "duration_ms": 123.45
}
```

### Failed Request

```json
{
  "timestamp": "2025-01-07T10:30:45.123Z",
  "level": "ERROR",
  "message": "Request failed",
  "trace_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "span_id": "f47ac10b",
  "method": "GET",
  "path": "/api/v1/reminders/999",
  "client_host": "192.168.1.100",
  "error_type": "NotFoundError",
  "error_message": "Reminder not found",
  "duration_ms": 45.67
}
```

## Testing

### Unit Tests

Run the test suite:

```bash
pytest tests/unit/test_middleware/test_debug.py -v
```

### Integration Testing

```python
import httpx

async def test_trace_propagation():
    trace_id = "test-trace-id-123"

    async with httpx.AsyncClient() as client:
        # Send request with trace ID
        response = await client.get(
            "http://localhost:8000/api/v1/reminders",
            headers={"X-Trace-Id": trace_id}
        )

        # Verify trace ID is propagated
        assert response.headers["X-Trace-Id"] == trace_id
        assert "X-Span-Id" in response.headers
```

## Troubleshooting

### Trace IDs Not Appearing

1. **Check Middleware is Enabled**:
   ```bash
   APP_ENABLE_DEBUG_MIDDLEWARE=true
   ```

2. **Verify Middleware Order**:
   Debug middleware should run before logging middleware

3. **Check Logs**:
   ```bash
   grep "DebugMiddleware enabled" logs/app.log
   ```

### Missing Context in Logs

1. **Enable Context Injection**:
   ```bash
   LOG_INCLUDE_CONTEXT=true
   ```

2. **Verify ContextInjectingFilter**:
   Check logging configuration includes the filter

### Performance Issues

1. **Disable Request/Response Logging**:
   ```bash
   APP_DEBUG_LOG_REQUESTS=false
   APP_DEBUG_LOG_RESPONSES=false
   ```

2. **Enable Log Sampling**:
   ```bash
   LOG_ENABLE_SAMPLING=true
   LOG_SAMPLING_RATE_DEFAULT=0.1
   ```

## Best Practices

1. **Enable in Non-Production First**: Test in development/staging before production
2. **Use Log Sampling**: Reduce log volume in high-traffic production environments
3. **Propagate Trace IDs**: Always pass trace IDs to downstream services
4. **Monitor Performance**: Track middleware overhead in production
5. **Secure Query Params**: Disable query param logging if sensitive
6. **Correlate with OTel**: Integrate with OpenTelemetry for full observability
7. **Set Alerts**: Alert on missing trace IDs in critical paths

## References

- [OpenTelemetry Tracing](https://opentelemetry.io/docs/concepts/signals/traces/)
- [Distributed Tracing Best Practices](https://www.datadoghq.com/knowledge-center/distributed-tracing/)
- [FastAPI Middleware Guide](https://fastapi.tiangolo.com/tutorial/middleware/)
- [Structured Logging](https://www.structlog.org/en/stable/)
