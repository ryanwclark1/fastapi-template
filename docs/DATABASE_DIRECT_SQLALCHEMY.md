# Direct SQLAlchemy with Composable Mixins

**Philosophy:** Start simple with direct SQLAlchemy. Add abstractions only when specific pain points emerge.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Mixin System](#mixin-system)
3. [Common Patterns](#common-patterns)
4. [Error Handling](#error-handling)
5. [When to Add Abstraction](#when-to-add-abstraction)

---

## Quick Start

### Basic CRUD Endpoint

```python
from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from example_service.core.database import NotFoundError
from example_service.core.dependencies.database import get_db_session
from your_feature.models import YourModel
from your_feature.schemas import YourModelCreate, YourModelResponse

router = APIRouter(prefix="/your-resource", tags=["your-resource"])


@router.get("/", response_model=list[YourModelResponse])
async def list_items(
    session: AsyncSession = Depends(get_db_session),
) -> list[YourModelResponse]:
    """List all items."""
    result = await session.execute(select(YourModel))
    items = result.scalars().all()
    return [YourModelResponse.model_validate(item) for item in items]


@router.get("/{item_id}", response_model=YourModelResponse)
async def get_item(
    item_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> YourModelResponse:
    """Get a single item by ID."""
    result = await session.execute(
        select(YourModel).where(YourModel.id == item_id)
    )
    item = result.scalar_one_or_none()

    if item is None:
        raise NotFoundError("YourModel", {"id": item_id})

    return YourModelResponse.model_validate(item)


@router.post("/", response_model=YourModelResponse, status_code=status.HTTP_201_CREATED)
async def create_item(
    data: YourModelCreate,
    session: AsyncSession = Depends(get_db_session),
) -> YourModelResponse:
    """Create a new item."""
    item = YourModel(**data.model_dump())

    session.add(item)
    await session.commit()
    await session.refresh(item)

    return YourModelResponse.model_validate(item)


@router.patch("/{item_id}", response_model=YourModelResponse)
async def update_item(
    item_id: int,
    data: YourModelCreate,
    session: AsyncSession = Depends(get_db_session),
) -> YourModelResponse:
    """Update an existing item."""
    result = await session.execute(
        select(YourModel).where(YourModel.id == item_id)
    )
    item = result.scalar_one_or_none()

    if item is None:
        raise NotFoundError("YourModel", {"id": item_id})

    # Update fields
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(item, key, value)

    await session.commit()
    await session.refresh(item)

    return YourModelResponse.model_validate(item)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """Delete an item permanently."""
    result = await session.execute(
        select(YourModel).where(YourModel.id == item_id)
    )
    item = result.scalar_one_or_none()

    if item is None:
        raise NotFoundError("YourModel", {"id": item_id})

    await session.delete(item)
    await session.commit()
```

---

## Mixin System

The mixin system provides composable capabilities for your models **without abstraction overhead**.

### Available Mixins

```python
from example_service.core.database import (
    Base,
    IntegerPKMixin,      # Auto-increment integer primary key
    UUIDPKMixin,         # UUID v4 primary key
    TimestampMixin,      # created_at, updated_at
    AuditColumnsMixin,   # created_by, updated_by
    SoftDeleteMixin,     # deleted_at, is_deleted property
)
```

### Primary Key Strategies

**Integer Auto-increment (Default):**
```python
from sqlalchemy.orm import Mapped, mapped_column
from example_service.core.database import Base, IntegerPKMixin, TimestampMixin

class User(Base, IntegerPKMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True)
    full_name: Mapped[str] = mapped_column(String(255))

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
    content: Mapped[str]

# Gives you:
# - id: UUID (automatically generated)
# - created_at: datetime
# - updated_at: datetime
```

### Convenience Bases

For common combinations:

```python
from example_service.core.database import TimestampedBase, UUIDTimestampedBase, AuditedBase

# Integer PK + Timestamps (most common)
class User(TimestampedBase):
    __tablename__ = "users"
    email: Mapped[str]
    # Has: id (int), created_at, updated_at

# UUID PK + Timestamps
class Document(UUIDTimestampedBase):
    __tablename__ = "documents"
    title: Mapped[str]
    # Has: id (UUID), created_at, updated_at

# Integer PK + Timestamps + Audit Columns
class Order(AuditedBase):
    __tablename__ = "orders"
    total: Mapped[Decimal]
    # Has: id (int), created_at, updated_at, created_by, updated_by
```

### Audit Tracking

Track who created/modified records:

```python
from example_service.core.database import Base, IntegerPKMixin, TimestampMixin, AuditColumnsMixin

class Article(Base, IntegerPKMixin, TimestampMixin, AuditColumnsMixin):
    __tablename__ = "articles"

    title: Mapped[str]
    content: Mapped[str]

# Gives you:
# - created_by: str | None
# - updated_by: str | None

# In your endpoint:
@router.post("/articles")
async def create_article(
    data: ArticleCreate,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    article = Article(
        title=data.title,
        content=data.content,
        created_by=current_user.email,  # Set audit field
    )
    session.add(article)
    await session.commit()
    return article
```

### Soft Delete

Logical deletion instead of physical:

```python
from datetime import datetime, UTC
from example_service.core.database import Base, IntegerPKMixin, TimestampMixin, SoftDeleteMixin

class Post(Base, IntegerPKMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "posts"

    title: Mapped[str]
    content: Mapped[str]

# Gives you:
# - deleted_at: datetime | None
# - is_deleted: bool (property)

# Soft delete endpoint:
@router.delete("/posts/{post_id}")
async def soft_delete_post(
    post_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    result = await session.execute(
        select(Post).where(Post.id == post_id)
    )
    post = result.scalar_one_or_none()

    if post is None:
        raise NotFoundError("Post", {"id": post_id})

    # Soft delete - just set timestamp
    post.deleted_at = datetime.now(UTC)

    await session.commit()
    return {"message": "Post soft deleted"}

# List only non-deleted:
@router.get("/posts")
async def list_posts(session: AsyncSession = Depends(get_db_session)):
    result = await session.execute(
        select(Post).where(Post.deleted_at.is_(None))  # Filter out deleted
    )
    return result.scalars().all()

# Restore soft-deleted:
@router.post("/posts/{post_id}/restore")
async def restore_post(
    post_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    result = await session.execute(
        select(Post).where(Post.id == post_id)
    )
    post = result.scalar_one_or_none()

    if post is None:
        raise NotFoundError("Post", {"id": post_id})

    post.deleted_at = None  # Restore
    await session.commit()
    return post
```

---

## Common Patterns

### Filtering and Searching

```python
@router.get("/users/search")
async def search_users(
    query: str | None = None,
    is_active: bool | None = None,
    session: AsyncSession = Depends(get_db_session),
):
    """Search users with optional filters."""
    stmt = select(User)

    # Add filters conditionally
    if query:
        stmt = stmt.where(User.full_name.ilike(f"%{query}%"))

    if is_active is not None:
        stmt = stmt.where(User.is_active == is_active)

    stmt = stmt.order_by(User.created_at.desc())

    result = await session.execute(stmt)
    users = result.scalars().all()
    return users
```

### Pagination

```python
@router.get("/posts")
async def list_posts(
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_db_session),
):
    """List posts with pagination."""
    # Get total count
    count_result = await session.execute(
        select(func.count()).select_from(Post)
    )
    total = count_result.scalar_one()

    # Get paginated results
    result = await session.execute(
        select(Post)
        .order_by(Post.created_at.desc())
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

### Relationships and Eager Loading

```python
from sqlalchemy.orm import selectinload

@router.get("/users/{user_id}/with-posts")
async def get_user_with_posts(
    user_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    """Get user with posts eagerly loaded (prevent N+1)."""
    result = await session.execute(
        select(User)
        .where(User.id == user_id)
        .options(selectinload(User.posts))  # Eager load relationship
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise NotFoundError("User", {"id": user_id})

    return user
```

### Transactions

```python
@router.post("/transfer")
async def transfer_funds(
    from_account_id: int,
    to_account_id: int,
    amount: Decimal,
    session: AsyncSession = Depends(get_db_session),
):
    """Transfer funds between accounts (atomic transaction)."""
    try:
        # Get both accounts
        from_account_result = await session.execute(
            select(Account).where(Account.id == from_account_id)
        )
        from_account = from_account_result.scalar_one_or_none()

        to_account_result = await session.execute(
            select(Account).where(Account.id == to_account_id)
        )
        to_account = to_account_result.scalar_one_or_none()

        if not from_account or not to_account:
            raise NotFoundError("Account", {"id": from_account_id or to_account_id})

        # Validate balance
        if from_account.balance < amount:
            raise ValueError("Insufficient funds")

        # Perform transfer
        from_account.balance -= amount
        to_account.balance += amount

        # Commit atomically (both or neither)
        await session.commit()

        return {"message": "Transfer successful"}

    except Exception:
        await session.rollback()  # Rollback on any error
        raise
```

### Complex Queries

```python
from sqlalchemy import and_, or_, func, case

@router.get("/analytics/user-stats")
async def get_user_stats(
    session: AsyncSession = Depends(get_db_session),
):
    """Get user statistics with complex aggregation."""
    result = await session.execute(
        select(
            func.count(User.id).label("total_users"),
            func.count(case((User.is_active == True, 1))).label("active_users"),
            func.count(case((User.is_superuser == True, 1))).label("admin_users"),
            func.avg(
                func.extract("epoch", func.now() - User.created_at)
            ).label("avg_account_age_seconds"),
        )
    )
    stats = result.one()

    return {
        "total_users": stats.total_users,
        "active_users": stats.active_users,
        "admin_users": stats.admin_users,
        "avg_account_age_days": stats.avg_account_age_seconds / 86400 if stats.avg_account_age_seconds else 0,
    }
```

---

## Error Handling

### Using NotFoundError

```python
from example_service.core.database import NotFoundError

@router.get("/items/{item_id}")
async def get_item(
    item_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    result = await session.execute(
        select(Item).where(Item.id == item_id)
    )
    item = result.scalar_one_or_none()

    if item is None:
        # Raises HTTP 500 by default, needs exception handler
        raise NotFoundError("Item", {"id": item_id})

    return item
```

### Exception Handler (Add to main.py)

```python
from fastapi import Request
from fastapi.responses import JSONResponse
from example_service.core.database import NotFoundError, DatabaseError

@app.exception_handler(NotFoundError)
async def not_found_exception_handler(request: Request, exc: NotFoundError):
    """Convert NotFoundError to HTTP 404."""
    return JSONResponse(
        status_code=404,
        content={
            "detail": str(exc),
            "model": exc.model_name,
            "identifier": exc.identifier,
        },
    )

@app.exception_handler(DatabaseError)
async def database_exception_handler(request: Request, exc: DatabaseError):
    """Convert DatabaseError to HTTP 500."""
    return JSONResponse(
        status_code=500,
        content={
            "detail": str(exc),
            "details": exc.details,
        },
    )
```

---

## Query Filtering Utilities

To reduce repetitive filtering code, we provide utility filter classes that work **directly** with SQLAlchemy statements. These don't hide queries - they just clean them up.

### Available Filters

```python
from example_service.core.database import (
    SearchFilter,      # Multi-field text search
    OrderBy,           # Column sorting
    LimitOffset,       # Pagination
    CollectionFilter,  # WHERE ... IN
    BeforeAfter,       # Date range (exclusive)
    OnBeforeAfter,     # Date range (inclusive)
    FilterGroup,       # Combine filters
)
```

### SearchFilter - Multi-Field Text Search

Search across multiple fields with case-insensitive LIKE queries:

```python
from sqlalchemy import select
from example_service.core.database import SearchFilter
from example_service.features.reminders.models import Reminder

# Search across title and description
stmt = select(Reminder)
stmt = SearchFilter(
    fields=[Reminder.title, Reminder.description],
    value="meeting",
    case_insensitive=True,  # Default: True
).apply(stmt)

# Generates: WHERE (LOWER(title) LIKE '%meeting%' OR LOWER(description) LIKE '%meeting%')
```

**Parameters:**
- `fields`: Single field or list of fields to search
- `value`: Search term (automatically wrapped with `%`)
- `case_insensitive`: Use ILIKE (True) or LIKE (False)
- `operator`: Join multiple fields with "and" or "or" (default: "or")

### OrderBy - Column Sorting

Sort results by one or multiple columns:

```python
from example_service.core.database import OrderBy

# Single column sort
stmt = select(Reminder)
stmt = OrderBy(Reminder.created_at, "desc").apply(stmt)

# Multiple columns with different directions
stmt = OrderBy(
    fields=[Reminder.is_completed, Reminder.remind_at],
    sort_order=["asc", "desc"]
).apply(stmt)
```

### LimitOffset - Pagination

Simple pagination with LIMIT and OFFSET:

```python
from example_service.core.database import LimitOffset

# Page 1: First 50 items
stmt = select(Reminder)
stmt = LimitOffset(limit=50, offset=0).apply(stmt)

# Page 2: Next 50 items
stmt = LimitOffset(limit=50, offset=50).apply(stmt)
```

### CollectionFilter - WHERE IN Clauses

Filter by collection of values:

```python
from example_service.core.database import CollectionFilter

# WHERE user_id IN (1, 2, 3)
stmt = select(Reminder)
stmt = CollectionFilter(
    field=Reminder.user_id,
    values=[1, 2, 3]
).apply(stmt)

# WHERE status NOT IN ('deleted', 'archived')
stmt = CollectionFilter(
    field=Reminder.status,
    values=["deleted", "archived"],
    invert=True  # Use NOT IN
).apply(stmt)
```

### BeforeAfter - Date Range Filtering

Exclusive date range filtering (< and >):

```python
from datetime import datetime
from example_service.core.database import BeforeAfter

# Records after a specific date
stmt = select(Reminder)
stmt = BeforeAfter(
    field=Reminder.created_at,
    after=datetime(2024, 1, 1)
).apply(stmt)
# Generates: WHERE created_at > '2024-01-01'

# Records in a date range
stmt = BeforeAfter(
    field=Reminder.created_at,
    before=datetime(2024, 12, 31),
    after=datetime(2024, 1, 1)
).apply(stmt)
# Generates: WHERE created_at > '2024-01-01' AND created_at < '2024-12-31'
```

### OnBeforeAfter - Inclusive Date Ranges

Inclusive date range filtering (<= and >=):

```python
from example_service.core.database import OnBeforeAfter

# Records on or after a date (inclusive)
stmt = select(Reminder)
stmt = OnBeforeAfter(
    field=Reminder.created_at,
    on_or_after=datetime(2024, 1, 1)
).apply(stmt)
# Generates: WHERE created_at >= '2024-01-01'
```

### Combining Filters - Real World Example

The `/reminders/search` endpoint demonstrates practical filter composition:

```python
@router.get("/search", response_model=list[ReminderResponse])
async def search_reminders(
    session: AsyncSession = Depends(get_db_session),
    query: str | None = None,
    before: datetime | None = None,
    after: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
    sort_by: str = "created_at",
    sort_order: str = "desc",
) -> list[ReminderResponse]:
    """Search reminders with multiple filters."""
    stmt = select(Reminder)

    # Text search across multiple fields
    if query:
        stmt = SearchFilter(
            fields=[Reminder.title, Reminder.description],
            value=query,
            case_insensitive=True,
        ).apply(stmt)

    # Date range filtering
    if before or after:
        stmt = BeforeAfter(
            Reminder.created_at,
            before=before,
            after=after,
        ).apply(stmt)

    # Dynamic sorting
    sort_field = getattr(Reminder, sort_by, Reminder.created_at)
    stmt = OrderBy(sort_field, sort_order).apply(stmt)

    # Pagination
    stmt = LimitOffset(limit=limit, offset=offset).apply(stmt)

    result = await session.execute(stmt)
    reminders = result.scalars().all()
    return [ReminderResponse.model_validate(reminder) for reminder in reminders]
```

### FilterGroup - Advanced Composition

Combine multiple filters with explicit AND/OR logic:

```python
from example_service.core.database import FilterGroup

# Multiple filters combined with AND (default)
filters = FilterGroup([
    SearchFilter([User.name, User.email], "admin"),
    CollectionFilter(User.status, ["active", "pending"]),
    BeforeAfter(User.created_at, after=datetime(2024, 1, 1)),
])
stmt = select(User)
stmt = filters.apply(stmt)
```

### Best Practices

**✅ DO:**
- Use filters for common, repetitive patterns
- Chain filters with `.apply()` for clarity
- Keep the SQLAlchemy statement visible
- Add custom filters for domain-specific patterns

**❌ DON'T:**
- Hide the underlying query completely
- Use filters for one-off complex queries (just write SQL)
- Add filters before you feel the pain of repetition

**When to use filters vs raw SQLAlchemy:**
- **Use filters**: Common patterns like search, pagination, sorting
- **Use raw SQLAlchemy**: Complex joins, subqueries, domain-specific logic

---

## Encrypted Column Types

For sensitive data like SSNs, API keys, or personal information, use `EncryptedString` or `EncryptedText` types that transparently handle encryption/decryption using Fernet symmetric encryption.

### EncryptedString - Encrypted VARCHAR

For shorter sensitive data (up to 255 characters original length):

```python
from sqlalchemy.orm import Mapped, mapped_column
from example_service.core.database import UUIDTimestampedBase, EncryptedString
import os

class User(UUIDTimestampedBase):
    __tablename__ = "users"

    email: Mapped[str]
    # Transparent encryption for sensitive data
    ssn: Mapped[str] = mapped_column(
        EncryptedString(key=os.getenv("ENCRYPTION_KEY"))
    )
    api_token: Mapped[str | None] = mapped_column(
        EncryptedString(key=os.getenv("ENCRYPTION_KEY")),
        nullable=True
    )

# Usage - encryption is completely transparent:
user = User(
    email="user@example.com",
    ssn="123-45-6789",  # Will be encrypted in database
    api_token="sk_live_abc123"
)
session.add(user)
await session.commit()

# Retrieval automatically decrypts:
result = await session.execute(select(User).where(User.email == "user@example.com"))
user = result.scalar_one()
print(user.ssn)  # "123-45-6789" - automatically decrypted!
```

### EncryptedText - Encrypted TEXT

For larger sensitive content:

```python
from example_service.core.database import EncryptedText

class Document(UUIDTimestampedBase):
    __tablename__ = "documents"

    title: Mapped[str]
    # Use EncryptedText for larger content
    sensitive_content: Mapped[str] = mapped_column(
        EncryptedText(key=os.getenv("ENCRYPTION_KEY"))
    )
```

### Generating and Managing Encryption Keys

**Generate a key:**

```python
from cryptography.fernet import Fernet

# Generate a new key (do this ONCE, store securely)
key = Fernet.generate_key()
print(key.decode())  # Save this to your environment variables
```

**Store in environment:**

```bash
# .env file (NEVER commit this!)
ENCRYPTION_KEY=your-generated-key-here

# Or in production, use secrets management:
# - AWS Secrets Manager
# - HashiCorp Vault
# - Kubernetes Secrets
```

**Load in settings:**

```python
# example_service/core/settings/app.py
from pydantic_settings import BaseSettings

class AppSettings(BaseSettings):
    encryption_key: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

# Use in models
from example_service.core.settings import app_settings

class User(UUIDTimestampedBase):
    ssn: Mapped[str] = mapped_column(
        EncryptedString(key=app_settings.encryption_key)
    )
```

### Security Best Practices

**✅ DO:**
- Generate keys using `Fernet.generate_key()` - never manually create keys
- Store keys in environment variables or secrets management systems
- Use different keys for different environments (dev/staging/prod)
- Rotate keys periodically (requires re-encrypting data)
- Use `EncryptedString` for PII, tokens, and credentials
- Consider field-level encryption only for truly sensitive data

**❌ DON'T:**
- Hard-code encryption keys in source code
- Commit encryption keys to version control
- Use the same key across multiple environments
- Encrypt fields you need to search or filter by (encryption prevents indexing)
- Over-encrypt - it adds overhead and complexity

**Performance Considerations:**
- Encryption/decryption happens on every read/write
- Cannot create indexes on encrypted columns
- Cannot use WHERE clauses on encrypted values (except exact match with encrypted comparison)
- Use selectively for sensitive data only

**When to Use Encrypted Types:**
- Social Security Numbers, Tax IDs
- Credit card numbers (PCI compliance)
- API tokens and secrets
- Personal health information (PHI)
- Authentication credentials

**When NOT to Use:**
- Fields you need to search/filter by
- High-volume transactional data
- Already-hashed passwords (use proper password hashing instead)
- Data that needs to be indexed

### Database Dialect Support

The encrypted types automatically adapt to different databases:

- **PostgreSQL**: Uses `VARCHAR(255)` or `TEXT`
- **MySQL**: Uses `TEXT` (due to strict length limits)
- **Oracle**: Uses `VARCHAR2(4000)`
- **SQLite**: Uses `TEXT`

The encrypted data is stored as base64-encoded strings, so actual storage size will be ~33% larger than the original data.

---

## When to Add Abstraction

Start direct, add complexity when you feel pain.

### Helper Functions (First Step)

When you find yourself repeating queries:

```python
# In your router.py or a new helpers.py
from collections.abc import Sequence

async def _find_active_users(session: AsyncSession) -> Sequence[User]:
    """Helper: Find all active users."""
    result = await session.execute(
        select(User).where(User.is_active == True)
    )
    return result.scalars().all()

async def _find_user_by_email(session: AsyncSession, email: str) -> User | None:
    """Helper: Find user by email."""
    result = await session.execute(
        select(User).where(User.email == email)
    )
    return result.scalar_one_or_none()

# Use in endpoints:
@router.get("/users/active")
async def get_active_users(session: AsyncSession = Depends(get_db_session)):
    users = await _find_active_users(session)
    return users
```

### Repository Class (When You Have 5+ Helpers)

When helper functions grow unwieldy:

```python
# features/users/repository.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

class UserRepository:
    """User-specific queries (session passed to methods)."""

    async def find_by_email(
        self,
        session: AsyncSession,
        email: str,
    ) -> User | None:
        result = await session.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()

    async def find_active_users(
        self,
        session: AsyncSession,
    ) -> Sequence[User]:
        result = await session.execute(
            select(User).where(User.is_active == True)
        )
        return result.scalars().all()

# Use in endpoints:
@router.get("/users/active")
async def get_active_users(session: AsyncSession = Depends(get_db_session)):
    repo = UserRepository()
    users = await repo.find_active_users(session)
    return users
```

### Service Layer (When You Have Business Logic)

When you need validation, orchestration, or external integrations:

```python
# features/users/service.py
class UserService:
    """User business logic."""

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
            raise ValueError("Email already exists")

        # Create user
        user = User(**data.model_dump())
        session.add(user)
        await session.commit()

        # Send welcome email (external integration)
        await email_service.send_welcome(user.email)

        return user

# Use in endpoints:
@router.post("/users")
async def create_user(
    data: UserCreate,
    session: AsyncSession = Depends(get_db_session),
    email_service: EmailService = Depends(get_email_service),
):
    service = UserService()
    user = await service.create_user_with_welcome_email(session, data, email_service)
    return user
```

---

## Summary

**Golden Rule:** If you can see the SQL query in your endpoint, that's probably fine. Add abstraction when it solves a real problem you're experiencing right now.

**Progression:**
1. **Start:** Direct SQLAlchemy in endpoints ← **You are here**
2. **Next:** Helper functions for repeated queries
3. **Then:** Repository class if helpers grow to 5+
4. **Finally:** Service layer if business logic emerges

The mixin system is always valuable - use it freely!
