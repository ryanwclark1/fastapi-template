"""Dynamic GraphQL schema composer.

Builds Query, Mutation, and Subscription types dynamically from registered
features, enabling/disabling features based on configuration.

This approach provides:
- Feature toggling without code changes
- Automatic schema composition
- Type-safe resolver registration
- Clean separation of concerns
"""

from __future__ import annotations

import logging
from typing import Any

import strawberry

from example_service.features.graphql.config import (
    get_feature_registry,
    get_graphql_features,
)

logger = logging.getLogger(__name__)

__all__ = ["compose_mutation", "compose_query", "compose_subscription"]


def compose_query() -> type:
    """Compose Query type from enabled features.

    Returns:
        Strawberry Query type with all enabled feature queries

    Example:
        >>> query_type = compose_query()
        >>> schema = strawberry.Schema(query=query_type)
    """
    registry = get_feature_registry()
    features = get_graphql_features()

    # Collect all enabled query resolvers
    query_methods: dict[str, Any] = {}

    for feature_name, feature in registry._features.items():
        if not features.is_enabled(feature_name) or not feature.enabled:
            logger.debug("Skipping disabled feature: %s", feature_name)
            continue

        # Add all query resolvers from this feature
        for resolver in feature.queries:
            # Handle both raw functions and StrawberryField objects
            if hasattr(resolver, "python_name"):
                # Already a StrawberryField object
                field_name = resolver.python_name
                field_obj = resolver
            elif hasattr(resolver, "__name__"):
                # Raw function - needs to be wrapped
                field_name = resolver.__name__
                field_obj = strawberry.field(resolver)
            else:
                logger.warning(
                    f"Skipping resolver from feature '{feature_name}': "
                    f"Cannot determine name for {resolver}",
                )
                continue

            # Remove common suffixes for cleaner API
            field_name = field_name.replace("_query", "").replace("_resolver", "")

            if field_name in query_methods:
                logger.warning(
                    f"Duplicate query field '{field_name}' from feature '{feature_name}'. "
                    "Using first definition.",
                )
                continue

            query_methods[field_name] = field_obj

        logger.debug(
            f"Added {len(feature.queries)} queries from feature '{feature_name}'",
        )

    # If no queries enabled, provide a minimal health check query
    if not query_methods:
        logger.warning("No queries enabled! Adding minimal health query.")

        @strawberry.field(description="Health check endpoint")
        def health() -> str:
            """Basic health check query.

            Returns:
                Status string
            """
            return "ok"

        query_methods["health"] = health

    # Dynamically create Query type
    Query = type(
        "Query",
        (),
        {
            **query_methods,
            "__annotations__": {
                name: getattr(resolver, "__annotations__", {}).get("return", str)
                for name, resolver in query_methods.items()
            },
        },
    )

    # Apply Strawberry type decorator
    Query = strawberry.type(Query, description="Root query type")

    enabled_features = [
        name
        for name, f in registry._features.items()
        if features.is_enabled(name) and f.enabled
    ]
    logger.info(
        f"Composed Query type with {len(query_methods)} fields "
        f"from {len(enabled_features)} features: {', '.join(enabled_features)}",
    )

    return Query


