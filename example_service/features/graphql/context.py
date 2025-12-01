"""GraphQL context for request-scoped dependencies.

The context is created fresh for each GraphQL request and provides:
- Database session (for queries/mutations)
- DataLoaders (for N+1 prevention)
- Authenticated user (optional)
- Correlation ID (for distributed tracing)

Following Strawberry's FastAPI integration pattern:
https://strawberry.rocks/docs/integrations/fastapi#context_getter
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from strawberry.fastapi import BaseContext

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from starlette.background import BackgroundTasks
    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.websockets import WebSocket

    from example_service.core.schemas.auth import AuthUser
    from example_service.features.graphql.dataloaders import DataLoaders


@dataclass
class GraphQLContext(BaseContext):
    """Request context for GraphQL operations.

    Inherits from Strawberry's BaseContext and includes the standard
    FastAPI integration fields (request, response, background_tasks)
    plus custom dependencies for this application.

    Standard fields (per Strawberry docs):
    - request: The HTTP request (or None for WebSocket)
    - response: The HTTP response (for setting headers/cookies)
    - background_tasks: FastAPI BackgroundTasks for async operations

    Custom fields:
    - session: Database session (request-scoped)
    - loaders: DataLoaders (request-scoped, tied to session)
    - user: Authenticated user (from auth middleware)
    - correlation_id: For distributed tracing

    Example usage in resolver:
        @strawberry.field
        async def reminder(self, info: Info[GraphQLContext, None], id: UUID) -> ReminderType | None:
            ctx = info.context
            reminder = await ctx.loaders.reminders.load(id)
            return ReminderType.from_model(reminder) if reminder else None
    """

    # Standard Strawberry/FastAPI context fields
    request: Request | WebSocket | None = None
    response: Response | None = None
    background_tasks: BackgroundTasks | None = None

    # Custom application fields
    session: AsyncSession = field(default=None)  # type: ignore[assignment]
    loaders: DataLoaders = field(default=None)  # type: ignore[assignment]
    user: AuthUser | None = None
    correlation_id: str | None = None

    @property
    def is_authenticated(self) -> bool:
        """Check if the request is authenticated."""
        return self.user is not None


__all__ = ["GraphQLContext"]
