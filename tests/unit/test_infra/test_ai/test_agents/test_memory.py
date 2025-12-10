"""Tests for the AI agent memory systems."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from example_service.infra.ai.agents.memory import (
    BaseMemory,
    BufferMemory,
    ConversationMemory,
    MemoryMessage,
    SummaryMemory,
    WindowMemory,
    create_memory,
)


class TestMemoryMessage:
    """Tests for MemoryMessage."""

    def test_create_basic_message(self) -> None:
        """Test creating a basic message."""
        msg = MemoryMessage(role="user", content="Hello!")

        assert msg.role == "user"
        assert msg.content == "Hello!"
        assert msg.timestamp is not None
        assert msg.metadata == {}

    def test_message_to_dict(self) -> None:
        """Test converting message to dict."""
        msg = MemoryMessage(
            role="assistant",
            content="Hi there!",
            name="helper",
        )

        d = msg.to_dict()

        assert d["role"] == "assistant"
        assert d["content"] == "Hi there!"
        assert d["name"] == "helper"
        assert "timestamp" not in d  # Not in API dict

    def test_message_to_dict_with_tool_calls(self) -> None:
        """Test message with tool calls."""
        msg = MemoryMessage(
            role="assistant",
            tool_calls=[{"id": "call_1", "function": {"name": "search"}}],
        )

        d = msg.to_dict()

        assert d["role"] == "assistant"
        assert len(d["tool_calls"]) == 1
        assert d["tool_calls"][0]["id"] == "call_1"

    def test_message_from_dict(self) -> None:
        """Test creating message from dict."""
        data = {
            "role": "user",
            "content": "Test content",
            "timestamp": "2024-01-01T00:00:00+00:00",
            "token_count": 10,
            "metadata": {"source": "test"},
        }

        msg = MemoryMessage.from_dict(data)

        assert msg.role == "user"
        assert msg.content == "Test content"
        assert msg.token_count == 10
        assert msg.metadata["source"] == "test"

    def test_message_hash(self) -> None:
        """Test message hashing for deduplication."""
        msg1 = MemoryMessage(role="user", content="Hello")
        msg2 = MemoryMessage(role="user", content="Hello")
        msg3 = MemoryMessage(role="user", content="Different")

        # Same content should have same hash
        assert hash(msg1) == hash(msg2)
        # Different content should have different hash
        assert hash(msg1) != hash(msg3)


class TestBufferMemory:
    """Tests for BufferMemory."""

    def test_add_message(self) -> None:
        """Test adding messages."""
        memory = BufferMemory(max_messages=10)

        memory.add_message({"role": "user", "content": "Hello"})
        memory.add_message({"role": "assistant", "content": "Hi!"})

        assert memory.message_count == 2

    def test_add_message_object(self) -> None:
        """Test adding MemoryMessage objects."""
        memory = BufferMemory()

        memory.add_message(MemoryMessage(role="user", content="Test"))

        messages = memory.get_messages()
        assert len(messages) == 1
        assert messages[0]["content"] == "Test"

    def test_max_messages_limit(self) -> None:
        """Test that max_messages is enforced."""
        memory = BufferMemory(max_messages=3)

        for i in range(5):
            memory.add_message({"role": "user", "content": f"Message {i}"})

        assert memory.message_count == 3
        messages = memory.get_messages()
        # Should have last 3 messages
        assert messages[0]["content"] == "Message 2"
        assert messages[2]["content"] == "Message 4"

    def test_add_messages_batch(self) -> None:
        """Test adding multiple messages at once."""
        memory = BufferMemory()

        messages = [
            {"role": "user", "content": "First"},
            {"role": "assistant", "content": "Second"},
            {"role": "user", "content": "Third"},
        ]
        memory.add_messages(messages)

        assert memory.message_count == 3

    def test_get_messages(self) -> None:
        """Test getting messages as dicts."""
        memory = BufferMemory()
        memory.add_message({"role": "user", "content": "Hello"})

        messages = memory.get_messages()

        assert isinstance(messages, list)
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Hello"

    def test_get_memory_messages(self) -> None:
        """Test getting messages as MemoryMessage objects."""
        memory = BufferMemory()
        memory.add_message({"role": "user", "content": "Hello"})

        messages = memory.get_memory_messages()

        assert isinstance(messages[0], MemoryMessage)
        assert messages[0].role == "user"

    def test_clear(self) -> None:
        """Test clearing memory."""
        memory = BufferMemory()
        memory.add_message({"role": "user", "content": "Hello"})

        memory.clear()

        assert memory.message_count == 0
        assert memory.get_messages() == []

    def test_token_tracking(self) -> None:
        """Test token count tracking."""
        memory = BufferMemory()

        memory.add_message(MemoryMessage(role="user", content="Test", token_count=10))
        memory.add_message(MemoryMessage(role="assistant", content="Reply", token_count=15))

        assert memory.token_count == 25

    def test_serialize_deserialize(self) -> None:
        """Test serialization and deserialization."""
        memory = BufferMemory(max_messages=50)
        memory.add_message({"role": "user", "content": "Hello"})
        memory.add_message({"role": "assistant", "content": "Hi!"})

        # Serialize
        data = memory.to_dict()
        assert data["type"] == "buffer"
        assert data["max_messages"] == 50
        assert len(data["messages"]) == 2

        # Deserialize
        restored = BufferMemory.from_dict(data)
        assert restored.max_messages == 50
        assert restored.message_count == 2


class TestWindowMemory:
    """Tests for WindowMemory."""

    def test_sliding_window(self) -> None:
        """Test sliding window behavior."""
        memory = WindowMemory(window_size=3)

        for i in range(5):
            memory.add_message({"role": "user", "content": f"Message {i}"})

        messages = memory.get_messages()
        # Should only have last 3 non-system messages
        assert len(messages) == 3
        assert messages[0]["content"] == "Message 2"

    def test_keep_system_messages(self) -> None:
        """Test that system messages are preserved."""
        memory = WindowMemory(window_size=2, keep_system=True)

        memory.add_message({"role": "system", "content": "You are helpful"})
        memory.add_message({"role": "user", "content": "Message 1"})
        memory.add_message({"role": "user", "content": "Message 2"})
        memory.add_message({"role": "user", "content": "Message 3"})

        messages = memory.get_messages()

        # Should have system + last 2 user messages
        assert len(messages) == 3
        assert messages[0]["role"] == "system"
        assert messages[1]["content"] == "Message 2"
        assert messages[2]["content"] == "Message 3"

    def test_no_duplicate_system_messages(self) -> None:
        """Test system messages aren't duplicated."""
        memory = WindowMemory(window_size=5)

        memory.add_message({"role": "system", "content": "Same content"})
        memory.add_message({"role": "system", "content": "Same content"})

        messages = memory.get_messages()
        system_msgs = [m for m in messages if m["role"] == "system"]
        assert len(system_msgs) == 1

    def test_clear_conversation(self) -> None:
        """Test clearing conversation but keeping system."""
        memory = WindowMemory(window_size=5)
        memory.add_message({"role": "system", "content": "Instructions"})
        memory.add_message({"role": "user", "content": "Hello"})

        memory.clear_conversation()

        messages = memory.get_messages()
        assert len(messages) == 1
        assert messages[0]["role"] == "system"

    def test_serialize_deserialize(self) -> None:
        """Test serialization and deserialization."""
        memory = WindowMemory(window_size=5, keep_system=True)
        memory.add_message({"role": "system", "content": "System"})
        memory.add_message({"role": "user", "content": "User"})

        data = memory.to_dict()
        assert data["type"] == "window"

        restored = WindowMemory.from_dict(data)
        assert restored.window_size == 5
        assert restored.message_count == 2


