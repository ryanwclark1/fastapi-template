# Database Guide

**Philosophy:** Start simple with direct SQLAlchemy. Add abstractions only when specific pain points emerge.

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Directory Structure](#directory-structure)
3. [Mixin System](#mixin-system)
4. [Direct SQLAlchemy Patterns](#direct-sqlalchemy-patterns)
5. [Error Handling](#error-handling)
6. [Common Patterns](#common-patterns)
7. [When to Add Abstraction](#when-to-add-abstraction)
8. [Best Practices](#best-practices)

---

## Architecture Overview

```
┌─────────────────────────────────────────┐
│  FastAPI Endpoints (router.py)          │
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

---

## Directory Structure

```
example_service/
├── core/
│   ├── database/              # Base classes & mixins
│   │   ├── base.py            # Composable mixins (PK, Timestamps, Audit, SoftDelete)
│   │   ├── exceptions.py      # NotFoundError, DatabaseError
│   │   └── __init__.py        # Clean exports
│   ├── models/                # Core domain models
│   │   ├── user.py            # Example model
│   │   └── post.py            # Example model
│   └── dependencies/
│       └── database.py        # get_db_session (FastAPI dependency)
├── infra/
│   └── database/
│       └── session.py         # AsyncSession, engine, connection pool
└── features/
    └── reminders/             # Example feature module
        ├── models.py          # Feature-specific models
        ├── router.py          # Endpoints with direct SQLAlchemy
        └── schemas.py         # Pydantic request/response schemas
```

---

## Mixin System

Mixins provide model capabilities without abstraction overhead.

### Available Mixins

```python
from example_service.core.database import (
    Base,                  # SQLAlchemy declarative base
    IntegerPKMixin,        # Auto-increment integer primary key
    UUIDPKMixin,           # UUID v4 primary key
    TimestampMixin,        # created_at, updated_at
    AuditColumnsMixin,     # created_by, updated_by
    SoftDeleteMixin,       # deleted_at, is_deleted property
)
```

### Convenience Base Classes

For common combinations:

```python
from example_service.core.database import (
    TimestampedBase,       # Integer PK + Timestamps
    UUIDTimestampedBase,   # UUID PK + Timestamps
    AuditedBase,           # Integer PK + Timestamps + Audit
)
```

### Examples

**Standard Model (Integer PK + Timestamps):**
```python
class User(TimestampedBase):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(255), unique=True)
    # Inherits: id (int), created_at, updated_at
```

**UUID Primary Key:**
```python
class Event(UUIDTimestampedBase):
    __tablename__ = "events"
    event_type: Mapped[str]
    # Inherits: id (UUID), created_at, updated_at
```

**With Audit Trail:**
```python
class Transaction(AuditedBase):
    __tablename__ = "transactions"
    amount: Mapped[Decimal]
    # Inherits: id, created_at, updated_at, created_by, updated_by
```

**With Soft Delete:**
```python
class Post(Base, IntegerPKMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "posts"
    title: Mapped[str]
    # Inherits: id, created_at, updated_at, deleted_at, is_deleted
```

---

## Direct SQLAlchemy Patterns

### Basic CRUD Endpoint

```python
from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from example_service.core.database import NotFoundError
from example_service.core.dependencies.database import get_db_session
from your_feature.models import Item
from your_feature.schemas import ItemCreate, ItemResponse

router = APIRouter(prefix="/items", tags=["items"])


@router.get("/", response_model=list[ItemResponse])
async def list_items(session: AsyncSession = Depends(get_db_session)):
    """List all items."""
    result = await session.execute(select(Item))
    return result.scalars().all()


@router.get("/{item_id}", response_model=ItemResponse)
async def get_item(item_id: int, session: AsyncSession = Depends(get_db_session)):
    """Get a single item by ID."""
    result = await session.execute(select(Item).where(Item.id == item_id))
    item = result.scalar_one_or_none()
    if item is None:
        raise NotFoundError("Item", {"id": item_id})
    return item


@router.post("/", response_model=ItemResponse, status_code=status.HTTP_201_CREATED)
async def create_item(data: ItemCreate, session: AsyncSession = Depends(get_db_session)):
    """Create a new item."""
    item = Item(**data.model_dump())
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


@router.patch("/{item_id}", response_model=ItemResponse)
async def update_item(
    item_id: int,
    data: ItemCreate,
    session: AsyncSession = Depends(get_db_session),
):
    """Update an existing item."""
    result = await session.execute(select(Item).where(Item.id == item_id))
    item = result.scalar_one_or_none()
    if item is None:
        raise NotFoundError("Item", {"id": item_id})

    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(item, key, value)

    await session.commit()
    await session.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(item_id: int, session: AsyncSession = Depends(get_db_session)):
    """Delete an item."""
    result = await session.execute(select(Item).where(Item.id == item_id))
    item = result.scalar_one_or_none()
    if item is None:
        raise NotFoundError("Item", {"id": item_id})

    await session.delete(item)
    await session.commit()
```

---

## Error Handling

### NotFoundError

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

The exception handler (in `app/exception_handlers.py`) automatically converts this to an HTTP 404 response with RFC 7807 Problem Details format.

---

## Common Patterns

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
        select(Item).order_by(Item.created_at.desc()).limit(limit).offset(offset)
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

### Eager Loading (Prevent N+1)

```python
from sqlalchemy.orm import selectinload

@router.get("/users/{user_id}/with-posts")
async def get_user_with_posts(user_id: int, session: AsyncSession = Depends(get_db_session)):
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

### Soft Delete

```python
from datetime import UTC, datetime

@router.delete("/posts/{post_id}")
async def soft_delete_post(post_id: int, session: AsyncSession = Depends(get_db_session)):
    """Soft delete a post."""
    result = await session.execute(select(Post).where(Post.id == post_id))
    post = result.scalar_one_or_none()
    if post is None:
        raise NotFoundError("Post", {"id": post_id})

    post.deleted_at = datetime.now(UTC)  # Soft delete
    await session.commit()

@router.get("/posts")
async def list_posts(session: AsyncSession = Depends(get_db_session)):
    """List non-deleted posts."""
    result = await session.execute(
        select(Post).where(Post.deleted_at.is_(None))  # Exclude soft-deleted
    )
    return result.scalars().all()
```

---

## When to Add Abstraction

**Start simple. Add layers when you experience pain.**

### 1. Helper Functions (First Step)

When you repeat the same query 3+ times:

```python
# In router.py or separate helpers.py
async def _find_active_users(session: AsyncSession) -> Sequence[User]:
    result = await session.execute(select(User).where(User.is_active == True))
    return result.scalars().all()
```

### 2. Repository Class (If 5+ Helpers)

When helpers become unwieldy:

```python
class UserRepository:
    async def find_by_email(self, session: AsyncSession, email: str) -> User | None:
        result = await session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def find_active(self, session: AsyncSession) -> Sequence[User]:
        result = await session.execute(select(User).where(User.is_active == True))
        return result.scalars().all()
```

### 3. Service Layer (For Business Logic)

When you need validation, orchestration, or external integrations:

```python
class UserService:
    def __init__(self):
        self._repo = UserRepository()

    async def create_with_welcome_email(
        self, session: AsyncSession, data: UserCreate, email_service: EmailService
    ) -> User:
        # Validation
        if await self._repo.find_by_email(session, data.email):
            raise ValueError("Email already registered")

        # Create
        user = User(**data.model_dump())
        session.add(user)
        await session.commit()

        # External integration
        await email_service.send_welcome(user.email)
        return user
```

### Progressive Enhancement Path

```
Direct SQLAlchemy          ← Start here (simplest)
    ↓ (when queries repeat)
Helper Functions           ← Add when needed
    ↓ (when helpers grow)
Repository Class           ← Add when 5+ helpers
    ↓ (when business logic appears)
Service Layer              ← Add when orchestration needed
```

---

## Best Practices

1. **Keep mixins** - They're always useful (PK, Timestamps, Audit, SoftDelete)
2. **Start with direct queries** - Add abstraction when pain emerges
3. **Use NotFoundError** - Better than HTTPException for 404s
4. **Filter soft-deleted** - Always exclude `deleted_at IS NOT NULL` in queries
5. **Eager load relationships** - Use `selectinload()` to prevent N+1
6. **Transactions are automatic** - `commit()` makes changes atomic

**Golden Rule:** If you can see the SQL in your endpoint, that's probably good enough.

---

## Related Documentation

- [Quick Reference](./quick-reference.md) - Copy-paste patterns for common operations
