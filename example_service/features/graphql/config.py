"""GraphQL feature configuration.

Central configuration for enabling/disabling GraphQL features.
Feature toggles are read from core/settings/graphql.py and can be
configured via environment variables using the GRAPHQL_FEATURE_ prefix.

Usage:
    # In .env file
    GRAPHQL_FEATURE_TAGS=false
    GRAPHQL_FEATURE_AI=true

    # In code
    features = get_graphql_features()
    if features.tags:
        # Register tag resolvers

Environment Variables:
    GRAPHQL_FEATURE_REMINDERS=true     # Enable reminder queries/mutations (default: true)
    GRAPHQL_FEATURE_TAGS=true          # Enable tag queries/mutations (default: true)
    GRAPHQL_FEATURE_FLAGS=true         # Enable feature flag management (default: true)
    GRAPHQL_FEATURE_FILES=true         # Enable file upload/management (default: true)
    GRAPHQL_FEATURE_WEBHOOKS=true      # Enable webhook management (default: true)
    GRAPHQL_FEATURE_AUDIT_LOGS=true    # Enable audit log queries (default: true)
    GRAPHQL_FEATURE_AI=false           # Enable AI/ML features (default: false)
    GRAPHQL_FEATURE_TASKS=true         # Enable task management (default: true)
    GRAPHQL_FEATURE_SEARCH=true        # Enable search functionality (default: true)
    GRAPHQL_FEATURE_WORKFLOWS=true     # Enable AI workflow management (default: true)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["GraphQLFeatures", "get_feature_registry", "get_graphql_features"]


class GraphQLFeatures:
    """Feature flags for GraphQL schema composition.

    This class reads feature toggles from GraphQLSettings (core/settings/graphql.py)
    which are configured via environment variables using the GRAPHQL_FEATURE_ prefix.

    Each boolean property controls whether that feature's queries, mutations,
    and subscriptions are included in the schema.

    Properties:
        reminders: Enable reminder management
        tags: Enable tag management
        feature_flags: Enable feature flag management
        files: Enable file upload/management
        webhooks: Enable webhook management
        audit_logs: Enable audit log queries
        ai: Enable AI/ML features (experimental)
        tasks: Enable task management
        search: Enable search functionality
        workflows: Enable AI workflow management
    """

    def __init__(self) -> None:
        """Initialize by loading settings from environment."""
        from example_service.core.settings import get_graphql_settings

        self._settings = get_graphql_settings()

    @property
    def reminders(self) -> bool:
        """Check if reminders feature is enabled."""
        return self._settings.feature_reminders

    @property
    def tags(self) -> bool:
        """Check if tags feature is enabled."""
        return self._settings.feature_tags

    @property
    def feature_flags(self) -> bool:
        """Check if feature flags feature is enabled."""
        return self._settings.feature_flags

    @property
    def files(self) -> bool:
        """Check if files feature is enabled."""
        return self._settings.feature_files

    @property
    def webhooks(self) -> bool:
        """Check if webhooks feature is enabled."""
        return self._settings.feature_webhooks

    @property
    def audit_logs(self) -> bool:
        """Check if audit logs feature is enabled."""
        return self._settings.feature_audit_logs

    @property
    def ai(self) -> bool:
        """Check if AI feature is enabled."""
        return self._settings.feature_ai

    @property
    def tasks(self) -> bool:
        """Check if tasks feature is enabled."""
        return getattr(self._settings, "feature_tasks", True)

    @property
    def search(self) -> bool:
        """Check if search feature is enabled."""
        return getattr(self._settings, "feature_search", True)

    @property
    def workflows(self) -> bool:
        """Check if workflows feature is enabled."""
        return getattr(self._settings, "feature_workflows", True)

    def get_enabled_features(self) -> list[str]:
        """Get list of enabled feature names.

        Returns:
            List of enabled feature names (lowercase)

        Example:
            >>> features = get_graphql_features()
            >>> features.get_enabled_features()
            ['reminders', 'feature_flags', 'files', 'webhooks', 'audit_logs', 'tasks', 'search']
        """
        feature_map = {
            "reminders": self.reminders,
            "tags": self.tags,
            "feature_flags": self.feature_flags,
            "files": self.files,
            "webhooks": self.webhooks,
            "audit_logs": self.audit_logs,
            "ai": self.ai,
            "tasks": self.tasks,
            "search": self.search,
            "workflows": self.workflows,
        }
        return [name for name, enabled in feature_map.items() if enabled]

    def is_enabled(self, feature: str) -> bool:
        """Check if a specific feature is enabled.

        Args:
            feature: Feature name (e.g., 'tags', 'ai')

        Returns:
            True if feature is enabled, False otherwise

        Example:
            >>> features = get_graphql_features()
            >>> features.is_enabled('ai')
            False
        """
        feature_normalized = feature.lower().replace("-", "_")
        return getattr(self, feature_normalized, False)


# Global feature configuration instance
# This is initialized lazily on first access
_FEATURES: GraphQLFeatures | None = None


def get_graphql_features() -> GraphQLFeatures:
    """Get the current GraphQL feature configuration.

    Reads feature toggles from GraphQLSettings which are configured
    via environment variables (GRAPHQL_FEATURE_* prefix).

    Returns:
        GraphQLFeatures instance with current settings

    Example:
        >>> features = get_graphql_features()
        >>> if features.tags:
        ...     # Register tag resolvers
    """
    global _FEATURES
    if _FEATURES is None:
        _FEATURES = GraphQLFeatures()
    return _FEATURES


# ============================================================================
# Feature Registry
# ============================================================================


@dataclass
class FeatureResolvers:
    """Container for a feature's GraphQL resolvers.

    Attributes:
        name: Feature name (e.g., 'tags', 'ai')
        queries: List of query resolver functions
        mutations: List of mutation resolver functions
        subscriptions: List of subscription resolver functions
        enabled: Whether this feature is currently enabled
    """

    name: str
    queries: list[Callable] = field(default_factory=list)
    mutations: list[Callable] = field(default_factory=list)
    subscriptions: list[Callable] = field(default_factory=list)
    enabled: bool = True


class FeatureRegistry:
    """Registry for GraphQL feature resolvers.

    Provides a central place to register and retrieve feature-specific
    resolvers based on the feature configuration.

    Example:
        >>> registry = FeatureRegistry()
        >>> registry.register('tags', queries=[tag_query, tags_query])
        >>> registry.register('ai', queries=[chat_query], enabled=False)
        >>> enabled_queries = registry.get_enabled_queries()
    """

    def __init__(self) -> None:
        """Initialize the feature registry."""
        self._features: dict[str, FeatureResolvers] = {}

    def register(
        self,
        name: str,
        *,
        queries: list[Callable] | None = None,
        mutations: list[Callable] | None = None,
        subscriptions: list[Callable] | None = None,
        enabled: bool = True,
    ) -> None:
        """Register resolvers for a feature.

        Args:
            name: Feature name
            queries: Query resolver functions
            mutations: Mutation resolver functions
            subscriptions: Subscription resolver functions
            enabled: Whether feature is enabled (overrides global config)

        Example:
            >>> registry.register(
            ...     'tags',
            ...     queries=[tag_query, tags_query],
            ...     mutations=[create_tag_mutation, update_tag_mutation],
            ...     subscriptions=[tag_events_subscription],
            ... )
        """
        self._features[name] = FeatureResolvers(
            name=name,
            queries=queries or [],
            mutations=mutations or [],
            subscriptions=subscriptions or [],
            enabled=enabled,
        )

    def get_feature(self, name: str) -> FeatureResolvers | None:
        """Get resolvers for a specific feature.

        Args:
            name: Feature name

        Returns:
            FeatureResolvers if feature exists, None otherwise
        """
        return self._features.get(name)

    def get_enabled_queries(self) -> list[Callable]:
        """Get all query resolvers from enabled features.

        Returns:
            List of query resolver functions
        """
        features = get_graphql_features()
        queries = []
        for name, feature in self._features.items():
            if feature.enabled and features.is_enabled(name):
                queries.extend(feature.queries)
        return queries

    def get_enabled_mutations(self) -> list[Callable]:
        """Get all mutation resolvers from enabled features.

        Returns:
            List of mutation resolver functions
        """
        features = get_graphql_features()
        mutations = []
        for name, feature in self._features.items():
            if feature.enabled and features.is_enabled(name):
                mutations.extend(feature.mutations)
        return mutations

    def get_enabled_subscriptions(self) -> list[Callable]:
        """Get all subscription resolvers from enabled features.

        Returns:
            List of subscription resolver functions
        """
        features = get_graphql_features()
        subscriptions = []
        for name, feature in self._features.items():
            if feature.enabled and features.is_enabled(name):
                subscriptions.extend(feature.subscriptions)
        return subscriptions


# Global registry instance
_REGISTRY = FeatureRegistry()


def get_feature_registry() -> FeatureRegistry:
    """Get the global feature registry.

    Returns:
        Global FeatureRegistry instance

    Example:
        >>> registry = get_feature_registry()
        >>> registry.register('ai', queries=[chat_query])
    """
    return _REGISTRY
