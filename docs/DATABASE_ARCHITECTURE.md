# Database Architecture Guide

## Philosophy

**Start simple. Add complexity only when needed.**

This project uses **direct SQLAlchemy** with **composable mixins** for model capabilities. No repository abstraction by default - just solid foundation and helpful exceptions.

## Architecture Overview

```
┌─────────────────────────────────────────┐
│  FastAPI Endpoints (router.py)         │
│  - HTTP request/response handling       │
│  - Direct SQLAlchemy queries            │
│  - Session dependency injection         │
└─────────────┬───────────────────────────┘
              │ Depends(get_db_session)
              ▼
         ┌────────────────┐
         │  AsyncSession  │
         │  (injected)    │
         └────────┬───────┘
                  │ Direct queries
                  ▼
         ┌────────────────┐
         │  Models        │
         │  (with mixins) │
         └────────┬───────┘
                  │
                  ▼
         ┌────────────────┐
         │  Database      │
         │  (PostgreSQL)  │
         └────────────────┘
```

**Key Principle:** Database interaction is **visible** in endpoints. If you need to know what query runs, you can see it directly.

## Directory Structure

```
example_service/
├── core/
│   ├── database/              # ← Base classes & mixins
│   │   ├── base.py            # Composable mixins (PK, Timestamps, Audit, SoftDelete)
│   │   ├── exceptions.py      # NotFoundError, DatabaseError
│   │   └── __init__.py        # Clean exports
│   ├── models/                # Core domain models
│   │   ├── user.py
│   │   └── post.py
│   └── dependencies/
│       ├── database.py        # get_db_session
│       └── services.py        # Optional services if needed
├── infra/
│   └── database/
│       ├── session.py         # AsyncSession, engine, connection pool
│       └── base.py            # DEPRECATED (backward compatibility only)
└── features/
    └── reminders/             # Example feature module
        ├── models.py          # Feature-specific models (using mixins)
        ├── router.py          # Endpoints with direct SQLAlchemy
        └── schemas.py         # Pydantic request/response schemas
```

## Core Components

### 1. Composable Mixins

Mixins provide model capabilities without abstraction overhead.

#### Primary Key Strategies

**Integer Auto-increment (Default):**
```python
from example_service.core.database import Base, IntegerPKMixin, TimestampMixin

class User(Base, IntegerPKMixin, TimestampMixin):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(255), unique=True)

# Gives you:
# - id: int (auto-increment primary key)
# - created_at: datetime
# - updated_at: datetime
```

**UUID Primary Key:**
```python
from example_service.core.database import Base, UUIDPKMixin, TimestampMixin

class Document(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "documents"
    title: Mapped[str]

# Gives you:
# - id: UUID (automatically generated v4)
# - created_at: datetime
# - updated_at: datetime
```

#### Convenience Bases

For common combinations:

```python
from example_service.core.database import (
    TimestampedBase,      # Integer PK + Timestamps
    UUIDTimestampedBase,  # UUID PK + Timestamps
    AuditedBase,          # Integer PK + Timestamps + Audit
)

# Most common - backward compatible
class User(TimestampedBase):
    __tablename__ = "users"
    email: Mapped[str]

# Distributed systems
class Event(UUIDTimestampedBase):
    __tablename__ = "events"
    event_type: Mapped[str]

# Need audit trail
class Transaction(AuditedBase):
    __tablename__ = "transactions"
    amount: Mapped[Decimal]
    # Has: id, created_at, updated_at, created_by, updated_by
```

#### Timestamp Tracking

Automatic `created_at` and `updated_at`:

```python
from example_service.core.database import TimestampMixin

class Article(Base, IntegerPKMixin, TimestampMixin):
    __tablename__ = "articles"
    title: Mapped[str]
    content: Mapped[str]

# Automatically adds:
# - created_at: datetime (set on insert, both Python and DB level)
# - updated_at: datetime (set on insert, updated on every update)
```

**No manual timestamp management needed!**

#### Audit Columns

Track who created/modified:

```python
from example_service.core.database import AuditColumnsMixin

class Order(Base, IntegerPKMixin, TimestampMixin, AuditColumnsMixin):
    __tablename__ = "orders"
    total: Mapped[Decimal]

# Adds:
# - created_by: str | None
# - updated_by: str | None

# Set in endpoint:
@router.post("/orders")
async def create_order(
    data: OrderCreate,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    order = Order(
        total=data.total,
        created_by=current_user.email,  # Track who created it
    )
    session.add(order)
    await session.commit()
    return order
```

#### Soft Delete

Logical deletion instead of physical:

