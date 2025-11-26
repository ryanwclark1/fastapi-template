"""Unit tests for FastStream tracing utilities.

Tests for the supplementary tracing utilities in messaging/middleware.py:
- traced_handler() decorator
- add_message_span_attributes()
- add_message_span_event()

Note: The primary tracing is handled by FastStream's built-in
RabbitTelemetryMiddleware. These tests cover the supplementary utilities
for adding custom span data.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from example_service.infra.messaging.middleware import (
    _extract_event,
    add_message_span_attributes,
    add_message_span_event,
    traced_handler,
)


class TestTracedHandler:
    """Test suite for traced_handler decorator."""

    @pytest.fixture
    def mock_event(self) -> MagicMock:
        """Create a mock event with standard fields."""
        event = MagicMock()
        event.event_id = "test-event-123"
        event.event_type = "example.created"
        event.service = "example-service"
        return event

    @pytest.fixture
    def mock_tracer(self):
        """Create mock tracer with span."""
        with patch("example_service.infra.messaging.middleware._tracer") as tracer:
            mock_span = MagicMock()
            mock_span.is_recording.return_value = True
            tracer.start_span.return_value = mock_span
            yield tracer, mock_span

    async def test_creates_span_with_correct_name(self, mock_event, mock_tracer):
        """Test that span is created with handler name."""
        tracer, span = mock_tracer

        @traced_handler()
        async def my_handler(event):
            return "success"

        await my_handler(mock_event)

        tracer.start_span.assert_called_once()
        call_kwargs = tracer.start_span.call_args[1]
        assert call_kwargs["name"] == "message.my_handler"

    async def test_sets_span_attributes_from_event(self, mock_event, mock_tracer):
        """Test that span attributes include event fields."""
        tracer, span = mock_tracer

        @traced_handler()
        async def handler(event):
            pass

        await handler(mock_event)

        attributes = tracer.start_span.call_args[1]["attributes"]
        assert attributes["message.id"] == "test-event-123"
        assert attributes["message.type"] == "example.created"
        assert attributes["message.service"] == "example-service"
        assert attributes["handler.name"] == "handler"

    async def test_records_success_status(self, mock_event, mock_tracer):
        """Test that successful handler sets success status."""
        tracer, span = mock_tracer

        @traced_handler()
        async def handler(event):
            return {"status": "ok"}

        await handler(mock_event)

        span.set_attribute.assert_any_call("message.status", "success")
        span.end.assert_called_once()

    async def test_records_exception_on_failure(self, mock_event, mock_tracer):
        """Test that failed handler records exception."""
        tracer, span = mock_tracer

        @traced_handler()
        async def failing_handler(event):
            raise ValueError("Test error")

        with pytest.raises(ValueError):
            await failing_handler(mock_event)

        span.record_exception.assert_called_once()
        span.set_status.assert_called_once()
        span.set_attribute.assert_any_call("message.status", "failure")
        span.end.assert_called_once()

    async def test_custom_handler_name(self, mock_event, mock_tracer):
        """Test custom handler name in span."""
        tracer, span = mock_tracer

        @traced_handler("custom-name")
        async def handler(event):
            pass

        await handler(mock_event)

        call_kwargs = tracer.start_span.call_args[1]
        assert call_kwargs["name"] == "message.custom-name"

    async def test_handles_missing_event_fields(self, mock_tracer):
        """Test graceful handling of events without standard fields."""
        tracer, span = mock_tracer

        plain_dict = {"data": "value"}

        @traced_handler()
        async def handler(message):
            pass

        await handler(plain_dict)

        # Should still create span with handler.name attribute
        tracer.start_span.assert_called_once()
        attributes = tracer.start_span.call_args[1]["attributes"]
        assert attributes["handler.name"] == "handler"

    async def test_span_ends_even_on_exception(self, mock_event, mock_tracer):
        """Test that span.end() is called in finally block."""
        tracer, span = mock_tracer

        @traced_handler()
        async def failing_handler(event):
            raise RuntimeError("Crash")

        with pytest.raises(RuntimeError):
            await failing_handler(mock_event)

        # Verify span was ended despite exception
        span.end.assert_called_once()

    async def test_preserves_function_name_and_docstring(self, mock_tracer):
        """Test that wrapped function preserves metadata."""
        tracer, span = mock_tracer

        @traced_handler()
        async def documented_handler(event):
            """This is a documented handler."""
            pass

        assert documented_handler.__name__ == "documented_handler"
        assert "documented handler" in documented_handler.__doc__


class TestExtractEvent:
    """Test suite for _extract_event utility."""

    def test_extracts_from_first_positional_arg(self):
        """Test extraction from first positional argument."""
        event = MagicMock()
        event.event_id = "123"

        result = _extract_event((event,), {})
        assert result is event

    def test_extracts_from_event_kwarg(self):
        """Test extraction from 'event' keyword argument."""
        event = MagicMock()
        event.event_id = "123"

        result = _extract_event((), {"event": event})
        assert result is event

    def test_extracts_from_message_kwarg(self):
        """Test extraction from 'message' keyword argument."""
        event = MagicMock()
        event.event_id = "456"

        result = _extract_event((), {"message": event})
        assert result is event

    def test_returns_none_for_plain_args(self):
        """Test returns None when no event-like object found."""
        result = _extract_event(("plain_string",), {"key": "value"})
        assert result is None

    def test_extracts_from_any_kwarg_with_event_id(self):
        """Test extraction from any kwarg that has event_id."""
        event = MagicMock()
        event.event_id = "789"

        result = _extract_event((), {"custom_event": event})
        assert result is event


class TestSpanHelpers:
    """Test suite for span helper functions."""

    @patch("example_service.infra.messaging.middleware.trace")
    def test_add_message_span_attributes(self, mock_trace):
        """Test adding attributes to current span."""
        mock_span = MagicMock()
        mock_span.is_recording.return_value = True
        mock_trace.get_current_span.return_value = mock_span

        add_message_span_attributes({"custom.key": "value", "another": 123})

        mock_span.set_attribute.assert_any_call("custom.key", "value")
        mock_span.set_attribute.assert_any_call("another", 123)

    @patch("example_service.infra.messaging.middleware.trace")
    def test_add_message_span_attributes_skips_non_recording(self, mock_trace):
        """Test attributes are not added when span is not recording."""
        mock_span = MagicMock()
        mock_span.is_recording.return_value = False
        mock_trace.get_current_span.return_value = mock_span

        add_message_span_attributes({"key": "value"})

        mock_span.set_attribute.assert_not_called()

    @patch("example_service.infra.messaging.middleware.trace")
    def test_add_message_span_event(self, mock_trace):
        """Test adding event to current span."""
        mock_span = MagicMock()
        mock_span.is_recording.return_value = True
        mock_trace.get_current_span.return_value = mock_span

        add_message_span_event("my.event", {"key": "value"})

        mock_span.add_event.assert_called_once_with("my.event", {"key": "value"})

    @patch("example_service.infra.messaging.middleware.trace")
    def test_add_message_span_event_without_attributes(self, mock_trace):
        """Test adding event without attributes."""
        mock_span = MagicMock()
        mock_span.is_recording.return_value = True
        mock_trace.get_current_span.return_value = mock_span

        add_message_span_event("simple.event")

        mock_span.add_event.assert_called_once_with("simple.event", {})

    @patch("example_service.infra.messaging.middleware.trace")
    def test_add_message_span_event_skips_non_recording(self, mock_trace):
        """Test events are not added when span is not recording."""
        mock_span = MagicMock()
        mock_span.is_recording.return_value = False
        mock_trace.get_current_span.return_value = mock_span

        add_message_span_event("my.event")

        mock_span.add_event.assert_not_called()