class TestSummaryMemory:
    """Tests for SummaryMemory."""

    def test_recent_messages(self) -> None:
        """Test recent messages are kept."""
        memory = SummaryMemory(max_recent=3)

        for i in range(3):
            memory.add_message({"role": "user", "content": f"Message {i}"})

        messages = memory.get_messages()
        assert len(messages) == 3

    def test_overflow_to_pending(self) -> None:
        """Test messages overflow to pending summary."""
        memory = SummaryMemory(max_recent=2)

        for i in range(4):
            memory.add_message({"role": "user", "content": f"Message {i}"})

        # 2 should be in recent, 2 pending for summary
        assert memory.message_count == 2  # Only counts recent + system
        assert memory.pending_count == 2

    def test_set_summary(self) -> None:
        """Test setting summary directly."""
        memory = SummaryMemory(max_recent=5)
        memory.add_message({"role": "user", "content": "Hello"})

        memory.set_summary("Previous conversation about greetings")

        messages = memory.get_messages()
        # Should include summary as system message
        summary_msgs = [m for m in messages if "summary" in m.get("content", "").lower()]
        assert len(summary_msgs) == 1

    def test_system_messages_preserved(self) -> None:
        """Test system messages are preserved."""
        memory = SummaryMemory(max_recent=3)
        memory.add_message({"role": "system", "content": "Instructions"})
        memory.add_message({"role": "user", "content": "Hello"})

        messages = memory.get_messages()
        assert messages[0]["role"] == "system"

    @pytest.mark.anyio
    async def test_summarize_pending(self) -> None:
        """Test summarizing pending messages."""
        async def mock_summarizer(messages: list) -> str:
            return f"Summary of {len(messages)} messages"

        memory = SummaryMemory(max_recent=2, summarizer=mock_summarizer)

        for i in range(4):
            memory.add_message({"role": "user", "content": f"Message {i}"})

        await memory.summarize_pending()

        assert memory.pending_count == 0
        assert memory.get_summary() is not None
        assert "Summary of" in memory.get_summary()  # type: ignore

    def test_serialize_deserialize(self) -> None:
        """Test serialization and deserialization."""
        memory = SummaryMemory(max_recent=5)
        memory.add_message({"role": "user", "content": "Test"})
        memory.set_summary("Previous context")

        data = memory.to_dict()
        assert data["type"] == "summary"
        assert data["summary"] == "Previous context"

        restored = SummaryMemory.from_dict(data)
        assert restored.get_summary() == "Previous context"


