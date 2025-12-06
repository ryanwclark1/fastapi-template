"""Event types for AI workflow tracking and observability.

This module defines the event types used for:
- Workflow state tracking and resumption
- Real-time progress updates via WebSocket/SSE
- Cost tracking and budget enforcement
- Audit trail for compliance

Event Sourcing Lite:
    While not a full event-sourced system, these events enable:
    - Workflow state reconstruction
    - Progress replay for UI updates
    - Cost aggregation from event stream

Event Categories:
    - WorkflowEvent: Pipeline-level events (started, completed, failed)
    - StepEvent: Individual step events (started, completed, failed, skipped)
    - ProgressEvent: Fine-grained progress updates
    - CostEvent: Cost tracking events
    - CompensationEvent: Saga compensation events

Example:
    # Create events as workflow executes
    event = WorkflowStartedEvent(
        execution_id="exec-123",
        pipeline_name="call_analysis",
        tenant_id="tenant-456",
        input_data={"audio_url": "..."},
    )

    # Publish to event store and real-time channels
    await event_store.append(event)
    await websocket_manager.broadcast(event)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
import uuid


class EventType(str, Enum):
    """Types of AI workflow events."""

    # Workflow lifecycle
    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_COMPLETED = "workflow.completed"
    WORKFLOW_FAILED = "workflow.failed"
    WORKFLOW_CANCELLED = "workflow.cancelled"

    # Step lifecycle
    STEP_STARTED = "step.started"
    STEP_COMPLETED = "step.completed"
    STEP_FAILED = "step.failed"
    STEP_SKIPPED = "step.skipped"
    STEP_RETRYING = "step.retrying"

    # Provider events
    PROVIDER_CALLED = "provider.called"
    PROVIDER_SUCCEEDED = "provider.succeeded"
    PROVIDER_FAILED = "provider.failed"
    PROVIDER_FALLBACK = "provider.fallback"

    # Progress events
    PROGRESS_UPDATE = "progress.update"
    CHECKPOINT_REACHED = "checkpoint.reached"

    # Cost events
    COST_INCURRED = "cost.incurred"
    BUDGET_WARNING = "budget.warning"
    BUDGET_EXCEEDED = "budget.exceeded"

    # Compensation events
    COMPENSATION_STARTED = "compensation.started"
    COMPENSATION_STEP = "compensation.step"
    COMPENSATION_COMPLETED = "compensation.completed"
    COMPENSATION_FAILED = "compensation.failed"


@dataclass
class BaseEvent:
    """Base class for all AI workflow events.

    All events share common metadata:
    - event_id: Unique event identifier
    - event_type: Type of event
    - execution_id: Parent workflow execution ID
    - timestamp: When the event occurred
    - tenant_id: Optional tenant identifier
    """

    event_type: EventType
    execution_id: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary for serialization."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "execution_id": self.execution_id,
            "timestamp": self.timestamp.isoformat(),
            "tenant_id": self.tenant_id,
            "metadata": self.metadata,
            **self._get_specific_fields(),
        }

    def _get_specific_fields(self) -> dict[str, Any]:
        """Get event-specific fields for serialization.

        Override in subclasses to add specific fields.
        """
        return {}


# ============================================================================
# Workflow Events
# ============================================================================


@dataclass
class WorkflowStartedEvent(BaseEvent):
    """Event emitted when a workflow starts execution."""

    event_type: EventType = field(default=EventType.WORKFLOW_STARTED, init=False)
    pipeline_name: str = ""
    pipeline_version: str = ""
    input_data: dict[str, Any] = field(default_factory=dict)
    estimated_duration_seconds: int | None = None
    estimated_cost_usd: Decimal | None = None

    def _get_specific_fields(self) -> dict[str, Any]:
        return {
            "pipeline_name": self.pipeline_name,
            "pipeline_version": self.pipeline_version,
            "input_data_keys": list(self.input_data.keys()),  # Don't expose full input
            "estimated_duration_seconds": self.estimated_duration_seconds,
            "estimated_cost_usd": str(self.estimated_cost_usd) if self.estimated_cost_usd else None,
        }


@dataclass
class WorkflowCompletedEvent(BaseEvent):
    """Event emitted when a workflow completes successfully."""

    event_type: EventType = field(default=EventType.WORKFLOW_COMPLETED, init=False)
    pipeline_name: str = ""
    completed_steps: list[str] = field(default_factory=list)
    total_duration_ms: float = 0
    total_cost_usd: Decimal = field(default_factory=lambda: Decimal(0))
    output_keys: list[str] = field(default_factory=list)

    def _get_specific_fields(self) -> dict[str, Any]:
        return {
            "pipeline_name": self.pipeline_name,
            "completed_steps": self.completed_steps,
            "total_duration_ms": self.total_duration_ms,
            "total_cost_usd": str(self.total_cost_usd),
            "output_keys": self.output_keys,
        }


@dataclass
class WorkflowFailedEvent(BaseEvent):
    """Event emitted when a workflow fails."""

    event_type: EventType = field(default=EventType.WORKFLOW_FAILED, init=False)
    pipeline_name: str = ""
    failed_step: str | None = None
    error: str = ""
    error_code: str | None = None
    completed_steps: list[str] = field(default_factory=list)
    total_duration_ms: float = 0
    total_cost_usd: Decimal = field(default_factory=lambda: Decimal(0))
    retryable: bool = False

    def _get_specific_fields(self) -> dict[str, Any]:
        return {
            "pipeline_name": self.pipeline_name,
            "failed_step": self.failed_step,
            "error": self.error,
            "error_code": self.error_code,
            "completed_steps": self.completed_steps,
            "total_duration_ms": self.total_duration_ms,
            "total_cost_usd": str(self.total_cost_usd),
            "retryable": self.retryable,
        }


@dataclass
class WorkflowCancelledEvent(BaseEvent):
    """Event emitted when a workflow is cancelled."""

    event_type: EventType = field(default=EventType.WORKFLOW_CANCELLED, init=False)
    pipeline_name: str = ""
    reason: str = ""
    completed_steps: list[str] = field(default_factory=list)
    current_step: str | None = None

    def _get_specific_fields(self) -> dict[str, Any]:
        return {
            "pipeline_name": self.pipeline_name,
            "reason": self.reason,
            "completed_steps": self.completed_steps,
            "current_step": self.current_step,
        }


# ============================================================================
# Step Events
# ============================================================================


@dataclass
class StepStartedEvent(BaseEvent):
    """Event emitted when a step starts execution."""

    event_type: EventType = field(default=EventType.STEP_STARTED, init=False)
    step_name: str = ""
    step_index: int = 0
    total_steps: int = 0
    capability: str = ""
    provider_preference: list[str] = field(default_factory=list)

    def _get_specific_fields(self) -> dict[str, Any]:
        return {
            "step_name": self.step_name,
            "step_index": self.step_index,
            "total_steps": self.total_steps,
            "capability": self.capability,
            "provider_preference": self.provider_preference,
        }


@dataclass
class StepCompletedEvent(BaseEvent):
    """Event emitted when a step completes successfully."""

    event_type: EventType = field(default=EventType.STEP_COMPLETED, init=False)
    step_name: str = ""
    provider_used: str = ""
    fallbacks_attempted: list[str] = field(default_factory=list)
    retries: int = 0
    duration_ms: float = 0
    cost_usd: Decimal = field(default_factory=lambda: Decimal(0))
    output_key: str = ""

    def _get_specific_fields(self) -> dict[str, Any]:
        return {
            "step_name": self.step_name,
            "provider_used": self.provider_used,
            "fallbacks_attempted": self.fallbacks_attempted,
            "retries": self.retries,
            "duration_ms": self.duration_ms,
            "cost_usd": str(self.cost_usd),
            "output_key": self.output_key,
        }


@dataclass
class StepFailedEvent(BaseEvent):
    """Event emitted when a step fails."""

    event_type: EventType = field(default=EventType.STEP_FAILED, init=False)
    step_name: str = ""
    error: str = ""
    error_code: str | None = None
    provider_attempted: str | None = None
    fallbacks_attempted: list[str] = field(default_factory=list)
    retries: int = 0
    duration_ms: float = 0
    will_retry: bool = False
    continue_pipeline: bool = False

    def _get_specific_fields(self) -> dict[str, Any]:
        return {
            "step_name": self.step_name,
            "error": self.error,
            "error_code": self.error_code,
            "provider_attempted": self.provider_attempted,
            "fallbacks_attempted": self.fallbacks_attempted,
            "retries": self.retries,
            "duration_ms": self.duration_ms,
            "will_retry": self.will_retry,
            "continue_pipeline": self.continue_pipeline,
        }


@dataclass
class StepSkippedEvent(BaseEvent):
    """Event emitted when a step is skipped."""

    event_type: EventType = field(default=EventType.STEP_SKIPPED, init=False)
    step_name: str = ""
    reason: str = ""
    condition_evaluated: str | None = None

    def _get_specific_fields(self) -> dict[str, Any]:
        return {
            "step_name": self.step_name,
            "reason": self.reason,
            "condition_evaluated": self.condition_evaluated,
        }


@dataclass
class StepRetryingEvent(BaseEvent):
    """Event emitted when a step is being retried."""

    event_type: EventType = field(default=EventType.STEP_RETRYING, init=False)
    step_name: str = ""
    attempt: int = 0
    max_attempts: int = 0
    delay_ms: int = 0
    previous_error: str = ""

    def _get_specific_fields(self) -> dict[str, Any]:
        return {
            "step_name": self.step_name,
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "delay_ms": self.delay_ms,
            "previous_error": self.previous_error,
        }


# ============================================================================
# Progress Events
# ============================================================================


@dataclass
class ProgressUpdateEvent(BaseEvent):
    """Event emitted for progress updates."""

    event_type: EventType = field(default=EventType.PROGRESS_UPDATE, init=False)
    percent: float = 0.0
    message: str = ""
    current_step: str | None = None
    steps_completed: int = 0
    total_steps: int = 0
    estimated_remaining_seconds: int | None = None

    def _get_specific_fields(self) -> dict[str, Any]:
        return {
            "percent": self.percent,
            "message": self.message,
            "current_step": self.current_step,
            "steps_completed": self.steps_completed,
            "total_steps": self.total_steps,
            "estimated_remaining_seconds": self.estimated_remaining_seconds,
        }


@dataclass
class CheckpointReachedEvent(BaseEvent):
    """Event emitted when a progress checkpoint is reached."""

    event_type: EventType = field(default=EventType.CHECKPOINT_REACHED, init=False)
    checkpoint_name: str = ""
    step_name: str = ""
    percent: float = 0.0
    data_snapshot_keys: list[str] = field(default_factory=list)

    def _get_specific_fields(self) -> dict[str, Any]:
        return {
            "checkpoint_name": self.checkpoint_name,
            "step_name": self.step_name,
            "percent": self.percent,
            "data_snapshot_keys": self.data_snapshot_keys,
        }


# ============================================================================
# Cost Events
# ============================================================================


@dataclass
class CostIncurredEvent(BaseEvent):
    """Event emitted when cost is incurred."""

    event_type: EventType = field(default=EventType.COST_INCURRED, init=False)
    step_name: str = ""
    provider: str = ""
    capability: str = ""
    cost_usd: Decimal = field(default_factory=lambda: Decimal(0))
    usage: dict[str, Any] = field(default_factory=dict)

    def _get_specific_fields(self) -> dict[str, Any]:
        return {
            "step_name": self.step_name,
            "provider": self.provider,
            "capability": self.capability,
            "cost_usd": str(self.cost_usd),
            "usage": self.usage,
        }


@dataclass
class BudgetWarningEvent(BaseEvent):
    """Event emitted when approaching budget limit."""

    event_type: EventType = field(default=EventType.BUDGET_WARNING, init=False)
    budget_limit_usd: Decimal = field(default_factory=lambda: Decimal(0))
    current_spend_usd: Decimal = field(default_factory=lambda: Decimal(0))
    percent_used: float = 0.0
    threshold_percent: float = 80.0

    def _get_specific_fields(self) -> dict[str, Any]:
        return {
            "budget_limit_usd": str(self.budget_limit_usd),
            "current_spend_usd": str(self.current_spend_usd),
            "percent_used": self.percent_used,
            "threshold_percent": self.threshold_percent,
        }


@dataclass
class BudgetExceededEvent(BaseEvent):
    """Event emitted when budget limit is exceeded."""

    event_type: EventType = field(default=EventType.BUDGET_EXCEEDED, init=False)
    budget_limit_usd: Decimal = field(default_factory=lambda: Decimal(0))
    current_spend_usd: Decimal = field(default_factory=lambda: Decimal(0))
    exceeded_by_usd: Decimal = field(default_factory=lambda: Decimal(0))
    action_taken: str = ""  # e.g., "blocked", "warned", "allowed"

    def _get_specific_fields(self) -> dict[str, Any]:
        return {
            "budget_limit_usd": str(self.budget_limit_usd),
            "current_spend_usd": str(self.current_spend_usd),
            "exceeded_by_usd": str(self.exceeded_by_usd),
            "action_taken": self.action_taken,
        }


# ============================================================================
# Compensation Events
# ============================================================================


@dataclass
class CompensationStartedEvent(BaseEvent):
    """Event emitted when saga compensation begins."""

    event_type: EventType = field(default=EventType.COMPENSATION_STARTED, init=False)
    failed_step: str = ""
    steps_to_compensate: list[str] = field(default_factory=list)
    failure_reason: str = ""

    def _get_specific_fields(self) -> dict[str, Any]:
        return {
            "failed_step": self.failed_step,
            "steps_to_compensate": self.steps_to_compensate,
            "failure_reason": self.failure_reason,
        }


@dataclass
class CompensationStepEvent(BaseEvent):
    """Event emitted for each compensation step."""

    event_type: EventType = field(default=EventType.COMPENSATION_STEP, init=False)
    step_name: str = ""
    success: bool = False
    error: str | None = None
    duration_ms: float = 0

    def _get_specific_fields(self) -> dict[str, Any]:
        return {
            "step_name": self.step_name,
            "success": self.success,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


@dataclass
class CompensationCompletedEvent(BaseEvent):
    """Event emitted when saga compensation completes."""

    event_type: EventType = field(default=EventType.COMPENSATION_COMPLETED, init=False)
    compensated_steps: list[str] = field(default_factory=list)
    failed_compensations: list[str] = field(default_factory=list)
    total_duration_ms: float = 0
    full_rollback: bool = True

    def _get_specific_fields(self) -> dict[str, Any]:
        return {
            "compensated_steps": self.compensated_steps,
            "failed_compensations": self.failed_compensations,
            "total_duration_ms": self.total_duration_ms,
            "full_rollback": self.full_rollback,
        }


# Type alias for any event
AIWorkflowEvent = (
    WorkflowStartedEvent
    | WorkflowCompletedEvent
    | WorkflowFailedEvent
    | WorkflowCancelledEvent
    | StepStartedEvent
    | StepCompletedEvent
    | StepFailedEvent
    | StepSkippedEvent
    | StepRetryingEvent
    | ProgressUpdateEvent
    | CheckpointReachedEvent
    | CostIncurredEvent
    | BudgetWarningEvent
    | BudgetExceededEvent
    | CompensationStartedEvent
    | CompensationStepEvent
    | CompensationCompletedEvent
)
