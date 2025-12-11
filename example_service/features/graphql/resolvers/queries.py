"""Query resolvers for the GraphQL API.

Provides read operations for reminders:
- reminder(id): Get a single reminder by ID
- reminders(first, after, ...): List reminders with cursor pagination
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from sqlalchemy import select
import strawberry

from example_service.features.graphql.types.base import PageInfoType
from example_service.features.graphql.types.reminders import (
    ReminderConnection,
    ReminderEdge,
    ReminderType,
)
from example_service.features.reminders.models import Reminder
from example_service.features.reminders.repository import get_reminder_repository

if TYPE_CHECKING:
    from strawberry.types import Info

    from example_service.features.graphql.context import GraphQLContext

logger = logging.getLogger(__name__)

# Type aliases for annotated arguments with descriptions
FirstArg = Annotated[
    int, strawberry.argument(description="Number of items to return (forward pagination)"),
]
AfterArg = Annotated[
    str | None, strawberry.argument(description="Cursor to start after (forward pagination)"),
]
LastArg = Annotated[
    int | None, strawberry.argument(description="Number of items to return (backward pagination)"),
]
BeforeArg = Annotated[
    str | None, strawberry.argument(description="Cursor to start before (backward pagination)"),
]
IncludeCompletedArg = Annotated[
    bool, strawberry.argument(description="Include completed reminders"),
]


@strawberry.type(description="Root query type")
class Query:
    """GraphQL Query resolvers."""

    @strawberry.field(description="Get a single reminder by ID")
    async def reminder(
        self,
        info: Info[GraphQLContext, None],
        id: strawberry.ID,
    ) -> ReminderType | None:
        """Get a single reminder by ID.

        Uses DataLoader for efficient batching if called multiple times.

        Args:
            info: Strawberry info with context
            id: Reminder UUID

        Returns:
            ReminderType if found, None otherwise
        """
        ctx = info.context
        try:
            reminder_uuid = UUID(str(id))
        except ValueError:
            return None

        reminder = await ctx.loaders.reminders.load(reminder_uuid)
        if reminder is None:
            return None

        return ReminderType.from_model(reminder)

    @strawberry.field(description="List reminders with cursor pagination")
    async def reminders(
        self,
        info: Info[GraphQLContext, None],
        first: FirstArg = 50,
        after: AfterArg = None,
        last: LastArg = None,
        before: BeforeArg = None,
        include_completed: IncludeCompletedArg = True,
    ) -> ReminderConnection:
        """List reminders with Relay-style cursor pagination.

        Uses the existing paginate_cursor method from BaseRepository.

        Args:
            info: Strawberry info with context
            first: Items for forward pagination
            after: Cursor for forward pagination
            last: Items for backward pagination
            before: Cursor for backward pagination
            include_completed: Whether to include completed reminders

        Returns:
            ReminderConnection with edges and page_info
        """
        ctx = info.context
        repo = get_reminder_repository()

        # Build base statement
        stmt = select(Reminder)
        if not include_completed:
            stmt = stmt.where(not Reminder.is_completed)

        # Use existing cursor pagination
        connection = await repo.paginate_cursor(
            ctx.session,
            stmt,
            first=first if last is None else None,
            after=after,
            last=last,
            before=before,
            order_by=[
                (Reminder.created_at, "desc"),
                (Reminder.id, "asc"),
            ],
            include_total=True,
        )

        # Convert to GraphQL types
        edges = [
            ReminderEdge(
                node=ReminderType.from_model(edge.node),
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

        return ReminderConnection(edges=edges, page_info=page_info)

    @strawberry.field(description="Get overdue reminders (past due, not completed)")
    async def overdue_reminders(
        self,
        info: Info[GraphQLContext, None],
    ) -> list[ReminderType]:
        """Get all overdue reminders.

        Reminders are overdue if remind_at is in the past and not completed.

        Args:
            info: Strawberry info with context

        Returns:
            List of overdue reminders
        """
        ctx = info.context
        repo = get_reminder_repository()

        reminders = await repo.find_overdue(ctx.session)
        return [ReminderType.from_model(r) for r in reminders]


__all__ = ["Query"]
