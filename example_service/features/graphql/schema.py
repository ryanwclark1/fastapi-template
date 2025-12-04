"""GraphQL schema assembly.

Combines Query, Mutation, and Subscription types into a single schema
with configured extensions.

The schema is dynamically composed from registered features based on
the feature configuration, making it easy to enable/disable features.

To configure features, see:
    example_service.features.graphql.config.GraphQLFeatures
"""

from __future__ import annotations

import logging

import strawberry

# Import from extensions module (not the package)
import example_service.features.graphql.extensions as ext_module
from example_service.features.graphql.resolvers.feature_registry import (
    register_all_features,
)
from example_service.features.graphql.schema_composer import (
    compose_mutation,
    compose_query,
    compose_subscription,
)

logger = logging.getLogger(__name__)

# Register all features before composing schema
register_all_features()

# Compose schema dynamically from enabled features
Query = compose_query()
Mutation = compose_mutation()
Subscription = compose_subscription()

# Create the schema with all root types and extensions
schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    subscription=Subscription,
    extensions=ext_module.get_extensions(),
)

logger.info("GraphQL schema created successfully")

__all__ = ["schema"]
