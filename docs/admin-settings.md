# Database Admin Settings

## Overview

The `AdminSettings` class provides configuration for database administration features including health checks, query timeouts, rate limiting, and audit retention.

## Configuration

### Environment Variables

All admin settings use the `ADMIN_` prefix. Configure them via environment variables or `.env` file:

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

# Confirmation tokens
ADMIN_CONFIRMATION_TOKEN_EXPIRY_MINUTES=2
```

## Usage

### Direct Access

```python
from example_service.core.settings import get_admin_settings

settings = get_admin_settings()

if settings.enabled:
    timeout = settings.default_query_timeout_seconds
    # Use settings...
```

### Unified Settings

```python
from example_service.core.settings import get_settings

settings = get_settings()

if settings.admin.enabled:
    max_ops = settings.admin.rate_limit_max_ops
    # Use settings...
```

## Settings Reference

### Feature Toggle

- **`enabled`** (bool, default: `true`)
  - Enable database admin features globally

### Rate Limiting

- **`rate_limit_enabled`** (bool, default: `true`)
  - Enable rate limiting for admin operations

- **`rate_limit_max_ops`** (int, default: `5`, range: 1-100)
  - Maximum admin operations allowed per time window

- **`rate_limit_window_seconds`** (int, default: `60`, range: 10-3600)
  - Time window duration for rate limiting in seconds

### Query Timeouts

- **`default_query_timeout_seconds`** (int, default: `30`, range: 5-300)
  - Default timeout for admin queries

- **`health_check_timeout_seconds`** (int, default: `10`, range: 1-60)
  - Timeout for health check queries

### Health Thresholds

- **`connection_pool_critical_threshold`** (float, default: `90.0`, range: 0-100)
  - Connection pool usage percentage that triggers critical alerts

- **`connection_pool_warning_threshold`** (float, default: `75.0`, range: 0-100)
  - Connection pool usage percentage that triggers warnings

- **`cache_hit_ratio_warning_threshold`** (float, default: `85.0`, range: 0-100)
  - Cache hit ratio percentage below which warnings are triggered

### Audit Retention

- **`audit_log_retention_days`** (int, default: `90`, range: 1-730)
  - Number of days to retain audit logs before cleanup

### Confirmation Tokens

- **`confirmation_token_expiry_minutes`** (int, default: `2`, range: 1-10)
  - Time before confirmation tokens expire (for dangerous operations)

## Validation

All settings include validation constraints:

- Integer ranges enforce minimum and maximum values
- Float percentages are constrained to 0-100
- Settings are immutable (frozen) once loaded
- Invalid values raise `ValidationError` at startup

## Examples

### Production Configuration

```bash
# Enable all features with conservative limits
ADMIN_ENABLED=true
ADMIN_RATE_LIMIT_ENABLED=true
ADMIN_RATE_LIMIT_MAX_OPS=3
ADMIN_RATE_LIMIT_WINDOW_SECONDS=300
ADMIN_DEFAULT_QUERY_TIMEOUT_SECONDS=60
ADMIN_CONNECTION_POOL_CRITICAL_THRESHOLD=85.0
ADMIN_AUDIT_LOG_RETENTION_DAYS=180
```

### Development Configuration

```bash
# More permissive for development
ADMIN_ENABLED=true
ADMIN_RATE_LIMIT_ENABLED=false
ADMIN_DEFAULT_QUERY_TIMEOUT_SECONDS=300
ADMIN_AUDIT_LOG_RETENTION_DAYS=30
```

### Disabled Configuration

```bash
# Disable admin features entirely
ADMIN_ENABLED=false
```

## Testing

Clear the cache between tests to reload settings:

```python
from example_service.core.settings import get_admin_settings

# Clear cache to force reload
get_admin_settings.cache_clear()

# Settings will be reloaded from environment
settings = get_admin_settings()
```

## Integration Points

The admin settings are used by:

- **Health Check Endpoints** - Connection pool and cache monitoring
- **Admin API Routers** - Rate limiting and timeout configuration
- **Audit Service** - Log retention policies
- **Dangerous Operations** - Confirmation token expiry

## See Also

- [Database Settings](../example_service/core/settings/postgres.py) - Main database configuration
- [Health Check Settings](../example_service/core/settings/health.py) - Health monitoring configuration
- [Unified Settings](../example_service/core/settings/unified.py) - All settings composition
