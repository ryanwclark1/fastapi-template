"""Database models for AI Agent framework.

This module provides persistent storage for agent runs, enabling:
- Full run history with state persistence
- Step-by-step execution tracking
- Checkpoint/resume capabilities
- Cost and token tracking per run
- Message history for conversation context

Models:
- AIAgentRun: Main run tracking with full state
- AIAgentStep: Individual execution steps within a run
- AIAgentCheckpoint: Snapshots for pause/resume
- AIAgentMessage: Conversation history
- AIAgentToolCall: Tool invocations within a run
"""

from __future__ import annotations

from datetime import UTC, datetime
import enum
from typing import TYPE_CHECKING, Any
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
    AIAgentMessageRole,
    AIAgentRunStatus,
    AIAgentStepStatus,
    AIAgentStepType,
)

if TYPE_CHECKING:
    from example_service.features.tenants.models import Tenant
    from example_service.features.users.models import User


class AgentRunStatus(str, enum.Enum):
    """Status of an agent run."""

    PENDING = "pending"  # Created but not started
    RUNNING = "running"  # Currently executing
    PAUSED = "paused"  # Paused, can be resumed
    WAITING_INPUT = "waiting_input"  # Waiting for human input
    COMPLETED = "completed"  # Successfully finished
    FAILED = "failed"  # Failed with error
    CANCELLED = "cancelled"  # Cancelled by user/system
    TIMEOUT = "timeout"  # Exceeded time limit


class AgentStepType(str, enum.Enum):
    """Type of agent step."""

    LLM_CALL = "llm_call"  # Call to LLM
    TOOL_CALL = "tool_call"  # Tool/function execution
    HUMAN_INPUT = "human_input"  # Waiting for human input
    CHECKPOINT = "checkpoint"  # Checkpoint for state save
    BRANCH = "branch"  # Conditional branch decision
    PARALLEL = "parallel"  # Parallel execution
    SUBAGENT = "subagent"  # Delegation to sub-agent


class AgentStepStatus(str, enum.Enum):
    """Status of an agent step."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"


class AgentMessageRole(str, enum.Enum):
    """Role of a message in agent conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    FUNCTION = "function"


