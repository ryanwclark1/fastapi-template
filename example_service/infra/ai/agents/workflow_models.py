"""Database models for AI Workflow framework.

This module provides persistent storage for workflow definitions and executions:
- Reusable workflow definitions
- Workflow execution tracking
- Node execution history
- Human approval tracking
- Workflow state snapshots

Models:
- AIWorkflowDefinition: Reusable workflow templates
- AIWorkflowExecution: Running workflow instances
- AIWorkflowNodeExecution: Individual node executions
- AIWorkflowApproval: Human approval requests and responses
"""

from __future__ import annotations

from datetime import UTC, datetime
import enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from example_service.core.database.base import Base
from example_service.core.database.enums import (
    AIWorkflowNodeStatus,
    AIWorkflowNodeType,
    AIWorkflowStatus,
)
from example_service.core.models.tenant import Tenant
from example_service.core.models.user import User


class WorkflowStatus(str, enum.Enum):
    """Status of a workflow execution."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class WorkflowNodeStatus(str, enum.Enum):
    """Status of a workflow node execution."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    WAITING_APPROVAL = "waiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"


class WorkflowNodeType(str, enum.Enum):
    """Type of workflow node."""

    FUNCTION = "function"
    HUMAN_APPROVAL = "human_approval"
    CONDITIONAL = "conditional"
    PARALLEL = "parallel"
    SUBWORKFLOW = "subworkflow"


