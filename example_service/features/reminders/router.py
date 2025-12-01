"""API router for the reminders feature."""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from example_service.core.database import (
    BeforeAfter,
    LimitOffset,
    NotFoundError,
    OrderBy,
    SearchFilter,
)
from example_service.core.database.search import FullTextSearchFilter, WebSearchFilter
from example_service.core.dependencies.database import get_db_session
from example_service.core.dependencies.events import EventPublisherDep
from example_service.features.reminders.events import (
    ReminderCompletedEvent,
    ReminderCreatedEvent,
    ReminderDeletedEvent,
    ReminderUpdatedEvent,
)
from example_service.features.reminders.models import Reminder
from example_service.features.reminders.recurrence import (
    generate_occurrences,
    get_next_occurrence,
)
from example_service.features.reminders.repository import (
    ReminderRepository,
    get_reminder_repository,
)
from example_service.features.reminders.schemas import (
    OccurrenceResponse,
    OccurrencesResponse,
    ReminderCreate,
    ReminderCursorPage,
    ReminderResponse,
    ReminderSearchResult,
    ReminderUpdate,
)
from example_service.infra.logging import get_lazy_logger
from example_service.infra.metrics.tracking import track_feature_usage, track_user_action

router = APIRouter(prefix="/reminders", tags=["reminders"])

# Standard logger for INFO/WARNING/ERROR
logger = logging.getLogger(__name__)
# Lazy logger for DEBUG (zero overhead when DEBUG disabled)
lazy_logger = get_lazy_logger(__name__)


@router.get(
    "/",
    response_model=list[ReminderResponse],
    summary="List reminders",
    description="Return all reminders with smart ordering (pending first, by date).",
)
async def list_reminders(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    include_completed: bool = True,
) -> list[ReminderResponse]:
    """List reminders with optional filtering.

    Args:
        session: Database session
        include_completed: Whether to include completed reminders

    Returns:
        List of reminders ordered by completion status and date
    """
    stmt = select(Reminder)

    if not include_completed:
        stmt = stmt.where(Reminder.is_completed == False)  # noqa: E712

    # Smart ordering: pending first, by date, newest created first
    stmt = stmt.order_by(
        Reminder.is_completed.asc(),  # Pending reminders first
        Reminder.remind_at.asc().nullslast(),  # Soonest dates first
        Reminder.created_at.desc(),  # Newest first
    )

    result = await session.execute(stmt)
    reminders = result.scalars().all()
    return [ReminderResponse.model_validate(reminder) for reminder in reminders]


@router.get(
    "/paginated",
    response_model=ReminderCursorPage,
    summary="List reminders with cursor pagination",
    description="""
List reminders using cursor-based pagination for stable, efficient paging.

**Benefits over offset pagination:**
- Stable results even when data changes between pages
- Efficient for large datasets (uses indexed seeks, not OFFSET scans)
- Works well with infinite scroll UIs

**Usage:**
1. First request: `GET /paginated?limit=20`
2. Next page: `GET /paginated?limit=20&cursor={next_cursor}`
3. Repeat until `has_more` is false

The `cursor` is an opaque string - pass it back unchanged.
""",
)
async def list_reminders_paginated(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    repo: Annotated[ReminderRepository, Depends(get_reminder_repository)],
    limit: int = 50,
    cursor: str | None = None,
    include_completed: bool = True,
    sort_by: str = "created_at",
    sort_order: str = "desc",
) -> ReminderCursorPage:
    """List reminders with cursor-based pagination.

    Args:
        session: Database session
        repo: Reminder repository
        limit: Number of items per page (1-100)
        cursor: Opaque cursor from previous page's next_cursor
        include_completed: Whether to include completed reminders
        sort_by: Field to sort by (created_at, remind_at, updated_at)
        sort_order: Sort direction (asc, desc)

    Returns:
        CursorPage with items, cursors, and has_more flag
    """
    # Build base statement
    stmt = select(Reminder)

    if not include_completed:
        stmt = stmt.where(Reminder.is_completed == False)  # noqa: E712

    # Determine sort column
    sort_column = getattr(Reminder, sort_by, Reminder.created_at)

    # Build order_by list (must include a unique column for stable pagination)
    order_by = [
        (sort_column, sort_order),
        (Reminder.id, "asc"),  # Tiebreaker for stable ordering
    ]

    # Execute paginated query
    connection = await repo.paginate_cursor(
        session,
        stmt,
        first=min(limit, 100),  # Cap at 100
        after=cursor,
        order_by=order_by,
    )

    # Convert to REST-style response
    cursor_page = connection.to_cursor_page()

    # Transform items to response schema
    return ReminderCursorPage(
        items=[ReminderResponse.model_validate(edge.node) for edge in connection.edges],
        next_cursor=cursor_page.next_cursor,
        prev_cursor=cursor_page.prev_cursor,
        has_more=cursor_page.has_more,
    )


