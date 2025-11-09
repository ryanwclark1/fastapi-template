# FastAPI Best Practices

This document outlines best practices for developing and maintaining this FastAPI service. It should be updated as new patterns emerge and the project evolves.

**Last Updated:** November 2025
**Python Version:** 3.13+

---

## Table of Contents

1. [Project Structure](#project-structure)
2. [Async Programming](#async-programming)
3. [Pydantic Models & Validation](#pydantic-models--validation)
4. [Dependency Injection](#dependency-injection)
5. [Database Patterns](#database-patterns)
6. [API Design](#api-design)
7. [Error Handling](#error-handling)
8. [Testing](#testing)
9. [Performance](#performance)
10. [Security](#security)
11. [Logging & Observability](#logging--observability)
12. [Code Quality](#code-quality)

---

## Project Structure

### Feature-Based Organization

**✅ DO:** Organize code by business domain/feature
```python
features/
└── users/
    ├── router.py       # API endpoints
    ├── schemas.py      # Request/response models
    ├── services.py     # Business logic
    ├── repositories.py # Data access
    ├── models.py       # Database models
    └── dependencies.py # Feature-specific dependencies
```

**❌ DON'T:** Organize by file type (all routes together, all models together)
```python
# Anti-pattern
routes/
  ├── user_routes.py
  ├── order_routes.py
models/
  ├── user_models.py
  ├── order_models.py
```

### Module Boundaries

**✅ DO:** Keep features self-contained with clear interfaces
```python
# features/users/services.py
class UserService:
    """Self-contained user business logic."""
    async def create_user(self, data: UserCreate) -> User:
        # All user creation logic here
        pass
```

**✅ DO:** Use explicit imports with clear naming
```python
from example_service.features.users.schemas import (
    UserCreate,
    UserResponse,
    UserUpdate,
)
from example_service.features.orders.schemas import (
    OrderCreate,
    OrderResponse,
)
```

---

## Async Programming

### When to Use Async

**✅ DO:** Use `async def` for I/O-bound operations
```python
# Database queries
async def get_user(user_id: str, session: AsyncSession) -> User:
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()

# External API calls
async def fetch_user_data(user_id: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.get(f"https://api.example.com/users/{user_id}")
        return response.json()

# File I/O
async def read_file_async(path: str) -> str:
    async with aiofiles.open(path, 'r') as f:
        return await f.read()
```

**❌ DON'T:** Use `async def` for CPU-bound operations
```python
# Anti-pattern: async doesn't help with CPU-bound work
async def calculate_fibonacci(n: int) -> int:
    # This blocks the event loop!
    if n <= 1:
        return n
    return await calculate_fibonacci(n-1) + await calculate_fibonacci(n-2)

# ✅ Better: Use thread pool for CPU-bound work
import asyncio
from concurrent.futures import ProcessPoolExecutor

def cpu_intensive_task(data: list) -> list:
    # Heavy computation
    return [x ** 2 for x in data]

async def process_data(data: list) -> list:
    loop = asyncio.get_event_loop()
    with ProcessPoolExecutor() as executor:
        result = await loop.run_in_executor(executor, cpu_intensive_task, data)
    return result
```

### Sync SDKs in Async Code

**✅ DO:** Run synchronous SDKs in thread pools
```python
import asyncio
from functools import partial

# Synchronous SDK
from some_sync_library import SyncClient

async def call_sync_sdk(param: str) -> dict:
    """Wrap sync SDK call to avoid blocking event loop."""
    client = SyncClient()
    loop = asyncio.get_event_loop()

    # Run in thread pool
    result = await loop.run_in_executor(
        None,  # Uses default ThreadPoolExecutor
        partial(client.some_method, param)
    )
    return result
```

### Async Dependencies

**✅ DO:** Use async dependencies for I/O operations
```python
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_db)
) -> User:
    """Async dependency for user authentication."""
    user_id = await decode_token(token)  # Async token validation
    user = await get_user(user_id, session)  # Async DB query
    return user
```

---

## Pydantic Models & Validation

### Custom Base Model

**✅ DO:** Create a custom base model with common configuration
```python
# core/schemas/base.py
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class CustomBase(BaseModel):
    """Base model with common configuration."""

    model_config = ConfigDict(
        # Serialize datetimes as ISO strings
        json_encoders={
            datetime: lambda v: v.isoformat(),
        },
        # Allow arbitrary types
        arbitrary_types_allowed=False,
        # Validate on assignment
        validate_assignment=True,
        # Use enum values, not names
        use_enum_values=True,
    )

# Use in your schemas
class UserResponse(CustomBase):
    id: str
    email: str
    created_at: datetime
```

### Extensive Field Validation

**✅ DO:** Use Pydantic's built-in validators
```python
from pydantic import BaseModel, Field, EmailStr, HttpUrl
from typing import Annotated

class UserCreate(BaseModel):
    # Email validation
    email: EmailStr

    # String constraints
    username: Annotated[str, Field(
        min_length=3,
        max_length=50,
        pattern=r'^[a-zA-Z0-9_-]+$'
    )]

    # Password constraints
    password: Annotated[str, Field(
        min_length=8,
        max_length=100
    )]

    # Numeric constraints
    age: Annotated[int, Field(ge=18, le=120)]

    # URL validation
    website: HttpUrl | None = None
```

### Custom Validators

**✅ DO:** Use field validators for complex validation logic
```python
from pydantic import BaseModel, field_validator, model_validator

class UserCreate(BaseModel):
    email: str
    password: str
    password_confirm: str

    @field_validator('password')
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """Ensure password meets strength requirements."""
        if not any(c.isupper() for c in v):
            raise ValueError('Password must contain uppercase letter')
        if not any(c.islower() for c in v):
            raise ValueError('Password must contain lowercase letter')
        if not any(c.isdigit() for c in v):
            raise ValueError('Password must contain digit')
        return v

    @model_validator(mode='after')
    def validate_passwords_match(self) -> 'UserCreate':
        """Ensure password and confirmation match."""
        if self.password != self.password_confirm:
            raise ValueError('Passwords do not match')
        return self
```

### Settings Organization

**✅ DO:** Organize settings by domain when configuration grows large
```python
# core/settings.py - Main settings
class Settings(BaseSettings):
    service_name: str = "example-service"
    debug: bool = False

# features/users/config.py - Feature-specific settings
class UserSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="USER_")

    max_login_attempts: int = 5
    session_timeout: int = 3600
    password_reset_expiry: int = 86400

user_settings = UserSettings()
```

---

## Dependency Injection

### Dependency Chaining

**✅ DO:** Chain dependencies for composition and reuse
```python
from typing import Annotated
from fastapi import Depends

# Base dependency
async def get_db() -> AsyncSession:
    async with get_async_session() as session:
        yield session

# Depends on get_db
async def get_user_repository(
    session: Annotated[AsyncSession, Depends(get_db)]
) -> UserRepository:
    return UserRepository(session)

# Depends on get_user_repository
async def get_user_service(
    repository: Annotated[UserRepository, Depends(get_user_repository)]
) -> UserService:
    return UserService(repository)

# Route uses highest-level dependency
@router.get("/users/{user_id}")
async def get_user(
    user_id: str,
    service: Annotated[UserService, Depends(get_user_service)]
) -> UserResponse:
    return await service.get_user(user_id)
```

### Validation Dependencies

**✅ DO:** Use dependencies for complex validation requiring DB/API calls
```python
async def validate_user_exists(
    user_id: str,
    session: Annotated[AsyncSession, Depends(get_db)]
) -> User:
    """Dependency that validates user exists."""
    user = await get_user(user_id, session)
    if not user:
        raise NotFoundException(f"User {user_id} not found")
    return user

@router.put("/users/{user_id}")
async def update_user(
    user_id: str,
    data: UserUpdate,
    user: Annotated[User, Depends(validate_user_exists)]  # Validates + returns user
) -> UserResponse:
    # User is already validated and fetched
    return await update_user_data(user, data)
```

### Dependency Caching

**✅ REMEMBER:** FastAPI caches dependency results per request
```python
async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    # This will be called ONCE per request, even if used multiple times
    user = await decode_and_fetch_user(token)
    return user

@router.get("/profile")
async def get_profile(user: User = Depends(get_current_user)):
    # get_current_user called
    pass

@router.put("/profile")
async def update_profile(
    data: ProfileUpdate,
    user: User = Depends(get_current_user)  # Same user, not called again
):
    pass
```

---

## Database Patterns

### Connection Pooling

**✅ DO:** Configure connection pools appropriately
```python
# infra/database/session.py
engine = create_async_engine(
    settings.database_url,
    pool_size=20,           # Number of persistent connections
    max_overflow=10,        # Additional connections when pool is full
    pool_pre_ping=True,     # Verify connection before using
    pool_recycle=3600,      # Recycle connections after 1 hour
    echo=settings.debug,    # Log SQL in debug mode
)
```

### Naming Conventions

**✅ DO:** Configure consistent database naming conventions
```python
from sqlalchemy import MetaData

# Define naming convention
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}

class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
```

### Query Optimization

**✅ DO:** Use eager loading for related entities
```python
# Avoid N+1 queries
from sqlalchemy.orm import selectinload, joinedload

# One-to-many: use selectinload
stmt = (
    select(User)
    .options(selectinload(User.posts))
    .where(User.id == user_id)
)

# One-to-one or many-to-one: use joinedload
stmt = (
    select(Post)
    .options(joinedload(Post.author))
    .where(Post.id == post_id)
)
```

### Session Management

**✅ DO:** Use context managers for session lifecycle
```python
async def process_data():
    async with get_async_session() as session:
        async with session.begin():
            # Transactional work
            user = User(email="test@example.com")
            session.add(user)
            # Automatic commit on success, rollback on exception
```

---

## API Design

### REST Conventions

**✅ DO:** Follow REST conventions strictly
```python
# Resource-oriented endpoints
@router.get("/users")              # List users
@router.post("/users")             # Create user
@router.get("/users/{user_id}")    # Get user
@router.put("/users/{user_id}")    # Replace user
@router.patch("/users/{user_id}")  # Partial update
@router.delete("/users/{user_id}") # Delete user

# Nested resources
@router.get("/users/{user_id}/posts")         # List user's posts
@router.post("/users/{user_id}/posts")        # Create post for user
@router.get("/posts/{post_id}")               # Get post (not nested)
```

### Response Models

**✅ DO:** Use explicit response models
```python
from typing import Annotated
from fastapi import Body

@router.post(
    "/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {"description": "User already exists"},
        422: {"description": "Validation error"},
    }
)
async def create_user(
    user: Annotated[UserCreate, Body(description="User data")]
) -> UserResponse:
    """Create a new user account."""
    return await user_service.create(user)
```

### Pagination

**✅ DO:** Implement consistent pagination
```python
from example_service.core.schemas.base import PaginatedResponse

@router.get("/users", response_model=PaginatedResponse[UserResponse])
async def list_users(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    service: UserService = Depends(get_user_service)
) -> PaginatedResponse[UserResponse]:
    users, total = await service.list_users(
        skip=(page - 1) * page_size,
        limit=page_size
    )
    return PaginatedResponse.create(
        items=users,
        total=total,
        page=page,
        page_size=page_size
    )
```

---

## Error Handling

### RFC 7807 Problem Details

**✅ DO:** Use RFC 7807 for error responses
```python
from example_service.core.schemas.problem_details import ProblemDetails
from example_service.core.exceptions import AppException

# Raise custom exceptions
raise NotFoundException(
    detail=f"User {user_id} not found",
    type="user-not-found"
)

# Exception handler converts to RFC 7807
@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    return JSONResponse(
        status_code=exc.status_code,
        content=ProblemDetails(
            type=exc.type,
            title=status.HTTP_STATUS_CODES[exc.status_code],
            status=exc.status_code,
            detail=exc.detail,
            instance=str(request.url)
        ).model_dump()
    )
```

### Validation Errors

**⚠️ BEWARE:** `ValueError` can be caught by Pydantic as `ValidationError`
```python
# This ValueError will become a ValidationError
class UserCreate(BaseModel):
    age: int

    @field_validator('age')
    @classmethod
    def validate_age(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Age must be positive")  # Becomes ValidationError
        return v

# Use custom exceptions for non-validation errors
class BusinessLogicError(Exception):
    pass

@field_validator('age')
@classmethod
def validate_age(cls, v: int) -> int:
    if v < 0:
        raise BusinessLogicError("Invalid age")  # Won't be caught by Pydantic
    return v
```

---

## Testing

### Async Test Client

**✅ DO:** Use async test client from the start
```python
# tests/conftest.py
import pytest
from httpx import AsyncClient, ASGITransport
from example_service.app.main import create_app

@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as ac:
        yield ac

# tests/integration/test_api.py
@pytest.mark.asyncio
async def test_create_user(client: AsyncClient):
    response = await client.post(
        "/api/v1/users",
        json={"email": "test@example.com", "username": "test"}
    )
    assert response.status_code == 201
```

### Test Isolation

**✅ DO:** Isolate tests with fixtures and cleanup
```python
@pytest.fixture
async def db_session():
    """Provide a clean database session for each test."""
    async with get_async_session() as session:
        yield session
        # Rollback after test
        await session.rollback()

@pytest.fixture
async def test_user(db_session):
    """Create a test user."""
    user = User(email="test@example.com")
    db_session.add(user)
    await db_session.commit()
    yield user
    # Cleanup happens via session rollback
```

---

## Performance

### Database Query Optimization

**✅ DO:** Batch queries and use bulk operations
```python
# ✅ Good: Batch insert
async def create_users(users: list[UserCreate]) -> list[User]:
    db_users = [User(**user.model_dump()) for user in users]
    session.add_all(db_users)
    await session.commit()
    return db_users

# ❌ Bad: Individual inserts
async def create_users(users: list[UserCreate]) -> list[User]:
    db_users = []
    for user in users:
        db_user = User(**user.model_dump())
        session.add(db_user)
        await session.commit()  # Don't commit in loop!
        db_users.append(db_user)
    return db_users
```

### Caching

**✅ DO:** Cache frequently accessed, rarely changing data
```python
from functools import lru_cache
from example_service.infra.cache.redis import CacheService

# In-memory cache for static data
@lru_cache(maxsize=100)
def get_country_codes() -> dict[str, str]:
    """Cache country codes in memory."""
    return load_country_codes()

# Redis cache for dynamic data
async def get_user_permissions(user_id: str) -> list[str]:
    """Cache user permissions in Redis."""
    cache_key = f"permissions:{user_id}"

    # Try cache first
    cached = await cache_service.get(cache_key)
    if cached:
        return cached

    # Fetch and cache
    permissions = await fetch_permissions(user_id)
    await cache_service.set(cache_key, permissions, ttl=3600)
    return permissions
```

---

## Security

### Input Validation

**✅ DO:** Validate all inputs with Pydantic
```python
class UserCreate(BaseModel):
    email: EmailStr  # Validates email format
    username: Annotated[str, Field(pattern=r'^[a-zA-Z0-9_-]+$')]
    age: Annotated[int, Field(ge=0, le=150)]
```

### SQL Injection Prevention

**✅ DO:** Always use parameterized queries
```python
# ✅ Safe: SQLAlchemy uses parameters
stmt = select(User).where(User.email == email)

# ❌ Dangerous: String interpolation
stmt = f"SELECT * FROM users WHERE email = '{email}'"  # NEVER DO THIS!
```

### Secrets Management

**✅ DO:** Never commit secrets, use environment variables
```python
# ✅ Good: Read from environment
class Settings(BaseSettings):
    database_password: str
    jwt_secret: str

# ❌ Bad: Hardcoded secrets
database_password = "my-secret-password"  # NEVER DO THIS!
```

---

## Logging & Observability

### Structured Logging

**✅ DO:** Use structured logging with context
```python
import logging

logger = logging.getLogger(__name__)

# Include context in logs
logger.info(
    "User created",
    extra={
        "user_id": user.id,
        "email": user.email,
        "request_id": request.state.request_id,
        "tenant_id": request.state.tenant_id
    }
)
```

### Correlation IDs

**✅ DO:** Add correlation IDs to all requests
```python
# Already implemented in app/middleware.py
class RequestIDMiddleware:
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
```

---

## Code Quality

### Type Hints

**✅ DO:** Use type hints everywhere (Python 3.13+)
```python
from collections.abc import Sequence

# Modern type annotations
def get_users(skip: int = 0, limit: int = 100) -> Sequence[User]:
    """Get users with modern type hints."""
    pass

# Use | for unions (not Optional)
def get_user(user_id: str) -> User | None:
    """Returns user or None."""
    pass

# Use built-in generics
def process_items(items: list[dict[str, str]]) -> list[str]:
    """Process items with built-in generics."""
    pass
```

### Linting

**✅ DO:** Use Ruff for fast linting and formatting
```bash
# Format code
uv run ruff format .

# Lint code
uv run ruff check . --fix

# Type check
uv run mypy example_service
```

### Pre-commit Hooks

**✅ DO:** Use pre-commit hooks for quality checks
```bash
# Install hooks
uv run pre-commit install

# Run on all files
uv run pre-commit run --all-files
```

---

## Migration Patterns

### Alembic Best Practices

**✅ DO:** Use descriptive migration messages
```bash
# Good migration names
uv run alembic revision --autogenerate -m "add user email verification"
uv run alembic revision --autogenerate -m "add index on users.email"

# Bad migration names
uv run alembic revision --autogenerate -m "update"
uv run alembic revision --autogenerate -m "changes"
```

**✅ DO:** Review auto-generated migrations
```python
# Always review and edit autogenerated migrations
def upgrade() -> None:
    # Add custom data migrations if needed
    op.create_table(...)

    # Migrate existing data if necessary
    connection = op.get_bind()
    connection.execute(...)

def downgrade() -> None:
    # Always provide downgrade path
    op.drop_table(...)
```

---

## Updating This Document

This document should be updated when:

1. **New patterns are established** - Document successful patterns that solve recurring problems
2. **Anti-patterns are discovered** - Add examples of what NOT to do when issues arise
3. **Dependencies change** - Update if moving to new libraries or frameworks
4. **Architecture evolves** - Reflect structural changes in recommendations
5. **Performance insights** - Add learnings from production profiling
6. **Security issues** - Document security best practices as they're discovered

**How to update:**
1. Add new sections or subsections as needed
2. Use ✅ DO and ❌ DON'T patterns for clarity
3. Include code examples for both good and bad patterns
4. Update the "Last Updated" date at the top
5. Commit changes with a descriptive message

---

## References

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Pydantic Documentation](https://docs.pydantic.dev/)
- [SQLAlchemy 2.0 Documentation](https://docs.sqlalchemy.org/en/20/)
- [FastAPI Best Practices (zhanymkanov)](https://github.com/zhanymkanov/fastapi-best-practices)
- [Python Type Hints](https://docs.python.org/3/library/typing.html)
