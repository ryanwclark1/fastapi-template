"""Query resolvers for tags.

Provides read operations for tags:
- tag(id): Get a single tag by ID
- tags(first, after, ...): List tags with cursor pagination
- tagsByReminder(reminderId): Get tags for a specific reminder
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated
from uuid import UUID

import strawberry
from sqlalchemy import func, select

from example_service.features.graphql.types.base import PageInfoType
from example_service.features.graphql.types.tags import TagConnection, TagEdge, TagType
from example_service.features.tags.models import Tag, reminder_tags
from example_service.features.tags.schemas import TagResponse

if TYPE_CHECKING:
    from strawberry.types import Info

    from example_service.features.graphql.context import GraphQLContext

logger = logging.getLogger(__name__)

# Type aliases for annotated arguments
FirstArg = Annotated[
    int, strawberry.argument(description="Number of items to return (forward pagination)")
]
AfterArg = Annotated[
    str | None, strawberry.argument(description="Cursor to start after (forward pagination)")
]
LastArg = Annotated[
    int | None, strawberry.argument(description="Number of items to return (backward pagination)")
]
BeforeArg = Annotated[
    str | None, strawberry.argument(description="Cursor to start before (backward pagination)")
]


async def tag_query(
    info: Info[GraphQLContext, None],
    id: strawberry.ID,
) -> TagType | None:
    """Get a single tag by ID.

    Uses DataLoader for efficient batching if called multiple times.

    Args:
        info: Strawberry info with context
        id: Tag UUID

    Returns:
        TagType if found, None otherwise
    """
    ctx = info.context
    try:
        tag_uuid = UUID(str(id))
    except ValueError:
        return None

    tag = await ctx.loaders.tags.load(tag_uuid)
    if tag is None:
        return None

    # Convert: SQLAlchemy → Pydantic → GraphQL
    tag_pydantic = TagResponse.from_model(tag)
    return TagType.from_pydantic(tag_pydantic)


async def tags_query(
    info: Info[GraphQLContext, None],
    first: FirstArg = 50,
    after: AfterArg = None,
    last: LastArg = None,
    before: BeforeArg = None,
) -> TagConnection:
    """List tags with Relay-style cursor pagination.

    Args:
        info: Strawberry info with context
        first: Items for forward pagination
        after: Cursor for forward pagination
        last: Items for backward pagination
        before: Cursor for backward pagination

    Returns:
        TagConnection with edges and page_info
    """
    ctx = info.context
    from example_service.features.tags.repository import get_tag_repository

    repo = get_tag_repository()

    # Build base statement
    stmt = select(Tag)

    # Use cursor pagination
    connection = await repo.paginate_cursor(
        ctx.session,
        stmt,
        first=first if last is None else None,
        after=after,
        last=last,
        before=before,
        order_by=[
            (Tag.name, "asc"),
            (Tag.id, "asc"),
        ],
        include_total=True,
    )

    # Convert to GraphQL types via Pydantic
    edges = [
        TagEdge(
            node=TagType.from_pydantic(TagResponse.from_model(edge.node)),
            cursor=edge.cursor,
        )
        for edge in connection.edges
    ]

    page_info = PageInfoType(
        has_previous_page=connection.page_info.has_previous_page,
        has_next_page=connection.page_info.has_next_page,
        start_cursor=connection.page_info.start_cursor,
        end_cursor=connection.page_info.end_cursor,
        total_count=connection.page_info.total_count,
    )

    return TagConnection(edges=edges, page_info=page_info)


async def tags_by_reminder_query(
    info: Info[GraphQLContext, None],
    reminder_id: strawberry.ID,
) -> list[TagType]:
    """Get all tags for a specific reminder.

    Uses DataLoader for efficient batching.

    Args:
        info: Strawberry info with context
        reminder_id: Reminder UUID

    Returns:
        List of tags for the reminder
    """
    ctx = info.context
    try:
        reminder_uuid = UUID(str(reminder_id))
    except ValueError:
        return []

    # Use DataLoader for efficient batching
    tags = await ctx.loaders.reminder_tags.load(reminder_uuid)

    return [TagType.from_pydantic(TagResponse.from_model(tag)) for tag in tags]


async def popular_tags_query(
    info: Info[GraphQLContext, None],
    limit: int = 10,
) -> list[TagType]:
    """Get most popular tags by usage count.

    Args:
        info: Strawberry info with context
        limit: Maximum number of tags to return

    Returns:
        List of most-used tags
    """
    ctx = info.context

    # Query tags with reminder count
    stmt = (
        select(Tag, func.count(reminder_tags.c.reminder_id).label("reminder_count"))
        .outerjoin(reminder_tags, Tag.id == reminder_tags.c.tag_id)
        .group_by(Tag.id)
        .order_by(func.count(reminder_tags.c.reminder_id).desc())
        .limit(limit)
    )

    result = await ctx.session.execute(stmt)
    rows = result.all()

    # Convert to GraphQL types
    tags = []
    for row in rows:
        tag = row[0]
        # reminder_count = row[1]  # Available if needed
        tags.append(TagType.from_pydantic(TagResponse.from_model(tag)))

    return tags


__all__ = [
    "popular_tags_query",
    "tag_query",
    "tags_by_reminder_query",
    "tags_query",
]
