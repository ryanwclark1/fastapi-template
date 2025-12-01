# N+1 Query Detection Middleware

## Overview

The N+1 Query Detection Middleware provides real-time monitoring and detection of N+1 query patterns in FastAPI applications using SQLAlchemy. It helps identify performance issues during development and provides actionable recommendations for optimization.

## Features

- **Real-time N+1 pattern detection** - Identifies repeated similar queries during request processing
- **Request-level query analysis** - Tracks queries per request with context isolation
- **Performance headers** - Adds query count and timing information to responses
- **Slow query logging** - Independently logs queries exceeding a threshold
- **Detailed logging** - Provides actionable recommendations for optimization
- **Exclude patterns** - Filter system/internal queries from monitoring
- **Development-friendly** - Minimal overhead with comprehensive debugging information

## Installation

The middleware is included in the `example_service.app.middleware` package and requires SQLAlchemy for event integration.

```python
from example_service.app.middleware import (
    NPlusOneDetectionMiddleware,
    setup_n_plus_one_monitoring,
)
```

## Basic Usage

### 1. Add Middleware to FastAPI Application

```python
from fastapi import FastAPI
from example_service.app.middleware import NPlusOneDetectionMiddleware

app = FastAPI()

# Add middleware with default settings
app.add_middleware(NPlusOneDetectionMiddleware)

# Or with custom configuration
app.add_middleware(
    NPlusOneDetectionMiddleware,
    threshold=10,                    # Detect after 10 similar queries
    log_slow_queries=True,           # Log slow queries
    slow_query_threshold=1.0,        # 1 second threshold
    enable_detailed_logging=True,    # Enable request summaries
    exclude_patterns=[               # Exclude system tables
        r"pg_catalog",
        r"information_schema",
    ],
)
```

### 2. Set Up SQLAlchemy Event Integration

```python
from sqlalchemy.ext.asyncio import create_async_engine
from example_service.app.middleware import (
    NPlusOneDetectionMiddleware,
    setup_n_plus_one_monitoring,
)
from example_service.core.settings import get_db_settings

# Create engine
db_settings = get_db_settings()
engine = create_async_engine(
    db_settings.url,
    **db_settings.sqlalchemy_engine_kwargs(),
)

# Create middleware instance
middleware = NPlusOneDetectionMiddleware(
    app,
    threshold=10,
    enable_detailed_logging=True,
)

# Set up event listeners
set_request_context = setup_n_plus_one_monitoring(engine, middleware)
```

### 3. Track Queries in Request Context

Create a dependency to set the request context for query tracking:

```python
from fastapi import Depends, Request

async def track_queries(request: Request):
    """Dependency to enable query tracking for the request."""
    set_request_context(request)
    yield

# Use in endpoints
@app.get("/users", dependencies=[Depends(track_queries)])
async def get_users():
    # Queries will be tracked automatically
    users = await user_repository.get_all(session)
    return users
```

## Complete Integration Example

Here's a complete example showing integration with the existing database session:

```python
# example_service/infra/database/session.py
from sqlalchemy.ext.asyncio import create_async_engine
from example_service.app.middleware import (
    NPlusOneDetectionMiddleware,
    setup_n_plus_one_monitoring,
)

# Create engine (existing code)
engine = create_async_engine(
    db_settings.url,
    **db_settings.sqlalchemy_engine_kwargs(),
)

# Global variable to store context setter
_set_request_context = None

def init_n_plus_one_detection(app, middleware):
    """Initialize N+1 detection with SQLAlchemy engine."""
    global _set_request_context
    _set_request_context = setup_n_plus_one_monitoring(engine, middleware)

def get_request_context_setter():
    """Get the request context setter function."""
    return _set_request_context


# example_service/app/main.py
from fastapi import FastAPI, Depends, Request
from example_service.app.middleware import NPlusOneDetectionMiddleware
from example_service.infra.database.session import (
    init_n_plus_one_detection,
    get_request_context_setter,
)

app = FastAPI()

# Create middleware instance
n_plus_one_middleware = NPlusOneDetectionMiddleware(
    app,
    threshold=10,
    log_slow_queries=True,
    slow_query_threshold=1.0,
    enable_detailed_logging=app_settings.debug,
    exclude_patterns=[r"pg_catalog", r"information_schema"],
)

# Add middleware to app
app.add_middleware(
    NPlusOneDetectionMiddleware,
    threshold=10,
    log_slow_queries=True,
    slow_query_threshold=1.0,
    enable_detailed_logging=app_settings.debug,
    exclude_patterns=[r"pg_catalog", r"information_schema"],
)

# Initialize event listeners
init_n_plus_one_detection(app, n_plus_one_middleware)

# Create dependency
async def track_queries(request: Request):
    """Enable query tracking for request."""
    setter = get_request_context_setter()
    if setter:
        setter(request)
    yield

# Apply to all routes (optional)
@app.middleware("http")
async def enable_query_tracking(request: Request, call_next):
    """Middleware to enable query tracking for all requests."""
    setter = get_request_context_setter()
    if setter:
        setter(request)
    response = await call_next(request)
    return response
```

