"""Mutation resolvers for tags.

Provides write operations for tags:
- createTag: Create a new tag
- updateTag: Update an existing tag
- deleteTag: Delete a tag
- addTagsToReminder: Add tags to a reminder
- removeTagsFromReminder: Remove tags from a reminder
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

import strawberry
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from example_service.features.graphql.events import (
    publish_tag_event,
    serialize_model_for_event,
)
from example_service.features.graphql.types.tags import (
    CreateTagInput,
    DeletePayload,
    TagError,
    TagErrorCode,
    TagPayload,
    TagSuccess,
    TagType,
    UpdateTagInput,
)
from example_service.features.reminders.models import Reminder
from example_service.features.tags.models import Tag
from example_service.features.tags.schemas import TagResponse

if TYPE_CHECKING:
    from strawberry.types import Info

    from example_service.features.graphql.context import GraphQLContext

logger = logging.getLogger(__name__)


async def create_tag_mutation(
    info: Info[GraphQLContext, None],
    input: CreateTagInput,
) -> TagPayload:
    """Create a new tag.

    Args:
        info: Strawberry info with context
        input: Tag creation data

    Returns:
        TagSuccess with the created tag, or TagError
    """
    ctx = info.context

    # Convert GraphQL input to Pydantic for validation
    try:
        create_data = input.to_pydantic()
    except Exception as e:
        return TagError(
            code=TagErrorCode.VALIDATION_ERROR,
            message=f"Invalid input: {e!s}",
            field="input",
        )

    # Validation
    if not create_data.name or not create_data.name.strip():
        return TagError(
            code=TagErrorCode.VALIDATION_ERROR,
            message="Tag name is required",
            field="name",
        )

    if len(create_data.name) > 50:
        return TagError(
            code=TagErrorCode.VALIDATION_ERROR,
            message="Tag name must be 50 characters or less",
            field="name",
        )

    try:
        # Create tag from Pydantic data
        tag = Tag(
            name=create_data.name.strip().lower(),
            color=create_data.color,
            description=create_data.description.strip() if create_data.description else None,
        )
        ctx.session.add(tag)
        await ctx.session.commit()
        await ctx.session.refresh(tag)

        logger.info(f"Created tag: {tag.id} ({tag.name})")

        # Publish event for real-time subscriptions
        await publish_tag_event(
            event_type="CREATED",
            tag_data=serialize_model_for_event(tag),
        )

        # Convert: SQLAlchemy → Pydantic → GraphQL
        tag_pydantic = TagResponse.from_model(tag)
        return TagSuccess(tag=TagType.from_pydantic(tag_pydantic))

    except IntegrityError as e:
        await ctx.session.rollback()
        if "uq_tags_name" in str(e):
            return TagError(
                code=TagErrorCode.DUPLICATE_NAME,
                message=f"Tag with name '{create_data.name}' already exists",
                field="name",
            )
        logger.exception(f"Error creating tag: {e}")
        return TagError(
            code=TagErrorCode.INTERNAL_ERROR,
            message="Failed to create tag",
        )
    except Exception as e:
        logger.exception(f"Error creating tag: {e}")
        await ctx.session.rollback()
        return TagError(
            code=TagErrorCode.INTERNAL_ERROR,
            message="Failed to create tag",
        )


async def update_tag_mutation(
    info: Info[GraphQLContext, None],
    id: strawberry.ID,
    input: UpdateTagInput,
) -> TagPayload:
    """Update an existing tag.

    Args:
        info: Strawberry info with context
        id: Tag UUID
        input: Fields to update

    Returns:
        TagSuccess with the updated tag, or TagError
    """
    ctx = info.context
    from example_service.features.tags.repository import get_tag_repository

    repo = get_tag_repository()

    try:
        tag_uuid = UUID(str(id))
    except ValueError:
        return TagError(
            code=TagErrorCode.VALIDATION_ERROR,
            message="Invalid tag ID format",
            field="id",
        )

    # Convert GraphQL input to Pydantic
    try:
        update_data = input.to_pydantic()
    except Exception as e:
        return TagError(
            code=TagErrorCode.VALIDATION_ERROR,
            message=f"Invalid input: {e!s}",
            field="input",
        )

    try:
        tag = await repo.get(ctx.session, tag_uuid)
        if tag is None:
            return TagError(
                code=TagErrorCode.NOT_FOUND,
                message=f"Tag with ID {id} not found",
            )

        # Update fields
        if update_data.name is not None:
            if not update_data.name.strip():
                return TagError(
                    code=TagErrorCode.VALIDATION_ERROR,
                    message="Tag name cannot be empty",
                    field="name",
                )
            if len(update_data.name) > 50:
                return TagError(
                    code=TagErrorCode.VALIDATION_ERROR,
                    message="Tag name must be 50 characters or less",
                    field="name",
                )
            tag.name = update_data.name.strip().lower()

        if update_data.color is not None:
            tag.color = update_data.color

        if update_data.description is not None:
            tag.description = update_data.description.strip() if update_data.description else None

        await ctx.session.commit()
        await ctx.session.refresh(tag)

        logger.info(f"Updated tag: {tag.id} ({tag.name})")

        # Publish event for real-time subscriptions
        await publish_tag_event(
            event_type="UPDATED",
            tag_data=serialize_model_for_event(tag),
        )

        # Convert: SQLAlchemy → Pydantic → GraphQL
        tag_pydantic = TagResponse.from_model(tag)
        return TagSuccess(tag=TagType.from_pydantic(tag_pydantic))

    except IntegrityError as e:
        await ctx.session.rollback()
        if "uq_tags_name" in str(e):
            return TagError(
                code=TagErrorCode.DUPLICATE_NAME,
                message=f"Tag with name '{update_data.name}' already exists",
                field="name",
            )
        logger.exception(f"Error updating tag: {e}")
        return TagError(
            code=TagErrorCode.INTERNAL_ERROR,
            message="Failed to update tag",
        )
    except Exception as e:
        logger.exception(f"Error updating tag: {e}")
        await ctx.session.rollback()
        return TagError(
            code=TagErrorCode.INTERNAL_ERROR,
            message="Failed to update tag",
        )


async def delete_tag_mutation(
    info: Info[GraphQLContext, None],
    id: strawberry.ID,
) -> DeletePayload:
    """Delete a tag.

    Args:
        info: Strawberry info with context
        id: Tag UUID

    Returns:
        DeletePayload indicating success or failure
    """
    ctx = info.context
    from example_service.features.tags.repository import get_tag_repository

    repo = get_tag_repository()

    try:
        tag_uuid = UUID(str(id))
    except ValueError:
        return DeletePayload(
            success=False,
            message="Invalid tag ID format",
        )

    try:
        tag = await repo.get(ctx.session, tag_uuid)
        if tag is None:
            return DeletePayload(
                success=False,
                message=f"Tag with ID {id} not found",
            )

        # Store tag ID for event before deleting
        tag_id_str = str(tag.id)

        # Delete tag (cascade will remove associations)
        await repo.delete(ctx.session, tag)
        await ctx.session.commit()

        logger.info(f"Deleted tag: {tag_uuid} ({tag.name})")

        # Publish event for real-time subscriptions
        await publish_tag_event(
            event_type="DELETED",
            tag_data={"id": tag_id_str},
        )

        return DeletePayload(
            success=True,
            message="Tag deleted successfully",
        )

    except Exception as e:
        logger.exception(f"Error deleting tag: {e}")
        await ctx.session.rollback()
        return DeletePayload(
            success=False,
            message="Failed to delete tag",
        )


async def add_tags_to_reminder_mutation(
    info: Info[GraphQLContext, None],
    reminder_id: strawberry.ID,
    tag_ids: list[strawberry.ID],
) -> DeletePayload:
    """Add tags to a reminder.

    Args:
        info: Strawberry info with context
        reminder_id: Reminder UUID
        tag_ids: List of tag UUIDs to add

    Returns:
        DeletePayload indicating success or failure
    """
    ctx = info.context

    try:
        reminder_uuid = UUID(str(reminder_id))
        tag_uuids = [UUID(str(tid)) for tid in tag_ids]
    except ValueError:
        return DeletePayload(
            success=False,
            message="Invalid ID format",
        )

    try:
        # Get reminder
        stmt = select(Reminder).where(Reminder.id == reminder_uuid)
        result = await ctx.session.execute(stmt)
        reminder = result.scalar_one_or_none()

        if reminder is None:
            return DeletePayload(
                success=False,
                message=f"Reminder with ID {reminder_id} not found",
            )

        # Get tags
        stmt = select(Tag).where(Tag.id.in_(tag_uuids))
        result = await ctx.session.execute(stmt)
        tags = result.scalars().all()

        if len(tags) != len(tag_uuids):
            return DeletePayload(
                success=False,
                message="One or more tags not found",
            )

        # Add tags to reminder
        for tag in tags:
            if tag not in reminder.tags:
                reminder.tags.append(tag)

        await ctx.session.commit()

        logger.info(f"Added {len(tags)} tags to reminder: {reminder_uuid}")

        return DeletePayload(
            success=True,
            message=f"Added {len(tags)} tags to reminder",
        )

    except Exception as e:
        logger.exception(f"Error adding tags to reminder: {e}")
        await ctx.session.rollback()
        return DeletePayload(
            success=False,
            message="Failed to add tags to reminder",
        )


async def remove_tags_from_reminder_mutation(
    info: Info[GraphQLContext, None],
    reminder_id: strawberry.ID,
    tag_ids: list[strawberry.ID],
) -> DeletePayload:
    """Remove tags from a reminder.

    Args:
        info: Strawberry info with context
        reminder_id: Reminder UUID
        tag_ids: List of tag UUIDs to remove

    Returns:
        DeletePayload indicating success or failure
    """
    ctx = info.context

    try:
        reminder_uuid = UUID(str(reminder_id))
        tag_uuids = [UUID(str(tid)) for tid in tag_ids]
    except ValueError:
        return DeletePayload(
            success=False,
            message="Invalid ID format",
        )

    try:
        # Get reminder with tags
        stmt = select(Reminder).where(Reminder.id == reminder_uuid)
        result = await ctx.session.execute(stmt)
        reminder = result.scalar_one_or_none()

        if reminder is None:
            return DeletePayload(
                success=False,
                message=f"Reminder with ID {reminder_id} not found",
            )

        # Remove tags from reminder
        removed_count = 0
        for tag in list(reminder.tags):
            if tag.id in tag_uuids:
                reminder.tags.remove(tag)
                removed_count += 1

        await ctx.session.commit()

        logger.info(f"Removed {removed_count} tags from reminder: {reminder_uuid}")

        return DeletePayload(
            success=True,
            message=f"Removed {removed_count} tags from reminder",
        )

    except Exception as e:
        logger.exception(f"Error removing tags from reminder: {e}")
        await ctx.session.rollback()
        return DeletePayload(
            success=False,
            message="Failed to remove tags from reminder",
        )


__all__ = [
    "add_tags_to_reminder_mutation",
    "create_tag_mutation",
    "delete_tag_mutation",
    "remove_tags_from_reminder_mutation",
    "update_tag_mutation",
]
