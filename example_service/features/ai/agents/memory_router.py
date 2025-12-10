"""REST API endpoints for AI Agent memory management.

This module provides endpoints for:
- Managing conversation memories
- Storing and retrieving state data
- Memory persistence and snapshots

Endpoints:
    # Memory operations
    GET  /api/v1/ai/memory/{namespace}           - Get memory state
    POST /api/v1/ai/memory/{namespace}           - Add messages to memory
    DELETE /api/v1/ai/memory/{namespace}         - Clear memory

    # State store operations
    GET  /api/v1/ai/state/{namespace}/{key}      - Get state value
    PUT  /api/v1/ai/state/{namespace}/{key}      - Set state value
    DELETE /api/v1/ai/state/{namespace}/{key}    - Delete state value
    GET  /api/v1/ai/state/{namespace}            - List keys in namespace
    DELETE /api/v1/ai/state/{namespace}          - Clear namespace
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from example_service.features.auth.dependencies import get_current_user
from example_service.features.users.models import User
from example_service.infra.ai.agents.memory import (
    BufferMemory,
    ConversationMemory,
    MemoryMessage,
    SummaryMemory,
    WindowMemory,
    create_memory,
)
from example_service.infra.ai.agents.state_store import (
    InMemoryStateStore,
    ScopedStateStore,
    StateKey,
    get_state_store,
)

router = APIRouter(prefix="/memory", tags=["AI Memory"])


# =============================================================================
# In-memory storage (would use Redis/DB in production)
# =============================================================================

# Memory storage keyed by tenant:namespace
_memory_store: dict[str, Any] = {}


def get_memory_key(tenant_id: UUID, namespace: str) -> str:
    """Generate memory storage key."""
    return f"{tenant_id}:{namespace}"


def get_or_create_memory(
    tenant_id: UUID,
    namespace: str,
    memory_type: str = "buffer",
    **config: Any,
) -> Any:
    """Get or create a memory instance for the tenant."""
    key = get_memory_key(tenant_id, namespace)
    if key not in _memory_store:
        _memory_store[key] = create_memory(memory_type, **config)
    return _memory_store[key]


# =============================================================================
# Request/Response Schemas
# =============================================================================


class MessageSchema(BaseModel):
    """Schema for a memory message."""

    role: str = Field(..., description="Message role (user, assistant, system, tool)")
    content: str | None = Field(None, description="Message content")
    name: str | None = Field(None, description="Optional name")
    function_call: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AddMessagesRequest(BaseModel):
    """Request to add messages to memory."""

    messages: list[MessageSchema]


class MemoryStateResponse(BaseModel):
    """Response for memory state."""

    namespace: str
    memory_type: str
    message_count: int
    token_count: int | None
    messages: list[MessageSchema]

    # Additional info depending on memory type
    summary: str | None = None
    pending_for_summary: int = 0


class MemoryConfigRequest(BaseModel):
    """Request to configure memory."""

    memory_type: str = Field(
        "buffer",
        description="Memory type: buffer, window, summary, conversation",
    )
    max_messages: int = Field(100, ge=1, le=10000, description="Maximum messages")
    window_size: int = Field(10, ge=1, le=1000, description="Window size (for window memory)")
    max_recent: int = Field(10, ge=1, le=1000, description="Recent messages (for summary)")
    max_short_term: int = Field(20, ge=1, le=1000, description="Short-term size (for conversation)")


class StateValueRequest(BaseModel):
    """Request to set a state value."""

    value: Any
    ttl_seconds: int | None = Field(None, ge=1, description="Time-to-live in seconds")
    metadata: dict[str, Any] = Field(default_factory=dict)


class StateValueResponse(BaseModel):
    """Response for a state value."""

    key: str
    value: Any
    exists: bool
    metadata: dict[str, Any] = Field(default_factory=dict)


class StateListResponse(BaseModel):
    """Response for listing state keys."""

    namespace: str
    keys: list[str]
    count: int


# =============================================================================
# Memory Endpoints
# =============================================================================


@router.get("/{namespace}", response_model=MemoryStateResponse)
async def get_memory_state(
    namespace: str,
    include_messages: bool = Query(True, description="Include message list"),
    current_user: User = Depends(get_current_user),
) -> MemoryStateResponse:
    """Get memory state for a namespace.

    Returns the current state of the memory including:
    - Message count
    - Token count (if tracked)
    - Messages (if include_messages is True)
    - Summary (for summary memory)
    """
    key = get_memory_key(current_user.tenant_id, namespace)

    if key not in _memory_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory namespace '{namespace}' not found",
        )

    memory = _memory_store[key]

    # Determine memory type
    memory_type = "buffer"
    if isinstance(memory, WindowMemory):
        memory_type = "window"
    elif isinstance(memory, SummaryMemory):
        memory_type = "summary"
    elif isinstance(memory, ConversationMemory):
        memory_type = "conversation"

    messages = []
    if include_messages:
        for msg in memory.get_messages():
            messages.append(
                MessageSchema(
                    role=msg.get("role", ""),
                    content=msg.get("content"),
                    name=msg.get("name"),
                    function_call=msg.get("function_call"),
                    tool_calls=msg.get("tool_calls"),
                    tool_call_id=msg.get("tool_call_id"),
                )
            )

    response = MemoryStateResponse(
        namespace=namespace,
        memory_type=memory_type,
        message_count=memory.message_count,
        token_count=memory.token_count,
        messages=messages,
    )

    # Add summary info if applicable
    if isinstance(memory, SummaryMemory):
        response.summary = memory.get_summary()
        response.pending_for_summary = memory.pending_count

    return response


@router.post("/{namespace}", response_model=MemoryStateResponse, status_code=201)
async def add_messages(
    namespace: str,
    request: AddMessagesRequest,
    memory_type: str = Query("buffer", description="Memory type to create if doesn't exist"),
    max_messages: int = Query(100, ge=1, le=10000),
    current_user: User = Depends(get_current_user),
) -> MemoryStateResponse:
    """Add messages to memory.

    Creates the memory namespace if it doesn't exist.
    """
    memory = get_or_create_memory(
        current_user.tenant_id,
        namespace,
        memory_type=memory_type,
        max_messages=max_messages,
    )

    for msg in request.messages:
        memory.add_message(msg.model_dump(exclude_none=True))

    return await get_memory_state(namespace, include_messages=True, current_user=current_user)


@router.delete("/{namespace}", status_code=204)
async def clear_memory(
    namespace: str,
    current_user: User = Depends(get_current_user),
) -> None:
    """Clear all messages from a memory namespace."""
    key = get_memory_key(current_user.tenant_id, namespace)

    if key not in _memory_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory namespace '{namespace}' not found",
        )

    _memory_store[key].clear()


@router.post("/{namespace}/configure", response_model=MemoryStateResponse)
async def configure_memory(
    namespace: str,
    config: MemoryConfigRequest,
    current_user: User = Depends(get_current_user),
) -> MemoryStateResponse:
    """Configure or reconfigure a memory namespace.

    Warning: This will reset the memory if the type changes.
    """
    key = get_memory_key(current_user.tenant_id, namespace)

    # Create new memory with configuration
    _memory_store[key] = create_memory(
        config.memory_type,
        max_messages=config.max_messages,
        window_size=config.window_size,
        max_recent=config.max_recent,
        max_short_term=config.max_short_term,
    )

    return await get_memory_state(namespace, include_messages=True, current_user=current_user)


@router.get("/{namespace}/export")
async def export_memory(
    namespace: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Export memory state for persistence.

    Returns a serializable representation of the memory
    that can be used to restore state later.
    """
    key = get_memory_key(current_user.tenant_id, namespace)

    if key not in _memory_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory namespace '{namespace}' not found",
        )

    return _memory_store[key].to_dict()


