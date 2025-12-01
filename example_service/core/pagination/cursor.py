"""Cursor encoding and decoding for pagination.

Cursors are opaque strings that encode the position in a result set.
They contain the values of the sort fields for the current row,
allowing the next query to seek directly to that position.

The cursor format is:
1. JSON object with sort field values
2. Base64 URL-safe encoded for use in URLs

Example cursor payload:
    {"v": {"created_at": "2025-01-15T10:30:00Z", "id": "abc-123"}, "d": "forward"}

Encoded: eyJ2IjogeyJjcmVhdGVkX2F0IjogIjIwMjUtMDEtMTVUMTA6MzA6MDBaIiwgImlkIjogImFiYy0xMjMifSwgImQiOiAiZm9yd2FyZCJ9
"""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class CursorData(BaseModel):
    """Internal representation of cursor data.

    Attributes:
        values: Dictionary mapping sort field names to their values
        direction: Pagination direction (forward = after, backward = before)
    """

    values: dict[str, Any] = Field(
        description="Sort field values for seeking"
    )
    direction: Literal["forward", "backward"] = Field(
        default="forward",
        description="Pagination direction",
    )

    model_config = {"frozen": True}


class CursorCodec:
    """Encode and decode pagination cursors.

    Cursors are URL-safe base64 strings that encode the sort field
    values needed to seek to a specific position in the result set.

    Usage:
        # Encoding
        cursor = CursorCodec.encode(CursorData(
            values={"created_at": datetime.now(), "id": "abc-123"}
        ))

        # Decoding
        data = CursorCodec.decode(cursor)
        print(data.values)  # {"created_at": "2025-01-15T10:30:00", "id": "abc-123"}
    """

    @staticmethod
    def encode(data: CursorData) -> str:
        """Encode cursor data to an opaque string.

        Args:
            data: Cursor data with sort field values

        Returns:
            URL-safe base64 encoded string

        Example:
            cursor = CursorCodec.encode(CursorData(
                values={"created_at": now, "id": "123"},
                direction="forward",
            ))
        """
        # Serialize values to JSON-compatible format
        serialized = {
            "v": CursorCodec._serialize_values(data.values),
            "d": data.direction,
        }
        json_str = json.dumps(serialized, separators=(",", ":"))
        return base64.urlsafe_b64encode(json_str.encode()).decode()

    @staticmethod
    def decode(cursor: str) -> CursorData:
        """Decode a cursor string to cursor data.

        Args:
            cursor: URL-safe base64 encoded cursor string

        Returns:
            CursorData with sort field values

        Raises:
            ValueError: If cursor is invalid or corrupted
        """
        try:
            json_str = base64.urlsafe_b64decode(cursor.encode()).decode()
            payload = json.loads(json_str)

            return CursorData(
                values=payload.get("v", {}),
                direction=payload.get("d", "forward"),
            )
        except Exception as e:
            raise ValueError(f"Invalid cursor: {e}") from e

    @staticmethod
    def _serialize_values(values: dict[str, Any]) -> dict[str, Any]:
        """Serialize values to JSON-compatible format.

        Handles special types like datetime and UUID.
        """
        result = {}
        for key, value in values.items():
            if isinstance(value, datetime):
                result[key] = value.isoformat()
            elif isinstance(value, UUID):
                result[key] = str(value)
            elif value is None:
                result[key] = None
            else:
                result[key] = value
        return result

    @staticmethod
    def create_cursor(
        row: Any,
        sort_fields: list[str],
        direction: Literal["forward", "backward"] = "forward",
    ) -> str:
        """Create a cursor from a database row.

        Args:
            row: SQLAlchemy model instance or row
            sort_fields: List of attribute names to include in cursor
            direction: Pagination direction

        Returns:
            Encoded cursor string

        Example:
            cursor = CursorCodec.create_cursor(
                user,
                sort_fields=["created_at", "id"],
            )
        """
        values = {}
        for field in sort_fields:
            value = getattr(row, field, None)
            values[field] = value

        return CursorCodec.encode(CursorData(values=values, direction=direction))


__all__ = ["CursorCodec", "CursorData"]
