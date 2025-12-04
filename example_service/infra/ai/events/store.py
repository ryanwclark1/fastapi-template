"""Event Store for AI workflow events.

Provides event storage, retrieval, and real-time streaming:
- In-memory storage with optional persistence backend
- Event streaming to subscribers (WebSocket, SSE)
- Query by execution_id, tenant_id, event_type
- Workflow state reconstruction from events

Architecture:
    EventStore (interface)
        ├── InMemoryEventStore (default, for development/testing)
        ├── RedisEventStore (for production with Redis)
        └── PostgresEventStore (for production with PostgreSQL)

Usage:
    from example_service.infra.ai.events.store import get_event_store

    store = get_event_store()

    # Append events
    await store.append(workflow_started_event)

    # Query events
    events = await store.get_events(execution_id="exec-123")

    # Subscribe to real-time events
    async for event in store.subscribe(execution_id="exec-123"):
        await websocket.send(event.to_dict())

Example with WebSocket:
    @app.websocket("/ws/workflow/{execution_id}")
    async def workflow_stream(websocket, execution_id: str):
        await websocket.accept()
        async for event in store.subscribe(execution_id=execution_id):
            await websocket.send_json(event.to_dict())
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from example_service.infra.ai.events.types import (
    BaseEvent,
    EventType,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


class EventStore(ABC):
    """Abstract base class for event stores.

    All event store implementations must provide:
    - append(): Store a new event
    - get_events(): Query events by criteria
    - subscribe(): Real-time event subscription
    """

    @abstractmethod
    async def append(self, event: BaseEvent) -> None:
        """Append an event to the store.

        Args:
            event: Event to store
        """
        ...

    @abstractmethod
    async def get_events(
        self,
        *,
        execution_id: str | None = None,
        tenant_id: str | None = None,
        event_types: list[EventType] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 1000,
    ) -> list[BaseEvent]:
        """Query events by criteria.

        Args:
            execution_id: Filter by execution ID
            tenant_id: Filter by tenant ID
            event_types: Filter by event types
            since: Events after this time
            until: Events before this time
            limit: Maximum events to return

        Returns:
            List of matching events
        """
        ...

    @abstractmethod
    async def subscribe(
        self,
        *,
        execution_id: str | None = None,
        tenant_id: str | None = None,
        event_types: list[EventType] | None = None,
    ) -> AsyncIterator[BaseEvent]:
        """Subscribe to real-time events.

        Args:
            execution_id: Filter by execution ID
            tenant_id: Filter by tenant ID
            event_types: Filter by event types

        Yields:
            Matching events as they occur
        """
        ...

    @abstractmethod
    async def get_workflow_state(self, execution_id: str) -> dict[str, Any] | None:
        """Get current workflow state from events.

        Reconstructs workflow state from event history.

        Args:
            execution_id: Workflow execution ID

        Returns:
            Current state dict or None if not found
        """
        ...


@dataclass
class Subscription:
    """Internal representation of an event subscription."""

    queue: asyncio.Queue[BaseEvent]
    execution_id: str | None = None
    tenant_id: str | None = None
    event_types: set[EventType] | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    def matches(self, event: BaseEvent) -> bool:
        """Check if event matches subscription filters."""
        if self.execution_id and event.execution_id != self.execution_id:
            return False
        if self.tenant_id and event.tenant_id != self.tenant_id:
            return False
        return not (self.event_types and event.event_type not in self.event_types)


class InMemoryEventStore(EventStore):
    """In-memory event store for development and testing.

    Features:
    - Fast in-memory storage with indexes
    - Real-time pub/sub to subscribers
    - Automatic cleanup of old events
    - Workflow state reconstruction

    Note: Not suitable for production - events are lost on restart.
    Use RedisEventStore or PostgresEventStore for production.

    Example:
        store = InMemoryEventStore(max_events=10000, ttl_hours=24)
        await store.append(event)
        events = await store.get_events(execution_id="exec-123")
    """

    def __init__(
        self,
        max_events: int = 100000,
        ttl_hours: int = 24,
    ) -> None:
        """Initialize in-memory store.

        Args:
            max_events: Maximum events to store
            ttl_hours: Time-to-live for events in hours
        """
        self.max_events = max_events
        self.ttl = timedelta(hours=ttl_hours)

        # Storage
        self._events: list[BaseEvent] = []
        self._by_execution: dict[str, list[BaseEvent]] = defaultdict(list)
        self._by_tenant: dict[str, list[BaseEvent]] = defaultdict(list)

        # Pub/Sub
        self._subscriptions: list[Subscription] = []
        self._lock = asyncio.Lock()

    async def append(self, event: BaseEvent) -> None:
        """Append event and notify subscribers."""
        async with self._lock:
            # Store event
            self._events.append(event)
            self._by_execution[event.execution_id].append(event)
            if event.tenant_id:
                self._by_tenant[event.tenant_id].append(event)

            # Cleanup if needed
            if len(self._events) > self.max_events:
                await self._cleanup()

        # Notify subscribers (outside lock)
        await self._notify_subscribers(event)

        logger.debug(
            f"Event stored: {event.event_type.value}",
            extra={
                "event_id": event.event_id,
                "execution_id": event.execution_id,
                "event_type": event.event_type.value,
            },
        )

    async def get_events(
        self,
        *,
        execution_id: str | None = None,
        tenant_id: str | None = None,
        event_types: list[EventType] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 1000,
    ) -> list[BaseEvent]:
        """Query events by criteria."""
        async with self._lock:
            # Start with most specific index
            if execution_id:
                events = self._by_execution.get(execution_id, [])
            elif tenant_id:
                events = self._by_tenant.get(tenant_id, [])
            else:
                events = self._events

            # Apply filters
            result = []
            for event in events:
                if event_types and event.event_type not in event_types:
                    continue
                if since and event.timestamp < since:
                    continue
                if until and event.timestamp > until:
                    continue
                result.append(event)
                if len(result) >= limit:
                    break

            return result

    async def subscribe(  # type: ignore[override, misc]
        self,
        *,
        execution_id: str | None = None,
        tenant_id: str | None = None,
        event_types: list[EventType] | None = None,
    ) -> AsyncIterator[BaseEvent]:
        """Subscribe to real-time events."""
        subscription = Subscription(
            queue=asyncio.Queue(),
            execution_id=execution_id,
            tenant_id=tenant_id,
            event_types=set(event_types) if event_types else None,
        )

        async with self._lock:
            self._subscriptions.append(subscription)

        try:
            while True:
                event = await subscription.queue.get()
                yield event
        finally:
            async with self._lock:
                if subscription in self._subscriptions:
                    self._subscriptions.remove(subscription)

    async def get_workflow_state(self, execution_id: str) -> dict[str, Any] | None:
        """Reconstruct workflow state from events."""
        events = await self.get_events(execution_id=execution_id)

        if not events:
            return None

        # Build state from events
        state: dict[str, Any] = {
            "execution_id": execution_id,
            "status": "unknown",
            "pipeline_name": None,
            "started_at": None,
            "completed_at": None,
            "current_step": None,
            "completed_steps": [],
            "failed_step": None,
            "error": None,
            "progress_percent": 0.0,
            "total_cost_usd": "0",
            "events_count": len(events),
        }

        for event in events:
            if event.event_type == EventType.WORKFLOW_STARTED:
                state["status"] = "running"
                state["pipeline_name"] = getattr(event, "pipeline_name", None)
                state["started_at"] = event.timestamp.isoformat()

            elif event.event_type == EventType.WORKFLOW_COMPLETED:
                state["status"] = "completed"
                state["completed_at"] = event.timestamp.isoformat()
                state["completed_steps"] = getattr(event, "completed_steps", [])
                state["total_cost_usd"] = str(getattr(event, "total_cost_usd", "0"))

            elif event.event_type == EventType.WORKFLOW_FAILED:
                state["status"] = "failed"
                state["completed_at"] = event.timestamp.isoformat()
                state["failed_step"] = getattr(event, "failed_step", None)
                state["error"] = getattr(event, "error", None)
                state["completed_steps"] = getattr(event, "completed_steps", [])

            elif event.event_type == EventType.WORKFLOW_CANCELLED:
                state["status"] = "cancelled"
                state["completed_at"] = event.timestamp.isoformat()

            elif event.event_type == EventType.STEP_STARTED:
                state["current_step"] = getattr(event, "step_name", None)

            elif event.event_type == EventType.STEP_COMPLETED:
                step_name = getattr(event, "step_name", None)
                completed_steps = state.get("completed_steps", [])
                if (
                    step_name
                    and isinstance(completed_steps, list)
                    and step_name not in completed_steps
                ):
                    completed_steps.append(step_name)
                    state["completed_steps"] = completed_steps

            elif event.event_type == EventType.PROGRESS_UPDATE:
                state["progress_percent"] = getattr(event, "percent", 0.0)

        return state

    async def _notify_subscribers(self, event: BaseEvent) -> None:
        """Notify matching subscribers of new event."""
        for subscription in self._subscriptions:
            if subscription.matches(event):
                try:
                    subscription.queue.put_nowait(event)
                except asyncio.QueueFull:
                    logger.warning(
                        "Subscriber queue full, dropping event",
                        extra={"execution_id": event.execution_id},
                    )

    async def _cleanup(self) -> None:
        """Clean up old events."""
        cutoff = datetime.utcnow() - self.ttl
        old_count = len(self._events)

        # Remove old events
        self._events = [e for e in self._events if e.timestamp > cutoff]

        # Rebuild indexes (simpler than tracking removals)
        self._by_execution.clear()
        self._by_tenant.clear()
        for event in self._events:
            self._by_execution[event.execution_id].append(event)
            if event.tenant_id:
                self._by_tenant[event.tenant_id].append(event)

        removed = old_count - len(self._events)
        if removed > 0:
            logger.info(f"Cleaned up {removed} old events")


class EventPublisher:
    """High-level event publishing interface.

    Wraps EventStore with convenient publishing methods
    and automatic event creation.

    Example:
        publisher = EventPublisher(store)

        # Publish workflow events
        await publisher.workflow_started(
            execution_id="exec-123",
            pipeline_name="call_analysis",
            tenant_id="tenant-456",
        )

        await publisher.step_completed(
            execution_id="exec-123",
            step_name="transcribe",
            provider_used="deepgram",
            duration_ms=5000,
            cost_usd=Decimal("0.05"),
        )
    """

    def __init__(self, store: EventStore) -> None:
        """Initialize publisher.

        Args:
            store: Event store to publish to
        """
        self.store = store

    async def publish(self, event: BaseEvent) -> None:
        """Publish an event."""
        await self.store.append(event)

    async def workflow_started(
        self,
        execution_id: str,
        pipeline_name: str,
        tenant_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Publish workflow started event."""
        from example_service.infra.ai.events.types import WorkflowStartedEvent

        event = WorkflowStartedEvent(
            execution_id=execution_id,
            tenant_id=tenant_id,
            pipeline_name=pipeline_name,
            **kwargs,
        )
        await self.publish(event)

    async def workflow_completed(
        self,
        execution_id: str,
        tenant_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Publish workflow completed event."""
        from example_service.infra.ai.events.types import WorkflowCompletedEvent

        event = WorkflowCompletedEvent(
            execution_id=execution_id,
            tenant_id=tenant_id,
            **kwargs,
        )
        await self.publish(event)

    async def workflow_failed(
        self,
        execution_id: str,
        error: str,
        tenant_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Publish workflow failed event."""
        from example_service.infra.ai.events.types import WorkflowFailedEvent

        event = WorkflowFailedEvent(
            execution_id=execution_id,
            tenant_id=tenant_id,
            error=error,
            **kwargs,
        )
        await self.publish(event)

    async def step_started(
        self,
        execution_id: str,
        step_name: str,
        tenant_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Publish step started event."""
        from example_service.infra.ai.events.types import StepStartedEvent

        event = StepStartedEvent(
            execution_id=execution_id,
            tenant_id=tenant_id,
            step_name=step_name,
            **kwargs,
        )
        await self.publish(event)

    async def step_completed(
        self,
        execution_id: str,
        step_name: str,
        tenant_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Publish step completed event."""
        from example_service.infra.ai.events.types import StepCompletedEvent

        event = StepCompletedEvent(
            execution_id=execution_id,
            tenant_id=tenant_id,
            step_name=step_name,
            **kwargs,
        )
        await self.publish(event)

    async def step_failed(
        self,
        execution_id: str,
        step_name: str,
        error: str,
        tenant_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Publish step failed event."""
        from example_service.infra.ai.events.types import StepFailedEvent

        event = StepFailedEvent(
            execution_id=execution_id,
            tenant_id=tenant_id,
            step_name=step_name,
            error=error,
            **kwargs,
        )
        await self.publish(event)

    async def progress_update(
        self,
        execution_id: str,
        percent: float,
        message: str = "",
        tenant_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Publish progress update event."""
        from example_service.infra.ai.events.types import ProgressUpdateEvent

        event = ProgressUpdateEvent(
            execution_id=execution_id,
            tenant_id=tenant_id,
            percent=percent,
            message=message,
            **kwargs,
        )
        await self.publish(event)

    async def cost_incurred(
        self,
        execution_id: str,
        step_name: str,
        provider: str,
        cost_usd: Any,
        tenant_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Publish cost incurred event."""
        from decimal import Decimal

        from example_service.infra.ai.events.types import CostIncurredEvent

        event = CostIncurredEvent(
            execution_id=execution_id,
            tenant_id=tenant_id,
            step_name=step_name,
            provider=provider,
            cost_usd=Decimal(str(cost_usd)),
            **kwargs,
        )
        await self.publish(event)


# Singleton instance
_event_store: EventStore | None = None


def get_event_store() -> EventStore:
    """Get the global event store singleton.

    Returns:
        The singleton EventStore instance
    """
    global _event_store
    if _event_store is None:
        _event_store = InMemoryEventStore()
    return _event_store


def set_event_store(store: EventStore | None) -> None:
    """Set the global event store.

    Use this to configure a production event store.

    Args:
        store: EventStore implementation to use
    """
    global _event_store
    _event_store = store


def get_event_publisher() -> EventPublisher:
    """Get an event publisher using the global store.

    Returns:
        EventPublisher instance
    """
    return EventPublisher(get_event_store())