## Configuration Options

### Middleware Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `threshold` | `int` | `10` | Number of similar queries that triggers N+1 detection |
| `time_window` | `float` | `5.0` | Time window in seconds for query pattern analysis |
| `log_slow_queries` | `bool` | `True` | Whether to log slow queries independently |
| `slow_query_threshold` | `float` | `1.0` | Threshold in seconds for slow query logging |
| `enable_detailed_logging` | `bool` | `False` | Enable detailed request summaries |
| `exclude_patterns` | `list[str]` | `None` | List of regex patterns to exclude from monitoring |

### Response Headers

The middleware adds the following headers to responses:

- **X-Query-Count**: Total number of queries executed during request
- **X-Request-Time**: Total request processing time in seconds
- **X-N-Plus-One-Detected**: Number of N+1 patterns detected (only if detected)

## Detection Logic

The middleware detects N+1 patterns based on:

1. **Query Normalization**: Queries are normalized to identify patterns
   - Numeric values replaced with `?`
   - String literals replaced with `?`
   - Parameter placeholders normalized
   - Whitespace normalized

2. **Pattern Tracking**: Similar queries are grouped by normalized pattern

3. **N+1 Detection**: A pattern is flagged as N+1 if:
   - Executed >= threshold times (default: 10)
   - Same normalized query pattern
   - Executions occur in quick succession (< 1 second)

## Examples

### Example 1: Basic N+1 Detection

```python
# This code will trigger N+1 detection
@app.get("/users-with-posts")
async def get_users_with_posts(session: AsyncSession):
    # Query 1: Get all users
    users = await session.execute(select(User))

    # Queries 2-N: Get posts for each user (N+1 pattern!)
    for user in users.scalars():
        posts = await session.execute(
            select(Post).where(Post.user_id == user.id)
        )
        user.posts = posts.scalars().all()

    return users

# Log output:
# WARNING: N+1 Query Pattern Detected: GET /users-with-posts - 1 patterns, 51 total queries
# WARNING:   Pattern 1: 50 executions of query on 'posts' (0.250s total, 0.005s avg)
# WARNING: Recommendation: Use eager loading (joinedload/selectinload) or review repository loading strategies
```

### Example 2: Optimized with Eager Loading

```python
from sqlalchemy.orm import selectinload

# Optimized version using eager loading
@app.get("/users-with-posts")
async def get_users_with_posts(session: AsyncSession):
    # Single query with eager loading
    users = await session.execute(
        select(User).options(selectinload(User.posts))
    )

    return users.scalars().all()

# Log output:
# INFO: Request Summary: GET /users-with-posts - 2 queries, 0.050s, 0 N+1 patterns detected
```

### Example 3: Custom Exclude Patterns

```python
# Exclude system and migration queries
app.add_middleware(
    NPlusOneDetectionMiddleware,
    threshold=10,
    exclude_patterns=[
        r"pg_catalog",           # PostgreSQL system catalog
        r"information_schema",   # SQL standard system tables
        r"alembic_version",      # Migration version table
        r"pg_stat",              # PostgreSQL statistics
    ],
)
```

### Example 4: Development vs Production Configuration

