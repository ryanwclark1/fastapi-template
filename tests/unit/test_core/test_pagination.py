"""Unit tests for cursor-based pagination."""
from __future__ import annotations

import base64
import json

import pytest

from example_service.core.pagination.cursor import CursorCodec, CursorData
from example_service.core.pagination.schemas import (
    Connection,
    CursorPage,
    Edge,
    PageInfo,
)


# ──────────────────────────────────────────────────────────────
# Test CursorData and CursorCodec
# ──────────────────────────────────────────────────────────────


class TestCursorData:
    """Tests for CursorData model."""

    def test_cursor_data_creation(self):
        """CursorData should store values and direction."""
        cursor = CursorData(
            values={"id": "123", "created_at": "2025-01-01T00:00:00Z"},
            direction="forward",
        )

        assert cursor.values["id"] == "123"
        assert cursor.direction == "forward"

    def test_cursor_data_default_direction(self):
        """CursorData should default to forward direction."""
        cursor = CursorData(values={"id": "456"})

        assert cursor.direction == "forward"


class TestCursorCodec:
    """Tests for CursorCodec encode/decode."""

    def test_encode_cursor(self):
        """CursorCodec should encode data to base64 string."""
        cursor_data = CursorData(
            values={"id": "test-123", "score": 42},
            direction="forward",
        )

        encoded = CursorCodec.encode(cursor_data)

        # Should be a base64 string
        assert isinstance(encoded, str)
        # Should be decodable
        decoded_json = base64.urlsafe_b64decode(encoded.encode()).decode()
        decoded = json.loads(decoded_json)
        # Cursor uses short keys: "v" for values, "d" for direction
        assert decoded["v"]["id"] == "test-123"
        assert decoded["d"] == "forward"

    def test_decode_cursor(self):
        """CursorCodec should decode base64 string to CursorData."""
        original = CursorData(
            values={"name": "test", "rank": 100},
            direction="backward",
        )
        encoded = CursorCodec.encode(original)

        decoded = CursorCodec.decode(encoded)

        assert decoded.values["name"] == "test"
        assert decoded.values["rank"] == 100
        assert decoded.direction == "backward"

    def test_encode_decode_roundtrip(self):
        """Encode and decode should be inverse operations."""
        original = CursorData(
            values={
                "uuid": "550e8400-e29b-41d4-a716-446655440000",
                "timestamp": "2025-11-25T12:00:00Z",
                "priority": 5,
            },
            direction="forward",
        )

        encoded = CursorCodec.encode(original)
        decoded = CursorCodec.decode(encoded)

        assert decoded.values == original.values
        assert decoded.direction == original.direction

    def test_decode_invalid_cursor_raises(self):
        """CursorCodec should raise for invalid cursor strings."""
        with pytest.raises((ValueError, json.JSONDecodeError)):
            CursorCodec.decode("not-valid-base64!!!")

    def test_create_cursor_from_row(self):
        """CursorCodec should create cursor from database row."""
        # Mock a row-like object
        class MockRow:
            id = "row-123"
            created_at = "2025-01-01"

        row = MockRow()
        sort_fields = ["id", "created_at"]

        cursor = CursorCodec.create_cursor(row, sort_fields, "forward")

        # Decode and verify
        decoded = CursorCodec.decode(cursor)
        assert decoded.values["id"] == "row-123"
        assert decoded.values["created_at"] == "2025-01-01"
        assert decoded.direction == "forward"


# ──────────────────────────────────────────────────────────────
# Test Pagination Schemas
# ──────────────────────────────────────────────────────────────


class TestPageInfo:
    """Tests for PageInfo schema."""

    def test_page_info_creation(self):
        """PageInfo should store pagination metadata."""
        page_info = PageInfo(
            has_previous_page=False,
            has_next_page=True,
            start_cursor="cursor-start",
            end_cursor="cursor-end",
            total_count=100,
        )

        assert page_info.has_previous_page is False
        assert page_info.has_next_page is True
        assert page_info.start_cursor == "cursor-start"
        assert page_info.end_cursor == "cursor-end"
        assert page_info.total_count == 100

    def test_page_info_optional_fields(self):
        """PageInfo should allow optional cursors and count."""
        page_info = PageInfo(
            has_previous_page=False,
            has_next_page=False,
        )

        assert page_info.start_cursor is None
        assert page_info.end_cursor is None
        assert page_info.total_count is None


class TestEdge:
    """Tests for Edge schema."""

    def test_edge_creation(self):
        """Edge should wrap node with cursor."""

        class Item:
            def __init__(self, name: str):
                self.name = name

        item = Item(name="Test")
        edge = Edge(node=item, cursor="edge-cursor-123")

        assert edge.node.name == "Test"
        assert edge.cursor == "edge-cursor-123"


class TestConnection:
    """Tests for Connection schema."""

    def test_connection_creation(self):
        """Connection should contain edges and page_info."""

        class Item:
            def __init__(self, id: int):
                self.id = id

        edges = [
            Edge(node=Item(id=1), cursor="c1"),
            Edge(node=Item(id=2), cursor="c2"),
        ]
        page_info = PageInfo(
            has_previous_page=False,
            has_next_page=True,
            start_cursor="c1",
            end_cursor="c2",
        )

        connection = Connection(edges=edges, page_info=page_info)

        assert len(connection.edges) == 2
        assert connection.edges[0].node.id == 1
        assert connection.page_info.has_next_page is True

    def test_connection_to_cursor_page(self):
        """Connection.to_cursor_page should convert to REST format."""

        class Item:
            def __init__(self, name: str):
                self.name = name

        edges = [
            Edge(node=Item(name="A"), cursor="cA"),
            Edge(node=Item(name="B"), cursor="cB"),
            Edge(node=Item(name="C"), cursor="cC"),
        ]
        page_info = PageInfo(
            has_previous_page=True,
            has_next_page=True,
            start_cursor="cA",
            end_cursor="cC",
        )

        connection = Connection(edges=edges, page_info=page_info)
        cursor_page = connection.to_cursor_page()

        assert len(cursor_page.items) == 3
        assert cursor_page.items[0].name == "A"
        assert cursor_page.next_cursor == "cC"
        assert cursor_page.prev_cursor == "cA"
        assert cursor_page.has_more is True

    def test_empty_connection_to_cursor_page(self):
        """Empty connection should convert to empty cursor page."""
        page_info = PageInfo(
            has_previous_page=False,
            has_next_page=False,
        )

        connection = Connection(edges=[], page_info=page_info)
        cursor_page = connection.to_cursor_page()

        assert len(cursor_page.items) == 0
        assert cursor_page.next_cursor is None
        assert cursor_page.prev_cursor is None
        assert cursor_page.has_more is False


class TestCursorPage:
    """Tests for CursorPage (REST-style) schema."""

    def test_cursor_page_creation(self):
        """CursorPage should store items with pagination info."""
        items = [{"id": 1}, {"id": 2}]
        page = CursorPage(
            items=items,
            next_cursor="next-abc",
            prev_cursor=None,
            has_more=True,
        )

        assert page.items == items
        assert page.next_cursor == "next-abc"
        assert page.prev_cursor is None
        assert page.has_more is True

    def test_cursor_page_last_page(self):
        """Last page should have has_more=False."""
        page = CursorPage(
            items=[{"id": 99}],
            next_cursor=None,
            prev_cursor="prev-xyz",
            has_more=False,
        )

        assert page.has_more is False
        assert page.next_cursor is None
