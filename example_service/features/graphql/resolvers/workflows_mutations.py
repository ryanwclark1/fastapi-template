"""Mutation resolvers for the AI Workflow feature.

Provides:
- createWorkflowDefinition: Create a new workflow definition
- updateWorkflowDefinition: Update an existing workflow definition
- deleteWorkflowDefinition: Delete a workflow definition
- executeWorkflow: Execute a workflow
- cancelWorkflowExecution: Cancel a running workflow
- respondToApproval: Respond to an approval request
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
import strawberry

from example_service.features.graphql.types.workflows import (
    CreateWorkflowDefinitionInput,
    ExecuteWorkflowInput,
    RespondToApprovalInput,
    UpdateWorkflowDefinitionInput,
    WorkflowApprovalPayload,
    WorkflowApprovalSuccess,
    WorkflowApprovalType,
    WorkflowDefinitionPayload,
    WorkflowDefinitionSuccess,
    WorkflowDefinitionType,
    WorkflowError,
    WorkflowExecutionPayload,
    WorkflowExecutionSuccess,
    WorkflowExecutionType,
)
from example_service.infra.ai.agents.workflow_models import (
    AIWorkflowApproval,
    AIWorkflowDefinition,
    AIWorkflowExecution,
    WorkflowStatus,
)

if TYPE_CHECKING:
    from strawberry.types import Info

    from example_service.features.graphql.context import GraphQLContext

logger = logging.getLogger(__name__)


@strawberry.mutation(description="Create a new workflow definition")
async def create_workflow_definition_mutation(
    info: Info[GraphQLContext, None],
    input: CreateWorkflowDefinitionInput,
) -> WorkflowDefinitionPayload:
    """Create a new workflow definition.

    Args:
        info: Strawberry info with context
        input: Workflow definition input

    Returns:
        WorkflowDefinitionPayload with success or error
    """
    ctx = info.context

    # Validate required fields
    if not input.name:
        return WorkflowError(
            code="VALIDATION_ERROR",
            message="Workflow name is required",
            field="name",
        )

    if not input.slug:
        return WorkflowError(
            code="VALIDATION_ERROR",
            message="Workflow slug is required",
            field="slug",
        )

    if not input.entry_point:
        return WorkflowError(
            code="VALIDATION_ERROR",
            message="Entry point is required",
            field="entry_point",
        )

    # Check for existing slug
    existing = await ctx.session.execute(
        select(AIWorkflowDefinition).where(AIWorkflowDefinition.slug == input.slug)
    )
    if existing.scalar_one_or_none():
        return WorkflowError(
            code="DUPLICATE_SLUG",
            message=f"Workflow with slug '{input.slug}' already exists",
            field="slug",
        )

    try:
        # Get tenant_id from context user
        tenant_id = ctx.user.tenant_id if ctx.user else None
        if not tenant_id:
            return WorkflowError(
                code="AUTH_ERROR",
                message="Tenant ID is required",
            )

        definition = AIWorkflowDefinition(
            tenant_id=tenant_id,
            name=input.name,
            slug=input.slug,
            description=input.description,
            version=input.version,
            nodes=input.nodes or {},
            edges=input.edges or {},
            entry_point=input.entry_point,
            end_nodes=input.end_nodes or [],
            default_config=input.default_config or {},
            timeout_seconds=input.timeout_seconds,
            max_retries=input.max_retries,
            tags=input.tags or [],
            is_public=input.is_public,
            is_active=True,
            created_by_id=ctx.user.id if ctx.user else None,
        )

        ctx.session.add(definition)
        await ctx.session.commit()
        await ctx.session.refresh(definition)

        return WorkflowDefinitionSuccess(
            definition=WorkflowDefinitionType.from_model(definition)
        )

    except Exception as e:
        logger.exception("Failed to create workflow definition")
        await ctx.session.rollback()
        return WorkflowError(
            code="INTERNAL_ERROR",
            message=f"Failed to create workflow definition: {e!s}",
        )


@strawberry.mutation(description="Update an existing workflow definition")
async def update_workflow_definition_mutation(
    info: Info[GraphQLContext, None],
    id: strawberry.ID,
    input: UpdateWorkflowDefinitionInput,
) -> WorkflowDefinitionPayload:
    """Update a workflow definition.

    Args:
        info: Strawberry info with context
        id: Workflow definition UUID
        input: Update input

    Returns:
        WorkflowDefinitionPayload with success or error
    """
    ctx = info.context

    try:
        definition_uuid = UUID(str(id))
    except ValueError:
        return WorkflowError(
            code="INVALID_ID",
            message="Invalid workflow definition ID",
            field="id",
        )

    stmt = select(AIWorkflowDefinition).where(AIWorkflowDefinition.id == definition_uuid)
    result = await ctx.session.execute(stmt)
    definition = result.scalar_one_or_none()

    if definition is None:
        return WorkflowError(
            code="NOT_FOUND",
            message=f"Workflow definition '{id}' not found",
            field="id",
        )

    try:
        # Update fields if provided
        if input.name is not None:
            definition.name = input.name
        if input.description is not None:
            definition.description = input.description
        if input.version is not None:
            definition.version = input.version
        if input.nodes is not None:
            definition.nodes = input.nodes
        if input.edges is not None:
            definition.edges = input.edges
        if input.entry_point is not None:
            definition.entry_point = input.entry_point
        if input.end_nodes is not None:
            definition.end_nodes = input.end_nodes
        if input.default_config is not None:
            definition.default_config = input.default_config
        if input.timeout_seconds is not None:
            definition.timeout_seconds = input.timeout_seconds
        if input.max_retries is not None:
            definition.max_retries = input.max_retries
        if input.tags is not None:
            definition.tags = input.tags
        if input.is_active is not None:
            definition.is_active = input.is_active
        if input.is_public is not None:
            definition.is_public = input.is_public

        await ctx.session.commit()
        await ctx.session.refresh(definition)

        return WorkflowDefinitionSuccess(
            definition=WorkflowDefinitionType.from_model(definition)
        )

    except Exception as e:
        logger.exception("Failed to update workflow definition")
        await ctx.session.rollback()
        return WorkflowError(
            code="INTERNAL_ERROR",
            message=f"Failed to update workflow definition: {e!s}",
        )


@strawberry.mutation(description="Delete a workflow definition")
async def delete_workflow_definition_mutation(
    info: Info[GraphQLContext, None],
    id: strawberry.ID,
) -> WorkflowDefinitionPayload:
    """Delete a workflow definition.

    Args:
        info: Strawberry info with context
        id: Workflow definition UUID

    Returns:
        WorkflowDefinitionPayload with success or error
    """
    ctx = info.context

    try:
        definition_uuid = UUID(str(id))
    except ValueError:
        return WorkflowError(
            code="INVALID_ID",
            message="Invalid workflow definition ID",
            field="id",
        )

    stmt = select(AIWorkflowDefinition).where(AIWorkflowDefinition.id == definition_uuid)
    result = await ctx.session.execute(stmt)
    definition = result.scalar_one_or_none()

    if definition is None:
        return WorkflowError(
            code="NOT_FOUND",
            message=f"Workflow definition '{id}' not found",
            field="id",
        )

    try:
        # Soft delete by marking as inactive
        definition.is_active = False
        await ctx.session.commit()
        await ctx.session.refresh(definition)

        return WorkflowDefinitionSuccess(
            definition=WorkflowDefinitionType.from_model(definition)
        )

    except Exception as e:
        logger.exception("Failed to delete workflow definition")
        await ctx.session.rollback()
        return WorkflowError(
            code="INTERNAL_ERROR",
            message=f"Failed to delete workflow definition: {e!s}",
        )


@strawberry.mutation(description="Execute a workflow")
async def execute_workflow_mutation(
    info: Info[GraphQLContext, None],
    input: ExecuteWorkflowInput,
) -> WorkflowExecutionPayload:
    """Start a new workflow execution.

    Args:
        info: Strawberry info with context
        input: Execution input

    Returns:
        WorkflowExecutionPayload with success or error
    """
    ctx = info.context

    try:
        definition_uuid = UUID(str(input.definition_id))
    except ValueError:
        return WorkflowError(
            code="INVALID_ID",
            message="Invalid workflow definition ID",
            field="definition_id",
        )

    # Get workflow definition
    stmt = select(AIWorkflowDefinition).where(
        AIWorkflowDefinition.id == definition_uuid,
        AIWorkflowDefinition.is_active == True,  # noqa: E712
    )
    result = await ctx.session.execute(stmt)
    definition = result.scalar_one_or_none()

    if definition is None:
        return WorkflowError(
            code="NOT_FOUND",
            message=f"Workflow definition '{input.definition_id}' not found or inactive",
            field="definition_id",
        )

    try:
        # Get tenant_id from context user
        tenant_id = ctx.user.tenant_id if ctx.user else definition.tenant_id

        # Create execution record
        execution = AIWorkflowExecution(
            definition_id=definition.id,
            tenant_id=tenant_id,
            status=WorkflowStatus.PENDING.value,
            input_data=input.input_data or {},
            config=input.config or {},
            correlation_id=input.correlation_id,
            tags=input.tags or [],
            created_by_id=ctx.user.id if ctx.user else None,
        )

        ctx.session.add(execution)
        await ctx.session.commit()
        await ctx.session.refresh(execution)

        # TODO: Trigger actual workflow execution via task queue
        # For now, just create the execution record

        return WorkflowExecutionSuccess(
            execution=WorkflowExecutionType.from_model(execution)
        )

    except Exception as e:
        logger.exception("Failed to execute workflow")
        await ctx.session.rollback()
        return WorkflowError(
            code="INTERNAL_ERROR",
            message=f"Failed to execute workflow: {e!s}",
        )


@strawberry.mutation(description="Cancel a running workflow execution")
async def cancel_workflow_execution_mutation(
    info: Info[GraphQLContext, None],
    id: strawberry.ID,
    reason: str | None = None,
) -> WorkflowExecutionPayload:
    """Cancel a running workflow execution.

    Args:
        info: Strawberry info with context
        id: Workflow execution UUID
        reason: Optional cancellation reason

    Returns:
        WorkflowExecutionPayload with success or error
    """
    ctx = info.context

    try:
        execution_uuid = UUID(str(id))
    except ValueError:
        return WorkflowError(
            code="INVALID_ID",
            message="Invalid workflow execution ID",
            field="id",
        )

    stmt = select(AIWorkflowExecution).where(AIWorkflowExecution.id == execution_uuid)
    result = await ctx.session.execute(stmt)
    execution = result.scalar_one_or_none()

    if execution is None:
        return WorkflowError(
            code="NOT_FOUND",
            message=f"Workflow execution '{id}' not found",
            field="id",
        )

    # Check if execution can be cancelled
    cancellable_statuses = [
        WorkflowStatus.PENDING.value,
        WorkflowStatus.RUNNING.value,
        WorkflowStatus.PAUSED.value,
        WorkflowStatus.WAITING_APPROVAL.value,
    ]
    if execution.status not in cancellable_statuses:
        return WorkflowError(
            code="INVALID_STATE",
            message=f"Workflow execution in status '{execution.status}' cannot be cancelled",
        )

    try:
        execution.status = WorkflowStatus.CANCELLED.value
        execution.completed_at = datetime.now(UTC)
        if reason:
            execution.error = f"Cancelled: {reason}"

        await ctx.session.commit()
        await ctx.session.refresh(execution)

        return WorkflowExecutionSuccess(
            execution=WorkflowExecutionType.from_model(execution)
        )

    except Exception as e:
        logger.exception("Failed to cancel workflow execution")
        await ctx.session.rollback()
        return WorkflowError(
            code="INTERNAL_ERROR",
            message=f"Failed to cancel workflow execution: {e!s}",
        )


@strawberry.mutation(description="Respond to an approval request")
async def respond_to_approval_mutation(
    info: Info[GraphQLContext, None],
    input: RespondToApprovalInput,
) -> WorkflowApprovalPayload:
    """Respond to a pending approval request.

    Args:
        info: Strawberry info with context
        input: Approval response input

    Returns:
        WorkflowApprovalPayload with success or error
    """
    ctx = info.context

    try:
        approval_uuid = UUID(str(input.approval_id))
    except ValueError:
        return WorkflowError(
            code="INVALID_ID",
            message="Invalid approval ID",
            field="approval_id",
        )

    stmt = select(AIWorkflowApproval).where(AIWorkflowApproval.id == approval_uuid)
    result = await ctx.session.execute(stmt)
    approval = result.scalar_one_or_none()

    if approval is None:
        return WorkflowError(
            code="NOT_FOUND",
            message=f"Approval request '{input.approval_id}' not found",
            field="approval_id",
        )

    if not approval.is_pending:
        return WorkflowError(
            code="ALREADY_RESPONDED",
            message="Approval request has already been responded to",
        )

    if approval.is_expired:
        return WorkflowError(
            code="EXPIRED",
            message="Approval request has expired",
        )

    # Validate response is in options
    if input.response not in approval.options:
        return WorkflowError(
            code="INVALID_RESPONSE",
            message=f"Response must be one of: {', '.join(approval.options)}",
            field="response",
        )

    try:
        approval.is_pending = False
        approval.response = input.response
        approval.response_data = input.response_data
        approval.response_comment = input.comment
        approval.responded_by_id = ctx.user.id if ctx.user else None
        approval.responded_at = datetime.now(UTC)

        await ctx.session.commit()
        await ctx.session.refresh(approval)

        # TODO: Trigger workflow resumption via task queue
        # Update the parent workflow execution status

        return WorkflowApprovalSuccess(
            approval=WorkflowApprovalType.from_model(approval)
        )

    except Exception as e:
        logger.exception("Failed to respond to approval")
        await ctx.session.rollback()
        return WorkflowError(
            code="INTERNAL_ERROR",
            message=f"Failed to respond to approval: {e!s}",
        )


__all__ = [
    "cancel_workflow_execution_mutation",
    "create_workflow_definition_mutation",
    "delete_workflow_definition_mutation",
    "execute_workflow_mutation",
    "respond_to_approval_mutation",
    "update_workflow_definition_mutation",
]