@router.post("/{namespace}/import", response_model=MemoryStateResponse)
async def import_memory(
    namespace: str,
    data: dict[str, Any],
    current_user: User = Depends(get_current_user),
) -> MemoryStateResponse:
    """Import memory state from exported data.

    Restores memory from a previously exported state.
    """
    key = get_memory_key(current_user.tenant_id, namespace)

    # Determine type and restore
    memory_type = data.get("type", "buffer")

    if memory_type == "buffer":
        _memory_store[key] = BufferMemory.from_dict(data)
    elif memory_type == "window":
        _memory_store[key] = WindowMemory.from_dict(data)
    elif memory_type == "summary":
        _memory_store[key] = SummaryMemory.from_dict(data)
    elif memory_type == "conversation":
        _memory_store[key] = ConversationMemory.from_dict(data)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown memory type: {memory_type}",
        )

    return await get_memory_state(namespace, include_messages=True, current_user=current_user)


# =============================================================================
# State Store Endpoints
# =============================================================================

state_router = APIRouter(prefix="/state", tags=["AI State Store"])


def get_scoped_store(tenant_id: UUID, namespace: str) -> ScopedStateStore:
    """Get a scoped state store for the tenant."""
    return ScopedStateStore(
        store=get_state_store(),
        tenant_id=str(tenant_id),
        namespace=namespace,
    )