@router.get(
    "/search",
    response_model=list[ReminderResponse],
    summary="Search reminders",
    description="Search reminders by title/description with filtering and pagination.",
)
async def search_reminders(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    query: str | None = None,
    before: datetime | None = None,
    after: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
    sort_by: str = "created_at",
    sort_order: str = "desc",
) -> list[ReminderResponse]:
    """Search reminders using filter utilities.

    Demonstrates the use of SearchFilter, BeforeAfter, OrderBy, and LimitOffset
    filters working directly with SQLAlchemy statements.

    Args:
        session: Database session
        query: Search term for title/description
        before: Show reminders before this date
        after: Show reminders after this date
        limit: Maximum number of results
        offset: Number of results to skip (for pagination)
        sort_by: Field to sort by (created_at, remind_at, updated_at)
        sort_order: Sort direction (asc, desc)

    Returns:
        List of matching reminders
    """
    stmt = select(Reminder)

    # Text search across title and description using SearchFilter
    if query:
        stmt = SearchFilter(
            fields=[Reminder.title, Reminder.description],
            value=query,
            case_insensitive=True,
        ).apply(stmt)

    # Date range filtering using BeforeAfter
    if before or after:
        stmt = BeforeAfter(
            Reminder.created_at,
            before=before,
            after=after,
        ).apply(stmt)

    # Sorting using OrderBy
    sort_field = getattr(Reminder, sort_by, Reminder.created_at)
    stmt = OrderBy(sort_field, sort_order).apply(stmt)  # type: ignore

    # Pagination using LimitOffset
    stmt = LimitOffset(limit=limit, offset=offset).apply(stmt)

    result = await session.execute(stmt)
    reminders = result.scalars().all()

    # DEBUG - search context
    lazy_logger.debug(
        lambda: f"endpoint.search_reminders: query={query!r}, limit={limit}, offset={offset} -> {len(reminders)} results"
    )

    # INFO - empty search results with query (useful for debugging user issues)
    if query and len(reminders) == 0:
        logger.info(
            "Search returned no results",
            extra={
                "query": query[:100] if query else None,
                "has_date_filter": before is not None or after is not None,
                "operation": "endpoint.search_reminders",
            },
        )

    return [ReminderResponse.model_validate(reminder) for reminder in reminders]


