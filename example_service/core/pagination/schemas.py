"""Pagination response schemas for cursor-based pagination.

This module provides two pagination styles:

1. GraphQL Connection Pattern (Relay specification):
   - Standardized format for paginated data
   - Includes edges with cursors and nodes
   - PageInfo with navigation metadata
   - Future-proof for GraphQL integration

2. Simple REST Style:
   - Cleaner format for REST APIs
   - Just items, cursors, and has_more flag
   - Simpler client implementation

Both styles use the same underlying cursor mechanism.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageInfo(BaseModel):
    """Pagination metadata following GraphQL Relay specification.

    Provides information about the current page and available navigation.

    Attributes:
        has_previous_page: Whether there are items before the current page
        has_next_page: Whether there are items after the current page
        start_cursor: Cursor of the first item in this page
        end_cursor: Cursor of the last item in this page
        total_count: Total number of items (optional, can be expensive)
    """

    has_previous_page: bool = Field(
        description="Whether previous items exist"
    )
    has_next_page: bool = Field(
        description="Whether more items exist"
    )
    start_cursor: str | None = Field(
        default=None,
        description="Cursor of the first item",
    )
    end_cursor: str | None = Field(
        default=None,
        description="Cursor of the last item",
    )
    total_count: int | None = Field(
        default=None,
        description="Total count (optional)",
    )


class Edge(BaseModel, Generic[T]):
    """Edge wrapper for paginated items (Relay pattern).

    Each edge contains a node (the actual item) and its cursor
    for precise navigation.

    Attributes:
        node: The actual data item
        cursor: Cursor for this specific item
    """

    node: T = Field(description="The data item")
    cursor: str = Field(description="Cursor for this item")


class Connection(BaseModel, Generic[T]):
    """GraphQL Connection pattern for cursor pagination.

    The Connection pattern provides a standardized way to return
    paginated data with navigation capabilities.

    Usage:
        @router.get("/users", response_model=Connection[UserResponse])
        async def list_users(
            first: int = Query(50, ge=1, le=100),
            after: str | None = None,
        ):
            return await user_repo.paginate_cursor(
                session, stmt, first=first, after=after, ...
            )

    Client navigation:
        # First page
        GET /users?first=10

        # Next page (using end_cursor from previous response)
        GET /users?first=10&after=eyJjcmVhdGVkX2F0Ijoi...

        # Previous page (using start_cursor)
        GET /users?last=10&before=eyJjcmVhdGVkX2F0Ijoi...

    Attributes:
        edges: List of Edge objects containing nodes and cursors
        page_info: Navigation metadata
    """

    edges: list[Edge[T]] = Field(
        default_factory=list,
        description="List of edges (items with cursors)",
    )
    page_info: PageInfo = Field(
        description="Pagination metadata",
    )

    @property
    def nodes(self) -> list[T]:
        """Get just the nodes without edge wrappers.

        Convenience property for simpler access to items.
        """
        return [edge.node for edge in self.edges]

    def to_cursor_page(self) -> "CursorPage[T]":
        """Convert to simple REST-style pagination.

        Returns:
            CursorPage with items and cursors
        """
        return CursorPage(
            items=self.nodes,
            next_cursor=self.page_info.end_cursor if self.page_info.has_next_page else None,
            prev_cursor=self.page_info.start_cursor if self.page_info.has_previous_page else None,
            has_more=self.page_info.has_next_page,
            total_count=self.page_info.total_count,
        )


class CursorPage(BaseModel, Generic[T]):
    """Simple REST-style cursor pagination response.

    A cleaner alternative to the Connection pattern for REST APIs
    that don't need GraphQL compatibility.

    Usage:
        @router.get("/users", response_model=CursorPage[UserResponse])
        async def list_users(
            cursor: str | None = None,
            limit: int = Query(50, ge=1, le=100),
        ):
            connection = await user_repo.paginate_cursor(...)
            return connection.to_cursor_page()

    Attributes:
        items: List of data items
        next_cursor: Cursor for the next page (None if no more)
        prev_cursor: Cursor for the previous page (None if at start)
        has_more: Whether more items exist after this page
        total_count: Total count (optional)
    """

    items: list[T] = Field(
        default_factory=list,
        description="List of items",
    )
    next_cursor: str | None = Field(
        default=None,
        description="Cursor to fetch next page",
    )
    prev_cursor: str | None = Field(
        default=None,
        description="Cursor to fetch previous page",
    )
    has_more: bool = Field(
        default=False,
        description="Whether more items exist",
    )
    total_count: int | None = Field(
        default=None,
        description="Total count (optional)",
    )


__all__ = [
    "PageInfo",
    "Edge",
    "Connection",
    "CursorPage",
]
