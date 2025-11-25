# Reminders Feature - Repository Pattern Refactor

## Overview

The reminders feature has been refactored to use the new repository pattern, demonstrating a complete feature migration from raw SQLAlchemy to the enhanced database architecture.

## What Changed

### Before (Raw SQLAlchemy)

```python
# service.py
class ReminderService(BaseService):
    def __init__(self, session: AsyncSession):
        self._session = session

    async def list_reminders(self) -> list[Reminder]:
        result = await self._session.execute(
            select(Reminder).order_by(Reminder.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_reminder(self, reminder_id: UUID) -> Reminder | None:
        return await self._session.get(Reminder, reminder_id)

    async def create_reminder(self, payload: ReminderCreate) -> Reminder:
        reminder = Reminder(...)
        self._session.add(reminder)
        await self._session.commit()
        await self._session.refresh(reminder)
        return reminder
```

### After (Repository Pattern)

```python
# repository.py
class ReminderRepository(BaseRepository[Reminder]):
    def __init__(self, session: AsyncSession):
        super().__init__(Reminder, session)

    async def find_pending(self) -> Sequence[Reminder]:
        stmt = select(Reminder).where(Reminder.is_completed == False)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def find_overdue(self) -> Sequence[Reminder]:
        now = datetime.utcnow()
        stmt = select(Reminder).where(
            Reminder.is_completed == False,
            Reminder.remind_at < now
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

# service.py
class ReminderService(BaseService):
    def __init__(self, reminder_repo: ReminderRepository):
        self._repo = reminder_repo

    async def list_reminders(self) -> list[Reminder]:
        reminders = await self._repo.list_all_ordered()
        return list(reminders)

    async def get_reminder(self, reminder_id: UUID) -> Reminder | None:
        return await self._repo.get(reminder_id)

    async def create_reminder(self, payload: ReminderCreate) -> Reminder:
        reminder = Reminder(...)
        return await self._repo.create(reminder, auto_commit=True)
```

## Architecture

```
┌─────────────────────────────────────────┐
│  Router (router.py)                     │
│  - HTTP endpoints                       │
│  - Request/response handling            │
└─────────────┬───────────────────────────┘
              │ Depends(get_reminder_service)
              ▼
┌─────────────────────────────────────────┐
│  Service (service.py)                   │
│  - Business logic                       │
│  - Orchestration                        │
│  - Validation rules                     │
└─────────────┬───────────────────────────┘
              │ Uses reminder_repo
              ▼
┌─────────────────────────────────────────┐
│  Repository (repository.py)             │
│  - Data access queries                  │
│  - CRUD operations                      │
│  - Custom queries (find_pending, etc)   │
└─────────────┬───────────────────────────┘
              │ Operates on
              ▼
┌─────────────────────────────────────────┐
│  Model (models.py)                      │
│  - Reminder entity                      │
│  - Database schema                      │
└─────────────────────────────────────────┘
```

## Files Structure

```
features/reminders/
├── __init__.py
├── models.py         # Reminder model (unchanged)
├── repository.py     # ✨ NEW: ReminderRepository
├── service.py        # 📝 REFACTORED: Uses repository
├── router.py         # ✓ UNCHANGED: Already used service
└── schemas.py        # ✓ UNCHANGED: Pydantic schemas
```

## New Capabilities

### 1. ReminderRepository Custom Methods

The repository now provides domain-specific query methods:

**Status Filtering:**
```python
# Get pending reminders
pending = await repo.find_pending()

# Get completed reminders
completed = await repo.find_completed()

# Get overdue reminders
overdue = await repo.find_overdue()

# Get upcoming reminders (next 24 hours)
upcoming = await repo.find_upcoming(hours=24)
```

**Notification Management:**
```python
# Find reminders needing notifications
to_notify = await repo.find_unsent_notifications()

# Mark notification as sent
await repo.mark_notification_sent(reminder_id)
```

**Search and Filter:**
```python
# Search by title
result = await repo.search_by_title(
    "meeting",
    include_completed=False,
    limit=10,
    offset=0
)

# Smart ordering (pending first, by date)
reminders = await repo.list_all_ordered(include_completed=False)
```

**Convenience Methods:**
```python
# Mark as completed
reminder = await repo.mark_completed(reminder_id)

# Count pending
count = await repo.count_pending()
```

### 2. Enhanced Service Methods

The service layer now provides higher-level business operations:

**CRUD with Auto-Commit:**
```python
# Create with automatic transaction
reminder = await service.create_reminder(ReminderCreate(...))

# Update reminder
updated = await service.update_reminder(reminder_id, data)

# Delete reminder
await service.delete_reminder(reminder_id)
```

