"""Mutation resolvers for the AI feature.

Provides:
- createAIJob: Create a new AI processing job
- cancelAIJob: Cancel a pending/processing AI job
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
import strawberry

from example_service.features.ai.models import AIJob
from example_service.features.graphql.types.ai import (
    AIJobError,
    AIJobPayload,
    AIJobSuccess,
    AIJobType,
    CreateAIJobInput,
)
from example_service.features.graphql.types.reminders import DeletePayload

if TYPE_CHECKING:
    from strawberry.types import Info

    from example_service.features.graphql.context import GraphQLContext

logger = logging.getLogger(__name__)


@strawberry.mutation(description="Create a new AI processing job")
async def create_ai_job_mutation(
    info: Info[GraphQLContext, None],
    input: CreateAIJobInput,
) -> AIJobPayload:
    """Create a new AI processing job.

    Args:
        info: Strawberry info with context
        input: AI job creation data

    Returns:
        AIJobSuccess with the created job, or AIJobError
    """
    ctx = info.context

    # Validate input_data
    if not input.input_data:
        return AIJobError(
            code="VALIDATION_ERROR",
            message="input_data is required",
            field="input_data",
        )

    try:
        # Create the AI job
        job = AIJob(
            tenant_id="default",  # Would come from context in production
            job_type=input.job_type.value,
            status="pending",
            input_data=input.input_data,
            progress_percentage=0,
        )
        ctx.session.add(job)
        await ctx.session.commit()
        await ctx.session.refresh(job)

        logger.info("Created AI job: %s", job.id)

        return AIJobSuccess(job=AIJobType.from_model(job))

    except Exception as e:
        logger.exception("Error creating AI job: %s", e)
        await ctx.session.rollback()
        return AIJobError(
            code="INTERNAL_ERROR",
            message="Failed to create AI job",
        )


@strawberry.mutation(description="Cancel a pending or processing AI job")
async def cancel_ai_job_mutation(
    info: Info[GraphQLContext, None],
    id: strawberry.ID,
    reason: str | None = None,
) -> AIJobPayload:
    """Cancel a pending or processing AI job.

    Args:
        info: Strawberry info with context
        id: AI job UUID
        reason: Optional cancellation reason

    Returns:
        AIJobSuccess with the cancelled job, or AIJobError
    """
    ctx = info.context

    try:
        job_uuid = UUID(str(id))
    except ValueError:
        return AIJobError(
            code="VALIDATION_ERROR",
            message="Invalid job ID format",
            field="id",
        )

    try:
        stmt = select(AIJob).where(AIJob.id == job_uuid)
        result = await ctx.session.execute(stmt)
        job = result.scalar_one_or_none()

        if job is None:
            return AIJobError(
                code="NOT_FOUND",
                message=f"AI job with ID {id} not found",
            )

        # Check if job can be cancelled
        if job.status not in ["pending", "processing"]:
            return AIJobError(
                code="INVALID_STATE",
                message=f"Cannot cancel job in '{job.status}' status",
            )

        # Cancel the job
        job.status = "cancelled"
        if reason:
            job.error_message = f"Cancelled: {reason}"

        await ctx.session.commit()
        await ctx.session.refresh(job)

        logger.info("Cancelled AI job: %s", job.id)

        return AIJobSuccess(job=AIJobType.from_model(job))

    except Exception as e:
        logger.exception("Error cancelling AI job: %s", e)
        await ctx.session.rollback()
        return AIJobError(
            code="INTERNAL_ERROR",
            message="Failed to cancel AI job",
        )


@strawberry.mutation(description="Delete an AI job")
async def delete_ai_job_mutation(
    info: Info[GraphQLContext, None],
    id: strawberry.ID,
) -> DeletePayload:
    """Delete an AI job.

    Only completed, failed, or cancelled jobs can be deleted.

    Args:
        info: Strawberry info with context
        id: AI job UUID

    Returns:
        DeletePayload indicating success or failure
    """
    ctx = info.context

    try:
        job_uuid = UUID(str(id))
    except ValueError:
        return DeletePayload(
            success=False,
            message="Invalid job ID format",
        )

    try:
        stmt = select(AIJob).where(AIJob.id == job_uuid)
        result = await ctx.session.execute(stmt)
        job = result.scalar_one_or_none()

        if job is None:
            return DeletePayload(
                success=False,
                message=f"AI job with ID {id} not found",
            )

        # Check if job can be deleted
        if job.status in ["pending", "processing"]:
            return DeletePayload(
                success=False,
                message=f"Cannot delete job in '{job.status}' status. Cancel it first.",
            )

        await ctx.session.delete(job)
        await ctx.session.commit()

        logger.info("Deleted AI job: %s", job_uuid)

        return DeletePayload(
            success=True,
            message="AI job deleted successfully",
        )

    except Exception as e:
        logger.exception("Error deleting AI job: %s", e)
        await ctx.session.rollback()
        return DeletePayload(
            success=False,
            message="Failed to delete AI job",
        )


__all__ = [
    "cancel_ai_job_mutation",
    "create_ai_job_mutation",
    "delete_ai_job_mutation",
]
