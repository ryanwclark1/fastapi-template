"""REST API endpoints for AI Workflow management.

This module provides endpoints for:
- Creating and managing workflow definitions
- Executing workflows
- Approving/rejecting human approval requests
- Monitoring workflow execution status

Endpoints:
    # Definitions
    GET  /api/v1/ai/workflows                    - List workflow definitions
    POST /api/v1/ai/workflows                    - Create workflow definition
    GET  /api/v1/ai/workflows/{id}               - Get workflow definition
    PUT  /api/v1/ai/workflows/{id}               - Update workflow definition
    DELETE /api/v1/ai/workflows/{id}             - Delete workflow definition

    # Executions
    POST /api/v1/ai/workflows/{id}/execute       - Execute workflow
    GET  /api/v1/ai/workflows/executions         - List executions
    GET  /api/v1/ai/workflows/executions/{id}    - Get execution details
    POST /api/v1/ai/workflows/executions/{id}/cancel - Cancel execution

    # Approvals
    GET  /api/v1/ai/workflows/approvals          - List pending approvals
    POST /api/v1/ai/workflows/approvals/{id}/respond - Respond to approval
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from example_service.core.database import get_async_session
from example_service.features.auth.dependencies import get_current_user
from example_service.features.users.models import User
from example_service.infra.ai.agents.workflow_models import (
    AIWorkflowApproval,
    AIWorkflowDefinition,
    AIWorkflowExecution,
    AIWorkflowNodeExecution,
    WorkflowStatus,
)

router = APIRouter(prefix="/workflows", tags=["AI Workflows"])


# =============================================================================
# Request/Response Schemas
# =============================================================================


class NodeDefinitionSchema(BaseModel):
    """Schema for a workflow node definition."""

    name: str
    type: str  # function, human_approval, conditional, parallel
    config: dict[str, Any] = Field(default_factory=dict)


class WorkflowDefinitionCreate(BaseModel):
    """Request to create a workflow definition."""

    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    version: str = "1.0.0"

    nodes: dict[str, NodeDefinitionSchema] = Field(default_factory=dict)
    edges: dict[str, list[str]] = Field(default_factory=dict)
    entry_point: str
    end_nodes: list[str] = Field(default_factory=list)

    default_config: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int | None = None
    max_retries: int = 0
    tags: list[str] = Field(default_factory=list)


class WorkflowDefinitionUpdate(BaseModel):
    """Request to update a workflow definition."""

    name: str | None = None
    description: str | None = None
    version: str | None = None

    nodes: dict[str, Any] | None = None
    edges: dict[str, list[str]] | None = None
    entry_point: str | None = None
    end_nodes: list[str] | None = None

    default_config: dict[str, Any] | None = None
    timeout_seconds: int | None = None
    max_retries: int | None = None
    tags: list[str] | None = None
    is_active: bool | None = None


class WorkflowDefinitionResponse(BaseModel):
    """Response for a workflow definition."""

    id: UUID
    tenant_id: UUID
    name: str
    slug: str
    description: str | None
    version: str

    nodes: dict[str, Any]
    edges: dict[str, list[str]]
    entry_point: str
    end_nodes: list[str]

    default_config: dict[str, Any]
    timeout_seconds: int | None
    max_retries: int
    tags: list[str]
    is_active: bool

    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class WorkflowExecuteRequest(BaseModel):
    """Request to execute a workflow."""

    input_data: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str | None = None
    tags: list[str] = Field(default_factory=list)


class WorkflowExecutionResponse(BaseModel):
    """Response for a workflow execution."""

    id: UUID
    definition_id: UUID
    tenant_id: UUID
    status: str
    current_node: str | None
    executed_nodes: list[str]

    input_data: dict[str, Any]
    state_data: dict[str, Any]
    output_data: dict[str, Any] | None

    error: str | None
    error_code: str | None
    failed_node: str | None

    started_at: datetime | None
    completed_at: datetime | None
    duration_seconds: float | None

    total_cost_usd: float
    total_tokens: int
    retry_count: int

    created_at: datetime

    # Include pending approvals count
    pending_approvals_count: int = 0

    class Config:
        from_attributes = True


class WorkflowExecutionListResponse(BaseModel):
    """Response for listing workflow executions."""

    executions: list[WorkflowExecutionResponse]
    total_count: int
    page: int
    page_size: int
    has_next: bool


class NodeExecutionResponse(BaseModel):
    """Response for a node execution."""

    id: UUID
    node_name: str
    node_type: str
    status: str
    execution_order: int

    input_data: dict[str, Any]
    output_data: dict[str, Any] | None

    error: str | None
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: float | None
    attempt_number: int

    class Config:
        from_attributes = True


class ApprovalResponse(BaseModel):
    """Response for an approval request."""

    id: UUID
    workflow_execution_id: UUID
    node_name: str
    prompt: str
    options: list[str]
    context: dict[str, Any]

    is_pending: bool
    response: str | None
    response_data: dict[str, Any] | None
    responded_at: datetime | None

    created_at: datetime
    expires_at: datetime | None
    is_expired: bool

    class Config:
        from_attributes = True


class ApprovalRespondRequest(BaseModel):
    """Request to respond to an approval."""

    response: str
    response_data: dict[str, Any] | None = None
    comment: str | None = None


# =============================================================================
# Workflow Definition Endpoints
# =============================================================================


@router.get("", response_model=list[WorkflowDefinitionResponse])
async def list_workflow_definitions(
    is_active: bool | None = Query(None, description="Filter by active status"),
    tag: str | None = Query(None, description="Filter by tag"),
    search: str | None = Query(None, description="Search in name/description"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> list[WorkflowDefinitionResponse]:
    """List workflow definitions for the tenant."""
    query = select(AIWorkflowDefinition).where(
        AIWorkflowDefinition.tenant_id == current_user.tenant_id
    )

    if is_active is not None:
        query = query.where(AIWorkflowDefinition.is_active == is_active)

    if tag:
        query = query.where(AIWorkflowDefinition.tags.contains([tag]))

    if search:
        query = query.where(
            AIWorkflowDefinition.name.ilike(f"%{search}%")
            | AIWorkflowDefinition.description.ilike(f"%{search}%")
        )

    query = query.order_by(AIWorkflowDefinition.updated_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await session.execute(query)
    definitions = result.scalars().all()

    return [WorkflowDefinitionResponse.model_validate(d) for d in definitions]


@router.post("", response_model=WorkflowDefinitionResponse, status_code=201)
async def create_workflow_definition(
    request: WorkflowDefinitionCreate,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowDefinitionResponse:
    """Create a new workflow definition."""
    # Check for duplicate slug
    existing = await session.execute(
        select(AIWorkflowDefinition).where(
            and_(
                AIWorkflowDefinition.tenant_id == current_user.tenant_id,
                AIWorkflowDefinition.slug == request.slug,
            )
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Workflow with slug '{request.slug}' already exists",
        )

    # Validate entry point
    if request.entry_point not in request.nodes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Entry point '{request.entry_point}' not found in nodes",
        )

    definition = AIWorkflowDefinition(
        tenant_id=current_user.tenant_id,
        name=request.name,
        slug=request.slug,
        description=request.description,
        version=request.version,
        nodes={k: v.model_dump() for k, v in request.nodes.items()},
        edges=request.edges,
        entry_point=request.entry_point,
        end_nodes=request.end_nodes,
        default_config=request.default_config,
        timeout_seconds=request.timeout_seconds,
        max_retries=request.max_retries,
        tags=request.tags,
        created_by_id=current_user.id,
    )

    session.add(definition)
    await session.flush()
    await session.refresh(definition)

    return WorkflowDefinitionResponse.model_validate(definition)


@router.get("/{definition_id}", response_model=WorkflowDefinitionResponse)
async def get_workflow_definition(
    definition_id: UUID,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowDefinitionResponse:
    """Get a workflow definition by ID."""
    result = await session.execute(
        select(AIWorkflowDefinition).where(AIWorkflowDefinition.id == definition_id)
    )
    definition = result.scalar_one_or_none()

    if not definition:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow definition {definition_id} not found",
        )

    if definition.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    return WorkflowDefinitionResponse.model_validate(definition)


@router.put("/{definition_id}", response_model=WorkflowDefinitionResponse)
async def update_workflow_definition(
    definition_id: UUID,
    request: WorkflowDefinitionUpdate,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowDefinitionResponse:
    """Update a workflow definition."""
    result = await session.execute(
        select(AIWorkflowDefinition).where(AIWorkflowDefinition.id == definition_id)
    )
    definition = result.scalar_one_or_none()

    if not definition:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow definition {definition_id} not found",
        )

    if definition.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    # Update fields
    update_data = request.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(definition, field, value)

    await session.flush()
    await session.refresh(definition)

    return WorkflowDefinitionResponse.model_validate(definition)


@router.delete("/{definition_id}", status_code=204)
async def delete_workflow_definition(
    definition_id: UUID,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete a workflow definition."""
    result = await session.execute(
        select(AIWorkflowDefinition).where(AIWorkflowDefinition.id == definition_id)
    )
    definition = result.scalar_one_or_none()

    if not definition:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow definition {definition_id} not found",
        )

    if definition.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    await session.delete(definition)
    await session.flush()