```python
from example_service.core.database import SoftDeleteMixin

class Post(Base, IntegerPKMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "posts"
    title: Mapped[str]

# Adds:
# - deleted_at: datetime | None
# - is_deleted: bool (property)

# Soft delete:
@router.delete("/posts/{post_id}")
async def delete_post(post_id: int, session: AsyncSession = Depends(get_db_session)):
    result = await session.execute(select(Post).where(Post.id == post_id))
    post = result.scalar_one_or_none()

    if post is None:
        raise NotFoundError("Post", {"id": post_id})

    post.deleted_at = datetime.now(UTC)  # Soft delete
    await session.commit()

# Filter deleted:
@router.get("/posts")
async def list_posts(session: AsyncSession = Depends(get_db_session)):
    result = await session.execute(
        select(Post).where(Post.deleted_at.is_(None))  # Exclude deleted
    )
    return result.scalars().all()
```

### 2. Direct SQLAlchemy in Endpoints

**No repository abstraction by default.** See queries directly in endpoints:

```python
from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from example_service.core.database import NotFoundError
from example_service.core.dependencies.database import get_db_session
from your_feature.models import YourModel

router = APIRouter(prefix="/items", tags=["items"])


@router.get("/{item_id}")
async def get_item(
    item_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    """Get a single item - query is visible!"""
    result = await session.execute(
        select(YourModel).where(YourModel.id == item_id)
    )
    item = result.scalar_one_or_none()

    if item is None:
        raise NotFoundError("YourModel", {"id": item_id})

    return item


@router.post("/")
async def create_item(
    data: ItemCreate,
    session: AsyncSession = Depends(get_db_session),
):
    """Create item - direct SQLAlchemy!"""
    item = YourModel(**data.model_dump())

    session.add(item)
    await session.commit()
    await session.refresh(item)

    return item
```

**Benefits:**
- ✅ Clear what's happening - no hidden layers
- ✅ Easy to debug - query is right there
- ✅ Less navigation - everything in one file
- ✅ Flexible - easy to customize per endpoint

### 3. Exception Handling

Use `NotFoundError` for cleaner 404s:

```python
from example_service.core.database import NotFoundError

@router.get("/users/{user_id}")
async def get_user(user_id: int, session: AsyncSession = Depends(get_db_session)):
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise NotFoundError("User", {"id": user_id})  # Clean exception

    return user
```

**Add exception handler in main.py:**

```python
from fastapi import Request
from fastapi.responses import JSONResponse
from example_service.core.database import NotFoundError

@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError):
    return JSONResponse(
        status_code=404,
        content={
            "detail": str(exc),
            "model": exc.model_name,
            "identifier": exc.identifier,
        },
    )
```

## Common Patterns

### Basic CRUD

```python
@router.get("/")
async def list_items(session: AsyncSession = Depends(get_db_session)):
    """List all items."""
    result = await session.execute(select(Item))
    return result.scalars().all()


@router.get("/{item_id}")
async def get_item(item_id: int, session: AsyncSession = Depends(get_db_session)):
    """Get single item."""
    result = await session.execute(select(Item).where(Item.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise NotFoundError("Item", {"id": item_id})
    return item


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_item(data: ItemCreate, session: AsyncSession = Depends(get_db_session)):
    """Create item."""
    item = Item(**data.model_dump())
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


@router.patch("/{item_id}")
async def update_item(
    item_id: int,
    data: ItemUpdate,
    session: AsyncSession = Depends(get_db_session),
):
    """Update item."""
    result = await session.execute(select(Item).where(Item.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise NotFoundError("Item", {"id": item_id})

    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(item, key, value)

    await session.commit()
    await session.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(item_id: int, session: AsyncSession = Depends(get_db_session)):
    """Delete item."""
    result = await session.execute(select(Item).where(Item.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise NotFoundError("Item", {"id": item_id})

    await session.delete(item)
    await session.commit()
```

### Filtering

```python
@router.get("/search")
async def search_items(
    query: str | None = None,
    is_active: bool | None = None,
    session: AsyncSession = Depends(get_db_session),
):
    """Search with filters."""
    stmt = select(Item)

    if query:
        stmt = stmt.where(Item.name.ilike(f"%{query}%"))

    if is_active is not None:
        stmt = stmt.where(Item.is_active == is_active)

    stmt = stmt.order_by(Item.created_at.desc())

    result = await session.execute(stmt)
    return result.scalars().all()
```

### Pagination

