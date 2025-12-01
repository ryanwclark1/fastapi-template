"""Base GraphQL types for pagination and common patterns.

Provides Relay-compliant pagination types that mirror the existing
core/pagination types but as Strawberry GraphQL types.
"""

from __future__ import annotations

import strawberry


@strawberry.type(description="Pagination metadata following GraphQL Relay specification")
class PageInfoType:
    """GraphQL Relay PageInfo for cursor-based pagination.

    Mirrors example_service.core.pagination.schemas.PageInfo.
    """

    has_previous_page: bool = strawberry.field(description="Whether previous items exist")
    has_next_page: bool = strawberry.field(description="Whether more items exist")
    start_cursor: str | None = strawberry.field(
        default=None,
        description="Cursor of the first item",
    )
    end_cursor: str | None = strawberry.field(
        default=None,
        description="Cursor of the last item",
    )
    total_count: int | None = strawberry.field(
        default=None,
        description="Total count (optional, can be expensive)",
    )


__all__ = ["PageInfoType"]