```python
from example_service.core.settings import get_app_settings

app_settings = get_app_settings()

if app_settings.debug:
    # Development: Strict detection with detailed logging
    app.add_middleware(
        NPlusOneDetectionMiddleware,
        threshold=5,                     # More sensitive
        log_slow_queries=True,
        slow_query_threshold=0.1,        # 100ms threshold
        enable_detailed_logging=True,    # Verbose logs
    )
else:
    # Production: Relaxed detection, minimal logging
    app.add_middleware(
        NPlusOneDetectionMiddleware,
        threshold=20,                    # Less sensitive
        log_slow_queries=True,
        slow_query_threshold=1.0,        # 1s threshold
        enable_detailed_logging=False,   # Only N+1 warnings
    )
```

## Best Practices

### 1. Use Eager Loading

When you know you'll need related data, use SQLAlchemy's eager loading:

```python
from sqlalchemy.orm import selectinload, joinedload

# selectinload: Separate query with IN clause (recommended for collections)
users = await session.execute(
    select(User).options(selectinload(User.posts))
)

# joinedload: LEFT OUTER JOIN (recommended for many-to-one)
posts = await session.execute(
    select(Post).options(joinedload(Post.author))
)
```

### 2. Use Batch Loading

For collections, load in batches instead of one-by-one:

```python
# Bad: N+1 pattern
for user_id in user_ids:
    user = await session.get(User, user_id)

# Good: Batch loading
users = await session.execute(
    select(User).where(User.id.in_(user_ids))
)
```

### 3. Configure for Your Environment

```python
# Development: Strict detection
if app_settings.environment == "development":
    threshold = 5
    enable_detailed_logging = True

# Staging: Moderate detection
elif app_settings.environment == "staging":
    threshold = 10
    enable_detailed_logging = True

# Production: Relaxed detection
else:
    threshold = 20
    enable_detailed_logging = False
```

### 4. Monitor Response Headers

Use the response headers to track query counts in tests:

```python
def test_user_endpoint_query_count():
    response = client.get("/users")

    query_count = int(response.headers["X-Query-Count"])
    assert query_count <= 10, f"Too many queries: {query_count}"
```

### 5. Exclude System Queries

Always exclude system and framework queries:

```python
exclude_patterns=[
    r"pg_catalog",
    r"information_schema",
    r"alembic_version",
    r"sqlite_",
]
```

## Performance Impact

The middleware has minimal performance overhead:

- **Per-query overhead**: < 0.1ms (event listener execution)
- **Per-request overhead**: < 1ms (pattern analysis after response)
- **Memory overhead**: Minimal (tracks normalized patterns, not full queries)

The overhead is negligible compared to actual database query time.

## Troubleshooting

### Middleware Not Detecting Queries

1. Ensure SQLAlchemy event listeners are set up:
   ```python
   set_request_context = setup_n_plus_one_monitoring(engine, middleware)
   ```

2. Ensure request context is set for each request:
   ```python
   set_request_context(request)
   ```

3. Check that queries are executed within request context

### False Positives

If you're getting false positives:

1. Increase the threshold:
   ```python
   app.add_middleware(NPlusOneDetectionMiddleware, threshold=20)
   ```

2. Add exclude patterns for legitimate repeated queries:
   ```python
   exclude_patterns=[r"cache_lookup", r"session_check"]
   ```

### Missing Slow Query Logs

Ensure slow query logging is enabled:

```python
app.add_middleware(
    NPlusOneDetectionMiddleware,
    log_slow_queries=True,
    slow_query_threshold=0.1,  # Lower threshold
)
```

## Security Considerations

- **No sensitive data in logs**: Queries are normalized before logging (values replaced with `?`)
- **Exclude sensitive queries**: Use `exclude_patterns` to filter sensitive operations
- **Production safety**: Safe for production use with appropriate configuration
- **No parameter logging**: Query parameters are never logged

## Comprehensive Examples

### Example 1: Basic Setup with Dependency

This example shows the simplest way to set up N+1 detection using a dependency on specific endpoints.

```python
from fastapi import Depends, FastAPI

app = FastAPI()

# Configure N+1 detection
configure_n_plus_one_detection(app)

# Use dependency in endpoints
@app.get("/users", dependencies=[Depends(track_queries_dependency)])
async def get_users():
    """Get all users with query tracking."""
    # Queries will be automatically tracked
    return {"users": []}
```

### Example 2: Global Tracking for All Endpoints

Enable query tracking automatically for all endpoints without requiring a dependency on each route.

