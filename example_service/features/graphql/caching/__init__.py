"""Multi-tier caching infrastructure for GraphQL operations.

Provides three levels of caching for optimal performance:
1. Query-level caching (Redis) - Cache entire query results
2. Field-level caching (Redis) - Cache expensive computed fields
3. CDN caching (HTTP headers) - Cache public queries at the edge

Usage:
    # Query-level caching
    from example_service.features.graphql.caching import QueryCacheExtension

    extensions = [
        QueryCacheExtension(ttl=300),  # 5 minute cache
    ]

    # Field-level caching
    from example_service.features.graphql.caching import cached_field

    @strawberry.field
    @cached_field(ttl=3600)
    def expensive_field(self) -> int:
        return expensive_calculation()

    # CDN caching
    from example_service.features.graphql.caching import set_cache_headers

    set_cache_headers(response, max_age=300, public=True)
"""

from __future__ import annotations

from example_service.features.graphql.caching.cdn_headers import (
    get_cache_control_header,
    set_cache_headers,
    set_no_cache_headers,
)
from example_service.features.graphql.caching.field_cache import (
    cache_key,
    cached_field,
    invalidate_field_cache,
)
from example_service.features.graphql.caching.query_cache import (
    CacheConfig,
    QueryCacheExtension,
)

__all__ = [
    "CacheConfig",
    # Query-level caching
    "QueryCacheExtension",
    "cache_key",
    # Field-level caching
    "cached_field",
    "get_cache_control_header",
    "invalidate_field_cache",
    # CDN caching
    "set_cache_headers",
    "set_no_cache_headers",
]
