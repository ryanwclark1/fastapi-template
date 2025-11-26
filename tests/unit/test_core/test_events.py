"""Unit tests for the domain event system."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from example_service.core.events.base import DomainEvent
from example_service.core.events.registry import EventRegistry


# ──────────────────────────────────────────────────────────────
# Test DomainEvent base class
# ──────────────────────────────────────────────────────────────


class TestDomainEvent:
    """Tests for DomainEvent base class."""

    def test_event_has_auto_generated_id(self):
        """Event should auto-generate a UUID v7 event_id."""

        class TestEvent(DomainEvent):
            event_type = "test.event"
            data: str

        event = TestEvent(data="test")

        assert event.event_id is not None
        assert len(event.event_id) == 36  # UUID format

    def test_event_has_timestamp(self):
        """Event should auto-generate a timestamp."""

        class TestEvent(DomainEvent):
            event_type = "test.event"
            value: int

        before = datetime.now(UTC)
        event = TestEvent(value=42)
        after = datetime.now(UTC)

        assert event.timestamp >= before
        assert event.timestamp <= after

    def test_event_with_causation(self):
        """with_causation should copy correlation_id and set causation_id."""

        class TestEvent(DomainEvent):
            event_type = "test.event"
            name: str

        causing_event = TestEvent(name="cause")
        causing_event = causing_event.model_copy(
            update={"correlation_id": "corr-123"}
        )

        caused_event = TestEvent(name="effect")
        caused_event = caused_event.with_causation(causing_event)

        assert caused_event.causation_id == causing_event.event_id
        assert caused_event.correlation_id == "corr-123"

    def test_event_with_correlation(self):
        """with_correlation should set correlation_id."""

        class TestEvent(DomainEvent):
            event_type = "test.event"
            count: int

        event = TestEvent(count=10)
        event = event.with_correlation("my-correlation-id")

        assert event.correlation_id == "my-correlation-id"

    def test_to_outbox_payload(self):
        """to_outbox_payload should return serializable dict."""

        class TestEvent(DomainEvent):
            event_type = "test.created"
            event_version = 2
            item_id: str
            name: str

        event = TestEvent(item_id="123", name="Test Item")
        payload = event.to_outbox_payload()

        assert payload["event_type"] == "test.created"
        assert payload["event_version"] == 2
        assert payload["item_id"] == "123"
        assert payload["name"] == "Test Item"
        assert "event_id" in payload
        assert "timestamp" in payload

    def test_event_metadata(self):
        """Event should support arbitrary metadata."""

        class TestEvent(DomainEvent):
            event_type = "test.event"
            data: str

        event = TestEvent(
            data="test",
            metadata={"user_agent": "test-client", "ip": "127.0.0.1"},
        )

        assert event.metadata["user_agent"] == "test-client"
        assert event.metadata["ip"] == "127.0.0.1"


# ──────────────────────────────────────────────────────────────
# Test EventRegistry
# ──────────────────────────────────────────────────────────────


class TestEventRegistry:
    """Tests for EventRegistry."""

    def test_register_event(self):
        """Registry should track registered event types."""
        registry = EventRegistry()

        @registry.register
        class MyEvent(DomainEvent):
            event_type = "my.event"
            event_version = 1
            value: str

        assert registry.get("my.event") == MyEvent
        assert registry.get("my.event", version=1) == MyEvent

    def test_register_multiple_versions(self):
        """Registry should support multiple versions of an event."""
        registry = EventRegistry()

        @registry.register
        class MyEventV1(DomainEvent):
            event_type = "my.event"
            event_version = 1
            name: str

        @registry.register
        class MyEventV2(DomainEvent):
            event_type = "my.event"
            event_version = 2
            name: str
            description: str | None = None

        # Default (latest version)
        assert registry.get("my.event") == MyEventV2

        # Specific versions
        assert registry.get("my.event", version=1) == MyEventV1
        assert registry.get("my.event", version=2) == MyEventV2

    def test_get_unknown_event(self):
        """Registry should return None for unknown event types."""
        registry = EventRegistry()

        assert registry.get("unknown.event") is None
        assert registry.get("unknown.event", version=1) is None

    def test_deserialize_event(self):
        """Registry should deserialize events from payload."""
        registry = EventRegistry()

        @registry.register
        class ItemCreated(DomainEvent):
            event_type = "item.created"
            event_version = 1
            item_id: str
            title: str

        payload = {
            "event_type": "item.created",
            "event_version": 1,
            "event_id": "abc-123",
            "timestamp": "2025-01-01T00:00:00Z",
            "item_id": "item-456",
            "title": "Test Item",
            "service": "test-service",
            "metadata": {},
        }

        event = registry.deserialize(payload)

        assert isinstance(event, ItemCreated)
        assert event.item_id == "item-456"
        assert event.title == "Test Item"

    def test_deserialize_unknown_event_raises(self):
        """Registry should raise for unknown event types in strict mode."""
        registry = EventRegistry()

        payload = {
            "event_type": "unknown.event",
            "event_version": 1,
        }

        with pytest.raises(ValueError, match="Unknown event type"):
            registry.deserialize(payload, strict_version=True)

    def test_list_event_types(self):
        """Registry should list all registered event types."""
        registry = EventRegistry()

        @registry.register
        class EventA(DomainEvent):
            event_type = "event.a"
            data: str

        @registry.register
        class EventB(DomainEvent):
            event_type = "event.b"
            data: str

        event_types = list(registry.list_types())
        assert "event.a" in event_types
        assert "event.b" in event_types


# ──────────────────────────────────────────────────────────────
# Test EventPublisher
# ──────────────────────────────────────────────────────────────


class TestEventPublisher:
    """Tests for EventPublisher."""

    @pytest.mark.asyncio
    async def test_publish_stages_event_in_outbox(self):
        """Publisher should stage events in the outbox table."""
        from example_service.core.events.publisher import EventPublisher

        # Create mock session
        mock_session = AsyncMock()
        mock_session.add = MagicMock()

        publisher = EventPublisher(mock_session)

        class TestEvent(DomainEvent):
            event_type = "test.published"
            item_id: str

        event = TestEvent(item_id="123")
        await publisher.publish(event)

        # Verify session.add was called with an outbox entry
        mock_session.add.assert_called_once()
        outbox_entry = mock_session.add.call_args[0][0]
        assert outbox_entry.event_type == "test.published"

    @pytest.mark.asyncio
    async def test_publish_many_stages_multiple_events(self):
        """Publisher should stage multiple events efficiently."""
        from example_service.core.events.publisher import EventPublisher

        mock_session = AsyncMock()
        mock_session.add_all = MagicMock()

        publisher = EventPublisher(mock_session)

        class TestEvent(DomainEvent):
            event_type = "test.batch"
            index: int

        events = [TestEvent(index=i) for i in range(5)]
        await publisher.publish_many(events)

        # Verify add_all was called with 5 outbox entries
        mock_session.add_all.assert_called_once()
        outbox_entries = mock_session.add_all.call_args[0][0]
        assert len(outbox_entries) == 5

    @pytest.mark.asyncio
    async def test_publish_many_falls_back_to_add_when_add_all_unavailable(self):
        """Publisher should fallback to add when session lacks add_all."""
        from example_service.core.events.publisher import EventPublisher

        mock_session = MagicMock()
        mock_session.add = MagicMock()
        mock_session.add_all = None  # Simulate AsyncSession without add_all

        publisher = EventPublisher(mock_session)

        class TestEvent(DomainEvent):
            event_type = "test.fallback"
            index: int

        events = [TestEvent(index=i) for i in range(3)]
        await publisher.publish_many(events)

        assert mock_session.add.call_count == 3
        assert publisher.pending_count == 3

    @pytest.mark.asyncio
    async def test_publish_many_respects_bulk_add_and_correlation(self):
        """Publisher should use add_all and propagate correlation IDs."""
        from example_service.core.events.publisher import EventPublisher

        mock_session = MagicMock()
        mock_session.add_all = MagicMock()

        publisher = EventPublisher(mock_session, correlation_id="bulk-corr")

        class TestEvent(DomainEvent):
            event_type = "test.bulk"
            payload: str

        events = [TestEvent(payload=f"event-{i}") for i in range(2)]
        await publisher.publish_many(events)

        mock_session.add_all.assert_called_once()
        outbox_entries = mock_session.add_all.call_args[0][0]
        assert all(entry.correlation_id == "bulk-corr" for entry in outbox_entries)
        assert publisher.pending_count == 2

    @pytest.mark.asyncio
    async def test_publisher_sets_correlation_id(self):
        """Publisher should set correlation_id from constructor."""
        from example_service.core.events.publisher import EventPublisher

        mock_session = AsyncMock()
        mock_session.add = MagicMock()

        publisher = EventPublisher(mock_session, correlation_id="request-456")

        class TestEvent(DomainEvent):
            event_type = "test.correlated"
            data: str

        event = TestEvent(data="test")
        await publisher.publish(event)

        outbox_entry = mock_session.add.call_args[0][0]
        assert outbox_entry.correlation_id == "request-456"
