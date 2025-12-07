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

try:
    from strawberry.fastapi import GraphQLRouter
except ImportError:
    GraphQLRouter = None  # type: ignore[assignment, misc]

from example_service.core.dependencies.auth import get_current_user_optional
from example_service.core.dependencies.database import get_db_session
from example_service.core.settings import get_app_settings, get_graphql_settings

# Only import GraphQL-specific modules if GraphQLRouter is available
if GraphQLRouter is not None:
    from example_service.features.graphql.context import GraphQLContext
    from example_service.features.graphql.dataloaders import create_dataloaders
    from example_service.features.graphql.playground import register_playground_routes
    from example_service.features.graphql.schema import schema
else:
    # Dummy imports to avoid NameError, but these won't be used
    GraphQLContext = None  # type: ignore[misc]
    create_dataloaders = None
    register_playground_routes = None
    schema = None

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from example_service.core.schemas.auth import AuthUser

logger = logging.getLogger(__name__)

# Only define these if GraphQLRouter is available to avoid FastAPI processing them
# when GraphQL is not enabled
if GraphQLRouter is not None:

    async def get_graphql_context(
        request: Request,
        response: Response,
        background_tasks: BackgroundTasks,
        session: Annotated[AsyncSession, Depends(get_db_session)],
        user: Annotated[AuthUser | None, Depends(get_current_user_optional)],
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
else:
    # Dummy function to avoid NameError, but it won't be used
    async def get_graphql_context(*_args: Any, **_kwargs: Any) -> Any:
        """Dummy function when GraphQL is not available."""
        msg = "strawberry is required for GraphQL support"
        raise ImportError(msg)


def create_graphql_router() -> APIRouter:
    """Create GraphQL router with settings-based configuration."""
    if GraphQLRouter is None:
        msg = "strawberry is required for GraphQL support"
        raise ImportError(msg)

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
        path="/",  # use root here; mounted prefix adds the actual path
    )

    router = APIRouter()
    router.include_router(graphql_app, prefix="")

    if use_local_playground and settings.playground_enabled:
        app_settings = get_app_settings()
        register_playground_routes(
            router,
            graphql_path=settings.path,
            title=app_settings.title,
            subscriptions_enabled=settings.subscriptions_enabled,
        )

    return router


# Create the router instance using settings (only if GraphQL is enabled)
# This will raise ImportError if strawberry is not available, which is caught in app/router.py
try:
    router = create_graphql_router()
except (ImportError, AttributeError):
    router = None  # type: ignore[assignment]


__all__ = ["create_graphql_router", "get_graphql_context", "router"]
