"""Generic pagination types and factories for GraphQL using Pydantic integration.

This module provides reusable Relay-compliant pagination patterns that work
with Pydantic models, eliminating the need to manually define Connection and
Edge types for each feature.

Example:
    from example_service.features.reminders.schemas import ReminderResponse
    from example_service.features.graphql.types.pagination import create_pydantic_connection

    # Automatically creates ReminderConnection with edges and page_info
    ReminderConnection = create_pydantic_connection(ReminderResponse, "Reminder")
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

import strawberry

from example_service.features.graphql.types.pydantic_bridge import (
    pydantic_type,
)

if TYPE_CHECKING:
    from pydantic import BaseModel

__all__ = [
    "PageInfoInput",
    "create_pydantic_connection",
    "create_pydantic_edge",
]

# Type variable for generic pagination
T = TypeVar("T", bound="BaseModel")


# ============================================================================
# Page Info Input (for cursor-based pagination queries)
# ============================================================================


@strawberry.input(description="Input for cursor-based pagination")
class PageInfoInput:
    """Input parameters for cursor-based pagination.

    This input type is used in queries to specify pagination parameters
    following the Relay cursor connection specification.
    """

    first: int | None = strawberry.field(
        default=None,
        description="Number of items to return from the start",
    )

    after: str | None = strawberry.field(
        default=None,
        description="Cursor to start pagination from (exclusive)",
    )

    last: int | None = strawberry.field(
        default=None,
        description="Number of items to return from the end",
    )

    before: str | None = strawberry.field(
        default=None,
        description="Cursor to end pagination at (exclusive)",
    )


# ============================================================================
# Pydantic-Based Connection Factories
# ============================================================================


def create_pydantic_edge[T: "BaseModel"](
    pydantic_model: type[T],
    type_name_prefix: str,
) -> type:
    """Create a Relay-compliant Edge type from a Pydantic model.

    This factory creates an Edge type with a node field that's automatically
    generated from the Pydantic model using the experimental Pydantic integration.

    Args:
        pydantic_model: The Pydantic model to use for the node type
        type_name_prefix: Prefix for the type name (e.g., "Reminder" -> "ReminderEdge")

    Returns:
        A Strawberry Edge type class

    Example:
        from example_service.features.reminders.schemas import ReminderResponse

        ReminderEdge = create_pydantic_edge(ReminderResponse, "Reminder")

        # Produces:
        # @strawberry.type
        # class ReminderEdge:
        #     node: ReminderType  # Auto-generated from ReminderResponse
        #     cursor: str
    """
    # Create the node type from Pydantic model
    @pydantic_type(
        model=pydantic_model,
        name=f"{type_name_prefix}Type",
        description=f"{type_name_prefix} node in the connection",
    )
    class NodeType:
        """Node type auto-generated from Pydantic model"""
        pass

    # Create the Edge type
    @strawberry.type(
        name=f"{type_name_prefix}Edge",
        description=f"Edge containing a {type_name_prefix} node and cursor",
    )
    class Edge:
        node: NodeType = strawberry.field(  # type: ignore
            description="The node containing the actual data"
        )
        cursor: str = strawberry.field(
            description="Opaque cursor for this edge used in pagination"
        )

    return Edge


def create_pydantic_connection[T: "BaseModel"](
    pydantic_model: type[T],
    type_name_prefix: str,
    page_info_type: type | None = None,
) -> type:
    """Create a Relay-compliant Connection type from a Pydantic model.

    This factory creates a complete Connection type with edges and page_info,
    where the node type is automatically generated from the Pydantic model.

    Args:
        pydantic_model: The Pydantic model to use for the node type
        type_name_prefix: Prefix for the type name (e.g., "Reminder" -> "ReminderConnection")
        page_info_type: Optional PageInfo type to use (defaults to importing from base.py)

    Returns:
        A Strawberry Connection type class

    Example:
        from example_service.features.reminders.schemas import ReminderResponse

        ReminderConnection = create_pydantic_connection(ReminderResponse, "Reminder")

        # Produces:
        # @strawberry.type
        # class ReminderConnection:
        #     edges: list[ReminderEdge]
        #     page_info: PageInfoType

        # Use in queries:
        @strawberry.field
        async def reminders(self, info: Info, first: int = 50) -> ReminderConnection:
            # Implementation...
            return ReminderConnection(edges=[...], page_info=...)
    """
    # Import PageInfoType here to avoid circular imports
    if page_info_type is None:
        from example_service.features.graphql.types.base import PageInfoType

        page_info_type = PageInfoType

    # Create the Edge type
    edge_type = create_pydantic_edge(pydantic_model, type_name_prefix)

    # Create the Connection type
    @strawberry.type(
        name=f"{type_name_prefix}Connection",
        description=f"Relay connection for {type_name_prefix} with cursor-based pagination",
    )
    class Connection:
        edges: list[edge_type] = strawberry.field(  # type: ignore
            description="List of edges containing nodes and their cursors"
        )
        page_info: page_info_type = strawberry.field(  # type: ignore
            description="Pagination information including hasNextPage, hasPreviousPage, etc."
        )

    return Connection


# ============================================================================
# Helper Functions for Building Connections
# ============================================================================


def build_connection(
    items: list[T],
    page_info: dict,
    cursor_fn: callable[[T], str],
) -> dict:
    """Helper to build a connection dictionary from items and page info.

    This utility makes it easier to construct connection objects in resolvers.

    Args:
        items: List of items (Pydantic models or SQLAlchemy models)
        page_info: Dictionary with pagination info (hasNextPage, hasPreviousPage, etc.)
        cursor_fn: Function that takes an item and returns its cursor string

    Returns:
        Dictionary with 'edges' and 'page_info' keys ready for Connection instantiation

    Example:
        # In a resolver:
        items, has_next = await repo.paginate_cursor(first=50, after=cursor)

        connection_dict = build_connection(
            items=items,
            page_info={
                "has_next_page": has_next,
                "has_previous_page": cursor is not None,
                "start_cursor": cursor_fn(items[0]) if items else None,
                "end_cursor": cursor_fn(items[-1]) if items else None,
            },
            cursor_fn=lambda item: base64_encode(f"reminder:{item.id}"),
        )

        return ReminderConnection(**connection_dict)
    """
    edges = [
        {
            "node": item,
            "cursor": cursor_fn(item),
        }
        for item in items
    ]

    return {
        "edges": edges,
        "page_info": page_info,
    }


# ============================================================================
# Documentation and Best Practices
# ============================================================================

"""
Usage Guide: Pydantic-Based Pagination

