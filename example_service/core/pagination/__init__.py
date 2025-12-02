"""Cursor-based pagination with GraphQL Connection and REST styles.

This module provides cursor-based (keyset) pagination that is:
- Stable: Results don't shift when data changes between pages
- Performant: Uses indexed seeks instead of OFFSET scans
- Flexible: Supports both GraphQL Connection and simple REST styles

GraphQL Connection Style:
    @router.get("/items", response_model=Connection[ItemResponse])
    async def list_items(
        first: int = Query(50, ge=1, le=100),
        after: str | None = None,
    ) -> Connection[ItemResponse]:
        result = await repo.paginate_cursor(
            session, stmt, first=first, after=after, order_by=[...]
        )
        return result

Simple REST Style:
    @router.get("/items", response_model=CursorPage[ItemResponse])
    async def list_items(...) -> CursorPage[ItemResponse]:
        connection = await repo.paginate_cursor(...)
        return connection.to_cursor_page()

The cursor encodes the sort field values needed to seek to the next page.
Cursors are opaque base64 strings that clients pass back unchanged.
"""

from example_service.core.pagination.cursor import CursorCodec, CursorData
from example_service.core.pagination.filters import CursorFilter
from example_service.core.pagination.schemas import (
    Connection,
    CursorPage,
    Edge,
    PageInfo,
)

__all__ = [
    # GraphQL-style schemas
    "Connection",
    # Cursor utilities
    "CursorCodec",
    "CursorData",
    # Filter
    "CursorFilter",
    # REST-style schemas
    "CursorPage",
    "Edge",
    "PageInfo",
]
