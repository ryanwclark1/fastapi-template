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

    model_config = {
        "json_schema_extra": {
            "example": {
                "query": "meeting tomorrow",
                "entity_types": ["reminders"],
                "highlight": True,
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


class EntitySearchResult(BaseModel):
    """Search results for a specific entity type."""

    entity_type: str
    total: int = Field(description="Total matching results")
    hits: list[SearchHit] = Field(description="Search results")


class SearchResponse(BaseModel):
    """Complete search response."""

    query: str = Field(description="Original search query")
    total_hits: int = Field(description="Total results across all entity types")
    results: list[EntitySearchResult] = Field(description="Results by entity type")
    suggestions: list[str] = Field(
        default_factory=list, description="Query suggestions for no/few results"
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


class SearchCapabilitiesResponse(BaseModel):
    """Response describing search capabilities."""

    entities: list[SearchableEntity]
    supported_syntax: list[SearchSyntax]
    max_query_length: int
    max_results_per_entity: int


__all__ = [
    "SearchSyntax",
    "SearchRequest",
    "SearchHit",
    "EntitySearchResult",
    "SearchResponse",
    "SearchSuggestionRequest",
    "SearchSuggestion",
    "SearchSuggestionsResponse",
    "SearchableEntity",
    "SearchCapabilitiesResponse",
]
