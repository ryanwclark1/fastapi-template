"""API router for the reminders feature."""
from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from example_service.core.database import (
    BeforeAfter,
    LimitOffset,
    NotFoundError,
    OrderBy,
    SearchFilter,
)
from example_service.core.dependencies.database import get_db_session
from example_service.features.reminders.models import Reminder
from example_service.features.reminders.schemas import ReminderCreate, ReminderResponse
from example_service.infra.logging import get_lazy_logger

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
    session: AsyncSession = Depends(get_db_session),
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
    "/search",
    response_model=list[ReminderResponse],
    summary="Search reminders",
    description="Search reminders by title/description with filtering and pagination.",
)
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
    "/overdue",
    response_model=list[ReminderResponse],
    summary="Get overdue reminders",
    description="Return reminders that are past their remind_at date and not completed.",
)
async def get_overdue_reminders(
    session: AsyncSession = Depends(get_db_session),
) -> list[ReminderResponse]:
    """Get overdue reminders that haven't been completed."""
    now = datetime.utcnow()
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
    session: AsyncSession = Depends(get_db_session),
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
    description="Create a new reminder entry.",
)
async def create_reminder(
    payload: ReminderCreate,
    session: AsyncSession = Depends(get_db_session),
) -> ReminderResponse:
    """Create a new reminder."""
    reminder = Reminder(
        title=payload.title,
        description=payload.description,
        remind_at=payload.remind_at,
    )

    session.add(reminder)
    await session.commit()
    await session.refresh(reminder)

    return ReminderResponse.model_validate(reminder)


@router.patch(
    "/{reminder_id}",
    response_model=ReminderResponse,
    summary="Update a reminder",
    description="Update an existing reminder.",
    responses={404: {"description": "Reminder not found"}},
)
async def update_reminder(
    reminder_id: UUID,
    payload: ReminderCreate,
    session: AsyncSession = Depends(get_db_session),
) -> ReminderResponse:
    """Update an existing reminder."""
    result = await session.execute(
        select(Reminder).where(Reminder.id == reminder_id)
    )
    reminder = result.scalar_one_or_none()

    if reminder is None:
        raise NotFoundError("Reminder", {"id": reminder_id})

    # Update fields
    reminder.title = payload.title
    reminder.description = payload.description
    reminder.remind_at = payload.remind_at

    await session.commit()
    await session.refresh(reminder)

    return ReminderResponse.model_validate(reminder)


@router.post(
    "/{reminder_id}/complete",
    response_model=ReminderResponse,
    summary="Mark reminder as completed",
    description="Mark a reminder as completed.",
    responses={404: {"description": "Reminder not found"}},
)
async def complete_reminder(
    reminder_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> ReminderResponse:
    """Mark a reminder as completed."""
    result = await session.execute(
        select(Reminder).where(Reminder.id == reminder_id)
    )
    reminder = result.scalar_one_or_none()

    if reminder is None:
        raise NotFoundError("Reminder", {"id": reminder_id})

    reminder.is_completed = True

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
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """Delete a reminder permanently."""
    result = await session.execute(
        select(Reminder).where(Reminder.id == reminder_id)
    )
    reminder = result.scalar_one_or_none()

    if reminder is None:
        raise NotFoundError("Reminder", {"id": reminder_id})

    await session.delete(reminder)
    await session.commit()

    # INFO - permanent data removal (audit trail)
    logger.info(
        "Reminder deleted",
        extra={"reminder_id": str(reminder_id), "operation": "endpoint.delete_reminder"},
    )
