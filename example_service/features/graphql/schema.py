"""GraphQL schema assembly.

Combines Query, Mutation, and Subscription types into a single schema
with configured extensions.
"""

from __future__ import annotations

import strawberry

from example_service.features.graphql.extensions import get_extensions
from example_service.features.graphql.resolvers.mutations import Mutation
from example_service.features.graphql.resolvers.queries import Query
from example_service.features.graphql.resolvers.subscriptions import Subscription

# Create the schema with all root types and extensions
schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    subscription=Subscription,
    extensions=get_extensions(),
)

__all__ = ["schema"]
