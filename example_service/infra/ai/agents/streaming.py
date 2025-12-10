"""Streaming responses for AI agents.

This module provides streaming capabilities for long-running agent tasks:
- Server-Sent Events (SSE) streaming
- WebSocket streaming
- Progress tracking
- Partial result delivery
- Cancellation support

Example:
    from example_service.infra.ai.agents.streaming import (
        StreamingAgent,
        StreamEvent,
        EventType,
    )

    # Create a streaming agent
    agent = StreamingAgent(config=AgentConfig(...))

    # Stream responses via SSE
    async for event in agent.stream("Analyze this data"):
        if event.type == EventType.TOKEN:
            print(event.data, end="", flush=True)
        elif event.type == EventType.TOOL_CALL:
            print(f"\\nCalling tool: {event.data['name']}")
        elif event.type == EventType.COMPLETE:
            print(f"\\nDone! Total tokens: {event.data['total_tokens']}")
"""

from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, AsyncGenerator, Callable, TypeVar
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

T = TypeVar("T")


# =============================================================================
# Event Types
# =============================================================================


class EventType(str, Enum):
    """Types of streaming events."""

    # Content events
    TOKEN = "token"  # Single token from LLM
    CHUNK = "chunk"  # Multiple tokens as a chunk
    CONTENT = "content"  # Complete content block

    # Tool/Function events
    TOOL_CALL = "tool_call"  # Tool is being called
    TOOL_RESULT = "tool_result"  # Tool returned result

    # Progress events
    PROGRESS = "progress"  # Progress update
    STEP_START = "step_start"  # Agent step starting
    STEP_END = "step_end"  # Agent step completed

    # Status events
    START = "start"  # Stream starting
    COMPLETE = "complete"  # Stream completed successfully
    ERROR = "error"  # Error occurred
    CANCELLED = "cancelled"  # Stream cancelled

    # Workflow events
    NODE_START = "node_start"  # Workflow node starting
    NODE_END = "node_end"  # Workflow node completed
    APPROVAL_REQUIRED = "approval_required"  # Human approval needed

    # Metadata events
    METADATA = "metadata"  # Additional metadata
    HEARTBEAT = "heartbeat"  # Keep-alive signal


@dataclass
class StreamEvent:
    """A streaming event from an agent.

    Attributes:
        type: Type of event
        data: Event payload
        timestamp: When the event occurred
        sequence: Event sequence number
        metadata: Additional metadata
    """

    type: EventType
    data: Any
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    sequence: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_sse(self) -> str:
        """Convert to Server-Sent Events format.

        Returns:
            SSE-formatted string
        """
        event_data = {
            "type": self.type.value,
            "data": self.data,
            "sequence": self.sequence,
            "timestamp": self.timestamp.isoformat(),
        }
        if self.metadata:
            event_data["metadata"] = self.metadata

        return f"event: {self.type.value}\ndata: {json.dumps(event_data)}\n\n"

    def to_json(self) -> str:
        """Convert to JSON format for WebSocket.

        Returns:
            JSON string
        """
        return json.dumps({
            "type": self.type.value,
            "data": self.data,
            "sequence": self.sequence,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        })


# =============================================================================
# Stream State
# =============================================================================


class StreamState(str, Enum):
    """State of a stream."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERROR = "error"


@dataclass
class StreamStatus:
    """Status of an active stream.

    Attributes:
        stream_id: Unique stream identifier
        state: Current stream state
        started_at: When streaming started
        total_events: Number of events emitted
        total_tokens: Total tokens streamed
        current_step: Current processing step
        progress_percent: Progress percentage (0-100)
        error: Error message if failed
    """

    stream_id: UUID
    state: StreamState = StreamState.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None
    total_events: int = 0
    total_tokens: int = 0
    current_step: str | None = None
    progress_percent: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "stream_id": str(self.stream_id),
            "state": self.state.value,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "total_events": self.total_events,
            "total_tokens": self.total_tokens,
            "current_step": self.current_step,
            "progress_percent": self.progress_percent,
            "error": self.error,
        }


# =============================================================================
# Stream Handler Protocol
# =============================================================================


class StreamHandler(ABC):
    """Abstract base class for stream handlers.

    Implementations can handle streaming via different transports:
    - SSE (Server-Sent Events)
    - WebSocket
    - gRPC streaming
    - Custom protocols
    """

    @abstractmethod
    async def emit(self, event: StreamEvent) -> None:
        """Emit an event to the stream.

        Args:
            event: Event to emit
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close the stream."""
        pass

    @abstractmethod
    def is_closed(self) -> bool:
        """Check if stream is closed."""
        pass


class AsyncGeneratorHandler(StreamHandler):
    """Handler that yields events as an async generator."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[StreamEvent | None] = asyncio.Queue()
        self._closed = False

    async def emit(self, event: StreamEvent) -> None:
        """Emit an event."""
        if not self._closed:
            await self._queue.put(event)

    async def close(self) -> None:
        """Close the stream."""
        self._closed = True
        await self._queue.put(None)  # Signal end of stream

    def is_closed(self) -> bool:
        """Check if closed."""
        return self._closed

    async def __aiter__(self) -> AsyncGenerator[StreamEvent, None]:
        """Iterate over events."""
        while True:
            event = await self._queue.get()
            if event is None:
                break
            yield event


