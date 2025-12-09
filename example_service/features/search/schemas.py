"""Search schemas for API requests and responses."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class SearchSyntax(StrEnum):
    """Search query syntax modes."""

    PLAIN = "plain"  # Simple AND matching
    WEB = "web"  # Web-style with operators
    PHRASE = "phrase"  # Exact phrase matching


class SearchFilter(BaseModel):
    """Filter for refining search results."""

    field: str = Field(description="Field name to filter on")
    value: str | list[str] = Field(description="Value(s) to filter by")
    operator: str = Field(default="eq", description="Filter operator: eq, ne, in, range")


class SearchRequest(BaseModel):
    """Search request parameters."""

    query: str = Field(min_length=1, max_length=500, description="Search query")
    entity_types: list[str] | None = Field(
        default=None, description="Entity types to search (all if not specified)"
    )
    syntax: SearchSyntax = Field(
        default=SearchSyntax.WEB, description="Query syntax mode"
    )
    highlight: bool = Field(
        default=True, description="Include highlighted snippets"
    )
    highlight_tag: str = Field(
        default="<mark>", description="HTML tag for highlights"
    )
    limit: int = Field(default=20, ge=1, le=100, description="Results per entity type")
    offset: int = Field(default=0, ge=0, description="Offset for pagination")
    min_rank: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Minimum rank threshold"
    )
    include_facets: bool = Field(
        default=False, description="Include faceted search results"
    )
    filters: list[SearchFilter] | None = Field(
        default=None, description="Filters for drill-down within results"
    )
    expand_synonyms: bool = Field(
        default=True, description="Expand query with synonyms"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "query": "meeting tomorrow",
                "entity_types": ["reminders"],
                "highlight": True,
                "include_facets": True,
                "filters": [{"field": "is_completed", "value": "false"}],
            }
        }
    }


class SearchHit(BaseModel):
    """A single search result."""

    entity_type: str = Field(description="Type of entity")
    entity_id: str = Field(description="Entity ID")
    rank: float = Field(description="Search relevance rank (0-1)")
    title: str | None = Field(default=None, description="Result title")
    snippet: str | None = Field(default=None, description="Text snippet with highlights")
    data: dict[str, Any] = Field(default_factory=dict, description="Full entity data")
    created_at: datetime | None = Field(default=None, description="Entity creation time")


class FacetValue(BaseModel):
    """A single facet value with count."""

    value: str = Field(description="Facet value")
    count: int = Field(description="Number of results with this value")


class FacetResult(BaseModel):
    """Facet results for a field."""

    field: str = Field(description="Field name")
    display_name: str = Field(description="Human-readable field name")
    values: list[FacetValue] = Field(description="Value counts")


class EntitySearchResult(BaseModel):
    """Search results for a specific entity type."""

    entity_type: str
    total: int = Field(description="Total matching results")
    hits: list[SearchHit] = Field(description="Search results")
    facets: list[FacetResult] | None = Field(
        default=None, description="Facet counts for this entity type"
    )


class DidYouMeanSuggestion(BaseModel):
    """'Did you mean?' suggestion for typos."""

    original_query: str = Field(description="Original query with possible typo")
    suggested_query: str = Field(description="Suggested correction")
    confidence: float = Field(
        description="Confidence score (0-1) for the suggestion",
        ge=0.0,
        le=1.0,
    )


class SearchResponse(BaseModel):
    """Complete search response."""

    query: str = Field(description="Original search query")
    total_hits: int = Field(description="Total results across all entity types")
    results: list[EntitySearchResult] = Field(description="Results by entity type")
    suggestions: list[str] = Field(
        default_factory=list, description="Query suggestions for no/few results"
    )
    did_you_mean: DidYouMeanSuggestion | None = Field(
        default=None, description="Spelling correction suggestion"
    )
    facets: list[FacetResult] | None = Field(
        default=None, description="Aggregated facet counts across all entity types"
    )
    took_ms: int = Field(description="Search time in milliseconds")


class SearchSuggestionRequest(BaseModel):
    """Request for search suggestions/autocomplete."""

    prefix: str = Field(min_length=2, max_length=100, description="Query prefix")
    entity_type: str | None = Field(default=None, description="Limit to entity type")
    limit: int = Field(default=10, ge=1, le=50, description="Max suggestions")


class SearchSuggestion(BaseModel):
    """A search suggestion."""

    text: str = Field(description="Suggested search term")
    entity_type: str | None = Field(default=None, description="Entity type if specific")
    count: int = Field(default=0, description="Approximate result count")


class SearchSuggestionsResponse(BaseModel):
    """Response with search suggestions."""

    prefix: str
    suggestions: list[SearchSuggestion]


class SearchableEntity(BaseModel):
    """Information about a searchable entity."""

    name: str = Field(description="Entity type name")
    display_name: str = Field(description="Human-readable name")
    search_fields: list[str] = Field(description="Fields included in search")
    title_field: str | None = Field(default=None, description="Field used for result title")
    snippet_field: str | None = Field(default=None, description="Field used for snippets")
    supports_fuzzy: bool = Field(
        default=False, description="Whether fuzzy matching is available"
    )
    facet_fields: list[str] = Field(
        default_factory=list, description="Fields available for faceted search"
    )


class SearchCapabilitiesResponse(BaseModel):
    """Response describing search capabilities."""

    entities: list[SearchableEntity]
    supported_syntax: list[SearchSyntax]
    max_query_length: int
    max_results_per_entity: int
    features: list[str] = Field(
        default_factory=list, description="List of available search features"
    )


class SearchAnalyticsRequest(BaseModel):
    """Request for search analytics."""

    days: int = Field(default=30, ge=1, le=365, description="Number of days to analyze")


class SearchAnalyticsResponse(BaseModel):
    """Search analytics summary."""

    total_searches: int = Field(description="Total number of searches")
    unique_queries: int = Field(description="Number of unique search queries")
    zero_result_rate: float = Field(description="Percentage of searches with no results")
    avg_results_count: float = Field(description="Average results per search")
    avg_response_time_ms: float = Field(description="Average response time")
    click_through_rate: float = Field(description="Percentage of searches with clicks")
    top_queries: list[dict[str, Any]] = Field(description="Most popular queries")
    zero_result_queries: list[dict[str, Any]] = Field(description="Queries with no results")
    period_days: int = Field(description="Analysis period in days")


class RecordClickRequest(BaseModel):
    """Request to record a search result click."""

    search_id: int = Field(description="ID of the search query record")
    clicked_position: int = Field(ge=1, description="Position of clicked result (1-indexed)")
    clicked_entity_id: str = Field(description="ID of the clicked entity")


class SearchInsightResponse(BaseModel):
    """A single search insight or recommendation."""

    type: str = Field(description="Insight type: 'improvement', 'warning', 'info'")
    title: str = Field(description="Short title")
    description: str = Field(description="Detailed description")
    metric: str | None = Field(default=None, description="Related metric name")
    value: float | None = Field(default=None, description="Metric value")
    recommendation: str | None = Field(default=None, description="Actionable recommendation")


class SearchTrendPoint(BaseModel):
    """A single point in the search trends time series."""

    period: str = Field(description="Time period (ISO format)")
    count: int = Field(description="Total searches in period")
    unique_queries: int = Field(description="Unique queries in period")
    zero_results: int = Field(description="Searches with no results")


class SearchTrendsResponse(BaseModel):
    """Search trends over time."""

    interval: str = Field(description="Time grouping interval")
    days: int = Field(description="Number of days analyzed")
    trends: list[SearchTrendPoint] = Field(description="Time series data")
    total_searches: int = Field(description="Total searches in period")
    avg_daily_searches: float = Field(description="Average searches per day")


class ZeroResultQuery(BaseModel):
    """A query that returned no results."""

    query: str = Field(description="The search query text")
    count: int = Field(description="Number of times this was searched")


class ZeroResultsResponse(BaseModel):
    """Queries that returned no results."""

    days: int = Field(description="Number of days analyzed")
    total_zero_result_searches: int = Field(description="Total searches with no results")
    queries: list[ZeroResultQuery] = Field(description="Zero-result queries by frequency")
    recommendations: list[str] = Field(
        default_factory=list,
        description="Suggestions for addressing content gaps"
    )


__all__ = [
    "DidYouMeanSuggestion",
    "EntitySearchResult",
    "FacetResult",
    "FacetValue",
    "RecordClickRequest",
    "SearchAnalyticsRequest",
    "SearchAnalyticsResponse",
    "SearchCapabilitiesResponse",
    "SearchFilter",
    "SearchHit",
    "SearchInsightResponse",
    "SearchRequest",
    "SearchResponse",
    "SearchSuggestion",
    "SearchSuggestionRequest",
    "SearchSuggestionsResponse",
    "SearchSyntax",
    "SearchTrendPoint",
    "SearchTrendsResponse",
    "SearchableEntity",
    "ZeroResultQuery",
    "ZeroResultsResponse",
]
