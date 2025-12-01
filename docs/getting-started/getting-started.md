# Getting Started Guide

Step-by-step guide to set up and run the FastAPI template with all features enabled.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Quick Start (5 Minutes)](#quick-start-5-minutes)
3. [Full Setup (15 Minutes)](#full-setup-15-minutes)
4. [Configuration Recipes](#configuration-recipes)
5. [Common Patterns](#common-patterns)
6. [Troubleshooting](#troubleshooting)
7. [Next Steps](#next-steps)

---

## Prerequisites

### Required

- **Python 3.13+** - Modern Python with async support
- **uv** - Fast Python package installer (recommended)
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

### Optional (Enable as Needed)

- **Docker & Docker Compose** - For running infrastructure services
- **PostgreSQL 16+** - Database (or use Docker)
- **Redis 7+** - Caching and rate limiting (or use Docker)
- **RabbitMQ 3.13+** - Message queue (or use Docker)

### Development Tools

- **Git** - Version control
- **make** - Build automation (optional)
- **httpie** or **curl** - API testing

---

## Quick Start (5 Minutes)

Get the service running with minimal configuration.

### Step 1: Clone and Install

```bash
# Clone repository
git clone https://github.com/your-org/fastapi-template.git
cd fastapi-template

# Install dependencies
uv sync

# Or with pip
pip install -e .
```

### Step 2: Configure Environment

```bash
# Copy environment template
cp .env.example .env

# Edit minimal settings
# Required: None (uses SQLite by default for quick start)
```

### Step 3: Run Service

```bash
# Run with uvicorn
uv run uvicorn example_service.app.main:app --reload

# Or use the CLI
uv run example-service

# Service starts at http://localhost:8000
```

### Step 4: Test Endpoints

```bash
# Health check
curl http://localhost:8000/api/v1/health/

# API documentation
open http://localhost:8000/docs

# OpenAPI spec
curl http://localhost:8000/openapi.json
```

That's it! You have a basic service running. Continue to [Full Setup](#full-setup-15-minutes) for production features.

---

## Full Setup (15 Minutes)

Enable all features including authentication, caching, and observability.

### Step 1: Start Infrastructure Services

```bash
# Start PostgreSQL, Redis, RabbitMQ
cd deployment/docker
docker compose up -d db redis rabbitmq

# Verify services are running
docker compose ps

# Check logs
docker compose logs -f
```

### Step 2: Configure Database

```bash
# Update .env with database connection
cat >> .env << 'EOF'
DB_ENABLED=true
DB_DSN=postgresql+psycopg://postgres:postgres@localhost:5432/example_service
EOF

# Run migrations
uv run alembic upgrade head

# Verify database
uv run python -c "
from example_service.core.settings import get_db_settings
from example_service.infra.database import get_engine
import asyncio

async def test():
    settings = get_db_settings()
    engine = get_engine(settings)
    async with engine.connect() as conn:
        print('✓ Database connected')

asyncio.run(test())
"
```

### Step 3: Configure Redis

```bash
# Add Redis configuration to .env
cat >> .env << 'EOF'
REDIS_REDIS_URL=redis://localhost:6379/0
EOF

# Test Redis connection
uv run python -c "
from example_service.infra.cache import get_cache
import asyncio

async def test():
    redis = get_cache()
    await redis.set('test', 'value')
    value = await redis.get('test')
    print(f'✓ Redis connected: {value}')

asyncio.run(test())
"
```

### Step 4: Enable Authentication (Optional)

If using Accent-Auth:

```bash
# Add authentication configuration
cat >> .env << 'EOF'
AUTH_SERVICE_URL=http://accent-auth:9497
AUTH_TOKEN_CACHE_TTL=300
AUTH_ENABLE_PERMISSION_CACHING=true
EOF
```

If using standalone:

```bash
# Authentication is optional for development
# See docs/integrations/accent-auth-integration.md for full setup
```

### Step 5: Enable Security Features

```bash
# Add security middleware configuration
cat >> .env << 'EOF'
APP_ENABLE_RATE_LIMITING=true
APP_RATE_LIMIT_PER_MINUTE=120
APP_STRICT_CSP=true
APP_ENABLE_REQUEST_SIZE_LIMIT=true
APP_REQUEST_SIZE_LIMIT=10485760
EOF
```

### Step 6: Enable Observability

```bash
# Add observability configuration
cat >> .env << 'EOF'
OTEL_ENABLED=true
OTEL_ENDPOINT=http://localhost:4317
LOG_JSON_LOGS=true
LOG_LEVEL=INFO
EOF

# Start observability stack (optional)
cd deployment/docker
docker compose up -d alloy prometheus grafana
```

### Step 7: Run Service

```bash
# Run with all features enabled
uv run uvicorn example_service.app.main:app --reload

# Or use the CLI with custom port
uv run example-service --port 8000 --host 0.0.0.0
```

### Step 8: Verify Setup

```bash
# Health check with dependencies
curl http://localhost:8000/api/v1/health/ready

# Expected response:
{
  "status": "healthy",
  "checks": {
    "database": "healthy",
    "cache": "healthy",
    "messaging": "healthy"
  }
}

# View metrics
curl http://localhost:8000/metrics

# View logs
tail -f logs/example-service.log
```

---

## Configuration Recipes

### Recipe 1: Development Environment

Optimized for local development with debugging.

```bash
# .env
APP_ENVIRONMENT=development
APP_DEBUG=true
APP_ENABLE_DEBUG_MIDDLEWARE=true
APP_ENABLE_RATE_LIMITING=false
LOG_LEVEL=DEBUG
LOG_JSON_LOGS=false
OTEL_ENABLED=false
DB_ECHO=true
```

**Features**:
- ✅ Debug middleware enabled
- ✅ Detailed logging
- ✅ SQL query echo
- ❌ Rate limiting disabled
- ❌ Observability disabled

### Recipe 2: Staging Environment

Production-like with additional debugging.

```bash
# .env
APP_ENVIRONMENT=staging
APP_DEBUG=false
APP_ENABLE_RATE_LIMITING=true
APP_RATE_LIMIT_PER_MINUTE=500
APP_STRICT_CSP=true
LOG_LEVEL=INFO
LOG_JSON_LOGS=true
OTEL_ENABLED=true
OTEL_SAMPLE_RATE=1.0
```

**Features**:
- ✅ Security enabled
- ✅ Rate limiting (generous)
- ✅ Full observability
- ✅ JSON logs

### Recipe 3: Production Environment

Maximum security and performance.

```bash
# .env
APP_ENVIRONMENT=production
APP_DEBUG=false
APP_DISABLE_DOCS=true
APP_STRICT_CSP=true
APP_ENABLE_RATE_LIMITING=true
APP_RATE_LIMIT_PER_MINUTE=120
APP_ENABLE_DEBUG_MIDDLEWARE=false
LOG_LEVEL=WARNING
LOG_JSON_LOGS=true
OTEL_ENABLED=true
OTEL_SAMPLE_RATE=0.1
```

**Features**:
- ✅ Maximum security
- ✅ Rate limiting (strict)
- ✅ Sampled tracing (10%)
- ❌ Debug features disabled
- ❌ API docs disabled

### Recipe 4: Multi-Tenant SaaS

With tenant isolation and authentication.

```bash
# .env
APP_ENVIRONMENT=production
AUTH_SERVICE_URL=http://accent-auth:9497
AUTH_TOKEN_CACHE_TTL=300
APP_ENABLE_RATE_LIMITING=true
DB_ENABLED=true
REDIS_REDIS_URL=redis://localhost:6379/0
```

**Code Setup**:
```python
# app/main.py
from example_service.core.middleware.tenant import (
    TenantMiddleware,
    HeaderTenantStrategy,
)

app.add_middleware(
    TenantMiddleware,
    strategies=[HeaderTenantStrategy(header_name="Accent-Tenant")],
    required=True,
)
```

### Recipe 5: Microservice in Service Mesh

With service discovery and distributed tracing.

```bash
# .env
APP_ENVIRONMENT=production
CONSUL_ENABLED=true
CONSUL_HOST=localhost
CONSUL_PORT=8500
OTEL_ENABLED=true
OTEL_ENDPOINT=http://collector:4317
RABBIT_ENABLED=true
```

---

## Common Patterns

### Pattern 1: Authenticated Endpoint

```python
from typing import Annotated
from fastapi import APIRouter, Depends
from example_service.core.dependencies.accent_auth import (
    require_acl,
    AuthUser,
)

router = APIRouter(prefix="/api/v1/data", tags=["data"])

@router.get("/")
async def list_data(
    user: Annotated[AuthUser, Depends(require_acl("data.read"))]
):
    """List data - requires data.read ACL."""
    return {
        "user_id": user.user_id,
        "tenant_id": user.metadata.get("tenant_uuid"),
        "data": []
    }
```

### Pattern 2: File Upload

```python
from fastapi import UploadFile
from example_service.infra.storage import get_storage_client

@router.post("/upload")
async def upload_file(file: UploadFile):
    """Upload file to S3."""
    client = get_storage_client()

    # Upload file
    result = await client.upload_file(
        file_obj=file.file,
        key=f"uploads/{file.filename}",
        content_type=file.content_type
    )

    # Generate presigned URL
    url = await client.get_presigned_url(result.key, expires_in=3600)

    return {
        "file_id": result.key,
        "download_url": url
    }
```

### Pattern 3: Real-time Event

```python
from example_service.infra.realtime.event_bridge import EventBridge

@router.post("/items")
async def create_item(item: ItemCreate):
    """Create item and broadcast event."""
    # Create item
    new_item = await item_service.create(item)

    # Broadcast to all connected clients
    bridge = EventBridge()
    await bridge.publish("items", {
        "type": "item.created",
        "data": new_item.dict()
    })

    return new_item
```

### Pattern 4: Background Task with Outbox

```python
from example_service.infra.events.outbox import save_event

@router.post("/process")
async def process_data(
    data: ProcessRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
):
    """Process data with reliable event publishing."""
    async with session.begin():
        # Update database
        result = await processor.process(data)

        # Save event to outbox (same transaction)
        await save_event(
            session=session,
            event_type="data.processed",
            payload={"id": result.id, "status": "completed"}
        )
        # Event will be published by background processor

    return result
```

### Pattern 5: WebSocket Connection

```python
from fastapi import WebSocket
from example_service.infra.realtime.manager import ConnectionManager

manager = ConnectionManager()

@app.websocket("/ws/{channel}")
async def websocket_endpoint(websocket: WebSocket, channel: str):
    """WebSocket endpoint with channel subscription."""
    connection_id = await manager.connect(websocket, [channel])
    try:
        async for message in websocket.iter_text():
            # Echo to all subscribers
            await manager.broadcast(channel, {
                "type": "message",
                "data": message
            })
    finally:
        await manager.disconnect(connection_id)
```

---

## Troubleshooting

### Issue 1: Service Won't Start

**Symptoms**:
```
ERROR: Could not connect to database
```

**Solutions**:

1. **Check database is running**:
   ```bash
   docker compose ps db
   # If not running:
   docker compose up -d db
   ```

2. **Verify database connection**:
   ```bash
   # Update DB_DSN in .env
   DB_DSN=postgresql+psycopg://postgres:postgres@localhost:5432/example_service
   ```

3. **Run migrations**:
   ```bash
   uv run alembic upgrade head
   ```

4. **Disable database for quick start**:
   ```bash
   DB_ENABLED=false
   ```

---

### Issue 2: Authentication Not Working

**Symptoms**:
```
401 Unauthorized: Missing X-Auth-Token header
```

**Solutions**:

1. **Check Accent-Auth service**:
   ```bash
   curl -I http://accent-auth:9497/api/auth/0.1/health
   ```

2. **Verify configuration**:
   ```bash
   # .env
   AUTH_SERVICE_URL=http://accent-auth:9497  # Check URL
   ```

3. **Use test token** (development only):
   ```bash
   # Generate test token
   curl -X POST http://accent-auth:9497/api/auth/0.1/token \
     -H "Content-Type: application/json" \
     -d '{"username": "admin", "password": "admin"}'
   ```

4. **Make endpoint public** (if not protected):
   ```python
   @router.get("/public")
   async def public_endpoint():
       # No authentication required
       return {"data": "public"}
   ```

---

### Issue 3: Rate Limiting Too Strict

**Symptoms**:
```
429 Too Many Requests
Retry-After: 45
```

**Solutions**:

1. **Increase limits**:
   ```bash
   # .env
   APP_RATE_LIMIT_PER_MINUTE=300  # Increase from 120
   ```

2. **Disable for development**:
   ```bash
   APP_ENABLE_RATE_LIMITING=false
   ```

3. **Add endpoint exemption**:
   ```python
   from example_service.app.middleware.constants import EXEMPT_PATHS
   EXEMPT_PATHS.append("/api/v1/my-endpoint")
   ```

---

### Issue 4: CORS Errors

**Symptoms**:
```
Access to fetch blocked by CORS policy
```

**Solutions**:

1. **Enable CORS for development**:
   ```bash
   # .env
   APP_DEBUG=true  # Enables CORS
   APP_CORS_ORIGINS=["http://localhost:3000"]
   ```

2. **Add specific origin**:
   ```bash
   APP_CORS_ORIGINS=["http://localhost:3000", "http://localhost:8080"]
   ```

---

### Issue 5: High Memory Usage

**Symptoms**:
- Service memory grows over time
- OOM errors

**Solutions**:

1. **Disable debug features**:
   ```bash
   APP_ENABLE_DEBUG_MIDDLEWARE=false
   LOG_LEVEL=INFO  # Not DEBUG
   ```

2. **Reduce connection pools**:
   ```bash
   DB_POOL_SIZE=5  # Reduce from 10
   DB_MAX_OVERFLOW=5
   REDIS_MAX_CONNECTIONS=25  # Reduce from 50
   ```

3. **Monitor memory**:
   ```bash
   # Check metrics
   curl http://localhost:8000/metrics | grep process_resident_memory
   ```

---

## Next Steps

### 1. Add Your First Feature

```bash
# Create feature module
mkdir -p example_service/features/myfeature
touch example_service/features/myfeature/__init__.py
touch example_service/features/myfeature/router.py
touch example_service/features/myfeature/models.py
touch example_service/features/myfeature/service.py
```

```python
# example_service/features/myfeature/router.py
from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/myfeature", tags=["myfeature"])

@router.get("/")
async def list_items():
    return {"items": []}
```

```python
# Register in app/router.py
from example_service.features.myfeature import router as myfeature_router

def register_routes(app: FastAPI) -> None:
    app.include_router(myfeature_router)
```

### 2. Add Database Models

```python
# example_service/features/myfeature/models.py
from sqlalchemy import Column, Integer, String
from example_service.infra.database import Base, TimestampMixin

class MyModel(Base, TimestampMixin):
    __tablename__ = "my_models"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
```

```bash
# Create migration
uv run alembic revision --autogenerate -m "Add MyModel"

# Apply migration
uv run alembic upgrade head
```

### 3. Add Tests

```python
# tests/unit/test_features/test_myfeature/test_api.py
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_list_items(client: AsyncClient):
    response = await client.get("/api/v1/myfeature/")
    assert response.status_code == 200
    assert "items" in response.json()
```

```bash
# Run tests
uv run pytest tests/unit/test_features/test_myfeature/
```

### 4. Add Documentation

```markdown
# docs/features/myfeature.md

# MyFeature Documentation

## Overview
Brief description of the feature.

## API Endpoints
- GET /api/v1/myfeature/ - List items
- POST /api/v1/myfeature/ - Create item

## Configuration
Required environment variables...
```

### 5. Deploy to Production

See deployment guides:
- [Kubernetes Deployment](deployment/kubernetes.md)
- [Docker Deployment](deployment/docker.md)
- [Security Configuration](SECURITY_CONFIGURATION.md)
- [Monitoring Setup](MONITORING_SETUP.md)

---

## Environment Variable Reference

### Quick Reference Table

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `APP_SERVICE_NAME` | No | example-service | Service name |
| `APP_DEBUG` | No | false | Debug mode |
| `DB_DSN` | No | None | Database connection string |
| `REDIS_REDIS_URL` | No | None | Redis connection string |
| `AUTH_SERVICE_URL` | No | None | Accent-Auth service URL |
| `APP_ENABLE_RATE_LIMITING` | No | false | Enable rate limiting |
| `OTEL_ENABLED` | No | false | Enable OpenTelemetry |

See [.env.example](/home/administrator/Code/fastapi-template/.env.example) for complete reference.

---

## Additional Resources

### Documentation

- 🎯 [Feature Overview](ACCENT_AI_FEATURES.md) - Complete feature list
- 🛡️ [Middleware Guide](MIDDLEWARE_GUIDE.md) - Middleware configuration
- 🔐 [Authentication Guide](ACCENT_AUTH_INTEGRATION.md) - Auth setup
- 🏗️ [Architecture Overview](architecture/overview.md) - System design
- 🔒 [Security Guide](SECURITY_CONFIGURATION.md) - Security hardening

### Examples

- [Example Service Code](/home/administrator/Code/fastapi-template/example_service/)
- [Test Examples](/home/administrator/Code/fastapi-template/tests/)
- [CLI Examples](CLI_README.md)

### Tools

- **API Docs**: http://localhost:8000/docs
- **Metrics**: http://localhost:8000/metrics
- **Health**: http://localhost:8000/api/v1/health/

---

## FAQ

### Q: Do I need all dependencies?

**A**: No. Most dependencies are optional. Minimum requirements:
- Python 3.13+
- uv or pip

Enable features as needed:
- Database: `pip install sqlalchemy psycopg[binary]`
- Redis: `pip install redis`
- Storage: `pip install aioboto3`

### Q: Can I use without Accent-Auth?

**A**: Yes. Authentication is optional. Remove auth dependencies from endpoints:

```python
# Without auth
@router.get("/data")
async def get_data():
    return {"data": []}

# With optional auth
@router.get("/data")
async def get_data(
    user: Annotated[AuthUser | None, Depends(get_current_user_optional)]
):
    if user:
        # Authenticated
        pass
    return {"data": []}
```

### Q: How do I customize middleware?

**A**: See [MIDDLEWARE_GUIDE.md](MIDDLEWARE_GUIDE.md) for complete configuration options.

### Q: Where are the logs?

**A**:
- Console: `stdout` (default)
- File: `logs/example-service.log` (if enabled)
- JSON: Set `LOG_JSON_LOGS=true`

---

**Version**: 1.0.0
**Last Updated**: 2025-12-01
**Template**: FastAPI Production Template
