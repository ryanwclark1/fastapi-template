"""Query resolvers for the AI Workflow feature.

Provides:
- workflowDefinition: Get a single workflow definition by ID
- workflowDefinitions: List workflow definitions with cursor pagination
- workflowExecution: Get a single workflow execution by ID
- workflowExecutions: List workflow executions with cursor pagination
- workflowApprovals: List pending approvals with pagination
- workflowStats: Get aggregated workflow statistics
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta
import logging
from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from sqlalchemy import func, or_, select
import strawberry

from example_service.features.graphql.types.base import PageInfoType
from example_service.features.graphql.types.workflows import (
    WorkflowApprovalConnection,
    WorkflowApprovalEdge,
    WorkflowApprovalFilterInput,
    WorkflowApprovalType,
    WorkflowDefinitionConnection,
    WorkflowDefinitionEdge,
    WorkflowDefinitionFilterInput,
    WorkflowDefinitionType,
    WorkflowExecutionConnection,
    WorkflowExecutionEdge,
    WorkflowExecutionFilterInput,
    WorkflowExecutionType,
    WorkflowNodeExecutionType,
    WorkflowStatsType,
)
from example_service.infra.ai.agents.workflow_models import (
    AIWorkflowApproval,
    AIWorkflowDefinition,
    AIWorkflowExecution,
    AIWorkflowNodeExecution,
)

if TYPE_CHECKING:
    from strawberry.types import Info

    from example_service.features.graphql.context import GraphQLContext

logger = logging.getLogger(__name__)

# Type aliases for annotated arguments
FirstArg = Annotated[
    int, strawberry.argument(description="Number of items to return (forward pagination)"),
]
AfterArg = Annotated[
    str | None, strawberry.argument(description="Cursor to start after"),
]


@strawberry.field(description="Get a single workflow definition by ID")
async def workflow_definition_query(
    info: Info[GraphQLContext, None],
    id: strawberry.ID,
) -> WorkflowDefinitionType | None:
    """Get a single workflow definition by ID.

    Args:
        info: Strawberry info with context
        id: Workflow definition UUID

    Returns:
        WorkflowDefinitionType if found, None otherwise
    """
    ctx = info.context
    try:
        definition_uuid = UUID(str(id))
    except ValueError:
        return None

    stmt = select(AIWorkflowDefinition).where(AIWorkflowDefinition.id == definition_uuid)
    result = await ctx.session.execute(stmt)
    definition = result.scalar_one_or_none()

    if definition is None:
        return None

    return WorkflowDefinitionType.from_model(definition)


@strawberry.field(description="Get a workflow definition by slug")
async def workflow_definition_by_slug_query(
    info: Info[GraphQLContext, None],
    slug: str,
) -> WorkflowDefinitionType | None:
    """Get a workflow definition by slug.

    Args:
        info: Strawberry info with context
        slug: Workflow slug

    Returns:
        WorkflowDefinitionType if found, None otherwise
    """
    ctx = info.context

    stmt = select(AIWorkflowDefinition).where(AIWorkflowDefinition.slug == slug)
    result = await ctx.session.execute(stmt)
    definition = result.scalar_one_or_none()

    if definition is None:
        return None

    return WorkflowDefinitionType.from_model(definition)


@strawberry.field(description="List workflow definitions with cursor pagination")
async def workflow_definitions_query(
    info: Info[GraphQLContext, None],
    first: FirstArg = 50,
    after: AfterArg = None,
    filter: WorkflowDefinitionFilterInput | None = None,
) -> WorkflowDefinitionConnection:
    """List workflow definitions with Relay-style cursor pagination.

    Args:
        info: Strawberry info with context
        first: Items for forward pagination
        after: Cursor for forward pagination
        filter: Optional filters

    Returns:
        WorkflowDefinitionConnection with edges and page_info
    """
    ctx = info.context

    # Build base query
    stmt = select(AIWorkflowDefinition)

    # Apply filters
    if filter:
        if filter.is_active is not None:
            stmt = stmt.where(AIWorkflowDefinition.is_active == filter.is_active)
        if filter.is_public is not None:
            stmt = stmt.where(AIWorkflowDefinition.is_public == filter.is_public)
        if filter.tags:
            # Filter workflows that have any of the specified tags
            for tag in filter.tags:
                stmt = stmt.where(AIWorkflowDefinition.tags.contains([tag]))
        if filter.search:
            search_pattern = f"%{filter.search}%"
            stmt = stmt.where(
                or_(
                    AIWorkflowDefinition.name.ilike(search_pattern),
                    AIWorkflowDefinition.description.ilike(search_pattern),
                ),
            )

    # Order by created_at desc
    stmt = stmt.order_by(AIWorkflowDefinition.created_at.desc())

    # Simple offset-based pagination using cursor
    offset = 0
    if after:
        with contextlib.suppress(ValueError):
            offset = int(after)

    stmt = stmt.offset(offset).limit(first + 1)

    result = await ctx.session.execute(stmt)
    definitions = list(result.scalars().all())

    has_next = len(definitions) > first
    if has_next:
        definitions = definitions[:first]

    edges = [
        WorkflowDefinitionEdge(
            node=WorkflowDefinitionType.from_model(definition),
            cursor=str(offset + i),
        )
        for i, definition in enumerate(definitions)
    ]

    page_info = PageInfoType(
        has_previous_page=offset > 0,
        has_next_page=has_next,
        start_cursor=edges[0].cursor if edges else None,
        end_cursor=edges[-1].cursor if edges else None,
    )

    return WorkflowDefinitionConnection(edges=edges, page_info=page_info)


@strawberry.field(description="Get a single workflow execution by ID")
async def workflow_execution_query(
    info: Info[GraphQLContext, None],
    id: strawberry.ID,
) -> WorkflowExecutionType | None:
    """Get a single workflow execution by ID.

    Args:
        info: Strawberry info with context
        id: Workflow execution UUID

    Returns:
        WorkflowExecutionType if found, None otherwise
    """
    ctx = info.context
    try:
        execution_uuid = UUID(str(id))
    except ValueError:
        return None

    stmt = select(AIWorkflowExecution).where(AIWorkflowExecution.id == execution_uuid)
    result = await ctx.session.execute(stmt)
    execution = result.scalar_one_or_none()

    if execution is None:
        return None

    return WorkflowExecutionType.from_model(execution)


@strawberry.field(description="List workflow executions with cursor pagination")
async def workflow_executions_query(
    info: Info[GraphQLContext, None],
    first: FirstArg = 50,
    after: AfterArg = None,
    filter: WorkflowExecutionFilterInput | None = None,
) -> WorkflowExecutionConnection:
    """List workflow executions with Relay-style cursor pagination.

    Args:
        info: Strawberry info with context
        first: Items for forward pagination
        after: Cursor for forward pagination
        filter: Optional filters

    Returns:
        WorkflowExecutionConnection with edges and page_info
    """
    ctx = info.context

    # Build base query
    stmt = select(AIWorkflowExecution)

    # Apply filters
    if filter:
        if filter.definition_id:
            try:
                def_uuid = UUID(str(filter.definition_id))
                stmt = stmt.where(AIWorkflowExecution.definition_id == def_uuid)
            except ValueError:
                pass
        if filter.status:
            stmt = stmt.where(AIWorkflowExecution.status == filter.status.value)
        if filter.created_after:
            stmt = stmt.where(AIWorkflowExecution.created_at >= filter.created_after)
        if filter.created_before:
            stmt = stmt.where(AIWorkflowExecution.created_at <= filter.created_before)
        if filter.tags:
            for tag in filter.tags:
                stmt = stmt.where(AIWorkflowExecution.tags.contains([tag]))

    # Order by created_at desc
    stmt = stmt.order_by(AIWorkflowExecution.created_at.desc())

    # Simple offset-based pagination
    offset = 0
    if after:
        with contextlib.suppress(ValueError):
            offset = int(after)

    stmt = stmt.offset(offset).limit(first + 1)

    result = await ctx.session.execute(stmt)
    executions = list(result.scalars().all())

    has_next = len(executions) > first
    if has_next:
        executions = executions[:first]

    edges = [
        WorkflowExecutionEdge(
            node=WorkflowExecutionType.from_model(execution),
            cursor=str(offset + i),
        )
        for i, execution in enumerate(executions)
    ]

    page_info = PageInfoType(
        has_previous_page=offset > 0,
        has_next_page=has_next,
        start_cursor=edges[0].cursor if edges else None,
        end_cursor=edges[-1].cursor if edges else None,
    )

    return WorkflowExecutionConnection(edges=edges, page_info=page_info)


@strawberry.field(description="Get node executions for a workflow execution")
async def workflow_node_executions_query(
    info: Info[GraphQLContext, None],
    execution_id: strawberry.ID,
) -> list[WorkflowNodeExecutionType]:
    """Get all node executions for a workflow execution.

    Args:
        info: Strawberry info with context
        execution_id: Parent workflow execution UUID

    Returns:
        List of WorkflowNodeExecutionType
    """
    ctx = info.context
    try:
        exec_uuid = UUID(str(execution_id))
    except ValueError:
        return []

    stmt = (
        select(AIWorkflowNodeExecution)
        .where(AIWorkflowNodeExecution.workflow_execution_id == exec_uuid)
        .order_by(AIWorkflowNodeExecution.execution_order)
    )
    result = await ctx.session.execute(stmt)
    node_execs = result.scalars().all()

    return [WorkflowNodeExecutionType.from_model(ne) for ne in node_execs]


@strawberry.field(description="List workflow approvals with cursor pagination")
async def workflow_approvals_query(
    info: Info[GraphQLContext, None],
    first: FirstArg = 50,
    after: AfterArg = None,
    filter: WorkflowApprovalFilterInput | None = None,
) -> WorkflowApprovalConnection:
    """List workflow approvals with Relay-style cursor pagination.

    Args:
        info: Strawberry info with context
        first: Items for forward pagination
        after: Cursor for forward pagination
        filter: Optional filters

    Returns:
        WorkflowApprovalConnection with edges and page_info
    """
    ctx = info.context

    # Build base query
    stmt = select(AIWorkflowApproval)

    # Apply filters
    if filter:
        if filter.is_pending is not None:
            stmt = stmt.where(AIWorkflowApproval.is_pending == filter.is_pending)
        if filter.execution_id:
            try:
                exec_uuid = UUID(str(filter.execution_id))
                stmt = stmt.where(AIWorkflowApproval.workflow_execution_id == exec_uuid)
            except ValueError:
                pass

    # Order by created_at desc
    stmt = stmt.order_by(AIWorkflowApproval.created_at.desc())

    # Simple offset-based pagination
    offset = 0
    if after:
        with contextlib.suppress(ValueError):
            offset = int(after)

    stmt = stmt.offset(offset).limit(first + 1)

    result = await ctx.session.execute(stmt)
    approvals = list(result.scalars().all())

    has_next = len(approvals) > first
    if has_next:
        approvals = approvals[:first]

    edges = [
        WorkflowApprovalEdge(
            node=WorkflowApprovalType.from_model(approval),
            cursor=str(offset + i),
        )
        for i, approval in enumerate(approvals)
    ]

    page_info = PageInfoType(
        has_previous_page=offset > 0,
        has_next_page=has_next,
        start_cursor=edges[0].cursor if edges else None,
        end_cursor=edges[-1].cursor if edges else None,
    )

    return WorkflowApprovalConnection(edges=edges, page_info=page_info)


@strawberry.field(description="Get pending approvals for the current user")
async def pending_approvals_query(
    info: Info[GraphQLContext, None],
    first: FirstArg = 50,
    after: AfterArg = None,
) -> WorkflowApprovalConnection:
    """Get pending approvals that haven't expired.

    Args:
        info: Strawberry info with context
        first: Items for forward pagination
        after: Cursor for forward pagination

    Returns:
        WorkflowApprovalConnection with pending approvals
    """
    ctx = info.context
    now = datetime.now(UTC)

    # Build query for pending, non-expired approvals
    stmt = (
        select(AIWorkflowApproval)
        .where(AIWorkflowApproval.is_pending)
        .where(
            or_(
                AIWorkflowApproval.expires_at.is_(None),
                AIWorkflowApproval.expires_at > now,
            ),
        )
    )

    # Order by created_at desc
    stmt = stmt.order_by(AIWorkflowApproval.created_at.desc())

    # Simple offset-based pagination
    offset = 0
    if after:
        with contextlib.suppress(ValueError):
            offset = int(after)

    stmt = stmt.offset(offset).limit(first + 1)

    result = await ctx.session.execute(stmt)
    approvals = list(result.scalars().all())

    has_next = len(approvals) > first
    if has_next:
        approvals = approvals[:first]

    edges = [
        WorkflowApprovalEdge(
            node=WorkflowApprovalType.from_model(approval),
            cursor=str(offset + i),
        )
        for i, approval in enumerate(approvals)
    ]

    page_info = PageInfoType(
        has_previous_page=offset > 0,
        has_next_page=has_next,
        start_cursor=edges[0].cursor if edges else None,
        end_cursor=edges[-1].cursor if edges else None,
    )

    return WorkflowApprovalConnection(edges=edges, page_info=page_info)


@strawberry.field(description="Get aggregated workflow statistics")
async def workflow_stats_query(
    info: Info[GraphQLContext, None],
    days: int = 30,
) -> WorkflowStatsType:
    """Get aggregated workflow statistics for the specified period.

    Args:
        info: Strawberry info with context
        days: Number of days to include in statistics

    Returns:
        WorkflowStatsType with aggregated statistics
    """
    ctx = info.context
    since = datetime.now(UTC) - timedelta(days=days)

    # Get definition count
    def_count_result = await ctx.session.execute(
        select(func.count(AIWorkflowDefinition.id)).where(
            AIWorkflowDefinition.is_active,
        ),
    )
    total_definitions = def_count_result.scalar() or 0

    # Get execution counts by status
    exec_stats = await ctx.session.execute(
        select(
            AIWorkflowExecution.status,
            func.count(AIWorkflowExecution.id).label("count"),
        )
        .where(AIWorkflowExecution.created_at >= since)
        .group_by(AIWorkflowExecution.status),
    )
    exec_counts = {row.status: row.count for row in exec_stats}

    # Get pending approvals count
    pending_result = await ctx.session.execute(
        select(func.count(AIWorkflowApproval.id)).where(
            AIWorkflowApproval.is_pending,
        ),
    )
    pending_approvals = pending_result.scalar() or 0

    # Get usage aggregates
    usage_stats = await ctx.session.execute(
        select(
            func.sum(AIWorkflowExecution.total_cost_usd).label("total_cost"),
            func.sum(AIWorkflowExecution.total_tokens).label("total_tokens"),
            func.avg(
                func.extract(
                    "epoch",
                    AIWorkflowExecution.completed_at - AIWorkflowExecution.started_at,
                ),
            ).label("avg_duration"),
        )
        .where(AIWorkflowExecution.created_at >= since)
        .where(AIWorkflowExecution.status == "completed"),
    )
    usage = usage_stats.first()

    # Get executions by workflow
    workflow_stats = await ctx.session.execute(
        select(
            AIWorkflowDefinition.name,
            func.count(AIWorkflowExecution.id).label("count"),
        )
        .join(
            AIWorkflowExecution,
            AIWorkflowExecution.definition_id == AIWorkflowDefinition.id,
        )
        .where(AIWorkflowExecution.created_at >= since)
        .group_by(AIWorkflowDefinition.name),
    )
    executions_by_workflow = {row.name: row.count for row in workflow_stats}

    total_executions = sum(exec_counts.values())

    return WorkflowStatsType(
        total_definitions=total_definitions,
        total_executions=total_executions,
        completed_executions=exec_counts.get("completed", 0),
        failed_executions=exec_counts.get("failed", 0),
        running_executions=exec_counts.get("running", 0) + exec_counts.get("pending", 0),
        pending_approvals=pending_approvals,
        total_cost_usd=float(usage.total_cost or 0) if usage else 0,
        total_tokens=int(usage.total_tokens or 0) if usage else 0,
        avg_duration_seconds=(
            float(usage.avg_duration) if usage and usage.avg_duration else None
        ),
        executions_by_status=exec_counts,
        executions_by_workflow=executions_by_workflow,
    )


__all__ = [
    "pending_approvals_query",
    "workflow_approvals_query",
    "workflow_definition_by_slug_query",
    "workflow_definition_query",
    "workflow_definitions_query",
    "workflow_execution_query",
    "workflow_executions_query",
    "workflow_node_executions_query",
    "workflow_stats_query",
]
