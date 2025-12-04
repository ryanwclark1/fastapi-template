"""AI Workflow Events for tracking, observability, and real-time updates.

This module provides event infrastructure for:
- Workflow state tracking and resumption
- Real-time progress updates (WebSocket/SSE)
- Cost tracking and aggregation
- Audit trail for compliance

Quick Start:
    from example_service.infra.ai.events import (
        get_event_publisher,
        get_event_store,
        EventType,
    )

    # Get publisher for emitting events
    publisher = get_event_publisher()

    # Emit workflow events
    await publisher.workflow_started(
        execution_id="exec-123",
        pipeline_name="call_analysis",
        tenant_id="tenant-456",
    )

    # Subscribe to real-time updates
    store = get_event_store()
    async for event in store.subscribe(execution_id="exec-123"):
        # Forward to WebSocket, SSE, etc.
        await websocket.send_json(event.to_dict())
"""

# Event types
# Event store
from example_service.infra.ai.events.store import (
    EventPublisher,
    EventStore,
    InMemoryEventStore,
    get_event_publisher,
    get_event_store,
    set_event_store,
)
from example_service.infra.ai.events.types import (
    AIWorkflowEvent,
    BaseEvent,
    BudgetExceededEvent,
    BudgetWarningEvent,
    CheckpointReachedEvent,
    CompensationCompletedEvent,
    CompensationStartedEvent,
    CompensationStepEvent,
    CostIncurredEvent,
    EventType,
    ProgressUpdateEvent,
    StepCompletedEvent,
    StepFailedEvent,
    StepRetryingEvent,
    StepSkippedEvent,
    StepStartedEvent,
    WorkflowCancelledEvent,
    WorkflowCompletedEvent,
    WorkflowFailedEvent,
    WorkflowStartedEvent,
)

# Alias for consistency with other modules
configure_event_store = set_event_store

# Saga coordinator
from example_service.infra.ai.events.saga import SagaCoordinator  # noqa: E402

__all__ = [
    # Event types
    "AIWorkflowEvent",
    "BaseEvent",
    "BudgetExceededEvent",
    "BudgetWarningEvent",
    "CheckpointReachedEvent",
    "CompensationCompletedEvent",
    "CompensationStartedEvent",
    "CompensationStepEvent",
    "CostIncurredEvent",
    # Event store
    "EventPublisher",
    "EventStore",
    "EventType",
    "InMemoryEventStore",
    "ProgressUpdateEvent",
    # Saga coordinator
    "SagaCoordinator",
    "StepCompletedEvent",
    "StepFailedEvent",
    "StepRetryingEvent",
    "StepSkippedEvent",
    "StepStartedEvent",
    "WorkflowCancelledEvent",
    "WorkflowCompletedEvent",
    "WorkflowFailedEvent",
    "WorkflowStartedEvent",
    "configure_event_store",
    "get_event_publisher",
    "get_event_store",
    "set_event_store",
]