```python
from fastapi import FastAPI

app = FastAPI()

# Configure N+1 detection
configure_n_plus_one_detection(app)

# Enable global tracking
configure_global_query_tracking(app)

# All endpoints automatically tracked
@app.get("/users")
async def get_users():
    """Get all users with automatic tracking."""
    return {"users": []}
```

### Example 3: Custom Configuration for Specific Needs

Customize circuit breaker configuration for specific requirements like stricter thresholds.

```python
from fastapi import FastAPI
from example_service.app.middleware.n_plus_one_detection import (
    NPlusOneDetectionMiddleware,
    setup_n_plus_one_monitoring,
)
from example_service.infra.database.session import engine

app = FastAPI()

# Custom middleware configuration
middleware = NPlusOneDetectionMiddleware(
    app,
    threshold=5,  # Very sensitive
    log_slow_queries=True,
    slow_query_threshold=0.05,  # 50ms threshold
    enable_detailed_logging=True,
    exclude_patterns=[
        r"pg_catalog",
        r"information_schema",
        r"cache_.*",  # Exclude cache queries
        r"session_.*",  # Exclude session queries
    ],
)

app.add_middleware(
    NPlusOneDetectionMiddleware,
    threshold=5,
    log_slow_queries=True,
    slow_query_threshold=0.05,
    enable_detailed_logging=True,
    exclude_patterns=[
        r"pg_catalog",
        r"information_schema",
        r"cache_.*",
        r"session_.*",
    ],
)

# Set up event listeners
global _set_request_context
_set_request_context = setup_n_plus_one_monitoring(engine, middleware)
```

### Example 4: Testing with Query Count Assertions

Ensure your endpoints stay within query count limits using automated tests.

```python
from fastapi.testclient import TestClient
from example_service.app.main import app

client = TestClient(app)

# Test endpoint query count
response = client.get("/users")

# Check query count from response headers
query_count = int(response.headers.get("X-Query-Count", 0))
assert query_count <= 10, f"Too many queries: {query_count}"

# Check for N+1 detection
assert "X-N-Plus-One-Detected" not in response.headers, "N+1 query detected!"
```

### Example 5: Production Monitoring with Metrics

Integrate N+1 detection with Prometheus metrics for production monitoring.

```python
import prometheus_client

# Create custom metrics for N+1 detection
n_plus_one_detected = prometheus_client.Counter(
    "n_plus_one_patterns_detected_total",
    "Total number of N+1 patterns detected",
    ["endpoint", "method"],
)

query_count_histogram = prometheus_client.Histogram(
    "request_query_count",
    "Number of queries per request",
    ["endpoint"],
    buckets=[1, 5, 10, 20, 50, 100],
)

# In your middleware or application code
def track_n_plus_one_metrics(request, response):
    """Track N+1 detection metrics."""
    query_count = int(response.headers.get("X-Query-Count", 0))
    n_plus_one_count = int(response.headers.get("X-N-Plus-One-Detected", 0))

    # Record metrics
    query_count_histogram.labels(endpoint=request.url.path).observe(query_count)

    if n_plus_one_count > 0:
        n_plus_one_detected.labels(
            endpoint=request.url.path, method=request.method
        ).inc(n_plus_one_count)
```

### Example 6: Complete Configuration Function

A complete helper function that configures N+1 detection based on environment.