**Business Logic:**
```python
# Complete reminder (could trigger notifications)
reminder = await service.complete_reminder(reminder_id)

# Get statistics
stats = await service.get_reminder_stats()
# Returns: {"pending": 5, "completed": 10, "overdue": 2, "total": 15}
```

**Background Tasks:**
```python
# Process pending notifications (for worker)
processed = await service.process_pending_notifications()
```

## Usage Examples

### Example 1: List Pending Reminders

**Before:**
```python
@router.get("/reminders")
async def list_reminders(service: ReminderService = Depends(get_reminder_service)):
    reminders = await service.list_reminders()  # Returns all
    return [ReminderResponse.model_validate(r) for r in reminders]
```

**After (with new filtering):**
```python
@router.get("/reminders/pending")
async def list_pending(service: ReminderService = Depends(get_reminder_service)):
    reminders = await service.get_pending_reminders()  # Only pending
    return [ReminderResponse.model_validate(r) for r in reminders]
```

### Example 2: Complete Reminder

**Before (in service, manual update):**
```python
async def complete_reminder(self, reminder_id: UUID) -> Reminder:
    reminder = await self._session.get(Reminder, reminder_id)
    if not reminder:
        raise ValueError("Not found")
    reminder.is_completed = True
    await self._session.commit()
    return reminder
```

**After (repository convenience method):**
```python
async def complete_reminder(self, reminder_id: UUID) -> Reminder:
    # Repository handles the update
    reminder = await self._repo.mark_completed(reminder_id)

    # Service can add business logic
    # await self._notification_service.send_completion(reminder)

    return reminder
```

### Example 3: Get Statistics

**New capability not possible before:**
```python
@router.get("/reminders/stats")
async def get_stats(service: ReminderService = Depends(get_reminder_service)):
    stats = await service.get_reminder_stats()
    return {
        "pending": stats["pending"],
        "completed": stats["completed"],
        "overdue": stats["overdue"],
        "total": stats["total"],
    }
```

### Example 4: Background Notification Worker

**New capability:**
```python
# tasks/reminder_notifications.py
from taskiq import TaskiqScheduler
from example_service.core.dependencies.repositories import get_reminder_repository
from example_service.features.reminders.service import ReminderService

@scheduler.task(cron="*/15 * * * *")  # Every 15 minutes
async def process_reminder_notifications():
    """Send notifications for due reminders."""
    async with get_db_session() as session:
        repo = ReminderRepository(session)
        service = ReminderService(repo)

        processed = await service.process_pending_notifications()
        print(f"Sent {len(processed)} notifications")
```

## Benefits of Refactor

### 1. Separation of Concerns

**Before:**
- Service mixed data access (SQL) with business logic
- Harder to test - need full database setup

**After:**
- Repository handles all data access
- Service focuses on business rules
- Can mock repository in service tests

### 2. Reusability

**Before:**
- Query logic duplicated across methods
- No way to reuse queries in other features

**After:**
- Custom queries in repository can be reused
- Other features can use ReminderRepository
- Background tasks can use same repository

### 3. Testability

**Repository Tests (Fast):**
```python
@pytest.mark.asyncio
async def test_find_overdue(session):
    repo = ReminderRepository(session)

    # Create overdue reminder
    reminder = Reminder(
        title="Test",
        remind_at=datetime.utcnow() - timedelta(hours=2)
    )
    await repo.create(reminder)

    # Test query
    overdue = await repo.find_overdue()
    assert len(overdue) == 1
```

**Service Tests (Mocked):**
```python
@pytest.mark.asyncio
async def test_complete_reminder():
    # Mock repository
    repo = AsyncMock(spec=ReminderRepository)
    repo.mark_completed.return_value = Reminder(id=uuid4(), is_completed=True)

    # Test service
    service = ReminderService(repo)
    reminder = await service.complete_reminder(uuid4())

    assert reminder.is_completed
    repo.mark_completed.assert_called_once()
```

### 4. Type Safety

**Before:**
```python
async def get_reminder(self, reminder_id: UUID):
    return await self._session.get(Reminder, reminder_id)  # Type checker can't infer
```

**After:**
```python
async def get_reminder(self, reminder_id: UUID) -> Reminder | None:
    return await self._repo.get(reminder_id)  # Generic type preserved
```

### 5. Consistency

All features using repository pattern have consistent:
- Method signatures
- Error handling (NotFoundError)
- Transaction management (auto_commit parameter)
- Pagination (SearchResult)