# =============================================================================
# Workflow Execution Endpoints
# =============================================================================


@router.post("/{definition_id}/execute", response_model=WorkflowExecutionResponse, status_code=201)
async def execute_workflow(
    definition_id: UUID,
    request: WorkflowExecuteRequest,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowExecutionResponse:
    """Execute a workflow definition."""
    # Get definition
    result = await session.execute(
        select(AIWorkflowDefinition).where(AIWorkflowDefinition.id == definition_id)
    )
    definition = result.scalar_one_or_none()

    if not definition:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow definition {definition_id} not found",
        )

    if definition.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    if not definition.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Workflow definition is not active",
        )

    # Create execution
    execution = AIWorkflowExecution(
        definition_id=definition.id,
        tenant_id=current_user.tenant_id,
        status=WorkflowStatus.PENDING.value,
        current_node=definition.entry_point,
        input_data=request.input_data,
        state_data=request.input_data.copy(),
        config={**definition.default_config, **request.config},
        correlation_id=request.correlation_id,
        tags=request.tags,
        created_by_id=current_user.id,
    )

    session.add(execution)
    await session.flush()
    await session.refresh(execution)

    # Note: Actual execution would be triggered via background task/queue
    # Here we just create the execution record

    return _execution_to_response(execution)


@router.get("/executions", response_model=WorkflowExecutionListResponse)
async def list_workflow_executions(
    definition_id: UUID | None = Query(None, description="Filter by definition"),
    status_filter: str | None = Query(None, alias="status", description="Filter by status"),
    start_date: datetime | None = Query(None, description="Filter by start date"),
    end_date: datetime | None = Query(None, description="Filter by end date"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowExecutionListResponse:
    """List workflow executions for the tenant."""
    query = select(AIWorkflowExecution).where(
        AIWorkflowExecution.tenant_id == current_user.tenant_id
    )

    if definition_id:
        query = query.where(AIWorkflowExecution.definition_id == definition_id)

    if status_filter:
        query = query.where(AIWorkflowExecution.status == status_filter)

    if start_date:
        query = query.where(AIWorkflowExecution.created_at >= start_date)

    if end_date:
        query = query.where(AIWorkflowExecution.created_at <= end_date)

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_count = await session.scalar(count_query) or 0

    # Get page
    query = query.order_by(AIWorkflowExecution.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await session.execute(query)
    executions = result.scalars().all()

    return WorkflowExecutionListResponse(
        executions=[_execution_to_response(e) for e in executions],
        total_count=total_count,
        page=page,
        page_size=page_size,
        has_next=page * page_size < total_count,
    )


@router.get("/executions/{execution_id}", response_model=WorkflowExecutionResponse)
async def get_workflow_execution(
    execution_id: UUID,
    include_nodes: bool = Query(True, description="Include node executions"),
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowExecutionResponse:
    """Get workflow execution details."""
    result = await session.execute(
        select(AIWorkflowExecution).where(AIWorkflowExecution.id == execution_id)
    )
    execution = result.scalar_one_or_none()

    if not execution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow execution {execution_id} not found",
        )

    if execution.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    return _execution_to_response(execution)


@router.get("/executions/{execution_id}/nodes", response_model=list[NodeExecutionResponse])
async def get_workflow_execution_nodes(
    execution_id: UUID,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> list[NodeExecutionResponse]:
    """Get node executions for a workflow execution."""
    # Verify access
    result = await session.execute(
        select(AIWorkflowExecution).where(AIWorkflowExecution.id == execution_id)
    )
    execution = result.scalar_one_or_none()

    if not execution or execution.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow execution {execution_id} not found",
        )

    # Get nodes
    result = await session.execute(
        select(AIWorkflowNodeExecution)
        .where(AIWorkflowNodeExecution.workflow_execution_id == execution_id)
        .order_by(AIWorkflowNodeExecution.execution_order)
    )
    nodes = result.scalars().all()

    return [
        NodeExecutionResponse(
            id=n.id,
            node_name=n.node_name,
            node_type=n.node_type,
            status=n.status,
            execution_order=n.execution_order,
            input_data=n.input_data,
            output_data=n.output_data,
            error=n.error,
            started_at=n.started_at,
            completed_at=n.completed_at,
            duration_ms=n.duration_ms,
            attempt_number=n.attempt_number,
        )
        for n in nodes
    ]


@router.post("/executions/{execution_id}/cancel", response_model=WorkflowExecutionResponse)
async def cancel_workflow_execution(
    execution_id: UUID,
    reason: str = Query("User cancelled", description="Cancellation reason"),
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowExecutionResponse:
    """Cancel a workflow execution."""
    result = await session.execute(
        select(AIWorkflowExecution).where(AIWorkflowExecution.id == execution_id)
    )
    execution = result.scalar_one_or_none()

    if not execution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow execution {execution_id} not found",
        )

    if execution.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    if execution.status not in (
        WorkflowStatus.PENDING.value,
        WorkflowStatus.RUNNING.value,
        WorkflowStatus.WAITING_APPROVAL.value,
        WorkflowStatus.PAUSED.value,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel execution in status: {execution.status}",
        )

    execution.status = WorkflowStatus.CANCELLED.value
    execution.error = reason
    execution.completed_at = datetime.now(UTC)

    await session.flush()
    await session.refresh(execution)

    return _execution_to_response(execution)


# =============================================================================
# Approval Endpoints
# =============================================================================


@router.get("/approvals", response_model=list[ApprovalResponse])
async def list_pending_approvals(
    execution_id: UUID | None = Query(None, description="Filter by execution"),
    include_expired: bool = Query(False, description="Include expired approvals"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> list[ApprovalResponse]:
    """List pending approval requests."""
    query = (
        select(AIWorkflowApproval)
        .join(AIWorkflowExecution)
        .where(AIWorkflowExecution.tenant_id == current_user.tenant_id)
    )

    if not include_expired:
        query = query.where(AIWorkflowApproval.is_pending == True)  # noqa: E712

    if execution_id:
        query = query.where(AIWorkflowApproval.workflow_execution_id == execution_id)

    query = query.order_by(AIWorkflowApproval.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await session.execute(query)
    approvals = result.scalars().all()

    return [
        ApprovalResponse(
            id=a.id,
            workflow_execution_id=a.workflow_execution_id,
            node_name=a.node_name,
            prompt=a.prompt,
            options=a.options,
            context=a.context,
            is_pending=a.is_pending,
            response=a.response,
            response_data=a.response_data,
            responded_at=a.responded_at,
            created_at=a.created_at,
            expires_at=a.expires_at,
            is_expired=a.is_expired,
        )
        for a in approvals
    ]


@router.post("/approvals/{approval_id}/respond", response_model=ApprovalResponse)
async def respond_to_approval(
    approval_id: UUID,
    request: ApprovalRespondRequest,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> ApprovalResponse:
    """Respond to an approval request."""
    result = await session.execute(
        select(AIWorkflowApproval)
        .join(AIWorkflowExecution)
        .where(
            and_(
                AIWorkflowApproval.id == approval_id,
                AIWorkflowExecution.tenant_id == current_user.tenant_id,
            )
        )
    )
    approval = result.scalar_one_or_none()

    if not approval:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Approval request {approval_id} not found",
        )

    if not approval.is_pending:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Approval has already been responded to",
        )

    if approval.is_expired:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Approval request has expired",
        )

    if request.response not in approval.options:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid response. Must be one of: {approval.options}",
        )

    # Update approval
    approval.is_pending = False
    approval.response = request.response
    approval.response_data = request.response_data
    approval.response_comment = request.comment
    approval.responded_by_id = current_user.id
    approval.responded_at = datetime.now(UTC)

    await session.flush()
    await session.refresh(approval)

    # Note: Workflow continuation would be triggered via background task
    # based on the approval response

    return ApprovalResponse(
        id=approval.id,
        workflow_execution_id=approval.workflow_execution_id,
        node_name=approval.node_name,
        prompt=approval.prompt,
        options=approval.options,
        context=approval.context,
        is_pending=approval.is_pending,
        response=approval.response,
        response_data=approval.response_data,
        responded_at=approval.responded_at,
        created_at=approval.created_at,
        expires_at=approval.expires_at,
        is_expired=approval.is_expired,
    )


# =============================================================================
# Helper Functions
# =============================================================================


def _execution_to_response(execution: AIWorkflowExecution) -> WorkflowExecutionResponse:
    """Convert execution to response model."""
    pending_count = len([a for a in execution.approvals if a.is_pending])

    return WorkflowExecutionResponse(
        id=execution.id,
        definition_id=execution.definition_id,
        tenant_id=execution.tenant_id,
        status=execution.status,
        current_node=execution.current_node,
        executed_nodes=execution.executed_nodes,
        input_data=execution.input_data,
        state_data=execution.state_data,
        output_data=execution.output_data,
        error=execution.error,
        error_code=execution.error_code,
        failed_node=execution.failed_node,
        started_at=execution.started_at,
        completed_at=execution.completed_at,
        duration_seconds=execution.duration_seconds,
        total_cost_usd=execution.total_cost_usd,
        total_tokens=execution.total_tokens,
        retry_count=execution.retry_count,
        created_at=execution.created_at,
        pending_approvals_count=pending_count,
    )
