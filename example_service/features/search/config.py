"""Dynamic search configuration.

Provides configurable search settings that can be loaded from
environment variables, settings files, or database.

Features:
- Dynamic entity registration
- Synonym management
- Search feature flags
- Performance tuning parameters
- A/B testing configuration
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

if TYPE_CHECKING:
    from example_service.core.database.search.synonyms import SynonymDictionary


class SearchFeature(StrEnum):
    """Available search features that can be toggled."""

    FULL_TEXT_SEARCH = "full_text_search"
    FUZZY_MATCHING = "fuzzy_matching"
    HIGHLIGHTING = "highlighting"
    FACETED_SEARCH = "faceted_search"
    AUTOCOMPLETE = "autocomplete"
    DID_YOU_MEAN = "did_you_mean"
    SYNONYMS = "synonyms"
    CLICK_BOOSTING = "click_boosting"
    SEMANTIC_SEARCH = "semantic_search"
    INTENT_CLASSIFICATION = "intent_classification"


class EntitySearchConfig(BaseModel):
    """Configuration for a searchable entity."""

    display_name: str = Field(description="Human-readable name for the entity")
    model_path: str = Field(description="Full module path to the model class")
    search_fields: list[str] = Field(description="Fields to include in search vector")
    title_field: str | None = Field(default=None, description="Field for result title")
    snippet_field: str | None = Field(default=None, description="Field for snippets")
    id_field: str = Field(default="id", description="Primary key field")
    config: str = Field(default="english", description="PostgreSQL text search config")
    fuzzy_fields: list[str] = Field(default_factory=list, description="Fields for fuzzy matching")
    facet_fields: list[str] = Field(default_factory=list, description="Fields for faceted search")
    boost_factor: float = Field(default=1.0, ge=0.0, description="Ranking boost for this entity")
    max_results: int = Field(default=100, ge=1, le=1000, description="Max results per search")


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

    model_config = {"env_prefix": "SEARCH_"}


@dataclass
class SearchEntityRegistry:
    """Registry of searchable entities.

    Supports dynamic registration and lookup of searchable entities.

    Example:
        registry = SearchEntityRegistry()
        registry.register("posts", EntitySearchConfig(
            display_name="Posts",
            model_path="myapp.models.Post",
            search_fields=["title", "content"],
        ))

        config = registry.get("posts")
    """

    entities: dict[str, EntitySearchConfig] = field(default_factory=dict)

    def register(self, name: str, config: EntitySearchConfig) -> None:
        """Register a searchable entity.

        Args:
            name: Entity type identifier.
            config: Entity search configuration.
        """
        self.entities[name] = config

    def unregister(self, name: str) -> bool:
        """Unregister a searchable entity.

        Args:
            name: Entity type identifier.

        Returns:
            True if entity was removed.
        """
        if name in self.entities:
            del self.entities[name]
            return True
        return False

    def get(self, name: str) -> EntitySearchConfig | None:
        """Get entity configuration.

        Args:
            name: Entity type identifier.

        Returns:
            Entity configuration or None.
        """
        return self.entities.get(name)

    def list_entities(self) -> list[str]:
        """List all registered entity types.

        Returns:
            List of entity type names.
        """
        return list(self.entities.keys())

    def to_dict(self) -> dict[str, dict[str, Any]]:
        """Convert registry to dictionary format.

        Returns:
            Dictionary of entity configurations.
        """
        return {name: config.model_dump() for name, config in self.entities.items()}


@dataclass
class SearchConfiguration:
    """Complete search configuration.

    Combines settings, entity registry, and synonyms.
    """

    settings: SearchSettings = field(default_factory=SearchSettings)
    entity_registry: SearchEntityRegistry = field(default_factory=SearchEntityRegistry)
    _synonym_dictionary: SynonymDictionary | None = field(default=None, repr=False)

    def get_enabled_features(self) -> list[str]:
        """Get list of enabled search features.

        Returns:
            List of enabled feature names.
        """
        features = [
            SearchFeature.FULL_TEXT_SEARCH,
            SearchFeature.HIGHLIGHTING,
            SearchFeature.AUTOCOMPLETE,
            SearchFeature.DID_YOU_MEAN,
            SearchFeature.FUZZY_MATCHING,
            SearchFeature.FACETED_SEARCH,
        ]

        if self.settings.enable_synonyms:
            features.append(SearchFeature.SYNONYMS)
        if self.settings.enable_click_boosting:
            features.append(SearchFeature.CLICK_BOOSTING)
        if self.settings.enable_semantic_search:
            features.append(SearchFeature.SEMANTIC_SEARCH)
        if self.settings.enable_intent_classification:
            features.append(SearchFeature.INTENT_CLASSIFICATION)

        return [f.value for f in features]

    @property
    def synonym_dictionary(self) -> SynonymDictionary | None:
        """Get the synonym dictionary."""
        return self._synonym_dictionary

    @synonym_dictionary.setter
    def synonym_dictionary(self, dictionary: SynonymDictionary) -> None:
        """Set the synonym dictionary."""
        self._synonym_dictionary = dictionary


# Default entity configurations
DEFAULT_ENTITY_CONFIGS: dict[str, EntitySearchConfig] = {
    "reminders": EntitySearchConfig(
        display_name="Reminders",
        model_path="example_service.features.reminders.models.Reminder",
        search_fields=["title", "description"],
        title_field="title",
        snippet_field="description",
        config="english",
        fuzzy_fields=["title"],
        facet_fields=["is_completed"],
    ),
    "posts": EntitySearchConfig(
        display_name="Posts",
        model_path="example_service.core.models.post.Post",
        search_fields=["title", "content", "slug"],
        title_field="title",
        snippet_field="content",
        config="english",
        fuzzy_fields=["title"],
        facet_fields=["is_published", "author_id"],
    ),
    "users": EntitySearchConfig(
        display_name="Users",
        model_path="example_service.core.models.user.User",
        search_fields=["email", "username", "full_name"],
        title_field="username",
        snippet_field="full_name",
        config="simple",
        fuzzy_fields=["username", "full_name"],
        facet_fields=["is_active"],
    ),
}


def create_default_registry() -> SearchEntityRegistry:
    """Create a registry with default entity configurations.

    Returns:
        SearchEntityRegistry with default entities.
    """
    registry = SearchEntityRegistry()
    for name, config in DEFAULT_ENTITY_CONFIGS.items():
        registry.register(name, config)
    return registry


def create_default_configuration() -> SearchConfiguration:
    """Create default search configuration.

    Returns:
        SearchConfiguration with defaults.
    """
    from example_service.core.database.search.synonyms import get_default_synonyms

    config = SearchConfiguration(
        settings=SearchSettings(),
        entity_registry=create_default_registry(),
    )
    config.synonym_dictionary = get_default_synonyms()
    return config


# Global configuration instance
_search_config: SearchConfiguration | None = None


def get_search_config() -> SearchConfiguration:
    """Get the global search configuration.

    Returns:
        SearchConfiguration instance.
    """
    global _search_config
    if _search_config is None:
        _search_config = create_default_configuration()
    return _search_config


def set_search_config(config: SearchConfiguration) -> None:
    """Set the global search configuration.

    Args:
        config: Configuration to set.
    """
    global _search_config
    _search_config = config


__all__ = [
    "DEFAULT_ENTITY_CONFIGS",
    "EntitySearchConfig",
    "SearchConfiguration",
    "SearchEntityRegistry",
    "SearchFeature",
    "SearchSettings",
    "create_default_configuration",
    "create_default_registry",
    "get_search_config",
    "set_search_config",
]
