# Feature Implementation Guide

This guide establishes the patterns for implementing features in this FastAPI template. The **Reminders feature** (`example_service/features/reminders/`) serves as the canonical reference implementation.

## Directory Structure

Each feature should follow this structure:

```
features/{feature_name}/
    __init__.py       # Public exports
    models.py         # SQLAlchemy models
    schemas.py        # Pydantic request/response schemas
    repository.py     # Data access layer (extends BaseRepository)
    service.py        # Business logic (extends BaseService)
    router.py         # HTTP endpoints
    events.py         # Domain events (optional)
    dependencies.py   # Feature-specific dependencies (optional)
```

## Error Handling

### Required Pattern: Use AppException Hierarchy

**Always use custom exceptions from `core.exceptions`**, never raw `HTTPException`:

```python
# ✅ CORRECT - Use AppException subclasses
from example_service.core.database import NotFoundError
from example_service.core.exceptions import BadRequestException, ServiceUnavailableException

# 404 - Resource not found
raise NotFoundError("Reminder", {"id": reminder_id})

# 400 - Bad request / validation error
raise BadRequestException(
    detail="Reminder is not recurring",
    type="reminder-not-recurring",
    extra={"reminder_id": str(reminder_id)},
)

# 503 - Service unavailable
raise ServiceUnavailableException(detail="File storage is not configured")
```

```python
# ❌ WRONG - Never use HTTPException in feature routers
from fastapi import HTTPException

raise HTTPException(status_code=404, detail="Not found")  # DON'T DO THIS
```

### Exception Mapping

| Status Code | AppException Class | Use Case |
|-------------|-------------------|----------|
| 400 | `BadRequestException` | Invalid input, business rule violations |
| 401 | `UnauthorizedException` | Authentication required |
| 403 | `ForbiddenException` | Insufficient permissions |
| 404 | `NotFoundException` / `NotFoundError` | Resource not found |
| 409 | `ConflictException` | Duplicate resource, state conflict |
| 422 | `ValidationException` | Schema validation failures |
| 429 | `RateLimitException` | Rate limit exceeded |
| 500 | `InternalServerException` | Unexpected server errors |
| 503 | `ServiceUnavailableException` | External service unavailable |

## Response Transformation

### Pattern: `from_model()` vs `model_validate()`

Choose based on whether your response needs computed/transformed fields:

```python
# ✅ Use from_model() when response has computed fields
class ReminderResponse(BaseModel):
    recurrence: RecurrenceInfo | None = None  # Computed from recurrence_rule

    @classmethod
    def from_model(cls, reminder: Reminder) -> ReminderResponse:
        """Custom transformation with computed fields."""
        recurrence = None
        if reminder.recurrence_rule:
            recurrence = RecurrenceInfo(
                rule=reminder.recurrence_rule,
                description=describe_rrule(reminder.recurrence_rule),
                # ... more computed fields
            )
        return cls(
            id=reminder.id,
            title=reminder.title,
            recurrence=recurrence,
            # ...
        )

# Router usage
return ReminderResponse.from_model(reminder)
return [ReminderResponse.from_model(r) for r in reminders]
```

```python
# ✅ Use model_validate() for simple 1:1 mappings (no computed fields)
class TagResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    created_at: datetime

# Router usage
return TagResponse.model_validate(tag)
```

### Rule

**Be consistent within a feature.** If any endpoint in a feature uses `from_model()`, all endpoints returning that schema should use `from_model()`.

## Repository Pattern

### Base Repository Methods

Every repository inherits from `BaseRepository[T]` which provides:

```python
class BaseRepository[T]:
    async def get(session, id) -> T | None
    async def get_or_raise(session, id) -> T  # Raises NotFoundError
    async def get_by(session, attr, value) -> T | None
    async def list(session, limit, offset) -> Sequence[T]
    async def search(session, statement, limit, offset) -> SearchResult[T]
    async def create(session, instance) -> T
    async def delete(session, instance) -> None
    async def paginate_cursor(...) -> Connection[T]
```

### Adding Feature-Specific Methods

```python
class ReminderRepository(BaseRepository[Reminder]):
    """Repository for Reminder model."""

    def __init__(self) -> None:
        super().__init__(Reminder)

    async def list_all(
        self,
        session: AsyncSession,
        *,
        include_completed: bool = True,
    ) -> Sequence[Reminder]:
        """List all reminders with smart ordering."""
        stmt = select(Reminder)
        if not include_completed:
            stmt = stmt.where(Reminder.is_completed == False)
        stmt = stmt.order_by(...)
        result = await session.execute(stmt)
        return result.scalars().all()
```

### Router Usage

```python
@router.get("/")
async def list_reminders(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    repo: Annotated[ReminderRepository, Depends(get_reminder_repository)],
) -> list[ReminderResponse]:
    """Use repository methods instead of direct queries."""
    reminders = await repo.list_all(session, include_completed=True)
    return [ReminderResponse.from_model(r) for r in reminders]
```

## Logging Patterns

Use the dual-logger pattern for appropriate log levels:

```python
import logging
from example_service.infra.logging import get_lazy_logger

logger = logging.getLogger(__name__)        # Standard logger: INFO/WARNING/ERROR
lazy_logger = get_lazy_logger(__name__)     # Lazy logger: DEBUG (zero overhead when disabled)

# DEBUG - detailed context (no cost when DEBUG is off)
lazy_logger.debug(
    lambda: f"endpoint.search: query={query!r}, results={len(items)}"
)

# INFO - significant events, actionable conditions
logger.info(
    "Overdue reminders found",
    extra={"count": len(reminders), "operation": "endpoint.get_overdue"},
)

# WARNING/ERROR - issues that need attention
logger.warning("Rate limit approaching", extra={"current": count, "limit": max_count})
```

## Pagination Guidelines

| Pattern | When to Use | Schema |
|---------|-------------|--------|
| Raw `list[T]` | Bounded endpoints (health, stats), small fixed-size results | None |
| Offset (`limit`/`offset`) | Admin UIs, known small datasets (<10k items) | `PaginatedResponse[T]` |
| Cursor-based | Large datasets, infinite scroll, real-time data | `CursorPage[T]` |

```python
# Cursor-based pagination example
@router.get("/paginated", response_model=ReminderCursorPage)
async def list_paginated(
    repo: Annotated[ReminderRepository, Depends(get_reminder_repository)],
    limit: int = 50,
    cursor: str | None = None,
) -> ReminderCursorPage:
    connection = await repo.paginate_cursor(
        session, stmt, first=min(limit, 100), after=cursor, order_by=[...]
    )
    return ReminderCursorPage(
        items=[ReminderResponse.from_model(e.node) for e in connection.edges],
        next_cursor=connection.page_info.end_cursor,
        has_more=connection.page_info.has_next_page,
    )
```

## Reference Implementation

See `example_service/features/reminders/` for the complete reference implementation demonstrating all these patterns:

- **router.py**: Error handling, response transformation, repository injection
- **repository.py**: Custom repository methods extending BaseRepository
- **schemas.py**: Response schemas with `from_model()` pattern
- **service.py**: Business logic with logging patterns
- **events.py**: Domain events for event-driven architecture

## Pre-commit Enforcement

The following patterns are enforced by pre-commit hooks:

1. **No HTTPException in routers** - `tools/linting/no_http_exception.py`
2. **Service logging patterns** - `tools/linting/logging_checks.py`
3. **OpenAPI documentation** - `tools/linting/openapi_checks.py`