class AIAgentRun(Base):
    """Agent run tracking with full state persistence.

    Tracks complete agent execution from start to finish including:
    - Configuration and input data
    - Execution state and progress
    - Cost and token usage
    - Error tracking and retry info
    - Final output

    Examples:
        # Create a new agent run
        run = AIAgentRun(
            tenant_id="tenant-123",
            agent_type="research_agent",
            agent_version="1.0.0",
            input_data={"query": "What is quantum computing?"},
            config={"max_iterations": 10, "temperature": 0.7},
        )

        # Update run progress
        run.status = AgentRunStatus.RUNNING
        run.current_step = 3
        run.total_steps = 10
        run.progress_percent = 30.0
    """

    __tablename__ = "ai_agent_runs"

    # Primary key
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    # Tenant association
    tenant_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Agent identification
    agent_type: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Type/name of the agent (e.g., 'research_agent', 'code_review')",
    )
    agent_version: Mapped[str] = mapped_column(
        String(50),
        default="1.0.0",
        nullable=False,
        comment="Version of the agent definition",
    )

    # Run identification
    run_name: Mapped[str | None] = mapped_column(
        String(255),
        comment="Human-readable name for the run",
    )
    parent_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ai_agent_runs.id", ondelete="SET NULL"),
        comment="Parent run ID if this is a sub-agent run",
    )

    # Status tracking
    status: Mapped[str] = mapped_column(
        AIAgentRunStatus,
        default="pending",
        nullable=False,
    )
    status_message: Mapped[str | None] = mapped_column(
        Text,
        comment="Human-readable status message",
    )

    # Input/Output
    input_data: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Input data for the agent",
    )
    output_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        comment="Final output from the agent",
    )
    config: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Agent configuration (model, temperature, tools, etc.)",
    )

    # State management
    state: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Current agent state (for pause/resume)",
    )
    context: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Shared context data between steps",
    )

    # Progress tracking
    current_step: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="Current step number",
    )
    total_steps: Mapped[int | None] = mapped_column(
        Integer,
        comment="Total expected steps (if known)",
    )
    progress_percent: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
        comment="Progress percentage 0-100",
    )

    # Cost tracking
    total_cost_usd: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
        comment="Total cost in USD",
    )
    total_input_tokens: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="Total input tokens consumed",
    )
    total_output_tokens: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="Total output tokens generated",
    )

    # Retry tracking
    retry_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="Number of retry attempts",
    )
    max_retries: Mapped[int] = mapped_column(
        Integer,
        default=3,
        nullable=False,
        comment="Maximum retry attempts",
    )
    last_retry_at: Mapped[datetime | None] = mapped_column(
        comment="Timestamp of last retry attempt",
    )

    # Error tracking
    error_message: Mapped[str | None] = mapped_column(
        Text,
        comment="Error message if failed",
    )
    error_code: Mapped[str | None] = mapped_column(
        String(100),
        comment="Error code for programmatic handling",
    )
    error_details: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        comment="Detailed error information (stack trace, etc.)",
    )

    # Timing
    started_at: Mapped[datetime | None] = mapped_column(
        comment="When execution started",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        comment="When execution completed",
    )
    paused_at: Mapped[datetime | None] = mapped_column(
        comment="When execution was paused",
    )
    timeout_seconds: Mapped[int | None] = mapped_column(
        Integer,
        comment="Timeout in seconds",
    )

    # Metadata
    tags: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="Tags for filtering/categorization",
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Additional metadata",
    )
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
    created_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
    )

    # Relationships
    tenant: Mapped[Tenant] = relationship("Tenant")
    created_by: Mapped[User | None] = relationship("User")
    parent_run: Mapped[AIAgentRun | None] = relationship(
        "AIAgentRun",
        remote_side=[id],
        backref="child_runs",
    )
    steps: Mapped[list[AIAgentStep]] = relationship(
        "AIAgentStep",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="AIAgentStep.step_number",
    )
    messages: Mapped[list[AIAgentMessage]] = relationship(
        "AIAgentMessage",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="AIAgentMessage.sequence_number",
    )
    tool_calls: Mapped[list[AIAgentToolCall]] = relationship(
        "AIAgentToolCall",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="AIAgentToolCall.created_at",
    )
    checkpoints: Mapped[list[AIAgentCheckpoint]] = relationship(
        "AIAgentCheckpoint",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="AIAgentCheckpoint.created_at",
    )

    __table_args__ = (
        Index("ix_ai_agent_runs_tenant_status", "tenant_id", "status"),
        Index("ix_ai_agent_runs_tenant_agent", "tenant_id", "agent_type"),
        Index("ix_ai_agent_runs_created_at", "created_at"),
        Index("ix_ai_agent_runs_parent", "parent_run_id"),
        Index("ix_ai_agent_runs_status_created", "status", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<AIAgentRun(id={self.id}, agent={self.agent_type}, "
            f"status={self.status})>"
        )

    @property
    def duration_seconds(self) -> float | None:
        """Calculate run duration in seconds."""
        if self.started_at:
            end = self.completed_at or datetime.now(UTC)
            return (end - self.started_at).total_seconds()
        return None

    @property
    def is_terminal(self) -> bool:
        """Check if run is in a terminal state."""
        return self.status in (
            AgentRunStatus.COMPLETED.value,
            AgentRunStatus.FAILED.value,
            AgentRunStatus.CANCELLED.value,
            AgentRunStatus.TIMEOUT.value,
        )

    @property
    def is_resumable(self) -> bool:
        """Check if run can be resumed."""
        return self.status in (
            AgentRunStatus.PAUSED.value,
            AgentRunStatus.WAITING_INPUT.value,
        )


class AIAgentStep(Base):
    """Individual step within an agent run.

    Tracks each execution step with:
    - Step type and status
    - Input/output data
    - Cost and timing
    - Error information
    - Retry tracking

    Examples:
        step = AIAgentStep(
            run_id=run.id,
            step_number=1,
            step_type=AgentStepType.LLM_CALL,
            step_name="initial_reasoning",
            input_data={"messages": [...]},
        )
    """

    __tablename__ = "ai_agent_steps"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_agent_runs.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Step identification
    step_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Sequential step number within run",
    )
    step_type: Mapped[str] = mapped_column(
        AIAgentStepType,
        nullable=False,
    )
    step_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Descriptive name for the step",
    )
    parent_step_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ai_agent_steps.id", ondelete="SET NULL"),
        comment="Parent step ID for nested/parallel steps",
    )

    # Status
    status: Mapped[str] = mapped_column(
        AIAgentStepStatus,
        default="pending",
        nullable=False,
    )

    # Input/Output
    input_data: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Input data for the step",
    )
    output_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        comment="Output data from the step",
    )

    # Provider info (for LLM/tool calls)
    provider_name: Mapped[str | None] = mapped_column(
        String(100),
        comment="Provider used (openai, anthropic, etc.)",
    )
    model_name: Mapped[str | None] = mapped_column(
        String(255),
        comment="Model used for LLM calls",
    )

    # Cost tracking
    cost_usd: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
    )
    input_tokens: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    output_tokens: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    # Timing
    started_at: Mapped[datetime | None] = mapped_column()
    completed_at: Mapped[datetime | None] = mapped_column()
    duration_ms: Mapped[float | None] = mapped_column(
        Float,
        comment="Step duration in milliseconds",
    )

    # Retry tracking
    attempt_number: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        default=3,
        nullable=False,
    )

    # Error tracking
    error_message: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(100))
    is_retryable: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # Metadata
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Relationships
    run: Mapped[AIAgentRun] = relationship(
        "AIAgentRun",
        back_populates="steps",
    )
    parent_step: Mapped[AIAgentStep | None] = relationship(
        "AIAgentStep",
        remote_side=[id],
        backref="child_steps",
    )

    __table_args__ = (
        Index("ix_ai_agent_steps_run", "run_id"),
        Index("ix_ai_agent_steps_run_step", "run_id", "step_number"),
        Index("ix_ai_agent_steps_status", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<AIAgentStep(run_id={self.run_id}, step={self.step_number}, "
            f"type={self.step_type}, status={self.status})>"
        )


class AIAgentMessage(Base):
    """Conversation message within an agent run.

    Stores the complete conversation history for:
    - Context preservation across steps
    - Debugging and analysis
    - Resume from checkpoint

    Examples:
        message = AIAgentMessage(
            run_id=run.id,
            sequence_number=1,
            role=AgentMessageRole.USER,
            content="What is the capital of France?",
        )
    """

    __tablename__ = "ai_agent_messages"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_agent_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ai_agent_steps.id", ondelete="SET NULL"),
        comment="Step that generated this message",
    )

    # Message content
    sequence_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Order in conversation",
    )
    role: Mapped[str] = mapped_column(
        AIAgentMessageRole,
        nullable=False,
    )
    content: Mapped[str | None] = mapped_column(
        Text,
        comment="Message text content",
    )
    content_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        comment="Structured content (for multi-modal or tool results)",
    )

    # Function/tool call info
    function_name: Mapped[str | None] = mapped_column(
        String(255),
        comment="Function name for function calls",
    )
    function_args: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        comment="Function arguments",
    )
    tool_call_id: Mapped[str | None] = mapped_column(
        String(255),
        comment="Tool call ID for correlation",
    )

    # Token tracking
    token_count: Mapped[int | None] = mapped_column(
        Integer,
        comment="Token count for this message",
    )

    # Metadata
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Relationships
    run: Mapped[AIAgentRun] = relationship(
        "AIAgentRun",
        back_populates="messages",
    )

    __table_args__ = (
        Index("ix_ai_agent_messages_run", "run_id"),
        Index("ix_ai_agent_messages_run_seq", "run_id", "sequence_number"),
    )

    def __repr__(self) -> str:
        return (
            f"<AIAgentMessage(run_id={self.run_id}, seq={self.sequence_number}, "
            f"role={self.role})>"
        )


