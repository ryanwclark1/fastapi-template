"""CDN cache header utilities for public GraphQL queries.

Provides utilities for setting appropriate Cache-Control headers for public queries
that can be cached by CDNs and browser caches.

Usage:
    from example_service.features.graphql.caching.cdn_headers import set_cache_headers

    # In your GraphQL router/endpoint
    @app.post("/graphql")
    async def graphql_endpoint(request: Request, response: Response):
        result = await schema.execute(...)

        # Set cache headers for public queries
        set_cache_headers(response, max_age=300, public=True)

        return result
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.responses import Response

logger = logging.getLogger(__name__)

__all__ = [
    "get_cache_control_header",
    "set_cache_headers",
    "set_no_cache_headers",
]


def set_cache_headers(
    response: Response,
    max_age: int = 300,
    public: bool = True,
    stale_while_revalidate: int | None = None,
    stale_if_error: int | None = None,
) -> None:
    """Set Cache-Control headers for CDN/browser caching.

    Args:
        response: Starlette Response object
        max_age: Maximum age in seconds (default: 300 = 5 minutes)
        public: Whether cache is public (CDN can cache) or private (browser only)
        stale_while_revalidate: Seconds to serve stale content while revalidating
        stale_if_error: Seconds to serve stale content if origin is down

    Example:
        # Public query cacheable by CDN for 5 minutes
        set_cache_headers(response, max_age=300, public=True)

        # Private query cacheable only by browser for 1 minute
        set_cache_headers(response, max_age=60, public=False)

        # Public with stale-while-revalidate
        set_cache_headers(
            response,
            max_age=300,
            public=True,
            stale_while_revalidate=600,  # Serve stale for 10 minutes while fetching new
            stale_if_error=86400,  # Serve stale for 24 hours if origin is down
        )
    """
    cache_control = get_cache_control_header(
        max_age=max_age,
        public=public,
        stale_while_revalidate=stale_while_revalidate,
        stale_if_error=stale_if_error,
    )

    response.headers["Cache-Control"] = cache_control
    logger.debug(
        "Set cache headers",
        extra={"cache_control": cache_control},
    )


def set_no_cache_headers(response: Response) -> None:
    """Set headers to prevent any caching.

    Use for:
    - Mutations (data modification)
    - Authenticated user-specific queries
    - Sensitive data

    Args:
        response: Starlette Response object

    Example:
        # Mutation - never cache
        set_no_cache_headers(response)
    """
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"

    logger.debug("Set no-cache headers")


def get_cache_control_header(
    max_age: int,
    public: bool = True,
    stale_while_revalidate: int | None = None,
    stale_if_error: int | None = None,
) -> str:
    """Generate Cache-Control header value.

    Args:
        max_age: Maximum age in seconds
        public: Whether cache is public or private
        stale_while_revalidate: Seconds to serve stale content while revalidating
        stale_if_error: Seconds to serve stale content if origin is down

    Returns:
        Cache-Control header value

    Example:
        header = get_cache_control_header(max_age=300, public=True)
        # Returns: "public, max-age=300"
    """
    parts = []

    # Public/private
    if public:
        parts.append("public")
    else:
        parts.append("private")

    # Max age
    parts.append(f"max-age={max_age}")

    # Stale-while-revalidate (serve stale while fetching fresh)
    if stale_while_revalidate:
        parts.append(f"stale-while-revalidate={stale_while_revalidate}")

    # Stale-if-error (serve stale if origin is down)
    if stale_if_error:
        parts.append(f"stale-if-error={stale_if_error}")

    return ", ".join(parts)


# ============================================================================
# Usage Examples and Patterns
# ============================================================================

"""
Example: Basic usage in GraphQL endpoint
    from fastapi import FastAPI, Response
    from strawberry.fastapi import GraphQLRouter

    from example_service.features.graphql.caching.cdn_headers import (
        set_cache_headers,
        set_no_cache_headers,
    )
    from example_service.features.graphql.schema import schema

    app = FastAPI()

    async def custom_context_getter(request: Request, response: Response):
        # Create context...

        # Determine if query is cacheable
        # (This is simplified - in practice you'd parse the query)
        operation_type = get_operation_type(request)

        if operation_type == "query":
            # Public query - cache for 5 minutes
            set_cache_headers(response, max_age=300, public=True)
        else:
            # Mutation/subscription - no cache
            set_no_cache_headers(response)

        return context

    graphql_router = GraphQLRouter(
        schema,
        context_getter=custom_context_getter,
    )

    app.include_router(graphql_router, prefix="/graphql")

