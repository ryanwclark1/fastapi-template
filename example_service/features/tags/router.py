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
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from example_service.core.database import NotFoundError
from example_service.core.dependencies.database import get_db_session
from example_service.features.reminders.models import Reminder
from example_service.features.reminders.schemas import ReminderResponse
from example_service.features.tags.models import reminder_tags
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
from example_service.features.tags.service import TagService

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
    service = TagService(session)
    tags, counts = await service.list_tags(search=search, include_counts=include_counts)

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
    service = TagService(session)
    tag, count = await service.get_tag_with_count(tag_id)

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
    service = TagService(session)
    tag = await service.create_tag(payload)
    await session.commit()

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
    service = TagService(session)
    tag = await service.update_tag(tag_id, payload)
    await session.commit()

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
    service = TagService(session)
    await service.delete_tag(tag_id)
    await session.commit()


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
    # Verify tag exists using service
    service = TagService(session)
    await service.get_tag(tag_id)

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
        msg = "Reminder"
        raise NotFoundError(msg, {"id": str(reminder_id)})

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
        msg = "Reminder"
        raise NotFoundError(msg, {"id": str(reminder_id)})

    # Fetch and validate tags using service
    tag_service = TagService(session)
    if payload.tag_ids:
        tags = list(await tag_service.get_tags_by_ids(payload.tag_ids, raise_if_missing=True))
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
        msg = "Reminder"
        raise NotFoundError(msg, {"id": str(reminder_id)})

    # Fetch and validate tags using service
    tag_service = TagService(session)
    new_tags = await tag_service.get_tags_by_ids(payload.tag_ids, raise_if_missing=True)

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
        msg = "Reminder"
        raise NotFoundError(msg, {"id": str(reminder_id)})

    # Remove specified tags
    remove_ids = set(payload.tag_ids)
    reminder.tags = [tag for tag in reminder.tags if tag.id not in remove_ids]

    await session.commit()
    await session.refresh(reminder)

    return [TagResponse.model_validate(tag) for tag in reminder.tags]