class TestConversationMemory:
    """Tests for ConversationMemory."""

    def test_short_term_buffer(self) -> None:
        """Test short-term memory."""
        memory = ConversationMemory(max_short_term=5)

        for i in range(3):
            memory.add_message({"role": "user", "content": f"Message {i}"})

        assert memory.message_count == 3

    def test_overflow_to_long_term(self) -> None:
        """Test overflow to long-term memory."""
        short = WindowMemory(window_size=2)
        long = BufferMemory(max_messages=100)
        memory = ConversationMemory(
            short_term=short,
            long_term=long,
            max_short_term=2,
        )

        for i in range(5):
            memory.add_message({"role": "user", "content": f"Message {i}"})

        # Messages should be in both short and long term
        messages = memory.get_messages()
        assert len(messages) > 2  # Some in long-term

    def test_combined_messages(self) -> None:
        """Test getting combined messages."""
        memory = ConversationMemory(max_short_term=3)

        for i in range(3):
            memory.add_message({"role": "user", "content": f"Message {i}"})

        messages = memory.get_messages()
        assert len(messages) == 3

    def test_clear_short_term_only(self) -> None:
        """Test clearing only short-term memory."""
        memory = ConversationMemory(max_short_term=5)
        memory.add_message({"role": "user", "content": "Test"})

        memory.clear_short_term()

        # Should still work after clear
        assert memory.short_term.message_count == 0

    def test_serialize_deserialize(self) -> None:
        """Test serialization and deserialization."""
        memory = ConversationMemory(max_short_term=10)
        memory.add_message({"role": "user", "content": "Test"})

        data = memory.to_dict()
        assert data["type"] == "conversation"

        restored = ConversationMemory.from_dict(data)
        assert restored.max_short_term == 10


class TestCreateMemory:
    """Tests for the create_memory factory function."""

    def test_create_buffer_memory(self) -> None:
        """Test creating buffer memory."""
        memory = create_memory("buffer", max_messages=50)

        assert isinstance(memory, BufferMemory)
        assert memory.max_messages == 50

    def test_create_window_memory(self) -> None:
        """Test creating window memory."""
        memory = create_memory("window", window_size=10, keep_system=False)

        assert isinstance(memory, WindowMemory)
        assert memory.window_size == 10
        assert memory.keep_system is False

    def test_create_summary_memory(self) -> None:
        """Test creating summary memory."""
        memory = create_memory("summary", max_recent=5)

        assert isinstance(memory, SummaryMemory)
        assert memory.max_recent == 5

    def test_create_conversation_memory(self) -> None:
        """Test creating conversation memory."""
        memory = create_memory("conversation", max_short_term=15)

        assert isinstance(memory, ConversationMemory)
        assert memory.max_short_term == 15

    def test_invalid_memory_type(self) -> None:
        """Test invalid memory type raises error."""
        with pytest.raises(ValueError, match="Unknown memory type"):
            create_memory("invalid_type")
