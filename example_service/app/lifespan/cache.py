"""Redis cache lifespan management."""

from __future__ import annotations

import logging

from example_service.infra.cache.redis import start_cache, stop_cache

from .registry import lifespan_registry

logger = logging.getLogger(__name__)


@lifespan_registry.register(
    name="cache",
    startup_order=15,
    requires=["core"],
)
async def startup_cache(
    redis_settings: object,
    auth_settings: object,
    mock_settings: object,
    **kwargs: object,
) -> None:
    """Initialize Redis cache and rate limiting.

    Skips initialization in mock mode.

    Args:
        redis_settings: Redis settings
        auth_settings: Auth settings (for health provider registration)
        mock_settings: Mock mode settings
        **kwargs: Additional settings (ignored)
    """
    from example_service.core.settings.auth import AuthSettings
    from example_service.core.settings.mock import MockModeSettings
    from example_service.core.settings.redis import RedisSettings

    redis = (
        RedisSettings.model_validate(redis_settings)
        if not isinstance(redis_settings, RedisSettings)
        else redis_settings
    )
    auth = (
        AuthSettings.model_validate(auth_settings)
        if not isinstance(auth_settings, AuthSettings)
        else auth_settings
    )
    mock = (
        MockModeSettings.model_validate(mock_settings)
        if not isinstance(mock_settings, MockModeSettings)
        else mock_settings
    )

    # Skip Redis initialization in mock mode (not needed for UI development)
    if redis.is_configured and not mock.enabled:
        try:
            await start_cache()
            logger.info("Redis cache initialized")

            # Initialize rate limit state tracker for protection observability
            try:
                from example_service.infra.ratelimit import (
                    RateLimitStateTracker,
                    set_rate_limit_tracker,
                )

                rate_limit_tracker = RateLimitStateTracker(
                    failure_threshold=redis.rate_limit_failure_threshold,
                )
                set_rate_limit_tracker(rate_limit_tracker)
                logger.info(
                    "Rate limit state tracker initialized",
                    extra={"failure_threshold": redis.rate_limit_failure_threshold},
                )

                # Register rate limiter health provider with aggregator
                from example_service.features.health.providers import (
                    RateLimiterHealthProvider,
                )
                from example_service.features.health.service import (
                    get_health_aggregator,
                )

                aggregator = get_health_aggregator()
                if aggregator:
                    aggregator.add_provider(
                        RateLimiterHealthProvider(rate_limit_tracker)
                    )
                    logger.info("Rate limiter health provider registered")

                # Register Accent-Auth health provider (optional, never blocks startup)
                if auth.health_checks_enabled and auth.service_url:
                    try:
                        from example_service.features.health.providers import (
                            AccentAuthHealthProvider,
                        )

                        aggregator = get_health_aggregator()
                        if aggregator:
                            aggregator.add_provider(AccentAuthHealthProvider())
                            logger.info(
                                "Accent-Auth health provider registered",
                                extra={"auth_url": str(auth.service_url)},
                            )
                    except Exception as e:
                        logger.warning(
                            "Failed to register Accent-Auth health provider",
                            extra={"error": str(e)},
                        )
            except Exception as e:
                logger.warning(
                    "Failed to initialize rate limit state tracker",
                    extra={"error": str(e)},
                )
        except Exception as e:
            if redis.startup_require_cache:
                logger.error(
                    "Redis cache required but unavailable, failing startup",
                    extra={"error": str(e), "startup_require_cache": True},
                )
                raise
            logger.warning(
                "Redis cache unavailable, continuing in degraded mode",
                extra={"error": str(e), "startup_require_cache": False},
            )
            # Mark rate limiter as disabled when Redis is unavailable
            try:
                from example_service.infra.ratelimit import (
                    RateLimitStateTracker,
                    set_rate_limit_tracker,
                )

                tracker = RateLimitStateTracker()
                tracker.mark_disabled()
                set_rate_limit_tracker(tracker)
            except Exception as e:
                logger.debug("Failed to initialize rate limit tracker", exc_info=e)
    elif mock.enabled:
        logger.info(
            "Redis cache initialization skipped in mock mode",
            extra={"mock_mode": True, "persona": mock.persona},
        )


@lifespan_registry.register(name="cache")
async def shutdown_cache(
    redis_settings: object,
    mock_settings: object,
    **kwargs: object,
) -> None:
    """Close Redis cache.

    Skips shutdown in mock mode since it wasn't initialized.

    Args:
        redis_settings: Redis settings
        mock_settings: Mock mode settings
        **kwargs: Additional settings (ignored)
    """
    from example_service.core.settings.mock import MockModeSettings
    from example_service.core.settings.redis import RedisSettings

    redis = (
        RedisSettings.model_validate(redis_settings)
        if not isinstance(redis_settings, RedisSettings)
        else redis_settings
    )
    mock = (
        MockModeSettings.model_validate(mock_settings)
        if not isinstance(mock_settings, MockModeSettings)
        else mock_settings
    )

    # Close Redis cache
    # Skip in mock mode since it wasn't started
    if redis.is_configured and not mock.enabled:
        await stop_cache()
        logger.info("Redis cache closed")
