"""GraphQL types for the Search feature.

Provides:
- SearchHitType: A single search result
- SearchResponseType: Complete search response with results and facets
- SearchSuggestionType: Search suggestion/autocomplete
- FacetType: Faceted search results
- Input types for search queries
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

import strawberry
from strawberry.scalars import JSON

# --- Enums ---


@strawberry.enum(description="Search query syntax modes")
class SearchSyntaxEnum(Enum):
    """Search syntax mode."""

    PLAIN = "plain"  # Simple AND matching
    WEB = "web"  # Web-style with operators
    PHRASE = "phrase"  # Exact phrase matching


# --- Output Types ---


@strawberry.type(description="A single search result")
class SearchHitType:
    """GraphQL type for a search result hit."""

    entity_type: str = strawberry.field(description="Type of entity")
    entity_id: str = strawberry.field(description="Entity ID")
    rank: float = strawberry.field(description="Search relevance rank (0-1)")
    title: str | None = strawberry.field(description="Result title")
    snippet: str | None = strawberry.field(description="Text snippet with highlights")
    data: JSON = strawberry.field(description="Full entity data")
    created_at: datetime | None = strawberry.field(description="Entity creation time")


@strawberry.type(description="A single facet value with count")
class FacetValueType:
    """GraphQL type for a facet value."""

    value: str = strawberry.field(description="Facet value")
    count: int = strawberry.field(description="Number of results with this value")


@strawberry.type(description="Facet results for a field")
class FacetResultType:
    """GraphQL type for facet results."""

    field: str = strawberry.field(description="Field name")
    display_name: str = strawberry.field(description="Human-readable field name")
    values: list[FacetValueType] = strawberry.field(description="Value counts")


@strawberry.type(description="Search results for a specific entity type")
class EntitySearchResultType:
    """GraphQL type for entity-specific search results."""

    entity_type: str = strawberry.field(description="Entity type name")
    total: int = strawberry.field(description="Total matching results")
    hits: list[SearchHitType] = strawberry.field(description="Search results")
    facets: list[FacetResultType] | None = strawberry.field(
        description="Facet counts for this entity type"
    )


@strawberry.type(description="'Did you mean?' suggestion for typos")
class DidYouMeanSuggestionType:
    """GraphQL type for spelling correction suggestion."""

    original_query: str = strawberry.field(description="Original query with possible typo")
    suggested_query: str = strawberry.field(description="Suggested correction")
    confidence: float = strawberry.field(description="Confidence score (0-1)")


@strawberry.type(description="Complete search response")
class SearchResponseType:
    """GraphQL type for complete search response."""

    query: str = strawberry.field(description="Original search query")
    total_hits: int = strawberry.field(description="Total results across all entity types")
    results: list[EntitySearchResultType] = strawberry.field(description="Results by entity type")
    suggestions: list[str] = strawberry.field(description="Query suggestions for no/few results")
    did_you_mean: DidYouMeanSuggestionType | None = strawberry.field(
        description="Spelling correction suggestion"
    )
    facets: list[FacetResultType] | None = strawberry.field(
        description="Aggregated facet counts across all entity types"
    )
    took_ms: int = strawberry.field(description="Search time in milliseconds")


@strawberry.type(description="A search suggestion")
class SearchSuggestionType:
    """GraphQL type for a search suggestion."""

    text: str = strawberry.field(description="Suggested search term")
    entity_type: str | None = strawberry.field(description="Entity type if specific")
    count: int = strawberry.field(description="Approximate result count")


@strawberry.type(description="Response with search suggestions")
class SearchSuggestionsResponseType:
    """GraphQL type for search suggestions response."""

    prefix: str = strawberry.field(description="The prefix that was searched")
    suggestions: list[SearchSuggestionType] = strawberry.field(description="List of suggestions")


@strawberry.type(description="Information about a searchable entity")
class SearchableEntityType:
    """GraphQL type for searchable entity info."""

    name: str = strawberry.field(description="Entity type name")
    display_name: str = strawberry.field(description="Human-readable name")
    search_fields: list[str] = strawberry.field(description="Fields included in search")
    title_field: str | None = strawberry.field(description="Field used for result title")
    snippet_field: str | None = strawberry.field(description="Field used for snippets")
    supports_fuzzy: bool = strawberry.field(description="Whether fuzzy matching is available")
    facet_fields: list[str] = strawberry.field(description="Fields available for faceted search")


@strawberry.type(description="Search capabilities information")
class SearchCapabilitiesType:
    """GraphQL type for search capabilities response."""

    entities: list[SearchableEntityType] = strawberry.field(description="Searchable entities")
    supported_syntax: list[SearchSyntaxEnum] = strawberry.field(description="Supported syntax modes")
    max_query_length: int = strawberry.field(description="Maximum query length")
    max_results_per_entity: int = strawberry.field(description="Maximum results per entity type")
    features: list[str] = strawberry.field(description="List of available search features")


@strawberry.type(description="Search analytics summary")
class SearchAnalyticsType:
    """GraphQL type for search analytics."""

    total_searches: int = strawberry.field(description="Total number of searches")
    unique_queries: int = strawberry.field(description="Number of unique search queries")
    zero_result_rate: float = strawberry.field(description="Percentage of searches with no results")
    avg_results_count: float = strawberry.field(description="Average results per search")
    avg_response_time_ms: float = strawberry.field(description="Average response time")
    click_through_rate: float = strawberry.field(description="Percentage of searches with clicks")
    top_queries: JSON = strawberry.field(description="Most popular queries")
    zero_result_queries: JSON = strawberry.field(description="Queries with no results")
    period_days: int = strawberry.field(description="Analysis period in days")


@strawberry.type(description="A single point in the search trends time series")
class SearchTrendPointType:
    """GraphQL type for a search trend data point."""

    period: str = strawberry.field(description="Time period (ISO format)")
    count: int = strawberry.field(description="Total searches in period")
    unique_queries: int = strawberry.field(description="Unique queries in period")
    zero_results: int = strawberry.field(description="Searches with no results")


@strawberry.type(description="Search trends over time")
class SearchTrendsType:
    """GraphQL type for search trends response."""

    interval: str = strawberry.field(description="Time grouping interval")
    days: int = strawberry.field(description="Number of days analyzed")
    trends: list[SearchTrendPointType] = strawberry.field(description="Time series data")
    total_searches: int = strawberry.field(description="Total searches in period")
    avg_daily_searches: float = strawberry.field(description="Average searches per day")


@strawberry.type(description="A query that returned no results")
class ZeroResultQueryType:
    """GraphQL type for a zero-result query."""

    query: str = strawberry.field(description="The search query text")
    count: int = strawberry.field(description="Number of times this was searched")


@strawberry.type(description="Queries that returned no results")
class ZeroResultsResponseType:
    """GraphQL type for zero-results analysis."""

    days: int = strawberry.field(description="Number of days analyzed")
    total_zero_result_searches: int = strawberry.field(description="Total searches with no results")
    queries: list[ZeroResultQueryType] = strawberry.field(description="Zero-result queries by frequency")
    recommendations: list[str] = strawberry.field(description="Suggestions for addressing content gaps")


@strawberry.type(description="A single search insight or recommendation")
class SearchInsightType:
    """GraphQL type for a search insight."""

    type: str = strawberry.field(description="Insight type: 'improvement', 'warning', 'info'")
    title: str = strawberry.field(description="Short title")
    description: str = strawberry.field(description="Detailed description")
    metric: str | None = strawberry.field(description="Related metric name")
    value: float | None = strawberry.field(description="Metric value")
    recommendation: str | None = strawberry.field(description="Actionable recommendation")


# --- Input Types ---


@strawberry.input(description="Filter for refining search results")
class SearchFilterInput:
    """Input for search filters."""

    field: str = strawberry.field(description="Field name to filter on")
    value: str = strawberry.field(description="Value to filter by")
    operator: str = strawberry.field(
        default="eq", description="Filter operator: eq, ne, in, range"
    )


@strawberry.input(description="Search request parameters")
class SearchInput:
    """Input for search query."""

    query: str = strawberry.field(description="Search query (1-500 characters)")
    entity_types: list[str] | None = strawberry.field(
        default=None, description="Entity types to search (all if not specified)"
    )
    syntax: SearchSyntaxEnum = strawberry.field(
        default=SearchSyntaxEnum.WEB, description="Query syntax mode"
    )
    highlight: bool = strawberry.field(
        default=True, description="Include highlighted snippets"
    )
    highlight_tag: str = strawberry.field(
        default="<mark>", description="HTML tag for highlights"
    )
    limit: int = strawberry.field(
        default=20, description="Results per entity type (1-100)"
    )
    offset: int = strawberry.field(
        default=0, description="Offset for pagination"
    )
    min_rank: float = strawberry.field(
        default=0.0, description="Minimum rank threshold (0-1)"
    )
    include_facets: bool = strawberry.field(
        default=False, description="Include faceted search results"
    )
    filters: list[SearchFilterInput] | None = strawberry.field(
        default=None, description="Filters for drill-down within results"
    )
    expand_synonyms: bool = strawberry.field(
        default=True, description="Expand query with synonyms"
    )


@strawberry.input(description="Request for search suggestions/autocomplete")
class SearchSuggestionInput:
    """Input for search suggestions query."""

    prefix: str = strawberry.field(description="Query prefix (2-100 characters)")
    entity_type: str | None = strawberry.field(
        default=None, description="Limit to entity type"
    )
    limit: int = strawberry.field(
        default=10, description="Max suggestions (1-50)"
    )


@strawberry.input(description="Request to record a search result click")
class RecordClickInput:
    """Input for recording a search result click."""

    search_id: int = strawberry.field(description="ID of the search query record")
    clicked_position: int = strawberry.field(description="Position of clicked result (1-indexed)")
    clicked_entity_id: str = strawberry.field(description="ID of the clicked entity")


# --- Payload Types ---


@strawberry.type(description="Click recorded successfully")
class RecordClickSuccess:
    """Success payload for recordClick mutation."""

    success: bool = strawberry.field(description="Whether the click was recorded")
    message: str = strawberry.field(description="Status message")


@strawberry.type(description="Error recording click")
class RecordClickError:
    """Error payload for recordClick mutation."""

    code: str = strawberry.field(description="Error code")
    message: str = strawberry.field(description="Error message")


__all__ = [
    "DidYouMeanSuggestionType",
    "EntitySearchResultType",
    "FacetResultType",
    "FacetValueType",
    "RecordClickError",
    "RecordClickInput",
    "RecordClickSuccess",
    "SearchAnalyticsType",
    "SearchCapabilitiesType",
    "SearchFilterInput",
    "SearchHitType",
    "SearchInput",
    "SearchInsightType",
    "SearchResponseType",
    "SearchSuggestionInput",
    "SearchSuggestionType",
    "SearchSuggestionsResponseType",
    "SearchSyntaxEnum",
    "SearchTrendPointType",
    "SearchTrendsType",
    "SearchableEntityType",
    "ZeroResultQueryType",
    "ZeroResultsResponseType",
]