@router.get(
    "/fts",
    response_model=list[ReminderSearchResult],
    summary="Full-text search reminders",
    description="""
Search reminders using PostgreSQL full-text search with advanced features:
- **Stemming**: "running" matches "run", "runs", "running"
- **Stop words**: Common words like "the", "and" are ignored
- **Relevance ranking**: Results sorted by how well they match
- **Prefix matching**: Enable autocomplete with partial words

Use `mode=web` for Google-like syntax:
- `"exact phrase"` - match exact phrase
- `-word` - exclude word
- `word1 OR word2` - either word
""",
)
async def fulltext_search_reminders(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    q: str = "",
    mode: str = "plain",
    prefix: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[ReminderSearchResult]:
    """Full-text search reminders with PostgreSQL FTS.

    Args:
        session: Database session
        q: Search query string
        mode: Search mode - "plain" (default) or "web" (Google-like syntax)
        prefix: Enable prefix matching for autocomplete (last word matches prefix)
        limit: Maximum number of results
        offset: Number of results to skip

    Returns:
        List of reminders with relevance scores, sorted by relevance
    """
    if not q.strip():
        # Empty query returns all reminders
        stmt = select(Reminder).order_by(Reminder.created_at.desc())
        stmt = LimitOffset(limit=limit, offset=offset).apply(stmt)
        result = await session.execute(stmt)
        reminders = result.scalars().all()
        return [
            ReminderSearchResult(
                **ReminderResponse.model_validate(r).model_dump(),
                relevance=0.0,
            )
            for r in reminders
        ]

    # Build the search filter based on mode
    stmt = select(Reminder)

    if mode == "web":
        # Web-style search with operators: "phrase", -exclude, OR
        search_filter = WebSearchFilter(
            Reminder.search_vector,
            q,
            config="english",
            rank_order=True,
        )
        stmt = search_filter.apply(stmt)
        # Add rank column for relevance score
        # Note: WebSearchFilter doesn't have with_rank_column, so we add it manually
        ts_query = func.websearch_to_tsquery("english", q)
        stmt = stmt.add_columns(
            func.ts_rank(Reminder.search_vector, ts_query).label("search_rank")
        )
    else:
        # Plain text search with optional prefix matching
        search_filter = FullTextSearchFilter(
            Reminder.search_vector,
            q,
            config="english",
            rank_order=True,
            prefix_match=prefix,
        )
        stmt = search_filter.apply(stmt)
        stmt = search_filter.with_rank_column(stmt, "search_rank")

    # Apply pagination
    stmt = LimitOffset(limit=limit, offset=offset).apply(stmt)

    result = await session.execute(stmt)
    rows = result.all()

    # Build response with relevance scores
    search_results = []
    for row in rows:
        reminder = row[0]  # First element is the Reminder object
        rank = row.search_rank if hasattr(row, "search_rank") else 0.0
        search_results.append(
            ReminderSearchResult(
                **ReminderResponse.model_validate(reminder).model_dump(),
                relevance=float(rank),
            )
        )

    # Log search metrics
    lazy_logger.debug(
        lambda: f"endpoint.fulltext_search: q={q!r}, mode={mode}, prefix={prefix} -> {len(search_results)} results"
    )

    if q and len(search_results) == 0:
        logger.info(
            "Full-text search returned no results",
            extra={
                "query": q[:100],
                "mode": mode,
                "prefix_match": prefix,
                "operation": "endpoint.fulltext_search",
            },
        )

    return search_results


@router.get(
    "/overdue",
    response_model=list[ReminderResponse],
    summary="Get overdue reminders",
    description="Return reminders that are past their remind_at date and not completed.",
)
async def get_overdue_reminders(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[ReminderResponse]:
    """Get overdue reminders that haven't been completed."""
    now = datetime.now(UTC)
    stmt = (
        select(Reminder)
        .where(
            Reminder.is_completed == False,  # noqa: E712
            Reminder.remind_at.is_not(None),
            Reminder.remind_at < now,
        )
        .order_by(Reminder.remind_at.asc())
    )

    result = await session.execute(stmt)
    reminders = result.scalars().all()

    # INFO - actionable condition (overdue reminders need attention)
    if reminders:
        logger.info(
            "Overdue reminders retrieved",
            extra={"count": len(reminders), "operation": "endpoint.get_overdue_reminders"},
        )

    return [ReminderResponse.model_validate(reminder) for reminder in reminders]


@router.get(
    "/{reminder_id}",
    response_model=ReminderResponse,
    summary="Get a reminder",
    description="Fetch a reminder by its identifier.",
    responses={404: {"description": "Reminder not found"}},
)
async def get_reminder(
    reminder_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ReminderResponse:
    """Get a single reminder by ID."""
    result = await session.execute(
        select(Reminder).where(Reminder.id == reminder_id)
    )
    reminder = result.scalar_one_or_none()

    if reminder is None:
        raise NotFoundError("Reminder", {"id": reminder_id})

    return ReminderResponse.model_validate(reminder)


@router.post(
    "/",
    response_model=ReminderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a reminder",
    description="""
Create a new reminder, optionally with recurrence.

**Recurrence options:**

1. **Structured recurrence** - Use the `recurrence` object:
```json
{
  "title": "Weekly standup",
  "remind_at": "2025-01-01T09:00:00Z",
  "recurrence": {
    "frequency": "WEEKLY",
    "weekdays": ["MO", "WE", "FR"]
  }
}
```

2. **Raw RRULE** - Use `recurrence_rule` string:
```json
{
  "title": "Daily reminder",
  "remind_at": "2025-01-01T09:00:00Z",
  "recurrence_rule": "FREQ=DAILY;INTERVAL=1"
}
```

Supported frequencies: DAILY, WEEKLY, MONTHLY, YEARLY
""",
)
async def create_reminder(
    payload: ReminderCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    publisher: Annotated[EventPublisherDep, Depends()],
) -> ReminderResponse:
    """Create a new reminder with optional recurrence."""
    # Track business metrics
    track_feature_usage("reminders", is_authenticated=False)
    track_user_action("create", is_authenticated=False)

    # Determine the RRULE string (structured recurrence takes priority)
    recurrence_rule = None
    if payload.recurrence:
        recurrence_rule = payload.recurrence.to_rrule_string()
    elif payload.recurrence_rule:
        recurrence_rule = payload.recurrence_rule

    reminder = Reminder(
        title=payload.title,
        description=payload.description,
        remind_at=payload.remind_at,
        recurrence_rule=recurrence_rule,
        recurrence_end_at=payload.recurrence_end_at,
    )

    session.add(reminder)

    # Publish domain event (staged in outbox, committed with reminder)
    await publisher.publish(
        ReminderCreatedEvent(
            reminder_id=str(reminder.id),
            title=reminder.title,
            description=reminder.description,
            remind_at=reminder.remind_at,
        )
    )

    await session.commit()
    await session.refresh(reminder)

    return ReminderResponse.from_model(reminder)


@router.patch(
    "/{reminder_id}",
    response_model=ReminderResponse,
    summary="Update a reminder",
    description="Update an existing reminder. Only provided fields will be updated.",
    responses={404: {"description": "Reminder not found"}},
)
async def update_reminder(
    reminder_id: UUID,
    payload: ReminderUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    publisher: Annotated[EventPublisherDep, Depends()],
) -> ReminderResponse:
    """Update an existing reminder."""
    result = await session.execute(
        select(Reminder).where(Reminder.id == reminder_id)
    )
    reminder = result.scalar_one_or_none()

    if reminder is None:
        raise NotFoundError("Reminder", {"id": reminder_id})

    # Track business metrics
    track_user_action("update", is_authenticated=False)

    # Track changes for event
    changes: dict[str, object] = {}

    # Update only provided fields
    if payload.title is not None and reminder.title != payload.title:
        changes["title"] = payload.title
        reminder.title = payload.title

    if payload.description is not None and reminder.description != payload.description:
        changes["description"] = payload.description
        reminder.description = payload.description

    if payload.remind_at is not None and reminder.remind_at != payload.remind_at:
        changes["remind_at"] = payload.remind_at.isoformat() if payload.remind_at else None
        reminder.remind_at = payload.remind_at

    # Handle recurrence updates
    if payload.recurrence is not None:
        new_rule = payload.recurrence.to_rrule_string()
        if reminder.recurrence_rule != new_rule:
            changes["recurrence_rule"] = new_rule
            reminder.recurrence_rule = new_rule

    elif payload.recurrence_rule is not None:
        if reminder.recurrence_rule != payload.recurrence_rule:
            changes["recurrence_rule"] = payload.recurrence_rule
            reminder.recurrence_rule = payload.recurrence_rule

    if payload.recurrence_end_at is not None and reminder.recurrence_end_at != payload.recurrence_end_at:
        changes["recurrence_end_at"] = (
            payload.recurrence_end_at.isoformat() if payload.recurrence_end_at else None
        )
        reminder.recurrence_end_at = payload.recurrence_end_at

    # Publish domain event if there were changes
    if changes:
        await publisher.publish(
            ReminderUpdatedEvent(
                reminder_id=str(reminder_id),
                changes=changes,
            )
        )

    await session.commit()
    await session.refresh(reminder)

    return ReminderResponse.from_model(reminder)


@router.post(
    "/{reminder_id}/complete",
    response_model=ReminderResponse,
    summary="Mark reminder as completed",
    description="Mark a reminder as completed.",
    responses={404: {"description": "Reminder not found"}},
)
async def complete_reminder(
    reminder_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    publisher: Annotated[EventPublisherDep, Depends()],
) -> ReminderResponse:
    """Mark a reminder as completed."""
    result = await session.execute(
        select(Reminder).where(Reminder.id == reminder_id)
    )
    reminder = result.scalar_one_or_none()

    if reminder is None:
        raise NotFoundError("Reminder", {"id": reminder_id})

    # Track business metrics (completion is a significant action)
    track_user_action("complete", is_authenticated=False)

    reminder.is_completed = True

    # Publish domain event
    await publisher.publish(
        ReminderCompletedEvent(
            reminder_id=str(reminder_id),
            title=reminder.title,
        )
    )

    await session.commit()
    await session.refresh(reminder)

    return ReminderResponse.model_validate(reminder)


@router.delete(
    "/{reminder_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a reminder",
    description="Permanently delete a reminder.",
    responses={404: {"description": "Reminder not found"}},
)
async def delete_reminder(
    reminder_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    publisher: Annotated[EventPublisherDep, Depends()],
) -> None:
    """Delete a reminder permanently."""
    result = await session.execute(
        select(Reminder).where(Reminder.id == reminder_id)
    )
    reminder = result.scalar_one_or_none()

    if reminder is None:
        raise NotFoundError("Reminder", {"id": reminder_id})

    # Track business metrics
    track_user_action("delete", is_authenticated=False)

    # Publish domain event before deletion
    await publisher.publish(
        ReminderDeletedEvent(reminder_id=str(reminder_id))
    )

    await session.delete(reminder)
    await session.commit()

    # INFO - permanent data removal (audit trail)
    logger.info(
        "Reminder deleted",
        extra={"reminder_id": str(reminder_id), "operation": "endpoint.delete_reminder"},
    )


# ──────────────────────────────────────────────────────────────
# Recurrence Endpoints
# ──────────────────────────────────────────────────────────────


@router.get(
    "/{reminder_id}/occurrences",
    response_model=OccurrencesResponse,
    summary="Get occurrences for a recurring reminder",
    description="""
Get the upcoming occurrences for a recurring reminder.

Returns a list of dates when the reminder will occur, taking into account:
- The recurrence rule (RRULE)
- Any occurrence that has been "broken out" and modified individually
- The recurrence end date if specified

Use query parameters to control the date range and number of occurrences.
""",
    responses={
        404: {"description": "Reminder not found"},
        400: {"description": "Reminder is not recurring"},
    },
)
async def get_occurrences(
    reminder_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    after: datetime | None = None,
    before: datetime | None = None,
    limit: int = 50,
) -> OccurrencesResponse:
    """Get upcoming occurrences for a recurring reminder.

    Args:
        reminder_id: ID of the recurring reminder
        after: Only show occurrences after this date (default: now)
        before: Only show occurrences before this date
        limit: Maximum number of occurrences to return (1-100)

    Returns:
        List of occurrence dates with modification status
    """
    result = await session.execute(
        select(Reminder).where(Reminder.id == reminder_id)
    )
    reminder = result.scalar_one_or_none()

    if reminder is None:
        raise NotFoundError("Reminder", {"id": reminder_id})

    if not reminder.recurrence_rule:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail="Reminder is not recurring",
        )

    # Default to now if no after date specified
    if after is None:
        after = datetime.now(UTC)

    # Use recurrence end date if no before date specified
    if before is None and reminder.recurrence_end_at:
        before = reminder.recurrence_end_at

    # Get broken-out occurrences (children of this reminder)
    broken_out_result = await session.execute(
        select(Reminder)
        .where(Reminder.parent_id == reminder_id)
        .where(Reminder.occurrence_date.is_not(None))
    )
    broken_out = {r.occurrence_date: r for r in broken_out_result.scalars().all()}

    # Generate occurrences
    from example_service.features.reminders.recurrence import describe_rrule

    start = reminder.remind_at or reminder.created_at
    limit = min(limit, 100)

    occurrences = []
    for dt in generate_occurrences(
        reminder.recurrence_rule,
        start,
        after=after,
        before=before,
        count=limit,
    ):
        # Check if this occurrence was broken out
        broken = broken_out.get(dt)
        occurrences.append(
            OccurrenceResponse(
                date=dt,
                is_modified=broken is not None,
                reminder_id=broken.id if broken else None,
            )
        )

    return OccurrencesResponse(
        reminder_id=reminder_id,
        rule=reminder.recurrence_rule,
        description=describe_rrule(reminder.recurrence_rule),
        occurrences=occurrences,
        total_count=None,  # Unbounded recurrences don't have a total
    )


@router.post(
    "/{reminder_id}/occurrences/break-out",
    response_model=ReminderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Break out a single occurrence",
    description="""
Create an independent reminder from a specific occurrence in a recurring series.

This allows you to modify a single occurrence without affecting the rest of
the series. The new reminder will:
- Inherit title, description from the parent
- Have the specified occurrence date as remind_at
- Be linked to the parent via parent_id
- Not have its own recurrence rule

Common use cases:
- Rescheduling a single meeting
- Canceling one occurrence (by completing/deleting the broken-out reminder)
- Adding notes to a specific occurrence
""",
    responses={
        404: {"description": "Reminder not found"},
        400: {"description": "Reminder is not recurring or occurrence already exists"},
    },
)
async def break_out_occurrence(
    reminder_id: UUID,
    occurrence_date: datetime,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    publisher: Annotated[EventPublisherDep, Depends()],
) -> ReminderResponse:
    """Break out a single occurrence from a recurring series.

    Args:
        reminder_id: ID of the recurring reminder
        occurrence_date: The specific occurrence date to break out

    Returns:
        The new independent reminder
    """
    result = await session.execute(
        select(Reminder).where(Reminder.id == reminder_id)
    )
    reminder = result.scalar_one_or_none()

    if reminder is None:
        raise NotFoundError("Reminder", {"id": reminder_id})

    if not reminder.recurrence_rule:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail="Reminder is not recurring",
        )

    # Check if occurrence already broken out
    existing = await session.execute(
        select(Reminder)
        .where(Reminder.parent_id == reminder_id)
        .where(Reminder.occurrence_date == occurrence_date)
    )
    if existing.scalar_one_or_none():
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail="This occurrence has already been broken out",
        )

    # Create the broken-out occurrence
    broken_out = Reminder(
        title=reminder.title,
        description=reminder.description,
        remind_at=occurrence_date,
        parent_id=reminder_id,
        occurrence_date=occurrence_date,
    )

    session.add(broken_out)

    # Publish event
    await publisher.publish(
        ReminderCreatedEvent(
            reminder_id=str(broken_out.id),
            title=broken_out.title,
            description=broken_out.description,
            remind_at=broken_out.remind_at,
        )
    )

    await session.commit()
    await session.refresh(broken_out)

    logger.info(
        "Occurrence broken out from recurring reminder",
        extra={
            "parent_id": str(reminder_id),
            "occurrence_id": str(broken_out.id),
            "occurrence_date": occurrence_date.isoformat(),
            "operation": "endpoint.break_out_occurrence",
        },
    )

    return ReminderResponse.from_model(broken_out)


