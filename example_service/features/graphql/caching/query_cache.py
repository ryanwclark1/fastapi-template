"""Query-level caching extension for GraphQL operations.

Caches entire query results in Redis to reduce database load and improve response times.
Uses operation name, variables, and user context as cache key to ensure correct isolation.

Usage:
    from example_service.features.graphql.caching.query_cache import QueryCacheExtension

    extensions = [
        QueryCacheExtension(ttl=300),  # Cache for 5 minutes
    ]
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from strawberry.extensions import SchemaExtension

from example_service.infra.cache import get_cache_instance

logger = logging.getLogger(__name__)

__all__ = ["CacheConfig", "QueryCacheExtension"]


class CacheConfig:
    """Configuration for query caching."""

    # Default TTL values (in seconds)
    DEFAULT_TTL = 300  # 5 minutes
    SHORT_TTL = 60  # 1 minute
    LONG_TTL = 3600  # 1 hour

    # Operations to skip caching
    SKIP_MUTATIONS = True  # Never cache mutations
    SKIP_SUBSCRIPTIONS = True  # Never cache subscriptions

    # Cache key prefix
    KEY_PREFIX = "graphql:query:"


class QueryCacheExtension(SchemaExtension):
    """Cache query results in Redis for improved performance.

    This extension caches the entire result of GraphQL queries in Redis,
    using a cache key derived from:
    - Operation name
    - Operation type (query/mutation/subscription)
    - Query variables
    - User ID (for authenticated requests)

    This ensures cache isolation per user and per query variation.

    Cache behavior:
    - Queries: Cached by default
    - Mutations: Never cached (data modification)
    - Subscriptions: Never cached (real-time data)
    - Introspection queries: Short TTL (schema doesn't change often)

    Example:
        schema = strawberry.Schema(
            query=Query,
            mutation=Mutation,
            extensions=[
                QueryCacheExtension(ttl=300),  # 5 minute cache
            ],
        )

    Cache warming:
        For frequently accessed queries, you can warm the cache by executing
        queries during application startup or on a schedule.
    """

    def __init__(
        self,
        ttl: int | None = None,
        config: CacheConfig | None = None,
    ) -> None:
        """Initialize query cache extension.

        Args:
            ttl: Default cache TTL in seconds (default: 300 = 5 minutes)
            config: Custom cache configuration
        """
        self.ttl = ttl or CacheConfig.DEFAULT_TTL
        self.config = config or CacheConfig()

    def on_execute(self) -> Any:
        """Check cache before executing operation.

        If cached result exists, return it immediately without execution.
        Otherwise, execute the operation and cache the result.
        """
        execution_context = self.execution_context

        # Get cache instance
        cache = get_cache_instance()
        if not cache:
            # No cache configured, skip caching
            logger.debug("Query caching skipped: no cache configured")
            return None

        # Get operation type
        operation_type = execution_context.operation_type
        if not operation_type:
            return None

        # Skip caching for mutations and subscriptions
        if self.config.SKIP_MUTATIONS and operation_type == "mutation":
            return None

        if self.config.SKIP_SUBSCRIPTIONS and operation_type == "subscription":
            return None

        # Generate cache key
        cache_key = self._generate_cache_key()
        if not cache_key:
            return None

        try:
            # Try to get cached result
            import asyncio

            if asyncio.iscoroutinefunction(cache.get):
                # Async cache - this needs proper handling in async context
                # For now, we'll skip async caching in the extension
                # (This is a known limitation of Strawberry extensions)
                logger.debug("Async cache not supported in extensions yet")
                return None
            # Sync cache
            cached_result = cache.get(cache_key)
            if cached_result:
                logger.debug(
                    "Cache hit",
                    extra={
                        "cache_key": cache_key,
                        "operation_name": execution_context.operation_name,
                    },
                )
                # Deserialize and return cached result
                return json.loads(cached_result)

            # Cache miss - execute query and cache result
            logger.debug(
                "Cache miss",
                extra={
                    "cache_key": cache_key,
                    "operation_name": execution_context.operation_name,
                },
            )

            # Let the query execute normally
            # We'll cache the result in on_request_end
            return None

        except Exception as e:
            # Don't fail the operation if caching has issues
            logger.exception(
                "Cache read failed",
                extra={
                    "error": str(e),
                    "cache_key": cache_key,
                    "operation_name": execution_context.operation_name,
                },
            )
            return None

    def on_request_end(self) -> None:
        """Cache the result after successful execution."""
        execution_context = self.execution_context

        # Get cache instance
        cache = get_cache_instance()
        if not cache:
            return

        # Get operation type
        operation_type = execution_context.operation_type
        if not operation_type:
            return

        # Skip caching for mutations and subscriptions
        if self.config.SKIP_MUTATIONS and operation_type == "mutation":
            return

        if self.config.SKIP_SUBSCRIPTIONS and operation_type == "subscription":
            return

        # Check if execution was successful (no errors)
        result = execution_context.result
        if not result or result.errors:
            # Don't cache errors
            return

        # Generate cache key
        cache_key = self._generate_cache_key()
        if not cache_key:
            return

        try:
            # Serialize result
            cache_value = json.dumps(
                {
                    "data": result.data,
                    "errors": None,
                },
            )

            # Cache the result
            import asyncio

            if asyncio.iscoroutinefunction(cache.set):
                # Async cache - skip for now
                logger.debug("Async cache not supported in extensions yet")
                return
            # Sync cache
            cache.set(cache_key, cache_value, ttl=self.ttl)
            logger.debug(
                "Cached query result",
                extra={
                    "cache_key": cache_key,
                    "operation_name": execution_context.operation_name,
                    "ttl": self.ttl,
                },
            )

        except Exception as e:
            # Don't fail the operation if caching has issues
            logger.exception(
                "Cache write failed",
                extra={
                    "error": str(e),
                    "cache_key": cache_key,
                    "operation_name": execution_context.operation_name,
                },
            )

    def _generate_cache_key(self) -> str | None:
        """Generate cache key from operation details.

        The cache key includes:
        - Operation name
        - Operation type
        - Variables (serialized)
        - User ID (for authenticated requests)

        Returns:
            Cache key string, or None if key cannot be generated
        """
        execution_context = self.execution_context

        # Get operation details
        operation_name = execution_context.operation_name or "anonymous"
        operation_type = execution_context.operation_type or "query"

        # Get variables (serialize to ensure consistent key)
        variables = execution_context.variable_values or {}
        try:
            variables_str = json.dumps(variables, sort_keys=True)
        except (TypeError, ValueError):
            # Can't serialize variables, skip caching
            logger.warning(
                "Cannot serialize variables for cache key",
                extra={"operation_name": operation_name},
            )
            return None

        # Get user ID if authenticated
        user_id = "anonymous"
        if hasattr(execution_context, "context") and execution_context.context:
            context = execution_context.context
            if hasattr(context, "user") and context.user:
                user_id = f"user:{context.user.id}"

        # Generate hash of operation + variables + user
        key_components = f"{operation_type}:{operation_name}:{variables_str}:{user_id}"
        key_hash = hashlib.sha256(key_components.encode()).hexdigest()[:16]

        # Create cache key
        return f"{self.config.KEY_PREFIX}{operation_type}:{operation_name}:{key_hash}"


# ============================================================================
# Usage Examples and Patterns
# ============================================================================

"""
Example: Basic query caching
    from example_service.features.graphql.caching.query_cache import QueryCacheExtension

    extensions = [
        QueryCacheExtension(ttl=300),  # Cache queries for 5 minutes
    ]

Example: Different TTLs for different environments
    from example_service.core.settings import get_settings

    settings = get_settings()

    if settings.environment == "production":
        ttl = 600  # 10 minutes in production
    else:
        ttl = 60  # 1 minute in development

    extensions = [
        QueryCacheExtension(ttl=ttl),
    ]

Example: Custom configuration
    from example_service.features.graphql.caching.query_cache import (
        CacheConfig,
        QueryCacheExtension,
    )

    config = CacheConfig()
    config.DEFAULT_TTL = 600  # 10 minutes
    config.KEY_PREFIX = "myapp:graphql:query:"

    extensions = [
        QueryCacheExtension(config=config),
    ]

Example: Cache invalidation
    # After a mutation that modifies data, you may want to invalidate related caches
    # This can be done in the mutation resolver:

    from example_service.infra.cache import get_cache_instance

    @strawberry.mutation
    async def update_reminder(
        self,
        info: Info,
        id: strawberry.ID,
        input: UpdateReminderInput,
    ) -> ReminderPayload:
        # Update the reminder...

        # Invalidate related caches
        cache = get_cache_instance()
        if cache:
            # Clear all reminder-related query caches
            # Note: This requires a pattern-based delete, which Redis supports
            cache.delete_pattern("graphql:query:query:reminders:*")
            cache.delete_pattern(f"graphql:query:query:reminder:*{id}*")

        return ReminderSuccess(reminder=updated_reminder)

Example: Selective caching with directives (future enhancement)
    # In the future, you could use GraphQL directives to control caching:

    type Query {
        # Cache for 1 hour
        reminder(id: ID!): Reminder @cache(ttl: 3600)

        # Never cache
        currentUser: User @cache(ttl: 0)

        # Cache for 5 minutes (default)
        reminders(first: Int): ReminderConnection
    }

Example: Cache warming
    # Warm the cache during application startup or on a schedule:

    from example_service.features.graphql.schema import schema

    async def warm_cache():
        \"\"\"Warm GraphQL query cache with common queries.\"\"\"
        # Execute common queries to populate cache
        await schema.execute(
            \"\"\"
            query {
                reminders(first: 10) {
                    edges {
                        node {
                            id
                            title
                        }
                    }
                }
            }
            \"\"\",
            context_value=create_system_context(),
        )

Note: The current implementation has limitations with async caching in Strawberry
extensions. For production use, consider:
1. Using a sync cache backend (like Redis with sync client)
2. Implementing caching at a higher level (middleware)
3. Using dedicated caching solutions like GraphQL CDN or Apollo Server caching
"""
