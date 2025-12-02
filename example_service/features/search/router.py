"""Search REST API endpoints.

Provides unified search across multiple entity types.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from example_service.core.dependencies.auth import get_current_user
from example_service.core.dependencies.database import get_session

from .schemas import (
    SearchCapabilitiesResponse,
    SearchRequest,
    SearchResponse,
    SearchSuggestionRequest,
    SearchSuggestionsResponse,
    SearchSyntax,
)
from .service import SearchService

router = APIRouter(prefix="/search", tags=["search"])


@router.get(
    "/capabilities",
    response_model=SearchCapabilitiesResponse,
    summary="Get search capabilities",
    description="Get information about searchable entities and supported features.",
)
async def get_search_capabilities(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[dict, Depends(get_current_user)],
) -> SearchCapabilitiesResponse:
    """Get search capabilities.

    Returns information about:
    - Searchable entity types
    - Supported query syntax
    - Limits and constraints
    """
    service = SearchService(session)
    return service.get_capabilities()


@router.post(
    "",
    response_model=SearchResponse,
    summary="Search entities",
    description="Search across multiple entity types with full-text search.",
)
async def search(
    request: SearchRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[dict, Depends(get_current_user)],
) -> SearchResponse:
    """Execute a full-text search.

    Searches across specified entity types (or all if not specified)
    using PostgreSQL's full-text search capabilities.

    Supports multiple query syntaxes:
    - `plain`: Simple AND matching of words
    - `web`: Web-style with operators ("phrase", -exclude, OR)
    - `phrase`: Exact phrase matching

    Args:
        request: Search parameters including query and options.

    Returns:
        Search results with relevance ranking.
    """
    service = SearchService(session)
    return await service.search(request)


@router.get(
    "",
    response_model=SearchResponse,
    summary="Search entities (GET)",
    description="Search using query parameters instead of request body.",
)
async def search_get(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[dict, Depends(get_current_user)],
    q: Annotated[str, Query(min_length=1, max_length=500, description="Search query")],
    entities: Annotated[list[str] | None, Query(description="Entity types")] = None,
    syntax: Annotated[SearchSyntax, Query(description="Query syntax")] = SearchSyntax.WEB,
    highlight: Annotated[bool, Query(description="Include highlights")] = True,
    limit: Annotated[int, Query(ge=1, le=100, description="Results per entity")] = 20,
    offset: Annotated[int, Query(ge=0, description="Offset")] = 0,
) -> SearchResponse:
    """Execute search using query parameters.

    Convenience endpoint for simple GET-based searches.

    Args:
        q: Search query.
        entities: Entity types to search (comma-separated).
        syntax: Query syntax mode.
        highlight: Whether to include highlighted snippets.
        limit: Maximum results per entity type.
        offset: Pagination offset.

    Returns:
        Search results.
    """
    service = SearchService(session)

    request = SearchRequest(
        query=q,
        entity_types=entities,
        syntax=syntax,
        highlight=highlight,
        limit=limit,
        offset=offset,
    )

    return await service.search(request)


@router.get(
    "/suggest",
    response_model=SearchSuggestionsResponse,
    summary="Get search suggestions",
    description="Get autocomplete suggestions based on search prefix.",
)
async def get_suggestions(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[dict, Depends(get_current_user)],
    prefix: Annotated[str, Query(min_length=2, max_length=100, description="Search prefix")],
    entity_type: Annotated[str | None, Query(description="Limit to entity type")] = None,
    limit: Annotated[int, Query(ge=1, le=50, description="Max suggestions")] = 10,
) -> SearchSuggestionsResponse:
    """Get search suggestions for autocomplete.

    Returns suggestions based on matching content as the user types.

    Args:
        prefix: The text the user has typed.
        entity_type: Optional filter for specific entity type.
        limit: Maximum number of suggestions.

    Returns:
        List of suggestions.
    """
    service = SearchService(session)

    request = SearchSuggestionRequest(
        prefix=prefix,
        entity_type=entity_type,
        limit=limit,
    )

    return await service.suggest(request)