class AIWorkflowDefinition(Base):
    """Reusable workflow definition template.

    Stores the complete workflow graph definition including:
    - Node configurations
    - Edge connections
    - Entry and exit points
    - Default parameters
    """

    __tablename__ = "ai_workflow_definitions"

    # Primary key
    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )

    # Multi-tenancy
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Workflow identification
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[str] = mapped_column(String(50), default="1.0.0")

    # Workflow definition (JSON schema)
    nodes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    edges: Mapped[dict[str, list[str]]] = mapped_column(JSON, default=dict)
    entry_point: Mapped[str] = mapped_column(String(255), nullable=False)
    end_nodes: Mapped[list[str]] = mapped_column(JSON, default=list)

    # Default configuration
    default_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    timeout_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_retries: Mapped[int] = mapped_column(Integer, default=0)

    # Metadata
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)

    # Audit fields
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    created_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    tenant: Mapped[Tenant] = relationship(
        "Tenant",
        back_populates="workflow_definitions",
        lazy="selectin",
    )
    created_by: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[created_by_id],
        lazy="selectin",
    )
    executions: Mapped[list[AIWorkflowExecution]] = relationship(
        "AIWorkflowExecution",
        back_populates="definition",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # Indexes
    __table_args__ = (
        Index("ix_workflow_definitions_tenant_slug", "tenant_id", "slug", unique=True),
        Index("ix_workflow_definitions_tenant_active", "tenant_id", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<AIWorkflowDefinition {self.name} ({self.id})>"


class AIWorkflowExecution(Base):
    """Workflow execution instance.

    Tracks a single execution of a workflow definition including:
    - Current state and progress
    - Node execution history
    - Input/output data
    - Timing and cost metrics
    """

    __tablename__ = "ai_workflow_executions"

    # Primary key
    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )

    # Workflow definition reference
    definition_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_workflow_definitions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Multi-tenancy
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Execution status
    status: Mapped[str] = mapped_column(
        AIWorkflowStatus,
        default=WorkflowStatus.PENDING.value,
        index=True,
    )

    # Current execution state
    current_node: Mapped[str | None] = mapped_column(String(255), nullable=True)
    executed_nodes: Mapped[list[str]] = mapped_column(JSON, default=list)

    # Input/output data
    input_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    state_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Configuration overrides
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # Error tracking
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    failed_node: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Timing
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # Cost tracking
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)

    # Retry tracking
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    parent_execution_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ai_workflow_executions.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Metadata
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, default=dict
    )

    # Audit fields
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    created_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    definition: Mapped[AIWorkflowDefinition] = relationship(
        "AIWorkflowDefinition",
        back_populates="executions",
        lazy="selectin",
    )
    tenant: Mapped[Tenant] = relationship(
        "Tenant",
        back_populates="workflow_executions",
        lazy="selectin",
    )
    created_by: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[created_by_id],
        lazy="selectin",
    )
    node_executions: Mapped[list[AIWorkflowNodeExecution]] = relationship(
        "AIWorkflowNodeExecution",
        back_populates="workflow_execution",
        cascade="all, delete-orphan",
        order_by="AIWorkflowNodeExecution.started_at",
        lazy="selectin",
    )
    approvals: Mapped[list[AIWorkflowApproval]] = relationship(
        "AIWorkflowApproval",
        back_populates="workflow_execution",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    parent_execution: Mapped[AIWorkflowExecution | None] = relationship(
        "AIWorkflowExecution",
        remote_side=[id],
        lazy="selectin",
    )

    # Indexes
    __table_args__ = (
        Index("ix_workflow_executions_tenant_status", "tenant_id", "status"),
        Index("ix_workflow_executions_definition", "definition_id", "status"),
        Index("ix_workflow_executions_created", "tenant_id", "created_at"),
    )

    @property
    def duration_seconds(self) -> float | None:
        """Get execution duration in seconds."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    def __repr__(self) -> str:
        return f"<AIWorkflowExecution {self.id} ({self.status})>"


class AIWorkflowNodeExecution(Base):
    """Individual node execution within a workflow.

    Tracks each node's execution including:
    - Input/output for the node
    - Timing and status
    - Error details if failed
    """

    __tablename__ = "ai_workflow_node_executions"

    # Primary key
    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )

    # Parent workflow execution
    workflow_execution_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_workflow_executions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Node identification
    node_name: Mapped[str] = mapped_column(String(255), nullable=False)
    node_type: Mapped[str] = mapped_column(
        AIWorkflowNodeType,
        default=WorkflowNodeType.FUNCTION.value,
    )

    # Execution status
    status: Mapped[str] = mapped_column(
        AIWorkflowNodeStatus,
        default=WorkflowNodeStatus.PENDING.value,
        index=True,
    )

    # Execution order
    execution_order: Mapped[int] = mapped_column(Integer, default=0)

    # Input/output
    input_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Error tracking
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Timing
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # Retry tracking
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)

    # Metadata
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, default=dict
    )

    # Relationships
    workflow_execution: Mapped[AIWorkflowExecution] = relationship(
        "AIWorkflowExecution",
        back_populates="node_executions",
        lazy="selectin",
    )

    # Indexes
    __table_args__ = (
        Index(
            "ix_workflow_node_executions_workflow_node",
            "workflow_execution_id",
            "node_name",
        ),
    )

    @property
    def duration_ms(self) -> float | None:
        """Get execution duration in milliseconds."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds() * 1000
        return None

    def __repr__(self) -> str:
        return f"<AIWorkflowNodeExecution {self.node_name} ({self.status})>"


class AIWorkflowApproval(Base):
    """Human approval request for workflow execution.

    Tracks approval requests including:
    - Approval prompt and options
    - Response details
    - Timing and responder info
    """

    __tablename__ = "ai_workflow_approvals"

    # Primary key
    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )

    # Parent workflow execution
    workflow_execution_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_workflow_executions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Node reference
    node_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Approval request details
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[str]] = mapped_column(
        JSON, default=lambda: ["approve", "reject"]
    )
    context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # Status
    is_pending: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    timeout_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Response details
    response: Mapped[str | None] = mapped_column(String(100), nullable=True)
    response_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    response_comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Responder info
    responded_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    responded_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # Timing
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
    )
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # Metadata
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, default=dict
    )

    # Relationships
    workflow_execution: Mapped[AIWorkflowExecution] = relationship(
        "AIWorkflowExecution",
        back_populates="approvals",
        lazy="selectin",
    )
    responded_by: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[responded_by_id],
        lazy="selectin",
    )

    # Indexes
    __table_args__ = (
        Index("ix_workflow_approvals_pending", "is_pending", "workflow_execution_id"),
        Index("ix_workflow_approvals_expires", "is_pending", "expires_at"),
    )

    @property
    def is_expired(self) -> bool:
        """Check if approval request has expired."""
        if self.expires_at is None:
            return False
        return datetime.now(UTC) > self.expires_at

    def __repr__(self) -> str:
        status = "pending" if self.is_pending else f"responded:{self.response}"
        return f"<AIWorkflowApproval {self.node_name} ({status})>"
