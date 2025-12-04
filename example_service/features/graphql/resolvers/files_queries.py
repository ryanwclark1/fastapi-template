"""Query resolvers for files.

Provides read operations for files:
- file(id): Get a single file by ID
- files(first, after, ...): List files with cursor pagination
- filesByOwner(ownerId): Get files for a specific owner
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated
from uuid import UUID

import strawberry
from sqlalchemy import select

from example_service.features.files.models import File, FileStatus
from example_service.features.files.schemas import FileRead
from example_service.features.graphql.types.base import PageInfoType
from example_service.features.graphql.types.files import FileConnection, FileEdge, FileType

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


async def file_query(
    info: Info[GraphQLContext, None],
    id: strawberry.ID,
) -> FileType | None:
    """Get a single file by ID.

    Uses DataLoader for efficient batching if called multiple times.

    Args:
        info: Strawberry info with context
        id: File UUID

    Returns:
        FileType if found, None otherwise
    """
    ctx = info.context
    try:
        file_uuid = UUID(str(id))
    except ValueError:
        return None

    file = await ctx.loaders.files.load(file_uuid)
    if file is None:
        return None

    # Convert: SQLAlchemy → Pydantic → GraphQL
    file_pydantic = FileRead.from_orm(file)
    return FileType.from_pydantic(file_pydantic)


async def files_query(
    info: Info[GraphQLContext, None],
    first: FirstArg = 50,
    after: AfterArg = None,
    last: LastArg = None,
    before: BeforeArg = None,
    status: FileStatus | None = None,
) -> FileConnection:
    """List files with Relay-style cursor pagination.

    By default, excludes deleted files. Use status filter to include them.

    Args:
        info: Strawberry info with context
        first: Items for forward pagination
        after: Cursor for forward pagination
        last: Items for backward pagination
        before: Cursor for backward pagination
        status: Optional status filter

    Returns:
        FileConnection with edges and page_info
    """
    ctx = info.context
    from example_service.features.files.repository import get_file_repository

    repo = get_file_repository()

    # Build base statement - exclude deleted by default
    stmt = select(File)
    if status:
        # If status filter provided, apply it
        stmt = stmt.where(File.status == FileStatus(status.value))
    else:
        # Otherwise exclude deleted
        stmt = stmt.where(File.status != FileStatus.DELETED)

    # Use cursor pagination
    connection = await repo.paginate_cursor(
        ctx.session,
        stmt,
        first=first if last is None else None,
        after=after,
        last=last,
        before=before,
        order_by=[
            (File.created_at, "desc"),
            (File.id, "asc"),
        ],
        include_total=True,
    )

    # Convert to GraphQL types via Pydantic
    edges = [
        FileEdge(
            node=FileType.from_pydantic(FileRead.from_orm(edge.node)),
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

    return FileConnection(edges=edges, page_info=page_info)


async def files_by_owner_query(
    info: Info[GraphQLContext, None],
    owner_id: str,
    first: FirstArg = 50,
    after: AfterArg = None,
) -> FileConnection:
    """Get all files for a specific owner.

    Args:
        info: Strawberry info with context
        owner_id: Owner identifier
        first: Items for forward pagination
        after: Cursor for forward pagination

    Returns:
        FileConnection with files owned by the user
    """
    ctx = info.context
    from example_service.features.files.repository import get_file_repository

    repo = get_file_repository()

    # Build statement with owner filter
    stmt = (
        select(File)
        .where(File.owner_id == owner_id)
        .where(File.status != FileStatus.DELETED)
    )

    # Use cursor pagination
    connection = await repo.paginate_cursor(
        ctx.session,
        stmt,
        first=first,
        after=after,
        order_by=[
            (File.created_at, "desc"),
            (File.id, "asc"),
        ],
        include_total=True,
    )

    # Convert to GraphQL types via Pydantic
    edges = [
        FileEdge(
            node=FileType.from_pydantic(FileRead.from_orm(edge.node)),
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

    return FileConnection(edges=edges, page_info=page_info)


__all__ = [
    "file_query",
    "files_by_owner_query",
    "files_query",
]