@state_router.get("/{namespace}/{key}", response_model=StateValueResponse)
async def get_state_value(
    namespace: str,
    key: str,
    current_user: User = Depends(get_current_user),
) -> StateValueResponse:
    """Get a state value by key."""
    store = get_scoped_store(current_user.tenant_id, namespace)
    value = await store.get(key)

    return StateValueResponse(
        key=key,
        value=value,
        exists=value is not None,
    )


@state_router.put("/{namespace}/{key}", response_model=StateValueResponse)
async def set_state_value(
    namespace: str,
    key: str,
    request: StateValueRequest,
    current_user: User = Depends(get_current_user),
) -> StateValueResponse:
    """Set a state value.

    Optionally set a TTL for automatic expiration.
    """
    store = get_scoped_store(current_user.tenant_id, namespace)

    await store.set(
        key,
        request.value,
        ttl_seconds=request.ttl_seconds,
        metadata=request.metadata,
    )

    return StateValueResponse(
        key=key,
        value=request.value,
        exists=True,
        metadata=request.metadata,
    )


@state_router.delete("/{namespace}/{key}", status_code=204)
async def delete_state_value(
    namespace: str,
    key: str,
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete a state value."""
    store = get_scoped_store(current_user.tenant_id, namespace)
    deleted = await store.delete(key)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"State key '{key}' not found in namespace '{namespace}'",
        )


@state_router.get("/{namespace}", response_model=StateListResponse)
async def list_state_keys(
    namespace: str,
    pattern: str | None = Query(None, description="Key pattern filter"),
    current_user: User = Depends(get_current_user),
) -> StateListResponse:
    """List all keys in a state namespace."""
    store = get_scoped_store(current_user.tenant_id, namespace)
    keys = await store.list_keys(pattern=pattern)

    return StateListResponse(
        namespace=namespace,
        keys=keys,
        count=len(keys),
    )


@state_router.delete("/{namespace}", status_code=204)
async def clear_state_namespace(
    namespace: str,
    current_user: User = Depends(get_current_user),
) -> None:
    """Clear all state in a namespace."""
    store = get_scoped_store(current_user.tenant_id, namespace)
    await store.clear()


@state_router.post("/{namespace}/{key}/increment", response_model=StateValueResponse)
async def increment_state_value(
    namespace: str,
    key: str,
    amount: int = Query(1, description="Amount to increment by"),
    current_user: User = Depends(get_current_user),
) -> StateValueResponse:
    """Increment a numeric state value.

    Creates the key with initial value if it doesn't exist.
    """
    store = get_scoped_store(current_user.tenant_id, namespace)

    # Get current value
    current = await store.get(key)
    if current is not None and not isinstance(current, (int, float)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"State key '{key}' is not numeric",
        )

    new_value = (current or 0) + amount
    await store.set(key, new_value)

    return StateValueResponse(
        key=key,
        value=new_value,
        exists=True,
    )


# Combined router for both memory and state endpoints
combined_router = APIRouter()
combined_router.include_router(router)
combined_router.include_router(state_router)