```python
from sqlalchemy import func

@router.get("/")
async def list_items(
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_db_session),
):
    """Paginated list."""
    # Count total
    count_result = await session.execute(select(func.count()).select_from(Item))
    total = count_result.scalar_one()

    # Get page
    result = await session.execute(
        select(Item)
        .order_by(Item.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    items = result.scalars().all()

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_next": offset + limit < total,
    }
```

### Relationships (Eager Loading)

```python
from sqlalchemy.orm import selectinload

@router.get("/users/{user_id}/with-posts")
async def get_user_with_posts(
    user_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    """Prevent N+1 queries with eager loading."""
    result = await session.execute(
        select(User)
        .where(User.id == user_id)
        .options(selectinload(User.posts))  # Eager load
    )
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("User", {"id": user_id})
    return user
```

## When to Add Abstraction

**Start simple. Add layers when you experience pain.**

### 1. Helper Functions (First Step)

When you repeat the same query 3+ times:

```python
# In router.py or separate helpers.py
async def _find_active_users(session: AsyncSession) -> Sequence[User]:
    """Helper: Find active users."""
    result = await session.execute(
        select(User).where(User.is_active == True)
    )
    return result.scalars().all()

# Use in endpoints:
@router.get("/users/active")
async def get_active_users(session: AsyncSession = Depends(get_db_session)):
    users = await _find_active_users(session)
    return users
```

### 2. Repository Class (If 5+ Helper Functions)

When helpers become unwieldy:

```python
# features/users/repository.py
class UserRepository:
    """User-specific queries (session passed to methods)."""

    async def find_by_email(
        self,
        session: AsyncSession,
        email: str,
    ) -> User | None:
        result = await session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def find_active_users(self, session: AsyncSession) -> Sequence[User]:
        result = await session.execute(select(User).where(User.is_active == True))
        return result.scalars().all()

# Use in endpoints:
@router.get("/users/active")
async def get_active_users(session: AsyncSession = Depends(get_db_session)):
    repo = UserRepository()
    users = await repo.find_active_users(session)
    return users
```

### 3. Service Layer (If Business Logic Emerges)

When you need validation, orchestration, or external integrations:

```python
# features/users/service.py
class UserService:
    """Business logic."""

    def __init__(self):
        self._repo = UserRepository()

    async def create_user_with_welcome_email(
        self,
        session: AsyncSession,
        data: UserCreate,
        email_service: EmailService,
    ) -> User:
        # Validation
        if await self._repo.find_by_email(session, data.email):
            raise ValueError("Email already registered")

        # Create user
        user = User(**data.model_dump())
        session.add(user)
        await session.commit()

        # External integration
        await email_service.send_welcome(user.email)

        return user
```

## Migration from Repository Pattern

If you have existing code using repositories, you can migrate incrementally:

**Before (Repository):**
```python
@router.get("/{id}")
async def get_item(
    id: int,
    repo: ItemRepository = Depends(get_item_repository),
):
    item = await repo.get_by_id(id)  # What query is this?
    return item
```

**After (Direct SQLAlchemy):**
```python
@router.get("/{id}")
async def get_item(
    id: int,
    session: AsyncSession = Depends(get_db_session),
):
    result = await session.execute(
        select(Item).where(Item.id == id)  # Query is visible!
    )
    item = result.scalar_one_or_none()
    if not item:
        raise NotFoundError("Item", {"id": id})
    return item
```

## Best Practices

1. **Keep mixins** - They're always useful (PK, Timestamps, Audit, SoftDelete)
2. **Start with direct queries** - Add abstraction when pain emerges
3. **Use NotFoundError** - Better than HTTPException for 404s
4. **Filter soft-deleted** - Always exclude `deleted_at IS NOT NULL` in queries
5. **Eager load relationships** - Use `selectinload()` to prevent N+1
6. **Transactions are automatic** - `commit()` makes changes atomic

## Progressive Enhancement

```
Direct SQLAlchemy          ← Start here (simplest)
    ↓ (when queries repeat)
Helper Functions           ← Add when needed
    ↓ (when helpers grow)
Repository Class           ← Add when 5+ helpers
    ↓ (when business logic appears)
Service Layer              ← Add when orchestration needed
```

**Golden Rule:** If you can see the SQL in your endpoint, that's probably good enough.

## Additional Resources

- [Direct SQLAlchemy Guide](./DATABASE_DIRECT_SQLALCHEMY.md) - Comprehensive examples
- [Quick Reference](./DATABASE_QUICK_REFERENCE.md) - Copy-paste patterns
- [Repository Pattern Exploration](./ARCHIVE_REPOSITORY_PATTERN_EXPLORATION.md) - Why we simplified
