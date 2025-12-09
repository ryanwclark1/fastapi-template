"""Search REST API endpoints.

Provides unified search across multiple entity types.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, Query

from example_service.core.dependencies.accent_auth import get_current_user
from example_service.core.schemas.auth import AuthUser
from example_service.core.dependencies.database import get_db_session

from .schemas import (
    RecordClickRequest,
    SearchAnalyticsRequest,
    SearchAnalyticsResponse,
    SearchCapabilitiesResponse,
    SearchRequest,
    SearchResponse,
    SearchSuggestionRequest,
    SearchSuggestionsResponse,
    SearchSyntax,
    SearchTrendsResponse,
    ZeroResultsResponse,
)
from .service import SearchService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/search", tags=["search"])


@router.get(
    "/capabilities",
    response_model=SearchCapabilitiesResponse,
    summary="Get search capabilities",
    description="Get information about searchable entities and supported features.",
)
async def get_search_capabilities(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _user: Annotated[AuthUser, Depends(get_current_user)],
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
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _user: Annotated[AuthUser, Depends(get_current_user)],
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
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _user: Annotated[AuthUser, Depends(get_current_user)],
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
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _user: Annotated[AuthUser, Depends(get_current_user)],
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


# ──────────────────────────────────────────────────────────────
# Analytics Endpoints
# ──────────────────────────────────────────────────────────────


@router.get(
    "/analytics",
    response_model=SearchAnalyticsResponse,
    summary="Get search analytics",
    description="Get search statistics and insights for monitoring search quality.",
)
async def get_search_analytics(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _user: Annotated[AuthUser, Depends(get_current_user)],
    days: Annotated[int, Query(ge=1, le=365, description="Number of days to analyze")] = 30,
) -> SearchAnalyticsResponse:
    """Get search analytics and statistics.

    Returns metrics including:
    - Total and unique search counts
    - Zero-result rate
    - Average response time
    - Click-through rate
    - Popular queries
    - Queries with no results (content gaps)

    Args:
        days: Number of days to analyze (default: 30).

    Returns:
        Analytics summary with actionable insights.
    """
    service = SearchService(session)
    return await service.get_analytics(
        SearchAnalyticsRequest(days=days)
    )


@router.get(
    "/analytics/trends",
    response_model=SearchTrendsResponse,
    summary="Get search trends",
    description="View search volume and patterns over time.",
)
async def get_search_trends(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _user: Annotated[AuthUser, Depends(get_current_user)],
    days: Annotated[int, Query(ge=1, le=365, description="Number of days")] = 30,
    interval: Annotated[str, Query(description="Grouping interval", regex="^(hour|day|week)$")] = "day",
) -> SearchTrendsResponse:
    """Get search volume trends over time.

    Shows search activity patterns grouped by time interval.

    Args:
        days: Number of days to analyze.
        interval: Time grouping ("hour", "day", or "week").

    Returns:
        Time series data of search activity.
    """
    service = SearchService(session)
    return await service.get_trends(days=days, interval=interval)


@router.get(
    "/analytics/zero-results",
    response_model=ZeroResultsResponse,
    summary="Find content gaps",
    description="Get queries that returned no results to identify content gaps.",
)
async def get_zero_result_queries(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _user: Annotated[AuthUser, Depends(get_current_user)],
    days: Annotated[int, Query(ge=1, le=365, description="Number of days")] = 7,
    limit: Annotated[int, Query(ge=1, le=100, description="Max results")] = 20,
) -> ZeroResultsResponse:
    """Get queries that returned no results.

    These represent potential content gaps or opportunities for:
    - Adding missing content
    - Improving search synonyms
    - Adding spelling corrections

    Args:
        days: Number of days to analyze.
        limit: Maximum number of queries to return.

    Returns:
        List of zero-result queries with occurrence counts.
    """
    service = SearchService(session)
    return await service.get_zero_result_queries(days=days, limit=limit)


@router.post(
    "/analytics/click",
    summary="Record search result click",
    description="Track when a user clicks on a search result for CTR analytics.",
)
async def record_click(
    request: RecordClickRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _user: Annotated[AuthUser, Depends(get_current_user)],
) -> dict[str, bool]:
    """Record a click on a search result.

    Used for calculating click-through rate and improving rankings.

    Args:
        request: Click information including search ID and position.

    Returns:
        Success indicator.
    """
    service = SearchService(session)
    await service.record_click(
        search_id=request.search_id,
        clicked_position=request.clicked_position,
        clicked_entity_id=request.clicked_entity_id,
    )
    return {"success": True}


# ──────────────────────────────────────────────────────────────
# Performance Monitoring Endpoints
# ──────────────────────────────────────────────────────────────


@router.get(
    "/performance/slow-queries",
    summary="Get slow queries",
    description="Get queries that exceeded the slow query threshold.",
)
async def get_slow_queries(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _user: Annotated[AuthUser, Depends(get_current_user)],
    days: Annotated[int, Query(ge=1, le=365, description="Number of days")] = 7,
    limit: Annotated[int, Query(ge=1, le=100, description="Max results")] = 50,
) -> dict:
    """Get slow search queries for performance analysis.

    Args:
        days: Number of days to analyze.
        limit: Maximum number of queries to return.

    Returns:
        List of slow query records.
    """
    service = SearchService(session)
    slow_queries = await service.get_slow_queries(days=days, limit=limit)
    return {"slow_queries": slow_queries, "days": days}


@router.get(
    "/performance/stats",
    summary="Get performance statistics",
    description="Get aggregated query performance metrics.",
)
async def get_performance_stats(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _user: Annotated[AuthUser, Depends(get_current_user)],
    days: Annotated[int, Query(ge=1, le=365, description="Number of days")] = 7,
) -> dict:
    """Get query performance statistics.

    Returns metrics including:
    - Average response times
    - Percentile latencies (p50, p95, p99)
    - Slow query rates

    Args:
        days: Number of days to analyze.

    Returns:
        Performance statistics.
    """
    service = SearchService(session)
    stats = await service.get_performance_stats(days=days)
    return {"stats": stats, "days": days}


@router.get(
    "/health",
    summary="Search health check",
    description="Check the health of search components.",
)
async def search_health(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _user: Annotated[AuthUser, Depends(get_current_user)],
) -> dict:
    """Get health status of search components.

    Returns:
        Health status of cache, analytics, and other components.
    """
    from .circuit_breaker import get_circuit_stats

    circuit_stats = get_circuit_stats()

    return {
        "status": "healthy",
        "components": {
            "cache": {
                "circuit_breaker": {
                    name: {
                        "state": stats.state,
                        "failure_count": stats.failure_count,
                        "total_requests": stats.total_requests,
                    }
                    for name, stats in circuit_stats.items()
                }
            },
        },
    }