## Migration Pattern for Other Features

To migrate other features to this pattern:

### Step 1: Create Repository

```python
# features/your_feature/repository.py
from example_service.core.database import BaseRepository
from .models import YourModel

class YourRepository(BaseRepository[YourModel]):
    def __init__(self, session: AsyncSession):
        super().__init__(YourModel, session)

    async def find_by_custom_field(self, value: str) -> YourModel | None:
        stmt = select(YourModel).where(YourModel.field == value)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
```

### Step 2: Add DI Function

```python
# core/dependencies/repositories.py
async def get_your_repository(
    session: AsyncSession = Depends(get_db_session),
) -> YourRepository:
    return YourRepository(session)
```

### Step 3: Update Service

```python
# features/your_feature/service.py
class YourService(BaseService):
    def __init__(self, your_repo: YourRepository):  # Was: session
        self._repo = your_repo  # Was: self._session

    async def get_item(self, item_id: int):
        return await self._repo.get_by_id(item_id)  # Was: session.get(...)
```

### Step 4: Update Service DI

```python
# core/dependencies/services.py
async def get_your_service(
    your_repo: YourRepository = Depends(get_your_repository),  # Was: session
) -> YourService:
    return YourService(your_repo)  # Was: YourService(session)
```

### Step 5: Endpoints (Usually No Change)

If endpoints already use service, no changes needed:
```python
@router.get("/items/{item_id}")
async def get_item(
    item_id: int,
    service: YourService = Depends(get_your_service),  # Unchanged
):
    item = await service.get_item(item_id)  # Unchanged
    return item
```

## Common Patterns

### Pattern 1: Direct Repository (Simple CRUD)

For features with minimal business logic, inject repository directly:
```python
@router.get("/reminders")
async def list_reminders(
    repo: ReminderRepository = Depends(get_reminder_repository),
):
    result = await repo.search(limit=50)
    return [ReminderResponse.model_validate(r) for r in result.items]
```

### Pattern 2: Service Layer (Business Logic)

For features with validation, orchestration, or external integrations:
```python
@router.post("/reminders")
async def create_reminder(
    data: ReminderCreate,
    service: ReminderService = Depends(get_reminder_service),
):
    # Service handles validation, notifications, etc.
    reminder = await service.create_reminder(data)
    return ReminderResponse.model_validate(reminder)
```

## Testing the Refactor

### Unit Test Repository

```python
# tests/features/reminders/test_repository.py
import pytest
from datetime import datetime, timedelta
from example_service.features.reminders.repository import ReminderRepository
from example_service.features.reminders.models import Reminder

@pytest.mark.asyncio
async def test_find_overdue(db_session):
    repo = ReminderRepository(db_session)

    # Create overdue reminder
    overdue = Reminder(
        title="Overdue",
        remind_at=datetime.utcnow() - timedelta(hours=1),
        is_completed=False,
    )
    await repo.create(overdue)

    # Create future reminder
    future = Reminder(
        title="Future",
        remind_at=datetime.utcnow() + timedelta(hours=1),
        is_completed=False,
    )
    await repo.create(future)

    # Test
    overdue_reminders = await repo.find_overdue()
    assert len(overdue_reminders) == 1
    assert overdue_reminders[0].title == "Overdue"
```

### Integration Test Service

```python
# tests/features/reminders/test_service.py
import pytest
from example_service.features.reminders.service import ReminderService
from example_service.features.reminders.schemas import ReminderCreate

@pytest.mark.asyncio
async def test_create_and_complete(db_session):
    repo = ReminderRepository(db_session)
    service = ReminderService(repo)

    # Create
    reminder = await service.create_reminder(
        ReminderCreate(title="Test", description="Test reminder")
    )
    assert reminder.id is not None
    assert not reminder.is_completed

    # Complete
    completed = await service.complete_reminder(reminder.id)
    assert completed.is_completed
```

## Next Steps

1. **Add More Custom Queries**: Extend ReminderRepository with additional domain queries
2. **Implement Notifications**: Wire up actual notification sending in service
3. **Add Background Tasks**: Create Taskiq/APScheduler jobs using the service
4. **Add Pagination to Endpoints**: Use `SearchResult` for paginated API responses
5. **Migrate Other Features**: Apply this pattern to other features

## Resources

- [Database Architecture Guide](./DATABASE_ARCHITECTURE.md)
- [Quick Reference](./DATABASE_QUICK_REFERENCE.md)
- [BaseRepository API](../example_service/core/database/repository.py)
- [ReminderRepository Source](../example_service/features/reminders/repository.py)
