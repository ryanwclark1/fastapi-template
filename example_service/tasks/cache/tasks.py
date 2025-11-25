"""Cache warming and management task definitions.

This module provides:
- Pre-population of Redis cache with frequently accessed data
- Cache invalidation utilities
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import func, select

from example_service.core.settings import get_app_settings
from example_service.infra.cache.redis import get_cache
from example_service.infra.database.session import get_async_session
from example_service.tasks.broker import broker

logger = logging.getLogger(__name__)


if broker is not None:

    @broker.task()
    async def warm_cache() -> dict:
        """Pre-populate Redis cache with frequently accessed data.

        Scheduled: On startup + every 30 minutes.

        Caches:
        - Application settings
        - Database statistics
        - Frequently accessed aggregates

        Returns:
            Dictionary with list of warmed cache keys.

        Example:
                    from example_service.tasks.cache import warm_cache
            task = await warm_cache.kiq()
            result = await task.wait_result()
            print(result)
            # {'status': 'success', 'keys_warmed': ['app:settings', 'stats:active_reminders']}
        """
        cache = get_cache()
        if cache is None:
            logger.warning("Redis cache not available, skipping cache warming")
            return {"status": "skipped", "reason": "cache_not_available"}

        warmed_keys = []
        errors = []

        # Cache application info
        try:
            app_settings = get_app_settings()
            app_info = {
                "service_name": app_settings.service_name,
                "environment": app_settings.environment,
                "version": app_settings.version,
                "warmed_at": datetime.now(UTC).isoformat(),
            }
            await cache.set("app:info", app_info, ttl=3600)
            warmed_keys.append("app:info")
        except Exception as e:
            logger.warning(f"Failed to cache app info: {e}")
            errors.append({"key": "app:info", "error": str(e)})

        # Cache database statistics
        try:
            from example_service.features.reminders.models import Reminder

            async with get_async_session() as session:
                # Count active (incomplete) reminders
                stmt = (
                    select(func.count()).select_from(Reminder).where(Reminder.is_completed == False)  # noqa: E712
                )
                result = await session.execute(stmt)
                active_count = result.scalar() or 0

                # Count total reminders
                total_stmt = select(func.count()).select_from(Reminder)
                total_result = await session.execute(total_stmt)
                total_count = total_result.scalar() or 0

                # Count due reminders
                now = datetime.now(UTC)
                due_stmt = (
                    select(func.count())
                    .select_from(Reminder)
                    .where(
                        Reminder.remind_at <= now,
                        Reminder.is_completed == False,  # noqa: E712
                    )
                )
                due_result = await session.execute(due_stmt)
                due_count = due_result.scalar() or 0

            stats = {
                "active_reminders": active_count,
                "total_reminders": total_count,
                "due_reminders": due_count,
                "updated_at": datetime.now(UTC).isoformat(),
            }
            await cache.set("stats:reminders", stats, ttl=300)  # 5 min TTL
            warmed_keys.append("stats:reminders")

        except Exception as e:
            logger.warning(f"Failed to cache reminder stats: {e}")
            errors.append({"key": "stats:reminders", "error": str(e)})

        result = {
            "status": "success" if not errors else "partial",
            "keys_warmed": warmed_keys,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        if errors:
            result["errors"] = errors

        logger.info(
            "Cache warming completed",
            extra=result,
        )

        return result

    @broker.task()
    async def invalidate_cache_pattern(pattern: str) -> dict:
        """Invalidate cache keys matching a pattern.

        Called after data mutations that affect cached data.

        Args:
            pattern: Redis key pattern to match (e.g., "stats:*").

        Returns:
            Dictionary with pattern and count of deleted keys.

        Example:
                    from example_service.tasks.cache import invalidate_cache_pattern
            # Invalidate all stats cache
            task = await invalidate_cache_pattern.kiq(pattern="stats:*")
            result = await task.wait_result()
            print(result)
            # {'pattern': 'stats:*', 'deleted_count': 3}
        """
        cache = get_cache()
        if cache is None:
            logger.warning("Redis cache not available, skipping invalidation")
            return {"status": "skipped", "reason": "cache_not_available", "pattern": pattern}

        try:
            # Use SCAN to find matching keys (safe for production)
            deleted_count = await cache.delete_pattern(pattern)

            logger.info(
                "Cache invalidation completed",
                extra={"pattern": pattern, "deleted_count": deleted_count},
            )

            return {
                "status": "success",
                "pattern": pattern,
                "deleted_count": deleted_count,
            }
        except Exception as e:
            logger.exception(
                "Cache invalidation failed",
                extra={"pattern": pattern, "error": str(e)},
            )
            return {
                "status": "error",
                "pattern": pattern,
                "error": str(e),
            }

    @broker.task()
    async def get_cached_stats() -> dict:
        """Get cached statistics or compute if not cached.

        Returns:
            Dictionary with reminder statistics.
        """
        cache = get_cache()
        if cache is None:
            return {"status": "cache_unavailable"}

        # Try to get from cache first
        cached = await cache.get("stats:reminders")
        if cached:
            return {"status": "cached", "data": cached}

        # If not cached, trigger warming and return empty
        await warm_cache.kiq()
        return {"status": "warming_triggered", "data": None}
