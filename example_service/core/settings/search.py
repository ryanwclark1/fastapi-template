"""Search configuration settings.

Provides centralized search settings that can be loaded from
environment variables with SEARCH_ prefix.

Features controlled:
- Feature flags (synonyms, click boosting, semantic search, etc.)
- Performance tuning (cache TTL, max query length, result limits)
- Fuzzy search settings
- Click boosting configuration
- Slow query logging
- Circuit breaker settings
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SearchSettings(BaseSettings):
    """Search configuration settings.

    Can be loaded from environment variables with SEARCH_ prefix.
    """

    # Feature flags
    enable_synonyms: bool = Field(default=True, description="Enable synonym expansion")
    enable_click_boosting: bool = Field(default=True, description="Boost results based on clicks")
    enable_semantic_search: bool = Field(default=False, description="Enable vector search")
    enable_intent_classification: bool = Field(default=False, description="Enable query intent")
    enable_ab_testing: bool = Field(default=False, description="Enable A/B testing")

    # Performance tuning
    cache_ttl_seconds: int = Field(default=300, ge=0, description="Cache TTL in seconds")
    suggestion_cache_ttl: int = Field(default=600, ge=0, description="Suggestion cache TTL")
    max_query_length: int = Field(default=500, ge=1, description="Maximum query length")
    max_results_per_entity: int = Field(default=100, ge=1, description="Max results per entity")
    min_rank_threshold: float = Field(default=0.0, ge=0.0, le=1.0, description="Min rank threshold")

    # Fuzzy search settings
    fuzzy_threshold: float = Field(default=0.3, ge=0.0, le=1.0, description="Fuzzy match threshold")
    fuzzy_max_results: int = Field(default=10, ge=1, description="Max fuzzy results")

    # Click boosting settings
    click_boost_weight: float = Field(default=0.2, ge=0.0, le=1.0, description="Click boost weight")
    click_decay_days: int = Field(default=30, ge=1, description="Days before clicks decay")
    min_clicks_for_boost: int = Field(default=3, ge=1, description="Min clicks to apply boost")

    # Slow query logging
    slow_query_threshold_ms: int = Field(default=500, ge=0, description="Slow query threshold")
    enable_query_profiling: bool = Field(default=True, description="Enable query profiling")

    # Circuit breaker settings
    circuit_breaker_threshold: int = Field(default=5, ge=1, description="Failures before open")
    circuit_breaker_timeout: int = Field(default=30, ge=1, description="Seconds before retry")

    model_config = SettingsConfigDict(
        env_prefix="SEARCH_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        frozen=True,
        extra="ignore",
    )


__all__ = ["SearchSettings"]
