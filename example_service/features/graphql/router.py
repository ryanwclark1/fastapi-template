"""GraphQL router for FastAPI integration.

Provides:
- GraphQL endpoint at /graphql (mounted with prefix by app/router.py)
- GraphQL playground options (GraphiQL, Apollo Sandbox, Pathfinder, or local Playground)
- WebSocket support for subscriptions
- Request context with auth, session, and DataLoaders
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated, Any, Literal, cast

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from strawberry.fastapi import GraphQLRouter

from example_service.core.dependencies.auth import get_current_user_optional
from example_service.core.dependencies.database import get_db_session
from example_service.core.schemas.auth import AuthUser
from example_service.core.settings import get_app_settings, get_graphql_settings
from example_service.features.graphql.context import GraphQLContext
from example_service.features.graphql.dataloaders import create_dataloaders
from example_service.features.graphql.playground import register_playground_routes
from example_service.features.graphql.schema import schema

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

# Type aliases for dependency injection (avoids B008 linting errors)
SessionDep = Annotated[AsyncSession, Depends(get_db_session)]
UserDep = Annotated[AuthUser | None, Depends(get_current_user_optional)]


async def get_graphql_context(
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    session: SessionDep,
    user: UserDep,
) -> GraphQLContext:
    """Create GraphQL context from FastAPI dependencies.

    Following Strawberry's FastAPI integration pattern, this provides
    the standard context fields (request, response, background_tasks)
    plus application-specific dependencies.

    Args:
        request: FastAPI request
        response: FastAPI response (for setting headers/cookies)
        background_tasks: FastAPI background tasks
        session: Database session from dependency
        user: Authenticated user (or None)

    Returns:
        GraphQLContext for use in resolvers
    """
    correlation_id = getattr(request.state, "correlation_id", None)

    return GraphQLContext(
        request=request,
        response=response,
        background_tasks=background_tasks,
        session=session,
        loaders=create_dataloaders(session),
        user=user,
        correlation_id=correlation_id,
    )


def create_graphql_router() -> APIRouter:
    """Create GraphQL router with settings-based configuration."""
    settings = get_graphql_settings()

    # Build subscription protocols list if subscriptions are enabled
    subscription_protocols: Sequence[str] | None = None
    if settings.subscriptions_enabled:
        subscription_protocols = (
            "graphql-transport-ws",
            "graphql-ws",
        )

    graphql_ide_setting = settings.get_graphql_ide()
    use_local_playground = graphql_ide_setting == "playground"
    selected_ide: Literal["graphiql", "apollo-sandbox", "pathfinder"] | None = None
    if graphql_ide_setting in ("graphiql", "apollo-sandbox", "pathfinder"):
        selected_ide = cast(
            "Literal['graphiql', 'apollo-sandbox', 'pathfinder']", graphql_ide_setting
        )

    graphql_app = GraphQLRouter(
        schema,
        context_getter=cast("Any", get_graphql_context),
        subscription_protocols=subscription_protocols or (),
        graphql_ide=selected_ide,
    )

    router = APIRouter()
    router.include_router(graphql_app)

    if use_local_playground and settings.playground_enabled:
        app_settings = get_app_settings()
        register_playground_routes(
            router,
            graphql_path=settings.path,
            title=app_settings.title,
            subscriptions_enabled=settings.subscriptions_enabled,
        )

    return router


# Create the router instance using settings
router = create_graphql_router()


__all__ = ["router", "get_graphql_context", "create_graphql_router"]
