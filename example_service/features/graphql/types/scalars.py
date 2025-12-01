"""Custom GraphQL scalars.

Provides custom scalar types for:
- UUID: Serializes UUID objects to strings and parses strings to UUIDs
"""

from __future__ import annotations

from uuid import UUID as PyUUID

import strawberry

# UUID scalar that serializes to string and parses from string
UUID = strawberry.scalar(
    PyUUID,
    name="UUID",
    description="A UUID scalar type (serialized as string)",
    serialize=str,
    parse_value=lambda v: PyUUID(v) if isinstance(v, str) else v,
)

__all__ = ["UUID"]