Example: Conditional caching based on authentication
    async def context_getter(request: Request, response: Response):
        user = get_authenticated_user(request)
        context = create_context(user)

        # Only cache public (unauthenticated) queries
        if not user:
            set_cache_headers(response, max_age=300, public=True)
        else:
            # User-specific data - private cache only
            set_cache_headers(response, max_age=60, public=False)

        return context

Example: Different TTLs for different query types
    async def context_getter(request: Request, response: Response):
        operation_name = get_operation_name(request)

        cache_ttls = {
            "GetReminder": 300,  # 5 minutes
            "ListReminders": 180,  # 3 minutes
            "SearchReminders": 60,  # 1 minute (search results change frequently)
            "GetFeatureFlags": 3600,  # 1 hour (flags don't change often)
        }

        ttl = cache_ttls.get(operation_name, 300)  # Default 5 minutes
        set_cache_headers(response, max_age=ttl, public=True)

        return context

Example: Stale-while-revalidate pattern
    # Serve stale content for 10 minutes while fetching fresh data
    # This provides instant responses even if cache is expired
    set_cache_headers(
        response,
        max_age=300,  # Fresh for 5 minutes
        public=True,
        stale_while_revalidate=600,  # Serve stale for 10 more minutes while revalidating
        stale_if_error=86400,  # Serve stale for 24 hours if origin is down
    )

Example: CDN configuration (Cloudflare/Fastly/CloudFront)
    # Most CDNs respect Cache-Control headers automatically
    # But you can add CDN-specific headers for more control:

    def set_cdn_cache_headers(response: Response, ttl: int):
        # Standard Cache-Control
        set_cache_headers(response, max_age=ttl, public=True)

        # Cloudflare-specific (optional)
        response.headers["CDN-Cache-Control"] = f"max-age={ttl}"

        # Fastly-specific (optional)
        response.headers["Surrogate-Control"] = f"max-age={ttl}"

        # AWS CloudFront (respects Cache-Control)
        # No additional headers needed

Example: Vary header for content negotiation
    # Use Vary header to cache different versions based on headers
    def set_cache_with_vary(response: Response):
        set_cache_headers(response, max_age=300, public=True)

        # Cache different versions for different accept headers
        response.headers["Vary"] = "Accept, Accept-Encoding"

        # This ensures CDN caches separate versions for:
        # - application/json vs application/graphql+json
        # - gzip vs br compression

Best Practices:
1. Never cache mutations (always set no-cache)
2. Use shorter TTLs for frequently changing data
3. Use longer TTLs for static/reference data
4. Consider user authentication when setting public/private
5. Use stale-while-revalidate for better UX
6. Monitor cache hit rates
7. Implement cache invalidation strategies

Cache Invalidation Strategies:
1. Time-based (TTL) - automatic expiration
2. Event-based - invalidate on data changes
3. Purge API - manual cache clearing via CDN API
4. Cache tags - group-based invalidation

Security Considerations:
1. Never cache sensitive user data with public
2. Always use private for authenticated requests
3. Be careful with CORS and Vary headers
4. Consider cache poisoning attacks
5. Validate query complexity before caching

Performance Tips:
1. Use CDN edge locations close to users
2. Enable HTTP/2 or HTTP/3
3. Use compression (gzip/br)
4. Monitor cache hit ratio
5. Tune TTLs based on actual usage patterns
"""