class CallbackHandler(StreamHandler):
    """Handler that calls a callback for each event."""

    def __init__(
        self,
        callback: Callable[[StreamEvent], Any],
        async_callback: bool = False,
    ) -> None:
        self._callback = callback
        self._async = async_callback
        self._closed = False

    async def emit(self, event: StreamEvent) -> None:
        """Emit an event."""
        if not self._closed:
            if self._async:
                await self._callback(event)
            else:
                self._callback(event)

    async def close(self) -> None:
        """Close the stream."""
        self._closed = True

    def is_closed(self) -> bool:
        """Check if closed."""
        return self._closed


# =============================================================================
# Streaming Context
# =============================================================================


class StreamingContext:
    """Context for managing a streaming session.

    Provides methods for emitting events, tracking progress,
    and handling cancellation.

    Example:
        async with StreamingContext() as ctx:
            await ctx.emit_start()

            for chunk in process_data():
                await ctx.emit_chunk(chunk)
                await ctx.update_progress(i / total * 100)

            await ctx.emit_complete(result)
    """

    def __init__(
        self,
        handler: StreamHandler,
        stream_id: UUID | None = None,
        heartbeat_interval: float = 30.0,
    ) -> None:
        """Initialize streaming context.

        Args:
            handler: Stream handler for emitting events
            stream_id: Optional stream ID (generated if not provided)
            heartbeat_interval: Interval for heartbeat events (seconds)
        """
        self.stream_id = stream_id or uuid4()
        self.handler = handler
        self.status = StreamStatus(stream_id=self.stream_id)
        self._heartbeat_interval = heartbeat_interval
        self._heartbeat_task: asyncio.Task | None = None
        self._sequence = 0
        self._cancelled = False

    async def __aenter__(self) -> StreamingContext:
        """Enter context."""
        await self._start_heartbeat()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context."""
        await self._stop_heartbeat()
        if exc_type is not None:
            await self.emit_error(str(exc_val))
        await self.handler.close()

    async def _start_heartbeat(self) -> None:
        """Start heartbeat task."""
        if self._heartbeat_interval > 0:
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _stop_heartbeat(self) -> None:
        """Stop heartbeat task."""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

    async def _heartbeat_loop(self) -> None:
        """Emit heartbeat events periodically."""
        while not self._cancelled and not self.handler.is_closed():
            await asyncio.sleep(self._heartbeat_interval)
            if not self._cancelled and not self.handler.is_closed():
                await self._emit(EventType.HEARTBEAT, {"stream_id": str(self.stream_id)})

    async def _emit(
        self,
        event_type: EventType,
        data: Any,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Emit an event.

        Args:
            event_type: Type of event
            data: Event data
            metadata: Optional metadata
        """
        if self._cancelled or self.handler.is_closed():
            return

        self._sequence += 1
        self.status.total_events = self._sequence

        event = StreamEvent(
            type=event_type,
            data=data,
            sequence=self._sequence,
            metadata=metadata or {},
        )

        await self.handler.emit(event)

    def cancel(self) -> None:
        """Cancel the stream."""
        self._cancelled = True
        self.status.state = StreamState.CANCELLED

    @property
    def is_cancelled(self) -> bool:
        """Check if cancelled."""
        return self._cancelled

    # =========================================================================
    # Event emission methods
    # =========================================================================

    async def emit_start(self, metadata: dict[str, Any] | None = None) -> None:
        """Emit stream start event."""
        self.status.state = StreamState.RUNNING
        self.status.started_at = datetime.now(UTC)
        await self._emit(
            EventType.START,
            {"stream_id": str(self.stream_id)},
            metadata,
        )

    async def emit_token(self, token: str) -> None:
        """Emit a single token."""
        self.status.total_tokens += 1
        await self._emit(EventType.TOKEN, token)

    async def emit_chunk(self, chunk: str, token_count: int = 0) -> None:
        """Emit a chunk of content."""
        self.status.total_tokens += token_count
        await self._emit(EventType.CHUNK, {"content": chunk, "tokens": token_count})

    async def emit_content(self, content: str, token_count: int = 0) -> None:
        """Emit complete content."""
        self.status.total_tokens += token_count
        await self._emit(
            EventType.CONTENT,
            {"content": content, "tokens": token_count},
        )

    async def emit_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        call_id: str | None = None,
    ) -> None:
        """Emit tool call event."""
        await self._emit(
            EventType.TOOL_CALL,
            {
                "name": tool_name,
                "arguments": tool_args,
                "call_id": call_id or str(uuid4()),
            },
        )

    async def emit_tool_result(
        self,
        tool_name: str,
        result: Any,
        call_id: str | None = None,
        success: bool = True,
    ) -> None:
        """Emit tool result event."""
        await self._emit(
            EventType.TOOL_RESULT,
            {
                "name": tool_name,
                "result": result,
                "call_id": call_id,
                "success": success,
            },
        )

    async def emit_progress(
        self,
        percent: float,
        message: str | None = None,
    ) -> None:
        """Emit progress update."""
        self.status.progress_percent = percent
        await self._emit(
            EventType.PROGRESS,
            {"percent": percent, "message": message},
        )

    async def emit_step_start(self, step_name: str, step_index: int = 0) -> None:
        """Emit step start event."""
        self.status.current_step = step_name
        await self._emit(
            EventType.STEP_START,
            {"name": step_name, "index": step_index},
        )

    async def emit_step_end(
        self,
        step_name: str,
        step_index: int = 0,
        result: Any = None,
    ) -> None:
        """Emit step end event."""
        await self._emit(
            EventType.STEP_END,
            {"name": step_name, "index": step_index, "result": result},
        )

    async def emit_node_start(self, node_name: str, node_type: str) -> None:
        """Emit workflow node start event."""
        self.status.current_step = f"node:{node_name}"
        await self._emit(
            EventType.NODE_START,
            {"name": node_name, "type": node_type},
        )

    async def emit_node_end(
        self,
        node_name: str,
        node_type: str,
        result: Any = None,
    ) -> None:
        """Emit workflow node end event."""
        await self._emit(
            EventType.NODE_END,
            {"name": node_name, "type": node_type, "result": result},
        )

    async def emit_approval_required(
        self,
        approval_id: str,
        prompt: str,
        options: list[str],
    ) -> None:
        """Emit approval required event."""
        self.status.state = StreamState.PAUSED
        await self._emit(
            EventType.APPROVAL_REQUIRED,
            {
                "approval_id": approval_id,
                "prompt": prompt,
                "options": options,
            },
        )

    async def emit_metadata(self, data: dict[str, Any]) -> None:
        """Emit metadata event."""
        await self._emit(EventType.METADATA, data)

    async def emit_complete(
        self,
        result: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Emit completion event."""
        self.status.state = StreamState.COMPLETED
        self.status.completed_at = datetime.now(UTC)
        self.status.progress_percent = 100.0

        data = {
            "stream_id": str(self.stream_id),
            "total_events": self.status.total_events,
            "total_tokens": self.status.total_tokens,
        }
        if result is not None:
            data["result"] = result

        await self._emit(EventType.COMPLETE, data, metadata)

    async def emit_error(
        self,
        error: str,
        error_code: str | None = None,
        recoverable: bool = False,
    ) -> None:
        """Emit error event."""
        self.status.state = StreamState.ERROR
        self.status.error = error
        self.status.completed_at = datetime.now(UTC)

        await self._emit(
            EventType.ERROR,
            {
                "error": error,
                "code": error_code,
                "recoverable": recoverable,
            },
        )

    async def emit_cancelled(self, reason: str | None = None) -> None:
        """Emit cancellation event."""
        self.status.state = StreamState.CANCELLED
        self.status.completed_at = datetime.now(UTC)

        await self._emit(
            EventType.CANCELLED,
            {"reason": reason},
        )


# =============================================================================
# Streaming Response Models
# =============================================================================


class StreamConfig(BaseModel):
    """Configuration for streaming responses."""

    enable_heartbeat: bool = Field(True, description="Enable heartbeat events")
    heartbeat_interval: float = Field(30.0, ge=1.0, description="Heartbeat interval (seconds)")
    buffer_size: int = Field(10, ge=1, description="Event buffer size")
    include_tokens: bool = Field(True, description="Emit individual token events")
    include_progress: bool = Field(True, description="Emit progress events")
    chunk_size: int = Field(1, ge=1, description="Tokens per chunk event")


# =============================================================================
# Streaming Agent Wrapper
# =============================================================================


class StreamingAgentMixin:
    """Mixin that adds streaming capabilities to agents.

    Add this mixin to any agent class to enable streaming:

        class MyAgent(BaseAgent, StreamingAgentMixin):
            async def run(self, query: str) -> str:
                # Use streaming context
                async with self.create_stream() as ctx:
                    await ctx.emit_start()
                    # ... generate response ...
                    await ctx.emit_complete(result)
                return result
    """

    def __init__(
        self,
        *args: Any,
        stream_config: StreamConfig | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._stream_config = stream_config or StreamConfig()
        self._active_streams: dict[UUID, StreamingContext] = {}

    def create_stream(
        self,
        handler: StreamHandler | None = None,
        stream_id: UUID | None = None,
    ) -> StreamingContext:
        """Create a new streaming context.

        Args:
            handler: Optional custom handler (uses AsyncGeneratorHandler if not provided)
            stream_id: Optional stream ID

        Returns:
            StreamingContext for emitting events
        """
        if handler is None:
            handler = AsyncGeneratorHandler()

        ctx = StreamingContext(
            handler=handler,
            stream_id=stream_id,
            heartbeat_interval=(
                self._stream_config.heartbeat_interval
                if self._stream_config.enable_heartbeat
                else 0
            ),
        )
        self._active_streams[ctx.stream_id] = ctx
        return ctx

    def get_stream(self, stream_id: UUID) -> StreamingContext | None:
        """Get an active stream by ID."""
        return self._active_streams.get(stream_id)

    def cancel_stream(self, stream_id: UUID) -> bool:
        """Cancel an active stream.

        Args:
            stream_id: Stream to cancel

        Returns:
            True if stream was found and cancelled
        """
        ctx = self._active_streams.get(stream_id)
        if ctx:
            ctx.cancel()
            return True
        return False

    def list_active_streams(self) -> list[StreamStatus]:
        """List all active streams."""
        return [ctx.status for ctx in self._active_streams.values()]


# =============================================================================
# SSE Response Generator
# =============================================================================


async def create_sse_response(
    events: AsyncGenerator[StreamEvent, None],
) -> AsyncGenerator[str, None]:
    """Convert stream events to SSE format.

    Args:
        events: Async generator of events

    Yields:
        SSE-formatted strings

    Example:
        from starlette.responses import StreamingResponse

        @router.get("/stream")
        async def stream_endpoint():
            agent = StreamingAgent(...)
            events = agent.stream("query")
            return StreamingResponse(
                create_sse_response(events),
                media_type="text/event-stream",
            )
    """
    yield "retry: 1000\n\n"  # Reconnection interval

    async for event in events:
        yield event.to_sse()


async def create_json_stream(
    events: AsyncGenerator[StreamEvent, None],
) -> AsyncGenerator[str, None]:
    """Convert stream events to newline-delimited JSON.

    Args:
        events: Async generator of events

    Yields:
        JSON strings followed by newlines

    Example:
        async for line in create_json_stream(events):
            await websocket.send_text(line)
    """
    async for event in events:
        yield event.to_json() + "\n"


# =============================================================================
# Exports
# =============================================================================


__all__ = [
    # Event types
    "EventType",
    "StreamEvent",
    # Stream state
    "StreamState",
    "StreamStatus",
    # Handlers
    "AsyncGeneratorHandler",
    "CallbackHandler",
    "StreamHandler",
    # Context
    "StreamingContext",
    # Configuration
    "StreamConfig",
    # Mixin
    "StreamingAgentMixin",
    # Utilities
    "create_json_stream",
    "create_sse_response",
]
