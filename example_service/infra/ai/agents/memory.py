"""Memory systems for AI agents.

This module provides memory abstractions for maintaining context:
- BufferMemory: Simple message buffer with size limit
- WindowMemory: Sliding window of recent messages
- SummaryMemory: Summarizes old messages to maintain context
- ConversationMemory: Combines multiple memory strategies

Design Principles:
1. Pluggable: Easy to swap memory implementations
2. Token-aware: Respects token limits
3. Persistent: Can be saved/restored from database
4. Observable: Tracks memory operations

Example:
    from example_service.infra.ai.agents.memory import (
        ConversationMemory,
        BufferMemory,
        SummaryMemory,
    )

    # Simple buffer memory
    memory = BufferMemory(max_messages=100)
    memory.add_message({"role": "user", "content": "Hello"})
    messages = memory.get_messages()

    # Combined memory with summarization
    memory = ConversationMemory(
        short_term=BufferMemory(max_messages=10),
        long_term=SummaryMemory(summarizer=llm_summarize),
    )
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Callable, Protocol
import hashlib
import json
import logging

if TYPE_CHECKING:
    from collections.abc import Awaitable

logger = logging.getLogger(__name__)


class Message(Protocol):
    """Protocol for message-like objects."""

    role: str
    content: str | None


@dataclass
class MemoryMessage:
    """A message in memory.

    Extends basic message with metadata for memory management.
    """

    role: str
    content: str | None = None
    name: str | None = None
    function_call: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None

    # Memory metadata
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    token_count: int | None = None
    message_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for LLM API."""
        msg: dict[str, Any] = {"role": self.role}

        if self.content is not None:
            msg["content"] = self.content
        if self.name:
            msg["name"] = self.name
        if self.function_call:
            msg["function_call"] = self.function_call
        if self.tool_calls:
            msg["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            msg["tool_call_id"] = self.tool_call_id

        return msg

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryMessage:
        """Create from dictionary."""
        return cls(
            role=data["role"],
            content=data.get("content"),
            name=data.get("name"),
            function_call=data.get("function_call"),
            tool_calls=data.get("tool_calls"),
            tool_call_id=data.get("tool_call_id"),
            timestamp=datetime.fromisoformat(data["timestamp"])
            if "timestamp" in data
            else datetime.now(UTC),
            token_count=data.get("token_count"),
            message_id=data.get("message_id"),
            metadata=data.get("metadata", {}),
        )

    def __hash__(self) -> int:
        """Hash for deduplication."""
        content = json.dumps(self.to_dict(), sort_keys=True)
        return int(hashlib.md5(content.encode()).hexdigest(), 16)


class BaseMemory(ABC):
    """Abstract base class for memory implementations.

    Memory stores conversation history and provides context
    for agent interactions.
    """

    @abstractmethod
    def add_message(self, message: dict[str, Any] | MemoryMessage) -> None:
        """Add a message to memory.

        Args:
            message: Message to add (dict or MemoryMessage)
        """
        pass

    @abstractmethod
    def add_messages(self, messages: list[dict[str, Any] | MemoryMessage]) -> None:
        """Add multiple messages to memory.

        Args:
            messages: List of messages to add
        """
        pass

    @abstractmethod
    def get_messages(self) -> list[dict[str, Any]]:
        """Get messages for LLM context.

        Returns:
            List of message dicts for LLM API
        """
        pass

    @abstractmethod
    def clear(self) -> None:
        """Clear all messages from memory."""
        pass

    @abstractmethod
    def to_dict(self) -> dict[str, Any]:
        """Serialize memory state for persistence."""
        pass

    @classmethod
    @abstractmethod
    def from_dict(cls, data: dict[str, Any]) -> BaseMemory:
        """Restore memory from serialized state."""
        pass

    @property
    @abstractmethod
    def message_count(self) -> int:
        """Get number of messages in memory."""
        pass

    @property
    def token_count(self) -> int | None:
        """Get estimated token count (if available)."""
        return None


class BufferMemory(BaseMemory):
    """Simple buffer memory with size limit.

    Stores messages in a FIFO buffer. When max_messages is reached,
    oldest messages are removed.

    Example:
        memory = BufferMemory(max_messages=50)
        memory.add_message({"role": "user", "content": "Hello"})
        memory.add_message({"role": "assistant", "content": "Hi there!"})
        messages = memory.get_messages()
    """

    def __init__(
        self,
        max_messages: int = 100,
        max_tokens: int | None = None,
    ) -> None:
        """Initialize buffer memory.

        Args:
            max_messages: Maximum messages to keep
            max_tokens: Maximum tokens to keep (requires token counting)
        """
        self.max_messages = max_messages
        self.max_tokens = max_tokens
        self._messages: deque[MemoryMessage] = deque(maxlen=max_messages)
        self._total_tokens = 0

    def add_message(self, message: dict[str, Any] | MemoryMessage) -> None:
        """Add a message to the buffer."""
        if isinstance(message, dict):
            message = MemoryMessage(**message)

        # Track tokens if available
        if message.token_count:
            self._total_tokens += message.token_count

        # Check if we need to remove old messages for token limit
        if self.max_tokens and self._total_tokens > self.max_tokens:
            self._trim_to_token_limit()

        self._messages.append(message)

    def add_messages(self, messages: list[dict[str, Any] | MemoryMessage]) -> None:
        """Add multiple messages."""
        for msg in messages:
            self.add_message(msg)

    def get_messages(self) -> list[dict[str, Any]]:
        """Get all messages as dicts."""
        return [msg.to_dict() for msg in self._messages]

    def get_memory_messages(self) -> list[MemoryMessage]:
        """Get all messages as MemoryMessage objects."""
        return list(self._messages)

    def clear(self) -> None:
        """Clear all messages."""
        self._messages.clear()
        self._total_tokens = 0

    def _trim_to_token_limit(self) -> None:
        """Remove oldest messages to meet token limit."""
        while self._messages and self._total_tokens > self.max_tokens:
            removed = self._messages.popleft()
            if removed.token_count:
                self._total_tokens -= removed.token_count

    def to_dict(self) -> dict[str, Any]:
        """Serialize memory state."""
        return {
            "type": "buffer",
            "max_messages": self.max_messages,
            "max_tokens": self.max_tokens,
            "messages": [
                {
                    **msg.to_dict(),
                    "timestamp": msg.timestamp.isoformat(),
                    "token_count": msg.token_count,
                    "message_id": msg.message_id,
                    "metadata": msg.metadata,
                }
                for msg in self._messages
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BufferMemory:
        """Restore from serialized state."""
        memory = cls(
            max_messages=data.get("max_messages", 100),
            max_tokens=data.get("max_tokens"),
        )
        for msg_data in data.get("messages", []):
            memory.add_message(MemoryMessage.from_dict(msg_data))
        return memory

    @property
    def message_count(self) -> int:
        """Get message count."""
        return len(self._messages)

    @property
    def token_count(self) -> int | None:
        """Get total token count."""
        return self._total_tokens if self._total_tokens > 0 else None


class WindowMemory(BaseMemory):
    """Sliding window memory.

    Keeps only the most recent N messages, plus any system messages.

    Example:
        memory = WindowMemory(window_size=10, keep_system=True)
        # System message is always kept
        memory.add_message({"role": "system", "content": "You are a helpful assistant"})
        # Only last 10 non-system messages are kept
        for i in range(20):
            memory.add_message({"role": "user", "content": f"Message {i}"})
    """

    def __init__(
        self,
        window_size: int = 10,
        keep_system: bool = True,
    ) -> None:
        """Initialize window memory.

        Args:
            window_size: Number of recent messages to keep
            keep_system: Always keep system messages
        """
        self.window_size = window_size
        self.keep_system = keep_system
        self._system_messages: list[MemoryMessage] = []
        self._messages: deque[MemoryMessage] = deque(maxlen=window_size)

    def add_message(self, message: dict[str, Any] | MemoryMessage) -> None:
        """Add a message."""
        if isinstance(message, dict):
            message = MemoryMessage(**message)

        if self.keep_system and message.role == "system":
            # Check for duplicate system messages
            if not any(
                m.content == message.content for m in self._system_messages
            ):
                self._system_messages.append(message)
        else:
            self._messages.append(message)

    def add_messages(self, messages: list[dict[str, Any] | MemoryMessage]) -> None:
        """Add multiple messages."""
        for msg in messages:
            self.add_message(msg)

    def get_messages(self) -> list[dict[str, Any]]:
        """Get messages with system messages first."""
        all_messages = self._system_messages + list(self._messages)
        return [msg.to_dict() for msg in all_messages]

    def clear(self) -> None:
        """Clear all messages (including system)."""
        self._system_messages.clear()
        self._messages.clear()

    def clear_conversation(self) -> None:
        """Clear conversation but keep system messages."""
        self._messages.clear()

    def to_dict(self) -> dict[str, Any]:
        """Serialize memory state."""
        return {
            "type": "window",
            "window_size": self.window_size,
            "keep_system": self.keep_system,
            "system_messages": [
                {
                    **msg.to_dict(),
                    "timestamp": msg.timestamp.isoformat(),
                }
                for msg in self._system_messages
            ],
            "messages": [
                {
                    **msg.to_dict(),
                    "timestamp": msg.timestamp.isoformat(),
                }
                for msg in self._messages
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WindowMemory:
        """Restore from serialized state."""
        memory = cls(
            window_size=data.get("window_size", 10),
            keep_system=data.get("keep_system", True),
        )
        for msg_data in data.get("system_messages", []):
            memory._system_messages.append(MemoryMessage.from_dict(msg_data))
        for msg_data in data.get("messages", []):
            memory._messages.append(MemoryMessage.from_dict(msg_data))
        return memory

    @property
    def message_count(self) -> int:
        """Get total message count."""
        return len(self._system_messages) + len(self._messages)


# Type for summarizer function
Summarizer = Callable[[list[dict[str, Any]]], Awaitable[str]]


class SummaryMemory(BaseMemory):
    """Memory that summarizes old messages.

    Maintains recent messages in full, but summarizes older messages
    to preserve context while reducing token usage.

    Example:
        async def summarize(messages):
            # Use LLM to summarize
            return await llm.summarize(messages)

        memory = SummaryMemory(
            max_recent=10,
            summarizer=summarize,
        )
    """

    def __init__(
        self,
        max_recent: int = 10,
        summarizer: Summarizer | None = None,
        summary_prompt: str | None = None,
    ) -> None:
        """Initialize summary memory.

        Args:
            max_recent: Number of recent messages to keep in full
            summarizer: Async function to summarize messages
            summary_prompt: System prompt for summary context
        """
        self.max_recent = max_recent
        self._summarizer = summarizer
        self._summary_prompt = summary_prompt or (
            "The following is a summary of the earlier conversation:"
        )
        self._summary: str | None = None
        self._system_messages: list[MemoryMessage] = []
        self._recent_messages: deque[MemoryMessage] = deque(maxlen=max_recent)
        self._pending_for_summary: list[MemoryMessage] = []

    def add_message(self, message: dict[str, Any] | MemoryMessage) -> None:
        """Add a message."""
        if isinstance(message, dict):
            message = MemoryMessage(**message)

        if message.role == "system":
            if not any(
                m.content == message.content for m in self._system_messages
            ):
                self._system_messages.append(message)
        else:
            # If recent buffer is full, move oldest to pending summary
            if len(self._recent_messages) >= self.max_recent:
                oldest = self._recent_messages.popleft()
                self._pending_for_summary.append(oldest)

            self._recent_messages.append(message)

    def add_messages(self, messages: list[dict[str, Any] | MemoryMessage]) -> None:
        """Add multiple messages."""
        for msg in messages:
            self.add_message(msg)

    async def summarize_pending(self) -> None:
        """Summarize pending messages.

        Should be called periodically to update the summary.
        """
        if not self._pending_for_summary or not self._summarizer:
            return

        messages_to_summarize = [msg.to_dict() for msg in self._pending_for_summary]

        # Include existing summary in context
        if self._summary:
            messages_to_summarize.insert(0, {
                "role": "system",
                "content": f"Previous summary: {self._summary}",
            })

        try:
            self._summary = await self._summarizer(messages_to_summarize)
            self._pending_for_summary.clear()
            logger.debug(f"Updated summary: {self._summary[:100]}...")
        except Exception as e:
            logger.warning(f"Failed to summarize: {e}")

    def get_messages(self) -> list[dict[str, Any]]:
        """Get messages with summary."""
        messages = []

        # Add system messages
        for msg in self._system_messages:
            messages.append(msg.to_dict())

        # Add summary as context
        if self._summary:
            messages.append({
                "role": "system",
                "content": f"{self._summary_prompt}\n\n{self._summary}",
            })

        # Add recent messages
        for msg in self._recent_messages:
            messages.append(msg.to_dict())

        return messages

    def get_summary(self) -> str | None:
        """Get the current summary."""
        return self._summary

    def set_summary(self, summary: str) -> None:
        """Set the summary directly."""
        self._summary = summary

    def clear(self) -> None:
        """Clear all messages and summary."""
        self._system_messages.clear()
        self._recent_messages.clear()
        self._pending_for_summary.clear()
        self._summary = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize memory state."""
        return {
            "type": "summary",
            "max_recent": self.max_recent,
            "summary_prompt": self._summary_prompt,
            "summary": self._summary,
            "system_messages": [
                {
                    **msg.to_dict(),
                    "timestamp": msg.timestamp.isoformat(),
                }
                for msg in self._system_messages
            ],
            "recent_messages": [
                {
                    **msg.to_dict(),
                    "timestamp": msg.timestamp.isoformat(),
                }
                for msg in self._recent_messages
            ],
            "pending_for_summary": [
                {
                    **msg.to_dict(),
                    "timestamp": msg.timestamp.isoformat(),
                }
                for msg in self._pending_for_summary
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SummaryMemory:
        """Restore from serialized state."""
        memory = cls(
            max_recent=data.get("max_recent", 10),
            summary_prompt=data.get("summary_prompt"),
        )
        memory._summary = data.get("summary")

        for msg_data in data.get("system_messages", []):
            memory._system_messages.append(MemoryMessage.from_dict(msg_data))
        for msg_data in data.get("recent_messages", []):
            memory._recent_messages.append(MemoryMessage.from_dict(msg_data))
        for msg_data in data.get("pending_for_summary", []):
            memory._pending_for_summary.append(MemoryMessage.from_dict(msg_data))

        return memory

    @property
    def message_count(self) -> int:
        """Get count of recent messages."""
        return len(self._system_messages) + len(self._recent_messages)

    @property
    def pending_count(self) -> int:
        """Get count of messages pending summarization."""
        return len(self._pending_for_summary)


class ConversationMemory(BaseMemory):
    """Combined memory with short-term and long-term storage.

    Uses a short-term buffer for recent context and long-term
    storage (with summarization) for historical context.

    Example:
        memory = ConversationMemory(
            short_term=WindowMemory(window_size=10),
            long_term=SummaryMemory(summarizer=llm_summarize),
        )
    """

    def __init__(
        self,
        short_term: BaseMemory | None = None,
        long_term: BaseMemory | None = None,
        max_short_term: int = 20,
    ) -> None:
        """Initialize conversation memory.

        Args:
            short_term: Short-term memory (defaults to WindowMemory)
            long_term: Long-term memory (defaults to BufferMemory)
            max_short_term: Max messages in short-term before overflow
        """
        self.short_term = short_term or WindowMemory(window_size=max_short_term)
        self.long_term = long_term or BufferMemory(max_messages=1000)
        self.max_short_term = max_short_term
        self._overflow_threshold = max_short_term

    def add_message(self, message: dict[str, Any] | MemoryMessage) -> None:
        """Add message to short-term memory."""
        if isinstance(message, dict):
            message = MemoryMessage(**message)

        # Move overflow to long-term if needed
        if self.short_term.message_count >= self._overflow_threshold:
            self._move_to_long_term()

        self.short_term.add_message(message)

    def add_messages(self, messages: list[dict[str, Any] | MemoryMessage]) -> None:
        """Add multiple messages."""
        for msg in messages:
            self.add_message(msg)

    def _move_to_long_term(self) -> None:
        """Move oldest short-term messages to long-term."""
        if isinstance(self.short_term, WindowMemory):
            # Get messages that will be pushed out
            messages = self.short_term.get_messages()
            if messages:
                # Move oldest non-system message to long-term
                for msg in messages:
                    if msg.get("role") != "system":
                        self.long_term.add_message(msg)
                        break

    def get_messages(self) -> list[dict[str, Any]]:
        """Get combined messages from both memories."""
        # Long-term provides historical context
        long_term_msgs = self.long_term.get_messages()

        # Short-term provides recent context
        short_term_msgs = self.short_term.get_messages()

        # Combine, avoiding duplicates
        seen = set()
        combined = []

        for msg in long_term_msgs:
            key = (msg.get("role"), msg.get("content", "")[:100])
            if key not in seen:
                seen.add(key)
                combined.append(msg)

        for msg in short_term_msgs:
            key = (msg.get("role"), msg.get("content", "")[:100])
            if key not in seen:
                seen.add(key)
                combined.append(msg)

        return combined

    def clear(self) -> None:
        """Clear both memories."""
        self.short_term.clear()
        self.long_term.clear()

    def clear_short_term(self) -> None:
        """Clear only short-term memory."""
        self.short_term.clear()

    def to_dict(self) -> dict[str, Any]:
        """Serialize memory state."""
        return {
            "type": "conversation",
            "max_short_term": self.max_short_term,
            "short_term": self.short_term.to_dict(),
            "long_term": self.long_term.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConversationMemory:
        """Restore from serialized state."""
        short_term_data = data.get("short_term", {})
        long_term_data = data.get("long_term", {})

        short_term = _deserialize_memory(short_term_data)
        long_term = _deserialize_memory(long_term_data)

        return cls(
            short_term=short_term,
            long_term=long_term,
            max_short_term=data.get("max_short_term", 20),
        )

    @property
    def message_count(self) -> int:
        """Get total message count."""
        return self.short_term.message_count + self.long_term.message_count


def _deserialize_memory(data: dict[str, Any]) -> BaseMemory:
    """Deserialize memory from dict based on type."""
    memory_type = data.get("type", "buffer")

    if memory_type == "buffer":
        return BufferMemory.from_dict(data)
    elif memory_type == "window":
        return WindowMemory.from_dict(data)
    elif memory_type == "summary":
        return SummaryMemory.from_dict(data)
    elif memory_type == "conversation":
        return ConversationMemory.from_dict(data)
    else:
        logger.warning(f"Unknown memory type: {memory_type}, using BufferMemory")
        return BufferMemory.from_dict(data)


# Factory function for creating memory instances
def create_memory(
    memory_type: str = "buffer",
    **kwargs: Any,
) -> BaseMemory:
    """Create a memory instance.

    Args:
        memory_type: Type of memory (buffer, window, summary, conversation)
        **kwargs: Memory-specific configuration

    Returns:
        Configured memory instance
    """
    if memory_type == "buffer":
        return BufferMemory(
            max_messages=kwargs.get("max_messages", 100),
            max_tokens=kwargs.get("max_tokens"),
        )
    elif memory_type == "window":
        return WindowMemory(
            window_size=kwargs.get("window_size", 10),
            keep_system=kwargs.get("keep_system", True),
        )
    elif memory_type == "summary":
        return SummaryMemory(
            max_recent=kwargs.get("max_recent", 10),
            summarizer=kwargs.get("summarizer"),
            summary_prompt=kwargs.get("summary_prompt"),
        )
    elif memory_type == "conversation":
        return ConversationMemory(
            short_term=kwargs.get("short_term"),
            long_term=kwargs.get("long_term"),
            max_short_term=kwargs.get("max_short_term", 20),
        )
    else:
        raise ValueError(f"Unknown memory type: {memory_type}")