1. Define your Pydantic response schema:

   # features/reminders/schemas.py
   class ReminderResponse(BaseModel):
       id: UUID
       title: str
       description: str | None
       created_at: datetime

2. Create the Connection type:

   # features/graphql/types/reminders.py
   from example_service.features.reminders.schemas import ReminderResponse
   from example_service.features.graphql.types.pagination import create_pydantic_connection

   ReminderConnection = create_pydantic_connection(ReminderResponse, "Reminder")

3. Use in queries:

   # features/graphql/resolvers/queries.py
   @strawberry.field
   async def reminders(
       self,
       info: Info,
       first: int = 50,
       after: str | None = None,
   ) -> ReminderConnection:
       ctx = info.context
       repo = get_reminder_repository(ctx.session)

       # Use existing cursor pagination
       result = await repo.paginate_cursor(
           page_size=first,
           cursor=after,
       )

       # Build edges
       edges = [
           ReminderEdge(
               node=ReminderType.from_pydantic(ReminderResponse.from_model(r)),
               cursor=encode_cursor(r.id),
           )
           for r in result.items
       ]

       # Build page info
       page_info = PageInfoType(
           has_next_page=result.has_next,
           has_previous_page=after is not None,
           start_cursor=edges[0].cursor if edges else None,
           end_cursor=edges[-1].cursor if edges else None,
       )

       return ReminderConnection(edges=edges, page_info=page_info)

Benefits:
- Eliminates manual Connection/Edge type definitions
- Consistent Relay compliance across all features
- Type safety from Pydantic models to GraphQL
- DRY principle: one definition propagates everywhere
"""