class AIAgentToolCall(Base):
    """Tool invocation within an agent run.

    Tracks every tool call with:
    - Tool identification and arguments
    - Execution results
    - Timing and error info

    Examples:
        tool_call = AIAgentToolCall(
            run_id=run.id,
            step_id=step.id,
            tool_name="web_search",
            tool_args={"query": "latest AI news"},
        )
    """

    __tablename__ = "ai_agent_tool_calls"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_agent_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ai_agent_steps.id", ondelete="SET NULL"),
    )

    # Tool identification
    tool_call_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Unique tool call ID from LLM",
    )
    tool_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    tool_args: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    # Execution
    result: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        comment="Tool execution result",
    )
    result_text: Mapped[str | None] = mapped_column(
        Text,
        comment="Text representation of result",
    )
    success: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text)

    # Timing
    started_at: Mapped[datetime | None] = mapped_column()
    completed_at: Mapped[datetime | None] = mapped_column()
    duration_ms: Mapped[float | None] = mapped_column(Float)

    # Metadata
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Relationships
    run: Mapped[AIAgentRun] = relationship(
        "AIAgentRun",
        back_populates="tool_calls",
    )

    __table_args__ = (
        Index("ix_ai_agent_tool_calls_run", "run_id"),
        Index("ix_ai_agent_tool_calls_tool", "tool_name"),
        Index("ix_ai_agent_tool_calls_call_id", "tool_call_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<AIAgentToolCall(run_id={self.run_id}, tool={self.tool_name}, "
            f"success={self.success})>"
        )


class AIAgentCheckpoint(Base):
    """Checkpoint for agent run state persistence.

    Enables:
    - Pause and resume functionality
    - Recovery from failures
    - State snapshots for debugging

    Examples:
        checkpoint = AIAgentCheckpoint(
            run_id=run.id,
            checkpoint_name="after_research",
            step_number=5,
            state_snapshot=run.state,
            context_snapshot=run.context,
        )
    """

    __tablename__ = "ai_agent_checkpoints"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_agent_runs.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Checkpoint identification
    checkpoint_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Human-readable checkpoint name",
    )
    step_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Step number at checkpoint",
    )

    # State snapshots
    state_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Agent state at checkpoint",
    )
    context_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Context data at checkpoint",
    )
    messages_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="Conversation messages at checkpoint",
    )

    # Checkpoint type
    is_automatic: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        comment="Whether checkpoint was auto-created",
    )
    trigger_reason: Mapped[str | None] = mapped_column(
        String(255),
        comment="Reason for checkpoint creation",
    )

    # Validation
    is_valid: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        comment="Whether checkpoint is valid for resume",
    )
    invalidated_reason: Mapped[str | None] = mapped_column(
        String(255),
        comment="Reason if checkpoint was invalidated",
    )

    # Metadata
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Relationships
    run: Mapped[AIAgentRun] = relationship(
        "AIAgentRun",
        back_populates="checkpoints",
    )

    __table_args__ = (
        Index("ix_ai_agent_checkpoints_run", "run_id"),
        Index("ix_ai_agent_checkpoints_run_step", "run_id", "step_number"),
        Index("ix_ai_agent_checkpoints_valid", "run_id", "is_valid"),
    )

    def __repr__(self) -> str:
        return (
            f"<AIAgentCheckpoint(run_id={self.run_id}, "
            f"name={self.checkpoint_name}, step={self.step_number})>"
        )
