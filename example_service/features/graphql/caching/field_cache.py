"""Field-level caching utilities for expensive computed fields.

Provides decorators and utilities for caching individual field resolver results.
Useful for expensive computed fields that don't change frequently.

Usage:
    from example_service.features.graphql.caching.field_cache import cached_field

    @strawberry.type
    class ReminderType:
        @strawberry.field
        @cached_field(ttl=3600, key_func=lambda self: f"reminder:{self.id}:expensive_calc")
        def expensive_calculation(self) -> int:
            # Expensive operation here
            return calculate_something_expensive(self.id)
"""

from __future__ import annotations

import functools
import hashlib
import logging
from typing import TYPE_CHECKING, Any

from example_service.infra.cache import get_cache_instance

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

__all__ = ["cache_key", "cached_field", "invalidate_field_cache"]


def cache_key(*args: Any, prefix: str = "field") -> str:
    """Generate a cache key from arguments.

    Args:
        *args: Arguments to include in cache key
        prefix: Key prefix (default: "field")

    Returns:
        Cache key string
    """
    # Serialize arguments
    key_parts = [str(arg) for arg in args]
    key_str = ":".join(key_parts)

    # Hash for consistent length
    key_hash = hashlib.sha256(key_str.encode()).hexdigest()[:16]

    return f"{prefix}:{key_hash}"


def cached_field(
    ttl: int = 300,
    key_func: Callable[[Any], str] | None = None,
    skip_if: Callable[[Any], bool] | None = None,
) -> Callable:
    """Decorator for caching field resolver results.

    Caches the result of expensive field resolvers in Redis.

    Args:
        ttl: Cache TTL in seconds (default: 300 = 5 minutes)
        key_func: Function to generate cache key from self (default: uses object ID)
        skip_if: Optional function to skip caching based on conditions

    Returns:
        Decorated resolver function

    Example:
        @strawberry.type
        class ReminderType:
            @strawberry.field
            @cached_field(ttl=3600, key_func=lambda self: f"reminder:{self.id}:tags_count")
            def tags_count(self) -> int:
                # Expensive count operation
                return len(self.tags)

    Example with conditional caching:
        @strawberry.field
        @cached_field(
            ttl=3600,
            key_func=lambda self: f"reminder:{self.id}:formatted",
            skip_if=lambda self: self.is_completed,  # Don't cache completed reminders
        )
        def formatted_description(self) -> str:
            return format_markdown(self.description)
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            # Get cache instance
            cache = get_cache_instance()
            if not cache:
                # No cache configured, call function directly
                return func(self, *args, **kwargs)

            # Check if we should skip caching
            if skip_if and skip_if(self):
                return func(self, *args, **kwargs)

            # Generate cache key
            if key_func:
                cache_key_str = key_func(self)
            else:
                # Default: use object ID if available
                obj_id = getattr(self, "id", None)
                if obj_id:
                    cache_key_str = f"field:{func.__name__}:{obj_id}"
                else:
                    # No ID available, can't cache
                    return func(self, *args, **kwargs)

            try:
                # Try to get cached result
                import asyncio

                if asyncio.iscoroutinefunction(cache.get):
                    # Async cache - need to handle async
                    # For now, skip caching for async cache in sync resolvers
                    logger.debug("Async cache not supported in sync field resolvers")
                    return func(self, *args, **kwargs)
                # Sync cache
                cached_result = cache.get(cache_key_str)
                if cached_result is not None:
                    logger.debug(
                        "Field cache hit",
                        extra={
                            "cache_key": cache_key_str,
                            "field": func.__name__,
                        },
                    )
                    # Deserialize result
                    import json

                    return json.loads(cached_result)

                # Cache miss - call function and cache result
                result = func(self, *args, **kwargs)

                # Serialize and cache result
                import json

                cache_value = json.dumps(result)
                cache.set(cache_key_str, cache_value, ttl=ttl)

                logger.debug(
                    "Field cached",
                    extra={
                        "cache_key": cache_key_str,
                        "field": func.__name__,
                        "ttl": ttl,
                    },
                )

                return result

            except Exception as e:
                # Don't fail the field resolution if caching has issues
                logger.exception(
                    "Field cache error",
                    extra={
                        "error": str(e),
                        "field": func.__name__,
                    },
                )
                return func(self, *args, **kwargs)

        return wrapper

    return decorator


def invalidate_field_cache(cache_key: str) -> None:
    """Invalidate a field cache entry.

    Args:
        cache_key: Cache key to invalidate

    Example:
        # After updating a reminder, invalidate its cached fields
        invalidate_field_cache(f"reminder:{reminder_id}:tags_count")
        invalidate_field_cache(f"reminder:{reminder_id}:formatted")
    """
    cache = get_cache_instance()
    if cache:
        try:
            cache.delete(cache_key)
            logger.debug("Field cache invalidated", extra={"cache_key": cache_key})
        except Exception as e:
            logger.exception(
                "Field cache invalidation failed",
                extra={"error": str(e), "cache_key": cache_key},
            )


# ============================================================================
# Usage Examples
# ============================================================================

"""
Example: Basic field caching
    @strawberry.type
    class ReminderType:
        id: strawberry.ID
        title: str

        @strawberry.field
        @cached_field(ttl=3600, key_func=lambda self: f"reminder:{self.id}:tags_count")
        def tags_count(self) -> int:
            # This will be cached for 1 hour
            return len(self.tags)

Example: Conditional caching
    @strawberry.type
    class FileType:
        id: strawberry.ID
        status: str

        @strawberry.field
        @cached_field(
            ttl=1800,
            key_func=lambda self: f"file:{self.id}:thumbnail_url",
            skip_if=lambda self: self.status != "ready",  # Only cache ready files
        )
        def thumbnail_url(self) -> str | None:
            return generate_thumbnail_url(self.id)

Example: Cache invalidation after mutation
    @strawberry.mutation
    async def update_reminder(
        self,
        info: Info,
        id: strawberry.ID,
        input: UpdateReminderInput,
    ) -> ReminderPayload:
        # Update reminder...

        # Invalidate cached fields
        from example_service.features.graphql.caching.field_cache import invalidate_field_cache

        invalidate_field_cache(f"reminder:{id}:tags_count")
        invalidate_field_cache(f"reminder:{id}:formatted")

        return ReminderSuccess(reminder=updated_reminder)

Example: Complex expensive calculation
    @strawberry.type
    class AnalyticsType:
        @strawberry.field
        @cached_field(
            ttl=7200,  # Cache for 2 hours
            key_func=lambda self: f"analytics:{self.user_id}:engagement_score"
        )
        def engagement_score(self) -> float:
            # Very expensive calculation involving multiple database queries
            # and complex algorithms
            score = calculate_engagement_score(self.user_id)
            return score

Note: Field-level caching works best for:
- Expensive computed fields (complex calculations)
- Fields that don't change frequently
- Fields that are accessed often
- Read-heavy workloads

Avoid field-level caching for:
- Simple fields (direct attribute access)
- Fields that change frequently
- User-specific data that varies by request
- Fields with side effects
"""