def compose_mutation() -> type:
    """Compose Mutation type from enabled features.

    Returns:
        Strawberry Mutation type with all enabled feature mutations

    Example:
        >>> mutation_type = compose_mutation()
        >>> schema = strawberry.Schema(mutation=mutation_type)
    """
    registry = get_feature_registry()
    features = get_graphql_features()

    # Collect all enabled mutation resolvers
    mutation_methods: dict[str, Any] = {}

    for feature_name, feature in registry._features.items():
        if not features.is_enabled(feature_name) or not feature.enabled:
            continue

        # Add all mutation resolvers from this feature
        for resolver in feature.mutations:
            # Handle both raw functions and StrawberryField objects
            if hasattr(resolver, "python_name"):
                # Already a StrawberryField/StrawberryMutation object
                field_name = resolver.python_name
                field_obj = resolver
            elif hasattr(resolver, "__name__"):
                # Raw function - needs to be wrapped
                field_name = resolver.__name__
                field_obj = strawberry.mutation(resolver)
            else:
                logger.warning(
                    f"Skipping resolver from feature '{feature_name}': "
                    f"Cannot determine name for {resolver}",
                )
                continue

            # Remove common suffixes for cleaner API
            field_name = field_name.replace("_mutation", "").replace("_resolver", "")

            if field_name in mutation_methods:
                logger.warning(
                    f"Duplicate mutation field '{field_name}' from feature '{feature_name}'. "
                    "Using first definition.",
                )
                continue

            mutation_methods[field_name] = field_obj

        logger.debug(
            f"Added {len(feature.mutations)} mutations from feature '{feature_name}'",
        )

    # If no mutations enabled, provide a minimal noop mutation
    if not mutation_methods:
        logger.warning("No mutations enabled! Adding minimal noop mutation.")

        @strawberry.mutation(description="No-op mutation placeholder")
        def noop() -> bool:
            """Placeholder mutation when no features are enabled.

            Returns:
                Always returns True
            """
            return True

        mutation_methods["noop"] = noop

    # Dynamically create Mutation type
    Mutation = type(
        "Mutation",
        (),
        {
            **mutation_methods,
            "__annotations__": {
                name: getattr(resolver, "__annotations__", {}).get("return", bool)
                for name, resolver in mutation_methods.items()
            },
        },
    )

    # Apply Strawberry type decorator
    Mutation = strawberry.type(Mutation, description="Root mutation type")

    enabled_features = [
        name
        for name, f in registry._features.items()
        if features.is_enabled(name) and f.enabled and f.mutations
    ]
    logger.info(
        f"Composed Mutation type with {len(mutation_methods)} fields "
        f"from {len(enabled_features)} features: {', '.join(enabled_features)}",
    )

    return Mutation


def compose_subscription() -> type | None:
    """Compose Subscription type from enabled features.

    Returns:
        Strawberry Subscription type with all enabled feature subscriptions,
        or None if no subscriptions are enabled

    Example:
        >>> subscription_type = compose_subscription()
        >>> schema = strawberry.Schema(subscription=subscription_type)
    """
    registry = get_feature_registry()
    features = get_graphql_features()

    # Collect all enabled subscription resolvers
    subscription_methods: dict[str, Any] = {}

    for feature_name, feature in registry._features.items():
        if not features.is_enabled(feature_name) or not feature.enabled:
            continue

        # Add all subscription resolvers from this feature
        for resolver in feature.subscriptions:
            # Handle both raw functions and StrawberryField objects
            if hasattr(resolver, "python_name"):
                # Already a StrawberryField/StrawberrySubscription object
                field_name = resolver.python_name
                field_obj = resolver
            elif hasattr(resolver, "__name__"):
                # Raw function - needs to be wrapped
                field_name = resolver.__name__
                field_obj = strawberry.subscription(resolver)
            else:
                logger.warning(
                    f"Skipping resolver from feature '{feature_name}': "
                    f"Cannot determine name for {resolver}",
                )
                continue

            # Remove common suffixes for cleaner API
            field_name = field_name.replace("_subscription", "").replace(
                "_resolver", "",
            )

            if field_name in subscription_methods:
                logger.warning(
                    f"Duplicate subscription field '{field_name}' from feature '{feature_name}'. "
                    "Using first definition.",
                )
                continue

            subscription_methods[field_name] = field_obj

        logger.debug(
            f"Added {len(feature.subscriptions)} subscriptions from feature '{feature_name}'",
        )

    # If no subscriptions, return None (subscriptions are optional)
    if not subscription_methods:
        logger.info("No subscriptions enabled")
        return None

    # Dynamically create Subscription type
    Subscription = type(
        "Subscription",
        (),
        {
            **subscription_methods,
            "__annotations__": {
                name: getattr(resolver, "__annotations__", {}).get("return", str)
                for name, resolver in subscription_methods.items()
            },
        },
    )

    # Apply Strawberry type decorator
    Subscription = strawberry.type(Subscription, description="Root subscription type")

    enabled_features = [
        name
        for name, f in registry._features.items()
        if features.is_enabled(name) and f.enabled and f.subscriptions
    ]
    logger.info(
        f"Composed Subscription type with {len(subscription_methods)} fields "
        f"from {len(enabled_features)} features: {', '.join(enabled_features)}",
    )

    return Subscription
