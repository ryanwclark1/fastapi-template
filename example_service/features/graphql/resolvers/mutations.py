"""Mutation resolvers for the GraphQL API.

Provides write operations for reminders:
- createReminder: Create a new reminder
- updateReminder: Update an existing reminder
- completeReminder: Mark a reminder as completed
- deleteReminder: Delete a reminder
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING
from uuid import UUID

import strawberry

from example_service.features.graphql.types.reminders import (
    CreateReminderInput,
    DeletePayload,
    ErrorCode,
    ReminderError,
    ReminderPayload,
    ReminderSuccess,
    ReminderType,
    UpdateReminderInput,
)
from example_service.features.reminders.models import Reminder
from example_service.features.reminders.repository import get_reminder_repository

if TYPE_CHECKING:
    from strawberry.types import Info

    from example_service.features.graphql.context import GraphQLContext

logger = logging.getLogger(__name__)


async def _publish_reminder_event(
    event_type: str,
    reminder_data: dict,
) -> None:
    """Publish reminder event to Redis for subscriptions.

    Called from mutation resolvers to notify subscribers.

    Args:
        event_type: Type of event (created, updated, completed, deleted)
        reminder_data: Serialized reminder data
    """
    try:
        from redis.asyncio import Redis

        from example_service.core.settings import get_redis_settings

        redis_settings = get_redis_settings()
        if not redis_settings.is_configured:
            logger.debug("Redis not configured, skipping subscription publish")
            return

        redis = Redis.from_url(str(redis_settings.url))
        try:
            channel = "graphql:reminders"
            payload = json.dumps({
                "event_type": event_type,
                **reminder_data,
            })
            await redis.publish(channel, payload)
            logger.debug("Published %s event to %s", event_type, channel)
        finally:
            await redis.close()
    except Exception as e:
        # Don't fail mutations if publish fails
        logger.warning("Failed to publish reminder event: %s", e)


def _reminder_to_dict(reminder: Reminder) -> dict:
    """Convert reminder to dict for event publishing."""
    return {
        "id": str(reminder.id),
        "title": reminder.title,
        "description": reminder.description,
        "remind_at": reminder.remind_at.isoformat() if reminder.remind_at else None,
        "is_completed": reminder.is_completed,
        "created_at": reminder.created_at.isoformat(),
        "updated_at": reminder.updated_at.isoformat(),
    }


@strawberry.type(description="Root mutation type")
class Mutation:
    """GraphQL Mutation resolvers."""

    @strawberry.mutation(description="Create a new reminder")
    async def create_reminder(
        self,
        info: Info[GraphQLContext, None],
        input: CreateReminderInput,
    ) -> ReminderPayload:
        """Create a new reminder.

        Args:
            info: Strawberry info with context
            input: Reminder creation data

        Returns:
            ReminderSuccess with the created reminder, or ReminderError
        """
        ctx = info.context

        # Validation
        if not input.title or not input.title.strip():
            return ReminderError(
                code=ErrorCode.VALIDATION_ERROR,
                message="Title is required",
                field="title",
            )

        if len(input.title) > 200:
            return ReminderError(
                code=ErrorCode.VALIDATION_ERROR,
                message="Title must be 200 characters or less",
                field="title",
            )

        try:
            # Create reminder
            reminder = Reminder(
                title=input.title.strip(),
                description=input.description.strip() if input.description else None,
                remind_at=input.remind_at,
            )
            ctx.session.add(reminder)
            await ctx.session.commit()
            await ctx.session.refresh(reminder)

            logger.info("Created reminder: %s", reminder.id)

            # Publish event for subscriptions
            await _publish_reminder_event("CREATED", _reminder_to_dict(reminder))

            return ReminderSuccess(reminder=ReminderType.from_model(reminder))

        except Exception as e:
            logger.exception("Error creating reminder: %s", e)
            await ctx.session.rollback()
            return ReminderError(
                code=ErrorCode.INTERNAL_ERROR,
                message="Failed to create reminder",
            )

    @strawberry.mutation(description="Update an existing reminder")
    async def update_reminder(
        self,
        info: Info[GraphQLContext, None],
        id: strawberry.ID,
        input: UpdateReminderInput,
    ) -> ReminderPayload:
        """Update an existing reminder.

        Args:
            info: Strawberry info with context
            id: Reminder UUID
            input: Fields to update

        Returns:
            ReminderSuccess with the updated reminder, or ReminderError
        """
        ctx = info.context
        repo = get_reminder_repository()

        try:
            reminder_uuid = UUID(str(id))
        except ValueError:
            return ReminderError(
                code=ErrorCode.VALIDATION_ERROR,
                message="Invalid reminder ID format",
                field="id",
            )

        try:
            reminder = await repo.get(ctx.session, reminder_uuid)
            if reminder is None:
                return ReminderError(
                    code=ErrorCode.NOT_FOUND,
                    message=f"Reminder with ID {id} not found",
                )

            # Validation
            if input.title is not None:
                if not input.title.strip():
                    return ReminderError(
                        code=ErrorCode.VALIDATION_ERROR,
                        message="Title cannot be empty",
                        field="title",
                    )
                if len(input.title) > 200:
                    return ReminderError(
                        code=ErrorCode.VALIDATION_ERROR,
                        message="Title must be 200 characters or less",
                        field="title",
                    )
                reminder.title = input.title.strip()

            if input.description is not None:
                reminder.description = (
                    input.description.strip() if input.description else None
                )

            if input.remind_at is not None:
                reminder.remind_at = input.remind_at

            await ctx.session.commit()
            await ctx.session.refresh(reminder)

            logger.info("Updated reminder: %s", reminder.id)

            # Publish event for subscriptions
            await _publish_reminder_event("UPDATED", _reminder_to_dict(reminder))

            return ReminderSuccess(reminder=ReminderType.from_model(reminder))

        except Exception as e:
            logger.exception("Error updating reminder: %s", e)
            await ctx.session.rollback()
            return ReminderError(
                code=ErrorCode.INTERNAL_ERROR,
                message="Failed to update reminder",
            )

    @strawberry.mutation(description="Mark a reminder as completed")
    async def complete_reminder(
        self,
        info: Info[GraphQLContext, None],
        id: strawberry.ID,
    ) -> ReminderPayload:
        """Mark a reminder as completed.

        Args:
            info: Strawberry info with context
            id: Reminder UUID

        Returns:
            ReminderSuccess with the completed reminder, or ReminderError
        """
        ctx = info.context
        repo = get_reminder_repository()

        try:
            reminder_uuid = UUID(str(id))
        except ValueError:
            return ReminderError(
                code=ErrorCode.VALIDATION_ERROR,
                message="Invalid reminder ID format",
                field="id",
            )

        try:
            reminder = await repo.mark_completed(ctx.session, reminder_uuid)
            if reminder is None:
                return ReminderError(
                    code=ErrorCode.NOT_FOUND,
                    message=f"Reminder with ID {id} not found",
                )

            await ctx.session.commit()

            logger.info("Completed reminder: %s", reminder.id)

            # Publish event for subscriptions
            await _publish_reminder_event("COMPLETED", _reminder_to_dict(reminder))

            return ReminderSuccess(reminder=ReminderType.from_model(reminder))

        except Exception as e:
            logger.exception("Error completing reminder: %s", e)
            await ctx.session.rollback()
            return ReminderError(
                code=ErrorCode.INTERNAL_ERROR,
                message="Failed to complete reminder",
            )

    @strawberry.mutation(description="Delete a reminder")
    async def delete_reminder(
        self,
        info: Info[GraphQLContext, None],
        id: strawberry.ID,
    ) -> DeletePayload:
        """Delete a reminder.

        Args:
            info: Strawberry info with context
            id: Reminder UUID

        Returns:
            DeletePayload indicating success or failure
        """
        ctx = info.context
        repo = get_reminder_repository()

        try:
            reminder_uuid = UUID(str(id))
        except ValueError:
            return DeletePayload(
                success=False,
                message="Invalid reminder ID format",
            )

        try:
            reminder = await repo.get(ctx.session, reminder_uuid)
            if reminder is None:
                return DeletePayload(
                    success=False,
                    message=f"Reminder with ID {id} not found",
                )

            await repo.delete(ctx.session, reminder)
            await ctx.session.commit()

            logger.info("Deleted reminder: %s", reminder_uuid)

            # Publish event for subscriptions
            await _publish_reminder_event("DELETED", {"id": str(reminder_uuid)})

            return DeletePayload(
                success=True,
                message="Reminder deleted successfully",
            )

        except Exception as e:
            logger.exception("Error deleting reminder: %s", e)
            await ctx.session.rollback()
            return DeletePayload(
                success=False,
                message="Failed to delete reminder",
            )


__all__ = ["Mutation"]