```python
from fastapi import FastAPI
from example_service.app.middleware.n_plus_one_detection import (
    NPlusOneDetectionMiddleware,
    setup_n_plus_one_monitoring,
)
from example_service.core.settings import get_app_settings, get_db_settings
from example_service.infra.database.session import engine
import logging

logger = logging.getLogger(__name__)

# Global variable to store the request context setter
_set_request_context = None


def configure_n_plus_one_detection(app: FastAPI) -> None:
    """Configure N+1 detection middleware for the application.

    This function sets up the N+1 detection middleware with appropriate
    configuration based on the environment (development/staging/production).

    Args:
        app: FastAPI application instance

    Example:
        >>> from fastapi import FastAPI
        >>> app = FastAPI()
        >>> configure_n_plus_one_detection(app)
    """
    global _set_request_context

    app_settings = get_app_settings()
    db_settings = get_db_settings()

    # Skip if database is not configured
    if not db_settings.is_configured:
        logger.info("Database not configured, skipping N+1 detection setup")
        return

    # Configure based on environment
    if app_settings.environment == "development":
        # Development: Strict detection with detailed logging
        threshold = 5
        enable_detailed_logging = True
        slow_query_threshold = 0.1  # 100ms
    elif app_settings.environment == "staging":
        # Staging: Moderate detection with logging
        threshold = 10
        enable_detailed_logging = True
        slow_query_threshold = 0.5  # 500ms
    else:
        # Production: Relaxed detection, minimal logging
        threshold = 20
        enable_detailed_logging = False
        slow_query_threshold = 1.0  # 1 second

    # Exclude common system queries
    exclude_patterns = [
        r"pg_catalog",
        r"information_schema",
        r"alembic_version",
        r"pg_stat",
        r"sqlite_",
    ]

    # Create middleware instance
    middleware = NPlusOneDetectionMiddleware(
        app,
        threshold=threshold,
        log_slow_queries=True,
        slow_query_threshold=slow_query_threshold,
        enable_detailed_logging=enable_detailed_logging,
        exclude_patterns=exclude_patterns,
    )

    # Add middleware to application
    app.add_middleware(
        NPlusOneDetectionMiddleware,
        threshold=threshold,
        log_slow_queries=True,
        slow_query_threshold=slow_query_threshold,
        enable_detailed_logging=enable_detailed_logging,
        exclude_patterns=exclude_patterns,
    )

    # Set up SQLAlchemy event listeners
    _set_request_context = setup_n_plus_one_monitoring(engine, middleware)

    logger.info(
        "N+1 detection middleware configured",
        extra={
            "threshold": threshold,
            "slow_query_threshold": slow_query_threshold,
            "detailed_logging": enable_detailed_logging,
            "environment": app_settings.environment,
        },
    )


async def track_queries_dependency(request: Request) -> AsyncGenerator[None, None]:
    """FastAPI dependency to enable query tracking for a request.

    This dependency sets the request context for query tracking, allowing
    the N+1 detection middleware to monitor queries executed during the
    request lifecycle.

    Args:
        request: FastAPI request object

    Yields:
        None

    Example:
        >>> from fastapi import Depends
        >>>
        >>> @app.get("/users", dependencies=[Depends(track_queries_dependency)])
        >>> async def get_users():
        ...     return await user_repository.get_all(session)
    """
    if _set_request_context:
        _set_request_context(request)
    yield
```

### Example 7: Global Query Tracking via Middleware

Alternative approach using middleware to automatically enable query tracking for all requests.

```python
from fastapi import FastAPI, Request
import logging

logger = logging.getLogger(__name__)


def configure_global_query_tracking(app: FastAPI) -> None:
    """Configure global query tracking for all requests.

    This approach automatically enables query tracking for all requests
    without requiring a dependency. Use this for comprehensive monitoring
    across all endpoints.

    Args:
        app: FastAPI application instance

    Example:
        >>> from fastapi import FastAPI
        >>> app = FastAPI()
        >>> configure_n_plus_one_detection(app)
        >>> configure_global_query_tracking(app)
    """

    @app.middleware("http")
    async def enable_query_tracking(request: Request, call_next):
        """Middleware to enable query tracking for all requests."""
        if _set_request_context:
            _set_request_context(request)
        response = await call_next(request)
        return response

    logger.info("Global query tracking enabled for all requests")
```

## Related Documentation

- [SQLAlchemy Relationship Loading Techniques](https://docs.sqlalchemy.org/en/20/orm/queryguide/relationships.html)
- [FastAPI Middleware](https://fastapi.tiangolo.com/tutorial/middleware/)
- [Database Performance Best Practices](./DATABASE_BEST_PRACTICES.md)

## Testing

Run the middleware tests:

```bash
# Unit tests
pytest tests/unit/test_middleware/test_n_plus_one_detection.py -v

# Integration tests
pytest tests/integration/test_n_plus_one_middleware.py -v
```

## Contributing

When contributing improvements to the N+1 detection middleware:

1. Maintain backward compatibility
2. Add comprehensive tests for new features
3. Update this documentation
4. Ensure minimal performance overhead
5. Follow the existing code style
