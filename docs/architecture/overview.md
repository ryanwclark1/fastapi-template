# Architecture Overview

## Service Architecture

This service follows a layered architecture pattern with clear separation of concerns.

## Layers

### 1. Application Layer (`app/`)

The application layer handles HTTP concerns and FastAPI setup.

**Responsibilities:**
- FastAPI application creation
- Middleware configuration
- Router registration
- Lifecycle management

**Key Files:**
- `main.py` - Application factory
- `lifespan.py` - Startup/shutdown handlers
- `middleware.py` - Middleware configuration
- `router.py` - Router registry

### 2. Core Layer (`core/`)

The core layer contains shared infrastructure and business logic foundations.

**Responsibilities:**
- Configuration management
- Dependency injection
- Base classes and interfaces
- Shared schemas and models
- Core business services

**Key Components:**
- `settings.py` - Pydantic settings
- `dependencies/` - FastAPI dependencies
- `schemas/` - Shared Pydantic schemas
- `services/` - Core business services
- `exceptions.py` - Custom exceptions

### 3. Feature Layer (`features/`)

Features are self-contained modules organized by business domain.

**Structure:**
```
features/
└── {feature_name}/
    ├── router.py       # FastAPI endpoints
    ├── schemas.py      # Request/response models
    ├── services.py     # Business logic
    ├── dependencies.py # Feature dependencies
    └── models.py       # Database models (optional)
```

**Example:**
```python
# features/users/router.py
from fastapi import APIRouter, Depends
from .schemas import UserCreate, UserResponse
from .services import UserService

router = APIRouter(prefix="/users", tags=["users"])

@router.post("/", response_model=UserResponse)
async def create_user(
    user: UserCreate,
    service: UserService = Depends(get_user_service)
):
    return await service.create(user)
```

### 4. Infrastructure Layer (`infra/`)

Infrastructure integrations with external systems and services.

**Components:**
- `database/` - Database session and connection management
- `cache/` - Caching infrastructure (Redis)
- `messaging/` - Message queue integration
- `storage/` - Object storage integration
- `external/` - External service clients
- `logging/` - Structured logging
- `metrics/` - Prometheus metrics
- `tracing/` - OpenTelemetry tracing
- `observability/` - Unified observability

## Data Flow

### Request Flow

```
HTTP Request
    ↓
Middleware (CORS, Request ID, Timing)
    ↓
Router (Feature endpoint)
    ↓
Dependencies (Auth, DB session)
    ↓
Service (Business logic)
    ↓
Repository/External (Data access)
    ↓
Response
```

### Example Request Flow

```python
# 1. Middleware adds request ID
# app/middleware.py
class RequestIDMiddleware:
    async def dispatch(self, request, call_next):
        request.state.request_id = str(uuid.uuid4())
        return await call_next(request)

# 2. Router receives request
# features/users/router.py
@router.post("/users")
async def create_user(
    user: UserCreate,
    session: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    service = UserService(session)
    return await service.create(user)

# 3. Service processes business logic
# features/users/services.py
class UserService:
    async def create(self, user: UserCreate) -> User:
        # Validate, transform, persist
        db_user = User(**user.model_dump())
        self.session.add(db_user)
        await self.session.commit()
        return db_user
```

## Dependency Flow

```
main.py (App creation)
    ↓
lifespan.py (Lifecycle events)
    ↓
middleware.py (Request processing)
    ↓
router.py (Route registration)
    ↓
features/*/router.py (Feature endpoints)
    ↓
core/dependencies/* (Shared dependencies)
    ↓
features/*/services.py (Business logic)
    ↓
infra/* (External systems)
```

## Configuration Management

Configuration flows from environment variables through Pydantic settings:

```python
# Environment variables
EXAMPLE_SERVICE_DATABASE_URL=postgresql+psycopg://...
EXAMPLE_SERVICE_REDIS_URL=redis://...

# core/settings.py
class Settings(BaseSettings):
    database_url: str
    redis_url: str

settings = Settings()

# Usage in infrastructure
engine = create_async_engine(settings.database_url)
```

## Error Handling

```
Exception
    ↓
Exception Handler (app/main.py)
    ↓
RFC 7807 Problem Details (core/schemas/problem_details.py)
    ↓
JSON Response
```

**Example:**
```python
# Custom exception
raise NotFoundException(
    detail="User not found",
    type="user-not-found"
)

# Exception handler
@app.exception_handler(AppException)
async def handle_app_exception(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content=ProblemDetails(
            type=exc.type,
            status=exc.status_code,
            detail=exc.detail
        ).model_dump()
    )
```

## Logging Strategy

All components use structured JSON logging:

```python
import logging
logger = logging.getLogger(__name__)

logger.info(
    "User created",
    extra={
        "user_id": user.id,
        "request_id": request.state.request_id
    }
)
```

## Testing Strategy

### Unit Tests
- Test individual components in isolation
- Mock external dependencies
- Fast execution

### Integration Tests
- Test API endpoints end-to-end
- Use test database
- Verify request/response contracts

## Deployment Architecture

```
Load Balancer
    ↓
Multiple Service Instances
    ↓
PostgreSQL (Database)
    ↓
Redis (Cache)
    ↓
External Services
```

## Design Principles

1. **Separation of Concerns** - Each layer has a specific responsibility
2. **Dependency Inversion** - Depend on abstractions, not implementations
3. **Single Responsibility** - Each module does one thing well
4. **Open/Closed** - Open for extension, closed for modification
5. **Testability** - All components are easily testable
6. **Configuration** - Everything configurable via environment

## Best Practices

1. **Use async/await** throughout
2. **Type hints** on all functions
3. **Pydantic schemas** for validation
4. **Structured logging** with context
5. **Error handling** with custom exceptions
6. **Testing** at all layers
7. **Documentation** for all public APIs
