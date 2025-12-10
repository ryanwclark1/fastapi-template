"""GraphQL types for AI Workflow feature.

Provides:
- WorkflowDefinitionType: GraphQL representation of a workflow template
- WorkflowExecutionType: GraphQL representation of a workflow execution
- WorkflowNodeExecutionType: GraphQL representation of node execution
- WorkflowApprovalType: GraphQL representation of human approval requests
- Input types for creating/managing workflows
- Connection types for pagination
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Annotated

import strawberry
from strawberry.scalars import JSON

from example_service.features.graphql.types.base import PageInfoType

if TYPE_CHECKING:
    from example_service.infra.ai.agents.workflow_models import (
        AIWorkflowApproval,
        AIWorkflowDefinition,
        AIWorkflowExecution,
        AIWorkflowNodeExecution,
    )


# --- Enums ---


@strawberry.enum(description="Status of a workflow execution")
class WorkflowStatusEnum(Enum):
    """Workflow execution status enum."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


@strawberry.enum(description="Status of a workflow node execution")
class WorkflowNodeStatusEnum(Enum):
    """Workflow node execution status enum."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    WAITING_APPROVAL = "waiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"


@strawberry.enum(description="Type of workflow node")
class WorkflowNodeTypeEnum(Enum):
    """Workflow node type enum."""

    FUNCTION = "function"
    HUMAN_APPROVAL = "human_approval"
    CONDITIONAL = "conditional"
    PARALLEL = "parallel"
    SUBWORKFLOW = "subworkflow"


# --- Output Types ---


@strawberry.type(description="Workflow definition template")
class WorkflowDefinitionType:
    """GraphQL type for Workflow Definition entity."""

    id: strawberry.ID = strawberry.field(description="Unique identifier (UUID)")
    tenant_id: str = strawberry.field(description="Tenant identifier")
    name: str = strawberry.field(description="Workflow name")
    slug: str = strawberry.field(description="URL-friendly slug")
    description: str | None = strawberry.field(description="Workflow description")
    version: str = strawberry.field(description="Workflow version")
    nodes: JSON = strawberry.field(description="Node definitions")
    edges: JSON = strawberry.field(description="Edge connections between nodes")
    entry_point: str = strawberry.field(description="Entry node name")
    end_nodes: list[str] = strawberry.field(description="Terminal node names")
    default_config: JSON = strawberry.field(description="Default configuration")
    timeout_seconds: int | None = strawberry.field(description="Execution timeout")
    max_retries: int = strawberry.field(description="Maximum retry attempts")
    tags: list[str] = strawberry.field(description="Workflow tags")
    is_active: bool = strawberry.field(description="Whether workflow is active")
    is_public: bool = strawberry.field(description="Whether workflow is public")
    created_at: datetime = strawberry.field(description="Creation timestamp")
    updated_at: datetime = strawberry.field(description="Last update timestamp")
    created_by_id: strawberry.ID | None = strawberry.field(
        description="Creator user ID"
    )

    @classmethod
    def from_model(cls, definition: AIWorkflowDefinition) -> WorkflowDefinitionType:
        """Convert SQLAlchemy model to GraphQL type."""
        return cls(
            id=strawberry.ID(str(definition.id)),
            tenant_id=str(definition.tenant_id),
            name=definition.name,
            slug=definition.slug,
            description=definition.description,
            version=definition.version,
            nodes=definition.nodes,
            edges=definition.edges,
            entry_point=definition.entry_point,
            end_nodes=definition.end_nodes,
            default_config=definition.default_config,
            timeout_seconds=definition.timeout_seconds,
            max_retries=definition.max_retries,
            tags=definition.tags,
            is_active=definition.is_active,
            is_public=definition.is_public,
            created_at=definition.created_at,
            updated_at=definition.updated_at,
            created_by_id=(
                strawberry.ID(str(definition.created_by_id))
                if definition.created_by_id
                else None
            ),
        )


@strawberry.type(description="Workflow execution instance")
class WorkflowExecutionType:
    """GraphQL type for Workflow Execution entity."""

    id: strawberry.ID = strawberry.field(description="Unique identifier (UUID)")
    definition_id: strawberry.ID = strawberry.field(
        description="Workflow definition ID"
    )
    tenant_id: str = strawberry.field(description="Tenant identifier")
    status: WorkflowStatusEnum = strawberry.field(description="Execution status")
    current_node: str | None = strawberry.field(description="Currently executing node")
    executed_nodes: list[str] = strawberry.field(
        description="Nodes that have been executed"
    )
    input_data: JSON = strawberry.field(description="Execution input data")
    state_data: JSON = strawberry.field(description="Current state data")
    output_data: JSON | None = strawberry.field(description="Execution output")
    config: JSON = strawberry.field(description="Execution configuration")
    error: str | None = strawberry.field(description="Error message if failed")
    error_code: str | None = strawberry.field(description="Error code if failed")
    failed_node: str | None = strawberry.field(description="Node that failed")
    started_at: datetime | None = strawberry.field(description="When execution started")
    completed_at: datetime | None = strawberry.field(
        description="When execution completed"
    )
    paused_at: datetime | None = strawberry.field(
        description="When execution was paused"
    )
    total_cost_usd: float = strawberry.field(description="Total cost in USD")
    total_tokens: int = strawberry.field(description="Total tokens consumed")
    retry_count: int = strawberry.field(description="Number of retries")
    correlation_id: str | None = strawberry.field(
        description="Correlation ID for tracing"
    )
    tags: list[str] = strawberry.field(description="Execution tags")
    metadata: JSON = strawberry.field(description="Additional metadata")
    created_at: datetime = strawberry.field(description="Creation timestamp")
    updated_at: datetime = strawberry.field(description="Last update timestamp")
    created_by_id: strawberry.ID | None = strawberry.field(
        description="User who started execution"
    )
    duration_seconds: float | None = strawberry.field(
        description="Total duration in seconds"
    )

    @classmethod
    def from_model(cls, execution: AIWorkflowExecution) -> WorkflowExecutionType:
        """Convert SQLAlchemy model to GraphQL type."""
        return cls(
            id=strawberry.ID(str(execution.id)),
            definition_id=strawberry.ID(str(execution.definition_id)),
            tenant_id=str(execution.tenant_id),
            status=WorkflowStatusEnum(execution.status),
            current_node=execution.current_node,
            executed_nodes=execution.executed_nodes,
            input_data=execution.input_data,
            state_data=execution.state_data,
            output_data=execution.output_data,
            config=execution.config,
            error=execution.error,
            error_code=execution.error_code,
            failed_node=execution.failed_node,
            started_at=execution.started_at,
            completed_at=execution.completed_at,
            paused_at=execution.paused_at,
            total_cost_usd=execution.total_cost_usd,
            total_tokens=execution.total_tokens,
            retry_count=execution.retry_count,
            correlation_id=execution.correlation_id,
            tags=execution.tags,
            metadata=execution.extra_metadata,
            created_at=execution.created_at,
            updated_at=execution.updated_at,
            created_by_id=(
                strawberry.ID(str(execution.created_by_id))
                if execution.created_by_id
                else None
            ),
            duration_seconds=execution.duration_seconds,
        )


@strawberry.type(description="Workflow node execution record")
class WorkflowNodeExecutionType:
    """GraphQL type for Workflow Node Execution entity."""

    id: strawberry.ID = strawberry.field(description="Unique identifier (UUID)")
    workflow_execution_id: strawberry.ID = strawberry.field(
        description="Parent execution ID"
    )
    node_name: str = strawberry.field(description="Name of the node")
    node_type: WorkflowNodeTypeEnum = strawberry.field(description="Type of node")
    status: WorkflowNodeStatusEnum = strawberry.field(description="Execution status")
    execution_order: int = strawberry.field(description="Order of execution")
    input_data: JSON = strawberry.field(description="Node input data")
    output_data: JSON | None = strawberry.field(description="Node output data")
    error: str | None = strawberry.field(description="Error message if failed")
    error_code: str | None = strawberry.field(description="Error code if failed")
    started_at: datetime | None = strawberry.field(description="When node started")
    completed_at: datetime | None = strawberry.field(description="When node completed")
    attempt_number: int = strawberry.field(description="Retry attempt number")
    metadata: JSON = strawberry.field(description="Additional metadata")
    duration_ms: float | None = strawberry.field(description="Duration in milliseconds")

    @classmethod
    def from_model(
        cls, node_exec: AIWorkflowNodeExecution
    ) -> WorkflowNodeExecutionType:
        """Convert SQLAlchemy model to GraphQL type."""
        return cls(
            id=strawberry.ID(str(node_exec.id)),
            workflow_execution_id=strawberry.ID(str(node_exec.workflow_execution_id)),
            node_name=node_exec.node_name,
            node_type=WorkflowNodeTypeEnum(node_exec.node_type),
            status=WorkflowNodeStatusEnum(node_exec.status),
            execution_order=node_exec.execution_order,
            input_data=node_exec.input_data,
            output_data=node_exec.output_data,
            error=node_exec.error,
            error_code=node_exec.error_code,
            started_at=node_exec.started_at,
            completed_at=node_exec.completed_at,
            attempt_number=node_exec.attempt_number,
            metadata=node_exec.extra_metadata,
            duration_ms=node_exec.duration_ms,
        )


@strawberry.type(description="Human approval request")
class WorkflowApprovalType:
    """GraphQL type for Workflow Approval entity."""

    id: strawberry.ID = strawberry.field(description="Unique identifier (UUID)")
    workflow_execution_id: strawberry.ID = strawberry.field(
        description="Parent execution ID"
    )
    node_name: str = strawberry.field(description="Approval node name")
    prompt: str = strawberry.field(description="Approval prompt message")
    options: list[str] = strawberry.field(description="Available response options")
    context: JSON = strawberry.field(description="Contextual data for approval")
    is_pending: bool = strawberry.field(description="Whether approval is pending")
    timeout_seconds: int | None = strawberry.field(description="Approval timeout")
    response: str | None = strawberry.field(description="Response choice")
    response_data: JSON | None = strawberry.field(
        description="Additional response data"
    )
    response_comment: str | None = strawberry.field(description="Approver's comment")
    responded_by_id: strawberry.ID | None = strawberry.field(
        description="User who responded"
    )
    responded_at: datetime | None = strawberry.field(
        description="When response was given"
    )
    created_at: datetime = strawberry.field(description="When approval was created")
    expires_at: datetime | None = strawberry.field(description="When approval expires")
    is_expired: bool = strawberry.field(description="Whether approval has expired")
    metadata: JSON = strawberry.field(description="Additional metadata")

    @classmethod
    def from_model(cls, approval: AIWorkflowApproval) -> WorkflowApprovalType:
        """Convert SQLAlchemy model to GraphQL type."""
        return cls(
            id=strawberry.ID(str(approval.id)),
            workflow_execution_id=strawberry.ID(str(approval.workflow_execution_id)),
            node_name=approval.node_name,
            prompt=approval.prompt,
            options=approval.options,
            context=approval.context,
            is_pending=approval.is_pending,
            timeout_seconds=approval.timeout_seconds,
            response=approval.response,
            response_data=approval.response_data,
            response_comment=approval.response_comment,
            responded_by_id=(
                strawberry.ID(str(approval.responded_by_id))
                if approval.responded_by_id
                else None
            ),
            responded_at=approval.responded_at,
            created_at=approval.created_at,
            expires_at=approval.expires_at,
            is_expired=approval.is_expired,
            metadata=approval.extra_metadata,
        )


@strawberry.type(description="Workflow execution statistics")
class WorkflowStatsType:
    """Aggregated workflow execution statistics."""

    total_definitions: int = strawberry.field(description="Total workflow definitions")
    total_executions: int = strawberry.field(description="Total executions")
    completed_executions: int = strawberry.field(description="Completed executions")
    failed_executions: int = strawberry.field(description="Failed executions")
    running_executions: int = strawberry.field(description="Currently running")
    pending_approvals: int = strawberry.field(description="Pending approval requests")
    total_cost_usd: float = strawberry.field(description="Total cost in USD")
    total_tokens: int = strawberry.field(description="Total tokens consumed")
    avg_duration_seconds: float | None = strawberry.field(
        description="Average execution duration"
    )
    executions_by_status: JSON = strawberry.field(description="Breakdown by status")
    executions_by_workflow: JSON = strawberry.field(description="Breakdown by workflow")


# --- Input Types ---


@strawberry.input(description="Input for creating a workflow definition")
class CreateWorkflowDefinitionInput:
    """Input for createWorkflowDefinition mutation."""

    name: str = strawberry.field(description="Workflow name")
    slug: str = strawberry.field(description="URL-friendly slug")
    description: str | None = strawberry.field(
        default=None, description="Workflow description"
    )
    version: str = strawberry.field(default="1.0.0", description="Workflow version")
    nodes: JSON = strawberry.field(description="Node definitions")
    edges: JSON = strawberry.field(description="Edge connections")
    entry_point: str = strawberry.field(description="Entry node name")
    end_nodes: list[str] = strawberry.field(description="Terminal node names")
    default_config: JSON | None = strawberry.field(
        default=None, description="Default config"
    )
    timeout_seconds: int | None = strawberry.field(default=None, description="Timeout")
    max_retries: int = strawberry.field(default=0, description="Max retries")
    tags: list[str] | None = strawberry.field(default=None, description="Tags")
    is_public: bool = strawberry.field(default=False, description="Is public")


@strawberry.input(description="Input for updating a workflow definition")
class UpdateWorkflowDefinitionInput:
    """Input for updateWorkflowDefinition mutation."""

    name: str | None = strawberry.field(default=None, description="Workflow name")
    description: str | None = strawberry.field(default=None, description="Description")
    version: str | None = strawberry.field(default=None, description="Version")
    nodes: JSON | None = strawberry.field(default=None, description="Node definitions")
    edges: JSON | None = strawberry.field(default=None, description="Edge connections")
    entry_point: str | None = strawberry.field(default=None, description="Entry node")
    end_nodes: list[str] | None = strawberry.field(
        default=None, description="End nodes"
    )
    default_config: JSON | None = strawberry.field(
        default=None, description="Default config"
    )
    timeout_seconds: int | None = strawberry.field(default=None, description="Timeout")
    max_retries: int | None = strawberry.field(default=None, description="Max retries")
    tags: list[str] | None = strawberry.field(default=None, description="Tags")
    is_active: bool | None = strawberry.field(default=None, description="Is active")
    is_public: bool | None = strawberry.field(default=None, description="Is public")


@strawberry.input(description="Input for executing a workflow")
class ExecuteWorkflowInput:
    """Input for executeWorkflow mutation."""

    definition_id: strawberry.ID = strawberry.field(
        description="Workflow definition ID"
    )
    input_data: JSON = strawberry.field(description="Execution input data")
    config: JSON | None = strawberry.field(default=None, description="Config overrides")
    correlation_id: str | None = strawberry.field(
        default=None, description="Correlation ID"
    )
    tags: list[str] | None = strawberry.field(
        default=None, description="Execution tags"
    )


@strawberry.input(description="Input for responding to an approval")
class RespondToApprovalInput:
    """Input for respondToApproval mutation."""

    approval_id: strawberry.ID = strawberry.field(description="Approval request ID")
    response: str = strawberry.field(description="Response choice (approve/reject)")
    response_data: JSON | None = strawberry.field(
        default=None, description="Additional data"
    )
    comment: str | None = strawberry.field(default=None, description="Approver comment")


@strawberry.input(description="Filter for workflow definitions query")
class WorkflowDefinitionFilterInput:
    """Filter input for workflow definitions query."""

    is_active: bool | None = strawberry.field(
        default=None, description="Filter by active"
    )
    is_public: bool | None = strawberry.field(
        default=None, description="Filter by public"
    )
    tags: list[str] | None = strawberry.field(
        default=None, description="Filter by tags"
    )
    search: str | None = strawberry.field(
        default=None, description="Search name/description"
    )


@strawberry.input(description="Filter for workflow executions query")
class WorkflowExecutionFilterInput:
    """Filter input for workflow executions query."""

    definition_id: strawberry.ID | None = strawberry.field(
        default=None, description="Filter by workflow"
    )
    status: WorkflowStatusEnum | None = strawberry.field(
        default=None, description="Filter by status"
    )
    created_after: datetime | None = strawberry.field(
        default=None, description="Created after"
    )
    created_before: datetime | None = strawberry.field(
        default=None, description="Created before"
    )
    tags: list[str] | None = strawberry.field(
        default=None, description="Filter by tags"
    )


@strawberry.input(description="Filter for workflow approvals query")
class WorkflowApprovalFilterInput:
    """Filter input for workflow approvals query."""

    is_pending: bool | None = strawberry.field(
        default=None, description="Filter by pending"
    )
    execution_id: strawberry.ID | None = strawberry.field(
        default=None, description="Filter by execution"
    )


# --- Payload Types ---


@strawberry.type(description="Successful workflow definition operation result")
class WorkflowDefinitionSuccess:
    """Success payload for workflow definition mutations."""

    definition: WorkflowDefinitionType = strawberry.field(
        description="The workflow definition"
    )


@strawberry.type(description="Successful workflow execution operation result")
class WorkflowExecutionSuccess:
    """Success payload for workflow execution mutations."""

    execution: WorkflowExecutionType = strawberry.field(
        description="The workflow execution"
    )


@strawberry.type(description="Successful approval response result")
class WorkflowApprovalSuccess:
    """Success payload for approval mutations."""

    approval: WorkflowApprovalType = strawberry.field(
        description="The approval request"
    )


@strawberry.type(description="Error result from a workflow operation")
class WorkflowError:
    """Error payload for workflow mutations."""

    code: str = strawberry.field(description="Error code")
    message: str = strawberry.field(description="Human-readable error message")
    field: str | None = strawberry.field(
        default=None, description="Field that caused the error"
    )


WorkflowDefinitionPayload = Annotated[
    WorkflowDefinitionSuccess | WorkflowError,
    strawberry.union(
        name="WorkflowDefinitionPayload",
        description="Result of a workflow definition mutation",
    ),
]

WorkflowExecutionPayload = Annotated[
    WorkflowExecutionSuccess | WorkflowError,
    strawberry.union(
        name="WorkflowExecutionPayload",
        description="Result of a workflow execution mutation",
    ),
]

WorkflowApprovalPayload = Annotated[
    WorkflowApprovalSuccess | WorkflowError,
    strawberry.union(
        name="WorkflowApprovalPayload",
        description="Result of an approval mutation",
    ),
]


# --- Connection Types ---


@strawberry.type(description="Edge containing a workflow definition and its cursor")
class WorkflowDefinitionEdge:
    """Edge wrapper for paginated workflow definitions."""

    node: WorkflowDefinitionType = strawberry.field(
        description="The workflow definition"
    )
    cursor: str = strawberry.field(description="Cursor for this item")


@strawberry.type(description="Paginated connection of workflow definitions")
class WorkflowDefinitionConnection:
    """GraphQL Connection for cursor-paginated workflow definitions."""

    edges: list[WorkflowDefinitionEdge] = strawberry.field(description="List of edges")
    page_info: PageInfoType = strawberry.field(description="Pagination metadata")


@strawberry.type(description="Edge containing a workflow execution and its cursor")
class WorkflowExecutionEdge:
    """Edge wrapper for paginated workflow executions."""

    node: WorkflowExecutionType = strawberry.field(description="The workflow execution")
    cursor: str = strawberry.field(description="Cursor for this item")


@strawberry.type(description="Paginated connection of workflow executions")
class WorkflowExecutionConnection:
    """GraphQL Connection for cursor-paginated workflow executions."""

    edges: list[WorkflowExecutionEdge] = strawberry.field(description="List of edges")
    page_info: PageInfoType = strawberry.field(description="Pagination metadata")


@strawberry.type(description="Edge containing a workflow approval and its cursor")
class WorkflowApprovalEdge:
    """Edge wrapper for paginated workflow approvals."""

    node: WorkflowApprovalType = strawberry.field(description="The approval request")
    cursor: str = strawberry.field(description="Cursor for this item")


@strawberry.type(description="Paginated connection of workflow approvals")
class WorkflowApprovalConnection:
    """GraphQL Connection for cursor-paginated workflow approvals."""

    edges: list[WorkflowApprovalEdge] = strawberry.field(description="List of edges")
    page_info: PageInfoType = strawberry.field(description="Pagination metadata")


__all__ = [
    # Enums
    "WorkflowNodeStatusEnum",
    "WorkflowNodeTypeEnum",
    "WorkflowStatusEnum",
    # Output types
    "WorkflowApprovalType",
    "WorkflowDefinitionType",
    "WorkflowExecutionType",
    "WorkflowNodeExecutionType",
    "WorkflowStatsType",
    # Input types
    "CreateWorkflowDefinitionInput",
    "ExecuteWorkflowInput",
    "RespondToApprovalInput",
    "UpdateWorkflowDefinitionInput",
    "WorkflowApprovalFilterInput",
    "WorkflowDefinitionFilterInput",
    "WorkflowExecutionFilterInput",
    # Payload types
    "WorkflowApprovalPayload",
    "WorkflowApprovalSuccess",
    "WorkflowDefinitionPayload",
    "WorkflowDefinitionSuccess",
    "WorkflowError",
    "WorkflowExecutionPayload",
    "WorkflowExecutionSuccess",
    # Connection types
    "WorkflowApprovalConnection",
    "WorkflowApprovalEdge",
    "WorkflowDefinitionConnection",
    "WorkflowDefinitionEdge",
    "WorkflowExecutionConnection",
    "WorkflowExecutionEdge",
]
