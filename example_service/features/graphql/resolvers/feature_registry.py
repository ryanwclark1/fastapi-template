"""Feature registry for GraphQL resolvers.

Central registration point for all GraphQL features. This module:
- Imports all feature-specific resolvers
- Registers them with the global feature registry
- Enables/disables features based on configuration

To add a new feature:
1. Create {feature}_queries.py, {feature}_mutations.py, {feature}_subscriptions.py
2. Import the resolver functions below
3. Call registry.register() with your feature name and resolvers
4. Add feature to GraphQLFeatures dataclass in config.py
"""

from __future__ import annotations

import logging

from example_service.features.graphql.config import get_feature_registry

# Import audit log resolvers
from example_service.features.graphql.resolvers.auditlogs_queries import (
    audit_log_query,
    audit_logs_by_entity_query,
    audit_logs_query,
)

# Import feature flag resolvers
from example_service.features.graphql.resolvers.featureflags_mutations import (
    create_feature_flag_mutation,
    delete_feature_flag_mutation,
    toggle_feature_flag_mutation,
    update_feature_flag_mutation,
)
from example_service.features.graphql.resolvers.featureflags_queries import (
    evaluate_flag_query,
    feature_flag_by_key_query,
    feature_flag_query,
    feature_flags_query,
)

# Import file resolvers
from example_service.features.graphql.resolvers.files_mutations import (
    confirm_file_upload_mutation,
    delete_file_mutation,
    initiate_file_upload_mutation,
)
from example_service.features.graphql.resolvers.files_queries import (
    file_query,
    files_by_owner_query,
    files_query,
)

# Import reminder resolvers (from monolithic files)
from example_service.features.graphql.resolvers.mutations import (
    Mutation as ReminderMutation,
)
from example_service.features.graphql.resolvers.queries import Query as ReminderQuery
from example_service.features.graphql.resolvers.subscriptions import (
    Subscription as ReminderSubscription,
)

# Import tag resolvers
from example_service.features.graphql.resolvers.tags_mutations import (
    add_tags_to_reminder_mutation,
    create_tag_mutation,
    delete_tag_mutation,
    remove_tags_from_reminder_mutation,
    update_tag_mutation,
)
from example_service.features.graphql.resolvers.tags_queries import (
    popular_tags_query,
    tag_query,
    tags_by_reminder_query,
    tags_query,
)

# Import webhook resolvers
from example_service.features.graphql.resolvers.webhooks_mutations import (
    create_webhook_mutation,
    delete_webhook_mutation,
    retry_delivery_mutation,
    test_webhook_mutation,
    update_webhook_mutation,
)
from example_service.features.graphql.resolvers.webhooks_queries import (
    webhook_deliveries_query,
    webhook_query,
    webhooks_query,
)

logger = logging.getLogger(__name__)

__all__ = ["get_registered_features_summary", "register_all_features"]


def register_all_features() -> None:
    """Register all GraphQL features with the global registry.

    This function should be called once during application startup
    to make all features available to the schema composer.

    Features are registered even if disabled - the schema composer
    will check the feature configuration to determine which to include.
    """
    registry = get_feature_registry()

    # ========================================================================
    # Reminders Feature
    # ========================================================================
    # Note: Reminders uses the old monolithic pattern (Query/Mutation/Subscription classes)
    # We extract the methods from these classes for registration

    reminder_query_instance = ReminderQuery()
    reminder_mutation_instance = ReminderMutation()
    reminder_subscription_instance = ReminderSubscription()

    registry.register(
        "reminders",
        queries=[
            reminder_query_instance.reminder,
            reminder_query_instance.reminders,
            reminder_query_instance.overdue_reminders,
        ],
        mutations=[
            reminder_mutation_instance.create_reminder,
            reminder_mutation_instance.update_reminder,
            reminder_mutation_instance.complete_reminder,
            reminder_mutation_instance.delete_reminder,
        ],
        subscriptions=[
            reminder_subscription_instance.reminder_events,
        ],
    )

    # ========================================================================
    # Tags Feature
    # ========================================================================
    registry.register(
        "tags",
        queries=[
            tag_query,
            tags_query,
            tags_by_reminder_query,
            popular_tags_query,
        ],
        mutations=[
            create_tag_mutation,
            update_tag_mutation,
            delete_tag_mutation,
            add_tags_to_reminder_mutation,
            remove_tags_from_reminder_mutation,
        ],
        # Subscriptions not yet implemented for tags
        subscriptions=[],
    )

    # ========================================================================
    # Feature Flags Feature
    # ========================================================================
    registry.register(
        "feature_flags",
        queries=[
            feature_flag_query,
            feature_flags_query,
            feature_flag_by_key_query,
            evaluate_flag_query,
        ],
        mutations=[
            create_feature_flag_mutation,
            update_feature_flag_mutation,
            toggle_feature_flag_mutation,
            delete_feature_flag_mutation,
        ],
        # Subscriptions not yet implemented for feature flags
        subscriptions=[],
    )

    # ========================================================================
    # Files Feature
    # ========================================================================
    registry.register(
        "files",
        queries=[
            file_query,
            files_query,
            files_by_owner_query,
        ],
        mutations=[
            initiate_file_upload_mutation,
            confirm_file_upload_mutation,
            delete_file_mutation,
        ],
        # Subscriptions not yet implemented for files
        subscriptions=[],
    )

    # ========================================================================
    # Webhooks Feature
    # ========================================================================
    registry.register(
        "webhooks",
        queries=[
            webhook_query,
            webhooks_query,
            webhook_deliveries_query,
        ],
        mutations=[
            create_webhook_mutation,
            update_webhook_mutation,
            delete_webhook_mutation,
            test_webhook_mutation,
            retry_delivery_mutation,
        ],
        # Subscriptions not yet implemented for webhooks
        subscriptions=[],
    )

    # ========================================================================
    # Audit Logs Feature
    # ========================================================================
    registry.register(
        "audit_logs",
        queries=[
            audit_log_query,
            audit_logs_query,
            audit_logs_by_entity_query,
        ],
        # Audit logs are read-only (no mutations)
        mutations=[],
        # Subscriptions not yet implemented for audit logs
        subscriptions=[],
    )

    logger.info("Registered all GraphQL features")


def get_registered_features_summary() -> dict[str, dict[str, int]]:
    """Get a summary of registered features and their resolver counts.

    Returns:
        Dictionary mapping feature names to counts of queries/mutations/subscriptions

    Example:
        >>> summary = get_registered_features_summary()
        >>> print(summary)
        {
            'reminders': {'queries': 3, 'mutations': 4, 'subscriptions': 1},
            'tags': {'queries': 4, 'mutations': 5, 'subscriptions': 0},
            ...
        }
    """
    from example_service.features.graphql.config import get_graphql_features

    registry = get_feature_registry()
    features = get_graphql_features()
    summary = {}

    for name, feature in registry._features.items():
        is_enabled = features.is_enabled(name) and feature.enabled
        summary[name] = {
            "queries": len(feature.queries),
            "mutations": len(feature.mutations),
            "subscriptions": len(feature.subscriptions),
            "enabled": is_enabled,
        }

    return summary
