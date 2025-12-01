"""GraphQL feature module using Strawberry.

This module provides a GraphQL API endpoint at /graphql with:
- Query resolvers for reminders
- Mutation resolvers with union error types
- WebSocket subscriptions for real-time updates
- Relay-compliant cursor pagination
- Authentication via existing auth dependencies
"""

from __future__ import annotations

from typing import Any

__all__ = ["router", "schema"]


def __getattr__(name: str) -> Any:
    if name == "router":
        from example_service.features.graphql.router import router as graphql_router

        return graphql_router
    if name == "schema":
        from example_service.features.graphql.schema import schema as graphql_schema

        return graphql_schema
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
