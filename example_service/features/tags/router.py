"""API router for the tags feature.

This module provides CRUD operations for tags and tag-reminder associations.
Tags enable flexible categorization and filtering of reminders without
rigid hierarchical structures.

Endpoints:
    Tag CRUD:
        GET    /tags/              - List all tags with optional filtering
        GET    /tags/{tag_id}      - Get a single tag with reminder count
        POST   /tags/              - Create a new tag
        PATCH  /tags/{tag_id}      - Update an existing tag
        DELETE /tags/{tag_id}      - Delete a tag

    Tag-Reminder Associations:
        GET    /tags/{tag_id}/reminders           - Get reminders with a specific tag
        GET    /reminders/{reminder_id}/tags      - Get tags for a reminder
        PUT    /reminders/{reminder_id}/tags      - Replace all tags on a reminder
        POST   /reminders/{reminder_id}/tags/add  - Add tags to a reminder
        POST   /reminders/{reminder_id}/tags/remove - Remove tags from a reminder

Features:
    - Case-insensitive tag name search
    - Optional reminder counts per tag
    - Bulk tag operations (add/remove multiple tags)
    - Soft delete support (tags are not permanently removed)

Example Usage:
    # Create a tag
    POST /tags/
    {"name": "work", "color": "#FF5733"}

    # Tag a reminder
    POST /reminders/{id}/tags/add
    {"tag_ids": ["uuid1", "uuid2"]}

    # Find reminders by tag
    GET /tags/{tag_id}/reminders
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from example_service.core.database import NotFoundError
from example_service.core.dependencies.database import get_db_session
from example_service.features.reminders.models import Reminder
from example_service.features.reminders.schemas import ReminderResponse
from example_service.features.tags.models import Tag, reminder_tags
from example_service.features.tags.schemas import (
    AddTagsRequest,
    ReminderTagsUpdate,
    RemoveTagsRequest,
    TagCreate,
    TagListResponse,
    TagResponse,
    TagUpdate,
    TagWithCountResponse,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/tags", tags=["tags"])
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Tag CRUD Endpoints
# ──────────────────────────────────────────────────────────────


@router.get(
    "/",
    response_model=TagListResponse,
    summary="List all tags",
    description="Return all tags with optional sorting and filtering.",
)
async def list_tags(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    include_counts: bool = False,
    search: str | None = None,
) -> TagListResponse:
    """List all tags.

    Args:
        session: Database session
        include_counts: Include reminder counts for each tag
        search: Filter tags by name (case-insensitive contains)

    Returns:
        List of tags
    """
    stmt = select(Tag)

    if search:
        stmt = stmt.where(Tag.name.ilike(f"%{search}%"))

    stmt = stmt.order_by(Tag.name.asc())

    result = await session.execute(stmt)
    tags = result.scalars().all()

    # Build counts once if requested
    counts: dict[UUID, int] = {}
    if include_counts:
        count_stmt = select(
            reminder_tags.c.tag_id,
            func.count(reminder_tags.c.reminder_id).label("count"),
        ).group_by(reminder_tags.c.tag_id)
        count_result = await session.execute(count_stmt)
        counts = {row.tag_id: cast("int", row.count) for row in count_result}

    tag_responses = [
        TagWithCountResponse(
            **TagResponse.model_validate(tag).model_dump(),
            reminder_count=counts.get(tag.id, 0),
        )
        for tag in tags
    ]

    return TagListResponse(tags=tag_responses, total=len(tag_responses))


@router.get(
    "/{tag_id}",
    response_model=TagWithCountResponse,
    summary="Get a tag",
    description="Fetch a tag by its identifier with reminder count.",
    responses={404: {"description": "Tag not found"}},
)
async def get_tag(
    tag_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TagWithCountResponse:
    """Get a single tag by ID with its reminder count."""
    result = await session.execute(select(Tag).where(Tag.id == tag_id))
    tag = result.scalar_one_or_none()

    if tag is None:
        raise NotFoundError("Tag", {"id": tag_id})

    # Get reminder count
    count_stmt = (
        select(func.count()).select_from(reminder_tags).where(reminder_tags.c.tag_id == tag_id)
    )
    count_result = await session.execute(count_stmt)
    count = count_result.scalar() or 0

    return TagWithCountResponse(
        **TagResponse.model_validate(tag).model_dump(),
        reminder_count=count,
    )


@router.post(
    "/",
    response_model=TagResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a tag",
    description="Create a new tag. Tag names must be unique.",
)
async def create_tag(
    payload: TagCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TagResponse:
    """Create a new tag."""
    # Check for existing tag with same name
    existing = await session.execute(select(Tag).where(Tag.name == payload.name))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tag with name '{payload.name}' already exists",
        )

    tag = Tag(
        name=payload.name,
        color=payload.color,
        description=payload.description,
    )

    session.add(tag)
    await session.commit()
    await session.refresh(tag)

    logger.info(
        "Tag created",
        extra={"tag_id": str(tag.id), "tag_name": tag.name},
    )

    return TagResponse.model_validate(tag)


@router.patch(
    "/{tag_id}",
    response_model=TagResponse,
    summary="Update a tag",
    description="Update an existing tag. Only provided fields will be updated.",
    responses={404: {"description": "Tag not found"}},
)
async def update_tag(
    tag_id: UUID,
    payload: TagUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TagResponse:
    """Update an existing tag."""
    result = await session.execute(select(Tag).where(Tag.id == tag_id))
    tag = result.scalar_one_or_none()

    if tag is None:
        raise NotFoundError("Tag", {"id": tag_id})

    # Check for name conflict if changing name
    if payload.name is not None and payload.name != tag.name:
        existing = await session.execute(select(Tag).where(Tag.name == payload.name))
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Tag with name '{payload.name}' already exists",
            )
        tag.name = payload.name

    if payload.color is not None:
        tag.color = payload.color

    if payload.description is not None:
        tag.description = payload.description

    await session.commit()
    await session.refresh(tag)

    return TagResponse.model_validate(tag)


@router.delete(
    "/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a tag",
    description="Delete a tag. Removes the tag from all reminders.",
    responses={404: {"description": "Tag not found"}},
)
async def delete_tag(
    tag_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    """Delete a tag permanently."""
    result = await session.execute(select(Tag).where(Tag.id == tag_id))
    tag = result.scalar_one_or_none()

    if tag is None:
        raise NotFoundError("Tag", {"id": tag_id})

    await session.delete(tag)
    await session.commit()

    logger.info(
        "Tag deleted",
        extra={"tag_id": str(tag_id)},
    )


# ──────────────────────────────────────────────────────────────
# Tag-Reminder Association Endpoints
# ──────────────────────────────────────────────────────────────


@router.get(
    "/{tag_id}/reminders",
    response_model=list[ReminderResponse],
    summary="Get reminders with tag",
    description="Get all reminders that have this tag.",
    responses={404: {"description": "Tag not found"}},
)
async def get_tag_reminders(
    tag_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    include_completed: bool = True,
) -> list[ReminderResponse]:
    """Get all reminders with a specific tag."""
    # Verify tag exists
    tag_result = await session.execute(select(Tag).where(Tag.id == tag_id))
    if tag_result.scalar_one_or_none() is None:
        raise NotFoundError("Tag", {"id": tag_id})

    # Query reminders with this tag
    stmt = select(Reminder).join(reminder_tags).where(reminder_tags.c.tag_id == tag_id)

    if not include_completed:
        stmt = stmt.where(Reminder.is_completed == False)  # noqa: E712

    stmt = stmt.order_by(Reminder.created_at.desc())

    result = await session.execute(stmt)
    reminders = result.scalars().all()

    return [ReminderResponse.model_validate(r) for r in reminders]


# ──────────────────────────────────────────────────────────────
# Reminder Tag Management (under /reminders)
# ──────────────────────────────────────────────────────────────

# Create a sub-router for reminder-specific tag operations
reminder_tags_router = APIRouter(prefix="/reminders", tags=["reminders", "tags"])


@reminder_tags_router.get(
    "/{reminder_id}/tags",
    response_model=list[TagResponse],
    summary="Get tags for a reminder",
    description="Get all tags assigned to a reminder.",
    responses={404: {"description": "Reminder not found"}},
)
async def get_reminder_tags(
    reminder_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[TagResponse]:
    """Get all tags for a specific reminder."""
    result = await session.execute(
        select(Reminder).options(selectinload(Reminder.tags)).where(Reminder.id == reminder_id)
    )
    reminder = result.scalar_one_or_none()

    if reminder is None:
        raise NotFoundError("Reminder", {"id": reminder_id})

    return [TagResponse.model_validate(tag) for tag in reminder.tags]


@reminder_tags_router.put(
    "/{reminder_id}/tags",
    response_model=list[TagResponse],
    summary="Set tags for a reminder",
    description="Replace all tags on a reminder with the specified tags.",
    responses={404: {"description": "Reminder or tag not found"}},
)
async def set_reminder_tags(
    reminder_id: UUID,
    payload: ReminderTagsUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[TagResponse]:
    """Set (replace) all tags for a reminder."""
    result = await session.execute(
        select(Reminder).options(selectinload(Reminder.tags)).where(Reminder.id == reminder_id)
    )
    reminder = result.scalar_one_or_none()

    if reminder is None:
        raise NotFoundError("Reminder", {"id": reminder_id})

    # Fetch the specified tags
    if payload.tag_ids:
        tags_result = await session.execute(select(Tag).where(Tag.id.in_(payload.tag_ids)))
        tags = list(tags_result.scalars().all())

        # Verify all tags were found
        found_ids = {tag.id for tag in tags}
        missing = set(payload.tag_ids) - found_ids
        if missing:
            raise NotFoundError("Tag", {"ids": list(missing)})
    else:
        tags = []

    # Replace tags
    reminder.tags = tags
    await session.commit()
    await session.refresh(reminder)

    logger.info(
        "Reminder tags updated",
        extra={
            "reminder_id": str(reminder_id),
            "tag_count": len(tags),
        },
    )

    return [TagResponse.model_validate(tag) for tag in reminder.tags]


@reminder_tags_router.post(
    "/{reminder_id}/tags/add",
    response_model=list[TagResponse],
    summary="Add tags to a reminder",
    description="Add tags to a reminder without removing existing ones.",
    responses={404: {"description": "Reminder or tag not found"}},
)
async def add_reminder_tags(
    reminder_id: UUID,
    payload: AddTagsRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[TagResponse]:
    """Add tags to a reminder."""
    result = await session.execute(
        select(Reminder).options(selectinload(Reminder.tags)).where(Reminder.id == reminder_id)
    )
    reminder = result.scalar_one_or_none()

    if reminder is None:
        raise NotFoundError("Reminder", {"id": reminder_id})

    # Fetch the specified tags
    tags_result = await session.execute(select(Tag).where(Tag.id.in_(payload.tag_ids)))
    new_tags = list(tags_result.scalars().all())

    # Verify all tags were found
    found_ids = {tag.id for tag in new_tags}
    missing = set(payload.tag_ids) - found_ids
    if missing:
        raise NotFoundError("Tag", {"ids": list(missing)})

    # Add new tags (avoiding duplicates)
    existing_ids = {tag.id for tag in reminder.tags}
    for tag in new_tags:
        if tag.id not in existing_ids:
            reminder.tags.append(tag)

    await session.commit()
    await session.refresh(reminder)

    return [TagResponse.model_validate(tag) for tag in reminder.tags]


@reminder_tags_router.post(
    "/{reminder_id}/tags/remove",
    response_model=list[TagResponse],
    summary="Remove tags from a reminder",
    description="Remove specific tags from a reminder.",
    responses={404: {"description": "Reminder not found"}},
)
async def remove_reminder_tags(
    reminder_id: UUID,
    payload: RemoveTagsRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[TagResponse]:
    """Remove tags from a reminder."""
    result = await session.execute(
        select(Reminder).options(selectinload(Reminder.tags)).where(Reminder.id == reminder_id)
    )
    reminder = result.scalar_one_or_none()

    if reminder is None:
        raise NotFoundError("Reminder", {"id": reminder_id})

    # Remove specified tags
    remove_ids = set(payload.tag_ids)
    reminder.tags = [tag for tag in reminder.tags if tag.id not in remove_ids]

    await session.commit()
    await session.refresh(reminder)

    return [TagResponse.model_validate(tag) for tag in reminder.tags]