@router.get(
    "/{reminder_id}/next",
    response_model=OccurrenceResponse | None,
    summary="Get next occurrence",
    description="Get the next upcoming occurrence for a recurring reminder.",
    responses={
        404: {"description": "Reminder not found"},
        400: {"description": "Reminder is not recurring"},
    },
)
async def get_next_reminder_occurrence(
    reminder_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    after: datetime | None = None,
) -> OccurrenceResponse | None:
    """Get the next occurrence for a recurring reminder.

    Args:
        reminder_id: ID of the recurring reminder
        after: Find next occurrence after this date (default: now)

    Returns:
        The next occurrence, or null if no more occurrences
    """
    result = await session.execute(
        select(Reminder).where(Reminder.id == reminder_id)
    )
    reminder = result.scalar_one_or_none()

    if reminder is None:
        raise NotFoundError("Reminder", {"id": reminder_id})

    if not reminder.recurrence_rule:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail="Reminder is not recurring",
        )

    # Default to now
    if after is None:
        after = datetime.now(UTC)

    start = reminder.remind_at or reminder.created_at
    next_dt = get_next_occurrence(reminder.recurrence_rule, start, after)

    if next_dt is None:
        return None

    # Check if already broken out
    existing = await session.execute(
        select(Reminder)
        .where(Reminder.parent_id == reminder_id)
        .where(Reminder.occurrence_date == next_dt)
    )
    broken = existing.scalar_one_or_none()

    return OccurrenceResponse(
        date=next_dt,
        is_modified=broken is not None,
        reminder_id=broken.id if broken else None,
    )
